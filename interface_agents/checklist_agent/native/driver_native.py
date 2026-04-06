"""Native GPT-OSS checklist extraction driver."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from agent.document_manager import DocumentManager
from agent.snapshot_builder import SnapshotBuilder
from agent.snapshot_formatter import SnapshotFormatter
from agent.stats_tracker import StatsTracker
from agent.tokenizer import TokenizerWrapper
from agent.tools import (
    AppendChecklistTool,
    GetChecklistTool,
    ListDocumentsTool,
    ReadDocumentTool,
    SearchDocumentRegexTool,
    UpdateChecklistTool,
)
from state.store import ChecklistStore, DerivedStateStore, Ledger

from native.gpt_oss_native_client import GPTOSSNativeClient, NativeTurnResult
from native.stop_tool import StopTool
from native.update_derived_state_tool import UpdateDerivedStateTool


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


class NativeDriver:
    """Native GPT-OSS tool-calling driver with compact memory strategy."""

    def __init__(
        self,
        corpus_path: str,
        store_path: str = "checklist_store.json",
        ledger_path: str = "ledger.jsonl",
        config_dir: str = "config",
        checklist_config_path: Optional[str] = None,
        model_name: str = "unsloth/gpt-oss-20b-BF16",
        max_steps: int = 300,
        reasoning_effort: str = "medium",
        verbose: bool = True,
        recent_actions: int = 5,
        k_recent_tool_outputs: int = 5,
    ):
        self.corpus_path = Path(corpus_path)
        self.config_dir = Path(config_dir)
        self.checklist_config_path = checklist_config_path
        self.model_name = model_name
        self.max_steps = max_steps
        self.reasoning_effort = reasoning_effort
        self.verbose = verbose if isinstance(verbose, int) else (1 if verbose else 0)
        self.recent_actions = recent_actions
        self.k_recent_tool_outputs = max(k_recent_tool_outputs, 1)

        store_path_obj = Path(store_path)
        if store_path_obj.parent.name != ".":
            self.output_dir = store_path_obj.parent
        else:
            case_id = self.corpus_path.name if self.corpus_path.is_dir() else "unknown_case"
            model_suffix = model_name.split("/")[-1]
            self.output_dir = Path(f"output/{model_suffix}/{case_id}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._load_config()

        self.store = ChecklistStore(storage_path=store_path, checklist_config=self.checklist_config)
        self.derived_state_store = DerivedStateStore(
            storage_path=str(self.output_dir / "derived_state.json")
        )
        self.ledger = Ledger(ledger_path)

        tokenizer = TokenizerWrapper(model_name)
        self.document_manager = DocumentManager(self.corpus_path, tokenizer=tokenizer)
        self.snapshot_builder = SnapshotBuilder(
            self.store,
            self.ledger,
            self.document_manager,
            checklist_config=self.checklist_config,
            user_instruction=self.user_instruction,
            task_constraints=self.task_constraints,
            focus_context=self.focus_context,
            recent_actions_detail=self.recent_actions,
        )

        self.tools = self._initialize_tools()
        self.tool_definitions = self._build_tool_definitions()

        self.client = GPTOSSNativeClient(
            model_name=model_name,
            temperature=self.model_settings.get("temperature", 0.7),
            top_p=self.model_settings.get("top_p", 1.0),
            top_k=self.model_settings.get("top_k", -1),
            max_tokens=self.model_settings.get("max_tokens", 32000),
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

    def _load_config(self) -> None:
        if self.checklist_config_path:
            checklist_file = Path(self.checklist_config_path)
        else:
            checklist_file = self.config_dir / "checklist_configs" / "all" / "all_26_items.yaml"
            if not checklist_file.exists():
                checklist_file = self.config_dir / "checklist_config.yaml"

        if not checklist_file.exists():
            raise FileNotFoundError(f"Checklist config not found: {checklist_file}")

        with checklist_file.open("r", encoding="utf-8") as f:
            checklist_data = yaml.safe_load(f) or {}
        self.checklist_config = checklist_data.get("checklist_items", {}) or {}
        self.user_instruction = checklist_data.get("user_instruction", "")
        self.task_constraints = checklist_data.get("constraints", []) or []
        focus_context = checklist_data.get("focus_context")
        self.focus_context = str(focus_context).strip() if isinstance(focus_context, str) else None
        if self.focus_context == "":
            self.focus_context = None

        model_config_file = self.config_dir / "model_config.yaml"
        if model_config_file.exists():
            with model_config_file.open("r", encoding="utf-8") as f:
                model_data = yaml.safe_load(f) or {}
            models = model_data.get("models", {}) or {}
            self.model_settings = models.get("gpt-oss", models.get("default", {})) or {}
        else:
            self.model_settings = {}

        prompt_file = Path(__file__).parent / "prompts_gpt_oss_native.yaml"
        if prompt_file.exists():
            with prompt_file.open("r", encoding="utf-8") as f:
                prompt_data = yaml.safe_load(f) or {}
            self.developer_prompt = prompt_data.get("developer_prompt", "").strip()
        else:
            self.developer_prompt = "You are a checklist extraction agent."

    def _initialize_tools(self) -> Dict[str, Any]:
        tools: Dict[str, Any] = {}
        tools["list_documents"] = ListDocumentsTool(self.document_manager, self.ledger)
        tools["read_document"] = ReadDocumentTool(self.document_manager, self.ledger)
        tools["search_document_regex"] = SearchDocumentRegexTool(self.document_manager, self.ledger)
        tools["get_checklist"] = GetChecklistTool(self.store)
        tools["append_checklist"] = AppendChecklistTool(self.store, self.ledger, self.document_manager)
        tools["update_checklist"] = UpdateChecklistTool(self.store, self.ledger, self.document_manager)
        tools["update_derived_state"] = UpdateDerivedStateTool(self.derived_state_store)
        tools["stop"] = StopTool(self.store)
        return tools

    def _build_tool_definitions(self) -> List[Dict[str, Any]]:
        definitions = []
        for tool in self.tools.values():
            input_schema = self._sanitize_schema_for_harmony(
                tool_name=tool.name,
                schema=tool.get_input_schema(),
            )
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
        """Ensure GPT-OSS Harmony template-required descriptions exist.

        GPT-OSS chat template references `param_spec.description` for each
        top-level function parameter. Some legacy tool schemas omit those.
        """
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
                param_clean = dict(param_spec)
            else:
                param_clean = {"type": "string"}
            if not str(param_clean.get("description") or "").strip():
                param_clean["description"] = f"{param_name} parameter for {tool_name}"
            sanitized_props[param_name] = param_clean

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

        if not resume:
            self.store.reset()
            self.derived_state_store.reset()
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
        else:
            stop_reason = "Reached maximum steps limit"

        return self._finalize_run(stop_reason=stop_reason)

    def _execute_step(self) -> Tuple[bool, str]:
        if self.verbose:
            print(f"\n--- Step {self.current_step}/{self.max_steps} ---")

        snapshot = self.snapshot_builder.build_snapshot(
            self.current_run_id or "unknown_run",
            self.current_step,
            self.last_tool_result,
            self.last_tool_name,
            include_last_result=(self.current_step == 1 or self.last_tool_result is not None),
            action_history=self.action_history,
            stop_count=self.stop_count,
            first_stop_step=self.first_stop_step,
            derived_state=self.derived_state_store.get_state(include_unpinned=True),
            derived_state_enabled=True,
        )
        user_prompt = SnapshotFormatter.format_as_markdown(snapshot)
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
                    print("First stop request received; running automatic checklist review.")

                if self.current_step < self.max_steps:
                    self.current_step += 1
                    auto_args: Dict[str, Any] = {}
                    auto_result, auto_success = self._execute_tool_call(
                        tool_name="get_checklist",
                        args=auto_args,
                        auto_generated=True,
                    )
                    self._append_tool_turn(
                        tool_name="get_checklist",
                        args=auto_args,
                        result=auto_result,
                    )
                    self._record_action(
                        tool_name="get_checklist",
                        args=auto_args,
                        result=auto_result,
                        success=auto_success,
                        auto_generated=True,
                    )
                    self.last_tool_result = auto_result
                    self.last_tool_name = "get_checklist"
                return False, ""

            if self.verbose:
                print("Second stop request received; terminating run.")
            return True, result.get("message") or "Stop requested"

        return False, ""

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
                        "Review phase: system will run get_checklist automatically. "
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
                self.snapshot_builder.mark_documents_discovered()

            if tool_name in {"list_documents", "get_checklist", "update_derived_state"} or (
                result.get("validation_errors") and not success
            ):
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
                "action": {"tool": tool_name, "args": args},
                "timestamp": now_iso_utc(),
                "success": success,
                "error": result.get("error"),
                "validation_errors": result.get("validation_errors", []),
                "tool_result": result,
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

    def _build_args_signature(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "read_document":
            return {
                "doc_id": args.get("doc_id"),
                "start_sentence": args.get("start_sentence"),
                "end_sentence": args.get("end_sentence"),
            }
        if tool_name == "search_document_regex":
            doc_ids = args.get("doc_ids") or []
            return {
                "doc_id": args.get("doc_id"),
                "doc_ids_count": len(doc_ids),
                "pattern": (args.get("pattern") or "")[:120],
            }
        if tool_name in {"append_checklist", "update_checklist"}:
            patch = args.get("patch") or []
            keys = [p.get("key") for p in patch if isinstance(p, dict) and p.get("key")]
            return {"keys": keys, "patch_count": len(patch)}
        if tool_name == "get_checklist":
            return {"item": args.get("item"), "items_count": len(args.get("items") or [])}
        if tool_name == "stop":
            return {"reason": args.get("reason", "")[:200]}
        if tool_name == "update_derived_state":
            source_document_ids = args.get("source_document_ids") or []
            return {
                "bucket": args.get("bucket"),
                "action": args.get("action"),
                "text_preview": str(args.get("text") or "")[:120],
                "source_document_ids_count": len(source_document_ids) if isinstance(source_document_ids, list) else 0,
            }
        return args

    def _normalize_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common native-call variants to tool contract shape."""
        if not isinstance(args, dict):
            return {}

        if tool_name not in {"append_checklist", "update_checklist"}:
            if tool_name == "search_document_regex":
                normalized: Dict[str, Any] = dict(args)

                if "doc_id" in normalized and normalized.get("doc_id") is not None:
                    normalized["doc_id"] = str(normalized["doc_id"]).strip()

                if "doc_ids" in normalized:
                    raw_doc_ids = normalized.get("doc_ids")
                    if raw_doc_ids is None:
                        normalized["doc_ids"] = []
                    elif isinstance(raw_doc_ids, list):
                        normalized["doc_ids"] = [
                            str(doc_id).strip()
                            for doc_id in raw_doc_ids
                            if str(doc_id).strip()
                        ]
                    else:
                        doc_val = str(raw_doc_ids).strip()
                        normalized["doc_ids"] = [doc_val] if doc_val else []

                return normalized

            if tool_name == "update_derived_state":
                normalized: Dict[str, Any] = dict(args)
                # Backward compatibility: if legacy operations array is passed,
                # take the first operation only (single-change contract).
                if "operations" in normalized and isinstance(normalized.get("operations"), list):
                    ops = normalized.get("operations") or []
                    first_op = ops[0] if ops and isinstance(ops[0], dict) else {}
                    normalized = dict(first_op)

                bucket_aliases = {
                    "confirmed": "confirmed_state",
                    "confirmed_state": "confirmed_state",
                    "open": "open_questions",
                    "open_question": "open_questions",
                    "open_questions": "open_questions",
                    "external": "external_refs",
                    "external_ref": "external_refs",
                    "external_refs": "external_refs",
                }
                action_aliases = {
                    "upsert": "upsert",
                    "add": "upsert",
                    "insert": "upsert",
                    "update": "upsert",
                    "pin": "upsert",
                    "remove": "remove",
                    "delete": "remove",
                    "unpin": "remove",
                }

                raw_bucket = str(normalized.get("bucket") or "").strip().lower()
                if raw_bucket:
                    normalized["bucket"] = bucket_aliases.get(raw_bucket, raw_bucket)

                raw_action = str(
                    normalized.get("action")
                    or normalized.get("op")
                    or normalized.get("type")
                    or ""
                ).strip().lower()
                if raw_action:
                    normalized["action"] = action_aliases.get(raw_action, raw_action)

                if "source_document_id" in normalized and "source_document_ids" not in normalized:
                    normalized["source_document_ids"] = [normalized.pop("source_document_id")]

                if "text" not in normalized:
                    if isinstance(normalized.get("value"), str):
                        normalized["text"] = normalized.pop("value")
                    elif isinstance(normalized.get("value"), dict):
                        value_obj = normalized.pop("value")
                        value_text = str(value_obj.get("value") or value_obj.get("text") or "").strip()
                        if value_text:
                            normalized["text"] = value_text
                        if "source_document_ids" not in normalized and isinstance(
                            value_obj.get("source_document_ids"), list
                        ):
                            normalized["source_document_ids"] = value_obj.get("source_document_ids")
                    elif isinstance(normalized.get("id"), str):
                        normalized["text"] = normalized.pop("id")
                    elif isinstance(normalized.get("key"), str):
                        normalized["text"] = normalized.pop("key")

                source_document_ids = normalized.get("source_document_ids")
                if source_document_ids is None:
                    source_document_ids = []
                if not isinstance(source_document_ids, list):
                    source_document_ids = [str(source_document_ids)]
                normalized["source_document_ids"] = [
                    str(doc_id).strip() for doc_id in source_document_ids if str(doc_id).strip()
                ]

                normalized.pop("op", None)
                normalized.pop("type", None)
                normalized.pop("id", None)
                normalized.pop("key", None)
                normalized.pop("value", None)
                normalized.pop("operations", None)
                return normalized
            return args

        normalized: Dict[str, Any] = dict(args)
        if "patch" not in normalized and any(
            key in normalized for key in ("key", "item", "value", "evidence", "extracted", "add_extracted")
        ):
            normalized = {"patch": [normalized]}

        patch = normalized.get("patch")
        if not isinstance(patch, list):
            return normalized

        normalized_patch: List[Dict[str, Any]] = []
        for patch_item in patch:
            if not isinstance(patch_item, dict):
                continue

            item = dict(patch_item)
            if "key" not in item and isinstance(item.get("item"), str):
                item["key"] = item.pop("item")
            if "key" not in item or not str(item.get("key")).strip():
                continue
            item["key"] = str(item["key"]).strip()

            if tool_name == "append_checklist" and "add_extracted" in item and "extracted" not in item:
                item["extracted"] = item.pop("add_extracted")

            # Legacy single-entry style: {"key":..., "value":..., "evidence":...}
            if "extracted" not in item and "value" in item:
                item["extracted"] = [
                    {
                        "value": item.get("value"),
                        "evidence": item.get("evidence"),
                    }
                ]

            if isinstance(item.get("extracted"), dict):
                item["extracted"] = [item["extracted"]]

            if isinstance(item.get("extracted"), list):
                extracted_norm: List[Dict[str, Any]] = []
                for extracted_item in item["extracted"]:
                    if not isinstance(extracted_item, dict):
                        continue
                    value = extracted_item.get("value")
                    evidence = self._normalize_evidence_entries(extracted_item.get("evidence"))
                    if isinstance(value, str) and value.strip() and evidence:
                        extracted_norm.append({"value": value.strip(), "evidence": evidence})
                item["extracted"] = extracted_norm

            # Remove legacy aliases after conversion.
            item.pop("item", None)
            item.pop("value", None)
            item.pop("evidence", None)

            if tool_name == "append_checklist":
                normalized_patch.append({"key": item["key"], "extracted": item.get("extracted", [])})
            else:
                cleaned: Dict[str, Any] = {"key": item["key"]}
                if "extracted" in item:
                    cleaned["extracted"] = item["extracted"]
                if "add_extracted" in item:
                    cleaned["add_extracted"] = item["add_extracted"]
                if "add_candidates" in item:
                    cleaned["add_candidates"] = item["add_candidates"]
                normalized_patch.append(cleaned)

        normalized["patch"] = normalized_patch
        return normalized

    def _normalize_evidence_entries(self, evidence: Any) -> List[Dict[str, Any]]:
        """Normalize evidence to [{source_document_id,start_sentence,end_sentence}, ...]."""
        if isinstance(evidence, dict):
            evidence_items = [evidence]
        elif isinstance(evidence, list):
            evidence_items = evidence
        else:
            evidence_items = []

        normalized: List[Dict[str, Any]] = []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue

            source_document_id = (
                item.get("source_document_id")
                or item.get("doc_id")
                or item.get("source_document")
            )
            if source_document_id is None:
                continue
            source_document_id = str(source_document_id)

            start_sentence = item.get("start_sentence")
            end_sentence = item.get("end_sentence")

            if isinstance(item.get("sentence"), int):
                start_sentence = item["sentence"]
                end_sentence = item["sentence"]
            elif (
                isinstance(item.get("sentences"), list)
                and item["sentences"]
                and all(isinstance(x, int) for x in item["sentences"])
            ):
                start_sentence = min(item["sentences"])
                end_sentence = max(item["sentences"])

            if not isinstance(start_sentence, int) or not isinstance(end_sentence, int):
                continue
            normalized.append(
                {
                    "source_document_id": source_document_id,
                    "start_sentence": start_sentence,
                    "end_sentence": end_sentence,
                }
            )

        return normalized

    def _summarize_result(self, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"success": result.get("error") is None}
        if result.get("error"):
            summary["error"] = result["error"]
            return summary

        if tool_name == "list_documents":
            docs = result.get("documents") or []
            summary["documents"] = len(docs)
            return summary
        if tool_name == "read_document":
            text = result.get("text") or ""
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
        if tool_name == "get_checklist":
            summary["completion_stats"] = result.get("completion_stats", {})
            summary["items"] = len(result.get("checklist") or [])
            return summary
        if tool_name in {"append_checklist", "update_checklist"}:
            summary["updated_keys"] = result.get("updated_keys", result.get("appended_keys", []))
            summary["validation_errors"] = result.get("validation_errors", [])
            return summary
        if tool_name == "update_derived_state":
            summary["updated_buckets"] = result.get("updated_buckets", [])
            summary["validation_errors"] = result.get("validation_errors", [])
            summary["pinned_counts"] = result.get("pinned_counts", {})
            return summary
        if tool_name == "stop":
            summary["stage"] = result.get("stage")
            summary["terminated"] = result.get("terminated")
            summary["completion_stats"] = result.get("completion_stats", {})
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
        final_stats = self.store.get_completion_stats()
        final_output = self.store.get_final_output()
        empty_keys = self.store.get_empty_keys()

        total_keys = len(self.store.checklist_keys)
        completion_threshold = int(total_keys * 0.5) if total_keys > 0 else 0
        final_status = "completed" if final_stats["filled"] >= completion_threshold else "partial"

        results = {
            "run_id": self.current_run_id,
            "total_steps": self.current_step,
            "completion_stats": final_stats,
            "empty_keys": empty_keys,
            "checklist": final_output,
            "action_history": self.action_history[:10],
            "timestamp": now_iso_utc(),
            "performance_metrics": {},
            "token_usage": self.stats_tracker.get_summary(),
            "final_status": final_status,
            "stop_reason": stop_reason,
            "derived_state": self.derived_state_store.get_state(include_unpinned=True).dict(),
            "derived_state_path": str(self.output_dir / "derived_state.json"),
        }

        output_file = self.output_dir / f"run_{str(self.current_run_id)[:8]}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        if self.verbose:
            print(f"\n{'=' * 60}")
            print("Native Run Complete")
            print(f"{'=' * 60}")
            print(f"Total Steps: {self.current_step}")
            print(f"Stop Reason: {stop_reason}")
            print(f"Keys Filled: {final_stats['filled']}/{len(self.store.checklist_keys)}")
            print(f"Empty Keys: {final_stats['empty']}")
            print(f"Results saved to: {output_file}")
            self.stats_tracker.print_summary()

        self.client.close()
        return results
