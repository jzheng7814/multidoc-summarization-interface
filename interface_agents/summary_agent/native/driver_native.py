"""Native GPT-OSS summary-generation driver."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SUMMARY_AGENT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv_file(path: Path) -> None:
    """Load KEY=VALUE lines from dotenv file into env without overriding existing values."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if value and ((value[0] == value[-1]) and value[0] in {'"', "'"}):
                value = value[1:-1]
            os.environ.setdefault(key, value)


DEFAULT_ENV_PATH = SUMMARY_AGENT_ROOT / ".env"
load_dotenv_file(Path(os.environ.get("INTERFACE_SUMMARY_AGENT_ENV_FILE", str(DEFAULT_ENV_PATH))))

DEFAULT_EXTRACTION_ROOT = SUMMARY_AGENT_ROOT.parent / "checklist_agent"
EXTRACTION_AGENT_ROOT = Path(
    os.environ.get(
        "INTERFACE_SUMMARY_AGENT_EXTRACTION_BASE_DIR",
        os.environ.get("INTERFACE_CHECKLIST_AGENT_BASE_DIR", str(DEFAULT_EXTRACTION_ROOT)),
    )
).expanduser().resolve()

if str(SUMMARY_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUMMARY_AGENT_ROOT))
if str(EXTRACTION_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_AGENT_ROOT))

from agent.document_manager import DocumentManager
from agent.stats_tracker import StatsTracker
from agent.tokenizer import TokenizerWrapper
from agent.tools import ListDocumentsTool, ReadDocumentTool, SearchDocumentRegexTool
from state.store import Ledger

from .gpt_oss_native_client import GPTOSSNativeClient, NativeTurnResult
from .stop_tool import StopTool
from runtime.snapshot_formatter import SummarySnapshotFormatter
from runtime.summary_state import SummaryStore
from runtime.tools import (
    AppendSummaryTool,
    DeleteSummaryTool,
    GetSummaryStateTool,
    UpdateSummaryTool,
)


DEFAULT_SUMMARY_CONSTRAINTS = [
    "Write plain narrative paragraphs only (no bullets, no markdown headings, no numbered lists).",
    "Keep the summary factually grounded in the checklist and source documents.",
    "Prefer concise, legally precise language over speculation.",
]


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolTurn:
    step: int
    tool_name: str
    args_full: Dict[str, Any]
    args_signature: Dict[str, Any]
    result_full: Dict[str, Any]
    result_summary: Dict[str, Any]


class NativeSummaryDriver:
    """Native GPT-OSS tool-calling loop for checklist-grounded summary drafting."""

    def __init__(
        self,
        corpus_path: str,
        request_payload: Dict[str, Any],
        summary_state_path: str = "summary_state.json",
        ledger_path: str = "ledger.jsonl",
        model_name: str = "unsloth/gpt-oss-20b-BF16",
        max_steps: int = 200,
        reasoning_effort: str = "medium",
        verbose: bool = True,
        recent_actions: int = 8,
        k_recent_tool_outputs: int = 5,
        prompt_config_path: Optional[str] = None,
    ):
        self.corpus_path = Path(corpus_path)
        self.request_payload = request_payload
        self.model_name = model_name
        self.max_steps = int(max_steps)
        self.reasoning_effort = str(reasoning_effort)
        self.verbose = verbose if isinstance(verbose, int) else (1 if verbose else 0)
        self.recent_actions = max(int(recent_actions), 1)
        self.k_recent_tool_outputs = max(int(k_recent_tool_outputs), 1)
        self.prompt_config_path = prompt_config_path

        self.request_id = str(request_payload.get("request_id") or "summary_request")
        self.case_id = str(request_payload.get("case_id") or "unknown_case")
        self.checklist = request_payload.get("checklist") or {}
        self.checklist_definitions = request_payload.get("checklist_definitions") or {}
        self.summary_constraints = request_payload.get("summary_constraints") or list(DEFAULT_SUMMARY_CONSTRAINTS)
        focus_context = request_payload.get("focus_context")
        self.focus_context = str(focus_context).strip() if isinstance(focus_context, str) else None
        if self.focus_context == "":
            self.focus_context = None

        summary_state_path_obj = Path(summary_state_path)
        self.output_dir = summary_state_path_obj.parent if summary_state_path_obj.parent.name != "." else Path(
            f"output/{model_name.split('/')[-1]}/{self.case_id}/summary_agent"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.summary_store = SummaryStore(storage_path=summary_state_path)
        self.ledger = Ledger(ledger_path)

        tokenizer = TokenizerWrapper(model_name)
        self.document_manager = DocumentManager(self.corpus_path, tokenizer=tokenizer)
        self.documents_discovered = False

        self.developer_prompt = self._load_developer_prompt(prompt_config_path)

        self.tools = self._initialize_tools()
        self.tool_definitions = self._build_tool_definitions()

        self.client = GPTOSSNativeClient(
            model_name=model_name,
            temperature=0.7,
            top_p=1.0,
            top_k=-1,
            max_tokens=32000,
            reasoning_effort=self.reasoning_effort,
        )

        self.stats_tracker = StatsTracker(output_dir=str(self.output_dir), case_id=None)
        self.raw_responses_path = self.output_dir / "raw_responses.jsonl"

        self.current_run_id: Optional[str] = None
        self.current_step = 0
        self.last_tool_result: Optional[Dict[str, Any]] = None
        self.last_tool_name: Optional[str] = None
        self.action_history: List[Dict[str, Any]] = []
        self.tool_turns: List[ToolTurn] = []
        self.stop_count = 0
        self.first_stop_step: Optional[int] = None

    def _load_developer_prompt(self, prompt_config_path: Optional[str]) -> str:
        if prompt_config_path:
            candidate = Path(prompt_config_path)
        else:
            candidate = Path(__file__).parent / "prompts_gpt_oss_summary_native.yaml"

        if not candidate.exists():
            return "You are a summary drafting agent. Emit one tool call per turn."

        with candidate.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
        return str(payload.get("developer_prompt") or "").strip()

    def _initialize_tools(self) -> Dict[str, Any]:
        tools: Dict[str, Any] = {}
        tools["list_documents"] = ListDocumentsTool(self.document_manager, self.ledger)
        tools["read_document"] = ReadDocumentTool(self.document_manager, self.ledger)
        tools["search_document_regex"] = SearchDocumentRegexTool(self.document_manager, self.ledger)
        tools["get_summary_state"] = GetSummaryStateTool(self.summary_store)
        tools["append_summary"] = AppendSummaryTool(self.summary_store)
        tools["update_summary"] = UpdateSummaryTool(self.summary_store)
        tools["delete_summary"] = DeleteSummaryTool(self.summary_store)
        tools["stop"] = StopTool(self.summary_store)
        return tools

    def _build_tool_definitions(self) -> List[Dict[str, Any]]:
        definitions: List[Dict[str, Any]] = []
        for tool in self.tools.values():
            input_schema = self._sanitize_schema_for_harmony(tool.name, tool.get_input_schema())
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": input_schema,
                    },
                }
            )
        return definitions

    def _sanitize_schema_for_harmony(self, tool_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}

        cleaned = dict(schema)
        properties = cleaned.get("properties")
        if not isinstance(properties, dict):
            cleaned["properties"] = {}
            cleaned.setdefault("required", [])
            return cleaned

        sanitized_props: Dict[str, Any] = {}
        for param_name, param_spec in properties.items():
            if isinstance(param_spec, dict):
                item = dict(param_spec)
            else:
                item = {"type": "string"}
            if not str(item.get("description") or "").strip():
                item["description"] = f"{param_name} parameter for {tool_name}"
            sanitized_props[param_name] = item

        cleaned["properties"] = sanitized_props
        cleaned.setdefault("required", [])
        return cleaned

    def run(self, run_id: Optional[str] = None, resume: bool = False) -> Dict[str, Any]:
        self.current_run_id = run_id or str(uuid.uuid4())
        self.current_step = 0
        self.last_tool_result = None
        self.last_tool_name = None
        self.action_history = []
        self.tool_turns = []
        self.stop_count = 0
        self.first_stop_step = None
        self.documents_discovered = False

        if not resume:
            self.summary_store.reset()
            self.ledger.reset()
            if self.raw_responses_path.exists():
                self.raw_responses_path.unlink()
        else:
            self.stats_tracker.load_existing_stats()

        stop_reason = "Reached maximum steps limit"
        while self.current_step < self.max_steps:
            self.current_step += 1
            should_stop, reason = self._execute_step()
            if should_stop:
                stop_reason = reason
                break

        return self._finalize_run(stop_reason=stop_reason)

    def _execute_step(self) -> Tuple[bool, str]:
        if self.verbose:
            print(f"\n--- Step {self.current_step}/{self.max_steps} ---")

        snapshot = self._build_snapshot()
        user_prompt = SummarySnapshotFormatter.format_snapshot(snapshot)
        messages = self._build_messages(user_prompt)

        model_turn = self.client.generate_tool_call(messages=messages, tools=self.tool_definitions)
        self._record_raw_response(self.current_step, model_turn)
        self.stats_tracker.update_stats(
            step=self.current_step,
            prompt_tokens=model_turn.prompt_tokens,
            completion_tokens=model_turn.completion_tokens,
            model=self.model_name,
            is_system_cached=self.current_step > 1,
        )

        if model_turn.parse_error:
            error_result = {"error": model_turn.parse_error}
            self.ledger.record_tool(
                tool_name="parse_error",
                args={},
                result=error_result,
                step=self.current_step,
                run_id=self.current_run_id or "unknown_run",
                success=False,
            )
            self._record_action(
                tool_name="parse_error",
                args={"error": model_turn.parse_error},
                result=error_result,
                success=False,
                auto_generated=False,
            )
            self.last_tool_result = error_result
            self.last_tool_name = "parse_error"
            return False, ""

        tool_name = str(model_turn.tool_name or "").strip()
        tool_args = self._normalize_tool_args(tool_name, model_turn.tool_args or {})

        if self.verbose:
            print(f"Action: {tool_name}")
            if self.verbose > 1:
                print(json.dumps(tool_args, indent=2, ensure_ascii=False))

        result, success = self._execute_tool_call(tool_name=tool_name, args=tool_args, auto_generated=False)
        self._append_tool_turn(tool_name=tool_name, args=tool_args, result=result)
        self._record_action(
            tool_name=tool_name,
            args=tool_args,
            result=result,
            success=success,
            auto_generated=False,
        )

        self.last_tool_result = result
        self.last_tool_name = tool_name

        if tool_name == "stop":
            self.stop_count += 1
            if self.stop_count == 1:
                self.first_stop_step = self.current_step
                if self.verbose:
                    print("First stop request received; running automatic summary-state review.")

                if self.current_step < self.max_steps:
                    self.current_step += 1
                    auto_args: Dict[str, Any] = {}
                    auto_result, auto_success = self._execute_tool_call(
                        tool_name="get_summary_state",
                        args=auto_args,
                        auto_generated=True,
                    )
                    self._append_tool_turn(
                        tool_name="get_summary_state",
                        args=auto_args,
                        result=auto_result,
                    )
                    self._record_action(
                        tool_name="get_summary_state",
                        args=auto_args,
                        result=auto_result,
                        success=auto_success,
                        auto_generated=True,
                    )
                    self.last_tool_result = auto_result
                    self.last_tool_name = "get_summary_state"
                return False, ""

            if self.verbose:
                print("Second stop request received; terminating run.")
            return True, str(result.get("message") or "Stop requested")

        return False, ""

    def _build_snapshot(self) -> Dict[str, Any]:
        documents: List[Dict[str, Any]] = []
        if self.documents_discovered:
            for doc_id in self.document_manager.list_documents():
                doc_info = self.document_manager.get_document_info(doc_id, self.ledger)
                if hasattr(doc_info, "dict"):
                    documents.append(doc_info.dict())
                else:
                    documents.append(doc_info)

        return {
            "run_id": self.current_run_id,
            "request_id": self.request_id,
            "case_id": self.case_id,
            "step": self.current_step,
            "max_steps": self.max_steps,
            "checklist": self.checklist,
            "checklist_definitions": self.checklist_definitions,
            "summary_constraints": self.summary_constraints,
            "focus_context": self.focus_context,
            "summary_state": self.summary_store.get_state(),
            "documents": documents,
            "documents_discovered": self.documents_discovered,
            "action_tail": self.action_history[-max(self.recent_actions, 1) :],
            "last_tool_result": self.last_tool_result,
            "last_tool_name": self.last_tool_name,
            "stop_count": self.stop_count,
            "first_stop_step": self.first_stop_step,
        }

    def _build_messages(self, user_prompt: str) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = [{"role": "developer", "content": self.developer_prompt}]

        turn_count = len(self.tool_turns)
        for idx, turn in enumerate(self.tool_turns):
            use_full = idx >= max(0, turn_count - self.k_recent_tool_outputs)
            args_for_context = turn.args_full if use_full else turn.args_signature
            result_for_context = turn.result_full if use_full else turn.result_summary

            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": turn.tool_name,
                                "arguments": json.dumps(args_for_context, ensure_ascii=False),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "name": turn.tool_name,
                    "content": json.dumps(result_for_context, ensure_ascii=False),
                }
            )

        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _execute_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        auto_generated: bool,
    ) -> Tuple[Dict[str, Any], bool]:
        if tool_name not in self.tools:
            result = {"error": f"Unknown tool: {tool_name}"}
            self.ledger.record_tool(
                tool_name=tool_name or "unknown_tool",
                args=args,
                result=result,
                step=self.current_step,
                run_id=self.current_run_id or "unknown_run",
                success=False,
            )
            return result, False

        tool = self.tools[tool_name]
        if hasattr(tool, "set_context"):
            tool.set_context(self.current_run_id or "unknown_run", self.current_step)

        try:
            result = tool.call(args)
            success = result.get("error") is None and not result.get("validation_errors")

            if tool_name == "stop":
                if self.stop_count == 0:
                    result["stage"] = "review"
                    result["terminated"] = False
                    result["message"] = (
                        "Review phase: system will run get_summary_state automatically. "
                        "Call stop again to finalize."
                    )
                else:
                    result["stage"] = "finalize"
                    result["terminated"] = True
                    result["message"] = "Final stop accepted."

                self.ledger.record_tool(
                    tool_name="stop",
                    args=args,
                    result=result,
                    step=self.current_step,
                    run_id=self.current_run_id or "unknown_run",
                    success=True,
                )
                return result, True

            if tool_name == "list_documents":
                self.documents_discovered = True

            # Read/search tools self-record richer coverage events in ledger.
            if tool_name not in {"read_document", "search_document_regex"}:
                self.ledger.record_tool(
                    tool_name=tool_name,
                    args=args,
                    result=result,
                    step=self.current_step,
                    run_id=self.current_run_id or "unknown_run",
                    success=success,
                )

            return result, success
        except Exception as exc:
            result = {"error": f"Tool execution error: {exc}"}
            self.ledger.record_tool(
                tool_name=tool_name,
                args=args,
                result=result,
                step=self.current_step,
                run_id=self.current_run_id or "unknown_run",
                success=False,
            )
            return result, False

    def _normalize_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(args, dict):
            return {}

        normalized = dict(args)

        if tool_name == "append_summary":
            if "text" not in normalized and isinstance(normalized.get("paragraph"), str):
                normalized["text"] = normalized.pop("paragraph")

        if tool_name in {"update_summary", "delete_summary"}:
            if "index" not in normalized and "paragraph_index" in normalized:
                normalized["index"] = normalized.pop("paragraph_index")
            if "paragraph_id" not in normalized and "id" in normalized:
                normalized["paragraph_id"] = normalized.pop("id")

        if tool_name == "search_document_regex":
            if "doc_id" in normalized and normalized.get("doc_id") is not None:
                normalized["doc_id"] = str(normalized["doc_id"]).strip()
            if "doc_ids" in normalized:
                raw_doc_ids = normalized.get("doc_ids")
                if raw_doc_ids is None:
                    normalized["doc_ids"] = []
                elif isinstance(raw_doc_ids, list):
                    normalized["doc_ids"] = [
                        str(doc_id).strip() for doc_id in raw_doc_ids if str(doc_id).strip()
                    ]
                else:
                    value = str(raw_doc_ids).strip()
                    normalized["doc_ids"] = [value] if value else []

        return normalized

    def _record_action(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        success: bool,
        auto_generated: bool,
    ) -> None:
        self.action_history.append(
            {
                "step": self.current_step,
                "tool_name": tool_name,
                "args": args,
                "timestamp": now_iso_utc(),
                "success": success,
                "error": result.get("error"),
                "validation_errors": result.get("validation_errors", []),
                "result_summary": self._summarize_result(tool_name, result),
                "auto_generated": auto_generated,
            }
        )

    def _append_tool_turn(self, tool_name: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
        self.tool_turns.append(
            ToolTurn(
                step=self.current_step,
                tool_name=tool_name,
                args_full=args,
                args_signature=self._build_args_signature(tool_name, args),
                result_full=result,
                result_summary=self._summarize_result(tool_name, result),
            )
        )

    def _build_args_signature(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "read_document":
            return {
                "doc_id": args.get("doc_id"),
                "start_sentence": args.get("start_sentence"),
                "end_sentence": args.get("end_sentence"),
            }
        if tool_name == "search_document_regex":
            return {
                "doc_id": args.get("doc_id"),
                "doc_ids_count": len(args.get("doc_ids") or []),
                "pattern": str(args.get("pattern") or "")[:120],
            }
        if tool_name in {"append_summary", "update_summary"}:
            return {
                "paragraph_id": args.get("paragraph_id"),
                "index": args.get("index"),
                "text_preview": str(args.get("text") or "")[:120],
            }
        if tool_name == "delete_summary":
            return {
                "paragraph_id": args.get("paragraph_id"),
                "index": args.get("index"),
            }
        if tool_name == "stop":
            return {"reason": str(args.get("reason") or "")[:160]}
        return args

    def _summarize_result(self, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"success": result.get("error") is None}
        if result.get("error"):
            summary["error"] = result["error"]
            return summary

        if tool_name == "list_documents":
            summary["documents"] = len(result.get("documents") or [])
            return summary
        if tool_name == "read_document":
            text = str(result.get("text") or "")
            summary.update(
                {
                    "doc_id": result.get("doc_id"),
                    "start_sentence": result.get("start_sentence"),
                    "end_sentence": result.get("end_sentence"),
                    "chars": len(text),
                }
            )
            return summary
        if tool_name == "search_document_regex":
            summary["total_matches"] = result.get("total_matches", 0)
            summary["documents_searched"] = len(result.get("documents_searched") or [])
            return summary
        if tool_name == "get_summary_state":
            stats = result.get("summary_stats") or {}
            summary["summary_stats"] = stats
            return summary
        if tool_name in {"append_summary", "update_summary", "delete_summary"}:
            summary["summary_stats"] = result.get("summary_stats", {})
            summary["paragraph_id"] = (
                result.get("appended_paragraph_id")
                or result.get("updated_paragraph_id")
                or result.get("deleted_paragraph_id")
            )
            summary["index"] = result.get("index")
            return summary
        if tool_name == "stop":
            summary["stage"] = result.get("stage")
            summary["terminated"] = result.get("terminated")
            summary["summary_stats"] = result.get("summary_stats", {})
            return summary

        summary["keys"] = list(result.keys())[:12]
        return summary

    def _record_raw_response(self, step: int, model_turn: NativeTurnResult) -> None:
        record = {
            "step": step,
            "timestamp": now_iso_utc(),
            "raw_response": model_turn.raw_text,
            "tool_name": model_turn.tool_name,
            "tool_args": model_turn.tool_args,
            "parse_error": model_turn.parse_error,
            "stats": {
                "prompt_tokens": model_turn.prompt_tokens,
                "completion_tokens": model_turn.completion_tokens,
                "model": self.model_name,
            },
        }
        with self.raw_responses_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _finalize_run(self, stop_reason: str) -> Dict[str, Any]:
        final_state = self.summary_store.get_state()
        final_text = str(final_state.get("summary_text") or "")
        final_stats = final_state.get("summary_stats") or {}
        final_status = "completed" if final_text.strip() else "partial"

        results = {
            "run_id": self.current_run_id,
            "request_id": self.request_id,
            "case_id": self.case_id,
            "total_steps": self.current_step,
            "summary": final_text,
            "summary_state": final_state,
            "summary_stats": final_stats,
            "checklist": self.checklist,
            "checklist_definitions": self.checklist_definitions,
            "focus_context": self.focus_context,
            "timestamp": now_iso_utc(),
            "token_usage": self.stats_tracker.get_summary(),
            "final_status": final_status,
            "stop_reason": stop_reason,
            "summary_state_path": str(self.summary_store.storage_path),
        }

        output_file = self.output_dir / f"run_{str(self.current_run_id)[:8]}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        if self.verbose:
            print(f"\n{'=' * 60}")
            print("Native Summary Run Complete")
            print(f"{'=' * 60}")
            print(f"Total Steps: {self.current_step}")
            print(f"Stop Reason: {stop_reason}")
            print(f"Paragraphs: {final_stats.get('paragraph_count', 0)}")
            print(f"Characters: {final_stats.get('character_count', 0)}")
            print(f"Results saved to: {output_file}")
            self.stats_tracker.print_summary()

        self.client.close()
        return results
