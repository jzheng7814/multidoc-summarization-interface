"""Base tool contract for summary-agent-specific tools."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict

from pydantic import BaseModel


class BaseTool(ABC):
    """Abstract base class for summary tools."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def get_input_schema(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_output_schema(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def format_output(self, output: Any) -> Dict[str, Any]:
        if isinstance(output, BaseModel):
            if hasattr(output, "model_dump"):
                return output.model_dump(mode="json")
            try:
                return json.loads(output.json())
            except Exception:
                return output.dict()
        return output
