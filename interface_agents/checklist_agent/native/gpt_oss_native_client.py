"""GPT-OSS native tool-calling client using Harmony chat template messages."""

from __future__ import annotations

import contextlib
import gc
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import ray
import torch
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.distributed.parallel_state import (
    destroy_distributed_environment,
    destroy_model_parallel,
)


@dataclass
class NativeTurnResult:
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    parse_error: Optional[str] = None


class GPTOSSNativeClient:
    """Lightweight GPT-OSS tool-calling client with persistent vLLM backend."""

    TOOL_CALL_PATTERNS = (
        re.compile(
            r"<\|start\|>assistant to=functions\.([A-Za-z0-9_]+)"
            r"<\|channel\|>commentary(?:\s+json)?<\|message\|>(.*)$",
            re.DOTALL,
        ),
        re.compile(
            r"<\|channel\|>commentary to=functions\.([A-Za-z0-9_]+)"
            r"\s*<\|constrain\|>json<\|message\|>(.*)$",
            re.DOTALL,
        ),
    )
    TOOL_REFERENCE_PATTERN = re.compile(r"to=functions\.([A-Za-z0-9_]+)")

    def __init__(
        self,
        model_name: str,
        temperature: float = 0.7,
        top_p: float = 1.0,
        top_k: int = -1,
        max_tokens: int = 32000,
        reasoning_effort: str = "medium",
        dtype: str = "bfloat16",
        gpu_memory_utilization: float = 0.8,
        tensor_parallel_size: Optional[int] = None,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.max_tokens = max_tokens
        normalized_effort = str(reasoning_effort).strip().lower()
        if normalized_effort not in {"low", "medium", "high"}:
            raise ValueError("reasoning_effort must be one of: low, medium, high")
        self.reasoning_effort = normalized_effort
        self.dtype = dtype
        self.gpu_memory_utilization = gpu_memory_utilization
        self.tensor_parallel_size = tensor_parallel_size or (torch.cuda.device_count() or 1)

        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self._llm: Optional[LLM] = None

    def _ensure_llm(self) -> LLM:
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm

    def _create_llm(self) -> LLM:
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "tensor_parallel_size": self.tensor_parallel_size,
            "dtype": self.dtype,
            "gpu_memory_utilization": self.gpu_memory_utilization,
            "disable_custom_all_reduce": True,
            "trust_remote_code": True,
            "max_model_len": 131072,
        }
        return LLM(**kwargs)

    def generate_tool_call(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> NativeTurnResult:
        llm = self._ensure_llm()

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            tools=tools,
            reasoning_effort=self.reasoning_effort,
        )

        sampling_params = SamplingParams(
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            max_tokens=self.max_tokens,
            skip_special_tokens=False,
            stop_token_ids=[200002, 200012],  # <|return|>, <|call|>
        )

        outputs = llm.generate([prompt], sampling_params)
        output = outputs[0]
        generated_text = output.outputs[0].text
        prompt_tokens = len(getattr(output, "prompt_token_ids", []) or [])
        completion_tokens = len(getattr(output.outputs[0], "token_ids", []) or [])

        try:
            tool_name, tool_args = self._extract_tool_call(generated_text)
            return NativeTurnResult(
                tool_name=tool_name,
                tool_args=tool_args,
                raw_text=generated_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except Exception as exc:
            return NativeTurnResult(
                tool_name=None,
                tool_args=None,
                raw_text=generated_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                parse_error=str(exc),
            )

    def _extract_tool_call(self, text: str) -> tuple[str, Dict[str, Any]]:
        parse_errors: List[str] = []

        # First try known well-formed variants.
        for pattern in self.TOOL_CALL_PATTERNS:
            matches = list(pattern.finditer(text))
            if not matches:
                continue
            for match in reversed(matches):
                tool_name = match.group(1).strip()
                raw_args = self._clean_raw_args(match.group(2))
                try:
                    parsed = self._parse_json_payload(raw_args)
                    if not isinstance(parsed, dict):
                        raise ValueError(
                            f"Tool call arguments must be an object for tool={tool_name}"
                        )
                    return tool_name, parsed
                except Exception as exc:
                    parse_errors.append(f"{tool_name}: {exc}")

        # Fallback parser for Harmony variants like:
        # <|channel|>analysis to=functions.read_document code<|message|>{...}
        refs = list(self.TOOL_REFERENCE_PATTERN.finditer(text))
        for ref in reversed(refs):
            tool_name = ref.group(1).strip()
            message_idx = text.find("<|message|>", ref.end())
            if message_idx == -1:
                parse_errors.append(f"{tool_name}: missing <|message|> block")
                continue
            raw_args = self._clean_raw_args(text[message_idx + len("<|message|>") :])
            try:
                parsed = self._parse_json_payload(raw_args)
                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"Tool call arguments must be an object for tool={tool_name}"
                    )
                return tool_name, parsed
            except Exception as exc:
                parse_errors.append(f"{tool_name}: {exc}")

        if parse_errors:
            preview = "; ".join(parse_errors[:3])
            raise ValueError(f"No parseable tool call found. {preview}")
        raise ValueError("No tool call found in GPT-OSS output")

    def _clean_raw_args(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = cleaned.replace("<|end|>", "").strip()
        return cleaned

    def _parse_json_payload(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        extracted = self._extract_json_by_braces(text)
        if extracted is None:
            raise ValueError(f"Unable to parse JSON arguments: {text[:240]}")
        return json.loads(extracted)

    def _extract_json_by_braces(self, text: str) -> Optional[str]:
        start = text.find("{")
        if start == -1:
            return None

        brace_count = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape_next:
                    escape_next = False
                elif ch == "\\":
                    escape_next = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[start : i + 1]
        return None

    def close(self) -> None:
        if self._llm is not None:
            self._cleanup_llm(self._llm)
            self._llm = None

    def _cleanup_llm(self, llm: LLM) -> None:
        destroy_model_parallel()
        destroy_distributed_environment()

        try:
            if hasattr(llm, "llm_engine") and hasattr(llm.llm_engine, "engine_core"):
                llm.llm_engine.engine_core.shutdown()
            elif hasattr(llm, "llm_engine") and hasattr(llm.llm_engine, "model_executor"):
                del llm.llm_engine.model_executor
        except Exception:
            pass

        del llm
        with contextlib.suppress(AssertionError):
            torch.distributed.destroy_process_group()
        gc.collect()
        torch.cuda.empty_cache()
        ray.shutdown()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
