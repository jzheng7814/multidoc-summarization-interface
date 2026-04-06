from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
from contextvars import ContextVar, Token

from app.core.config import Settings


class EventVisibility(IntEnum):
    TRACE = 10
    DEBUG = 20
    INFO = 30
    WARNING = 40
    ERROR = 50


@dataclass(frozen=True)
class Event:
    timestamp: str
    visibility: EventVisibility
    producer: str
    description: str
    payload: Optional[Dict[str, Any]] = None
    corpus_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "timestamp": self.timestamp,
            "visibility": self.visibility.name,
            "producer": self.producer,
            "description": self.description,
            "payload": self.payload,
        }
        if self.corpus_id is not None:
            data["corpus_id"] = self.corpus_id
        return data


class EventConsumer(Protocol):
    def accepts(self, level: EventVisibility) -> bool:
        ...

    async def handle_event(self, event: Event) -> None:
        ...


class BaseEventConsumer:
    def __init__(self, *, min_level: EventVisibility) -> None:
        self._min_level = min_level

    def accepts(self, level: EventVisibility) -> bool:
        return level >= self._min_level


class FileEventConsumer(BaseEventConsumer):
    def __init__(self, path: Path, *, min_level: EventVisibility = EventVisibility.DEBUG) -> None:
        super().__init__(min_level=min_level)
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a", encoding="utf-8")

    async def handle_event(self, event: Event) -> None:
        line = json.dumps(event.to_dict(), default=str)
        self._file.write(line + "\n")
        self._file.flush()

    async def close(self) -> None:
        self._file.close()


class ConsoleEventConsumer(BaseEventConsumer):
    def __init__(self, *, min_level: EventVisibility = EventVisibility.INFO) -> None:
        super().__init__(min_level=min_level)

    async def handle_event(self, event: Event) -> None:
        payload = ""
        if event.payload:
            payload = f" {json.dumps(event.payload, default=str)}"
        corpus_hint = f" corpus_id={event.corpus_id}" if event.corpus_id else ""
        sys.stdout.write(
            f"{event.timestamp} {event.visibility.name} {event.producer}{corpus_hint}: {event.description}{payload}\n"
        )
        sys.stdout.flush()


class UnixSocketEventConsumer(BaseEventConsumer):
    def __init__(self, socket_path: str) -> None:
        super().__init__(min_level=EventVisibility.TRACE)
        self._socket_path = socket_path
        self._server: Optional[asyncio.base_events.Server] = None
        self._connections: List[asyncio.StreamWriter] = []
        self._connections_lock = asyncio.Lock()

    async def start(self) -> None:
        socket_path = Path(self._socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()
        self._server = await asyncio.start_unix_server(self._handle_client, path=self._socket_path)
        asyncio.create_task(self._server.serve_forever())

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with self._connections_lock:
            self._connections.append(writer)
        try:
            await reader.read()
        finally:
            async with self._connections_lock:
                if writer in self._connections:
                    self._connections.remove(writer)
            writer.close()
            await writer.wait_closed()

    async def handle_event(self, event: Event) -> None:
        data = (json.dumps(event.to_dict(), default=str) + "\n").encode("utf-8")
        async with self._connections_lock:
            connections = list(self._connections)
        if not connections:
            return
        stale: List[asyncio.StreamWriter] = []
        for writer in connections:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                stale.append(writer)
        if stale:
            async with self._connections_lock:
                for writer in stale:
                    if writer in self._connections:
                        self._connections.remove(writer)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()


class EventManager:
    def __init__(self) -> None:
        self._queue: queue.Queue[object] = queue.Queue()
        self._consumers: List[EventConsumer] = []
        self._consumer_lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop_signal = object()

    def register_consumer(self, consumer: EventConsumer) -> None:
        with self._consumer_lock:
            self._consumers.append(consumer)

    def _snapshot_consumers(self) -> List[EventConsumer]:
        with self._consumer_lock:
            return list(self._consumers)

    def is_level_enabled(self, level: EventVisibility) -> bool:
        consumers = self._snapshot_consumers()
        return any(consumer.accepts(level) for consumer in consumers)

    async def emit(self, event: Event) -> None:
        if not self._snapshot_consumers():
            return
        self._queue.put(event)

    def submit(self, event: Event) -> None:
        if not self._snapshot_consumers():
            return
        self._queue.put(event)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                event = await asyncio.to_thread(self._queue.get)
            except asyncio.CancelledError:
                break
            if event is self._stop_signal:
                break
            if not isinstance(event, Event):
                continue
            consumers = self._snapshot_consumers()
            if not consumers:
                continue
            await asyncio.gather(
                *(consumer.handle_event(event) for consumer in consumers if consumer.accepts(event.visibility)),
                return_exceptions=True,
            )

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._queue.put(self._stop_signal)
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        consumers = self._snapshot_consumers()
        for consumer in consumers:
            close_fn = getattr(consumer, "close", None)
            if callable(close_fn):
                await close_fn()


class EventProducer:
    def __init__(self, name: str, manager: EventManager) -> None:
        self._name = name
        self._manager = manager

    def is_enabled(self, level: EventVisibility) -> bool:
        return self._manager.is_level_enabled(level)

    def emit(self, level: EventVisibility, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        event = Event(
            timestamp=_current_timestamp(),
            visibility=level,
            producer=self._name,
            description=description,
            payload=payload,
            corpus_id=get_event_corpus_id(),
        )
        self._manager.submit(event)

    def trace(self, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.emit(EventVisibility.TRACE, description, payload)

    def debug(self, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.emit(EventVisibility.DEBUG, description, payload)

    def info(self, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.emit(EventVisibility.INFO, description, payload)

    def warning(self, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.emit(EventVisibility.WARNING, description, payload)

    def error(self, description: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.emit(EventVisibility.ERROR, description, payload)


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


_EVENT_CORPUS_ID: ContextVar[Optional[str]] = ContextVar("event_corpus_id", default=None)


def bind_event_corpus_id(corpus_id: str) -> Token:
    return _EVENT_CORPUS_ID.set(corpus_id)


def reset_event_corpus_id(token: Token) -> None:
    _EVENT_CORPUS_ID.reset(token)


def get_event_corpus_id() -> Optional[str]:
    return _EVENT_CORPUS_ID.get()


@lru_cache(maxsize=1)
def get_event_manager() -> EventManager:
    return EventManager()


@lru_cache(maxsize=1)
def get_run_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def build_event_log_path(log_dir: str, prefix: str) -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    base_dir = Path(log_dir)
    if not base_dir.is_absolute():
        base_dir = backend_root / base_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{prefix}-{get_run_stamp()}.log"


@lru_cache(maxsize=128)
def get_event_producer(name: str) -> EventProducer:
    return EventProducer(name, get_event_manager())


_EVENT_SYSTEM_STARTED = False


async def init_event_system(settings: Settings) -> None:
    global _EVENT_SYSTEM_STARTED
    if _EVENT_SYSTEM_STARTED:
        return
    manager = get_event_manager()
    app_config = settings.app
    log_path = build_event_log_path(app_config.event_log_dir, app_config.event_log_prefix)
    manager.register_consumer(FileEventConsumer(log_path, min_level=EventVisibility.DEBUG))
    manager.register_consumer(ConsoleEventConsumer(min_level=EventVisibility.INFO))
    socket_consumer = UnixSocketEventConsumer(app_config.ipc_socket_path)
    manager.register_consumer(socket_consumer)
    await socket_consumer.start()
    await manager.start()
    _EVENT_SYSTEM_STARTED = True


async def shutdown_event_system() -> None:
    global _EVENT_SYSTEM_STARTED
    manager = get_event_manager()
    await manager.close()
    _EVENT_SYSTEM_STARTED = False
