"""Prompt formatter for summary-agent native turns."""

from __future__ import annotations

import json
from typing import Any, Dict, List


class SummarySnapshotFormatter:
    """Render a compact but explicit markdown snapshot for each agent turn."""

    @staticmethod
    def format_snapshot(snapshot: Dict[str, Any]) -> str:
        sections: List[str] = []
        sections.append(SummarySnapshotFormatter._format_header(snapshot))
        sections.append(SummarySnapshotFormatter._format_checklist(snapshot))
        sections.append(SummarySnapshotFormatter._format_summary_state(snapshot))
        sections.append(SummarySnapshotFormatter._format_documents(snapshot))
        sections.append(SummarySnapshotFormatter._format_recent_actions(snapshot))

        last_tool_name = snapshot.get("last_tool_name")
        last_tool_result = snapshot.get("last_tool_result")
        if last_tool_name and last_tool_result is not None:
            sections.append(SummarySnapshotFormatter._format_last_tool_result(last_tool_name, last_tool_result))

        if SummarySnapshotFormatter._should_show_stop_review(snapshot):
            sections.append(
                "## Stop Status\n"
                "You have completed the automatic review after the first stop call. "
                "Call `stop` again only if the summary is ready to finalize."
            )

        sections.append(
            "## Next Action\n"
            "Choose exactly one tool call that most improves summary quality. "
            "Use plain-text paragraph writing only (no bullets or markdown headings in summary text)."
        )
        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _format_header(snapshot: Dict[str, Any]) -> str:
        run_id = snapshot.get("run_id")
        step = snapshot.get("step")
        max_steps = snapshot.get("max_steps")
        case_id = snapshot.get("case_id")
        request_id = snapshot.get("request_id")

        lines = [
            "# Multi-Document Summary Drafting",
            f"**Run:** {run_id}",
            f"**Request ID:** {request_id}",
            f"**Case ID:** {case_id}",
            f"**Step:** {step}/{max_steps}",
            "",
            "## Objective",
            "Draft one high-quality summary of the target material using structured inputs as guidance and source documents as authority.",
            "Treat source documents as the primary authority when structured inputs are incomplete, ambiguous, or stale.",
            "Final output must be narrative paragraphs only (no bullet lists, no markdown headers).",
        ]

        focus_section = SummarySnapshotFormatter._format_focus_context(snapshot)
        if focus_section:
            lines.append("")
            lines.append(focus_section)

        return "\n".join(lines)

    @staticmethod
    def _format_focus_context(snapshot: Dict[str, Any]) -> str:
        focus_context = snapshot.get("focus_context")
        constraints = snapshot.get("summary_constraints") or []

        cleaned_constraints = [str(entry).strip() for entry in constraints if isinstance(entry, str) and entry.strip()]
        cleaned_focus = str(focus_context).strip() if isinstance(focus_context, str) else ""

        if not cleaned_focus and not cleaned_constraints:
            return ""

        lines = ["## Focus Context"]
        if cleaned_focus:
            lines.append(cleaned_focus)

        if cleaned_constraints:
            if len(lines) > 1:
                lines.append("")
            lines.append("Additional run-specific constraints:")
            for constraint in cleaned_constraints:
                lines.append(f"- {constraint}")

        return "\n".join(lines)

    @staticmethod
    def _format_checklist(snapshot: Dict[str, Any]) -> str:
        checklist = snapshot.get("checklist") or {}
        definitions = snapshot.get("checklist_definitions") or {}

        lines = ["## Checklist Guidance and Current Values"]
        ordered_keys: List[str] = []
        if isinstance(definitions, dict):
            ordered_keys.extend([str(k) for k in definitions.keys()])
        if isinstance(checklist, dict):
            for key in checklist.keys():
                key_str = str(key)
                if key_str not in ordered_keys:
                    ordered_keys.append(key_str)

        if not ordered_keys:
            lines.append("No checklist payload was provided.")
            return "\n".join(lines)

        for key in ordered_keys:
            item = checklist.get(key) if isinstance(checklist, dict) else None
            definition = definitions.get(key)
            if definition:
                lines.append(f"- **{key}**: {definition}")
            else:
                lines.append(f"- **{key}**")

            extracted = []
            if isinstance(item, dict):
                extracted = item.get("extracted") or []

            if not extracted:
                lines.append("  - Value: (empty)")
                continue

            for idx, extracted_item in enumerate(extracted, start=1):
                value = ""
                if isinstance(extracted_item, dict):
                    value = str(extracted_item.get("value") or "").strip()
                lines.append(f"  - Value {idx}: {value or '(empty)'}")

                evidence = extracted_item.get("evidence") if isinstance(extracted_item, dict) else []
                if not evidence:
                    lines.append("    - Evidence: (none)")
                    continue

                for ev in evidence:
                    if not isinstance(ev, dict):
                        continue
                    doc_id = ev.get("source_document_id", "?")
                    start_sentence = ev.get("start_sentence")
                    end_sentence = ev.get("end_sentence")
                    if start_sentence is not None and end_sentence is not None:
                        lines.append(
                            f"    - Evidence: doc_id={doc_id}, sentences={start_sentence}-{end_sentence}"
                        )
                    else:
                        start_offset = ev.get("start_offset")
                        end_offset = ev.get("end_offset")
                        lines.append(
                            f"    - Evidence: doc_id={doc_id}, offsets=[{start_offset}, {end_offset})"
                        )

        return "\n".join(lines)

    @staticmethod
    def _format_summary_state(snapshot: Dict[str, Any]) -> str:
        state = snapshot.get("summary_state") or {}
        paragraphs = state.get("paragraphs") or []
        summary_stats = state.get("summary_stats") or {}

        lines = [
            "## Current Summary Draft",
            f"Paragraph count: {summary_stats.get('paragraph_count', len(paragraphs))}",
            f"Character count: {summary_stats.get('character_count', 0)}",
        ]

        if not paragraphs:
            lines.append("(No paragraphs drafted yet.)")
            return "\n".join(lines)

        for idx, paragraph in enumerate(paragraphs):
            paragraph_id = paragraph.get("paragraph_id", f"p{idx:03d}")
            text = str(paragraph.get("text") or "").strip()
            lines.append(f"[{idx}] {paragraph_id}: {text}")

        return "\n".join(lines)

    @staticmethod
    def _format_documents(snapshot: Dict[str, Any]) -> str:
        documents = snapshot.get("documents") or []
        discovered = bool(snapshot.get("documents_discovered"))

        if not discovered:
            return "## Documents\nDocuments not listed yet. Call `list_documents` first."

        lines = ["## Documents"]
        if not documents:
            lines.append("No documents available.")
            return "\n".join(lines)

        for doc in documents:
            if hasattr(doc, "dict"):
                doc = doc.dict()
            if not isinstance(doc, dict):
                continue
            doc_id = doc.get("doc_id")
            doc_type = doc.get("type")
            sentence_count = doc.get("sentence_count")
            visited = doc.get("visited")
            coverage = doc.get("coverage") or {}
            ranges = coverage.get("sentence_ranges") if isinstance(coverage, dict) else None
            ranges_text = ""
            if ranges:
                range_parts = []
                for pair in ranges:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        range_parts.append(f"{pair[0]}-{pair[1]}")
                if range_parts:
                    ranges_text = f"; viewed={', '.join(range_parts)}"
            lines.append(
                f"- doc_id={doc_id} type={doc_type} sentences={sentence_count} visited={visited}{ranges_text}"
            )

        return "\n".join(lines)

    @staticmethod
    def _format_recent_actions(snapshot: Dict[str, Any]) -> str:
        actions = snapshot.get("action_tail") or []
        if not actions:
            return "## Recent Actions\n(No previous actions.)"

        lines = ["## Recent Actions"]
        for action in actions[-8:]:
            step = action.get("step")
            tool_name = action.get("tool_name")
            success = action.get("success")
            auto_generated = action.get("auto_generated")
            marker = "AUTO" if auto_generated else ""
            lines.append(f"- Step {step}: {tool_name} success={success} {marker}".strip())

            summary = action.get("result_summary")
            if summary:
                summary_json = json.dumps(summary, ensure_ascii=False)
                if len(summary_json) > 240:
                    summary_json = summary_json[:240] + "..."
                lines.append(f"  result={summary_json}")
            error = action.get("error")
            if error:
                lines.append(f"  error={error}")

        return "\n".join(lines)

    @staticmethod
    def _format_last_tool_result(tool_name: str, result: Dict[str, Any]) -> str:
        rendered = json.dumps(result, ensure_ascii=False)
        if len(rendered) > 2000:
            rendered = rendered[:2000] + "..."
        return f"## Last Tool Result\nTool: `{tool_name}`\nResult: {rendered}"

    @staticmethod
    def _should_show_stop_review(snapshot: Dict[str, Any]) -> bool:
        stop_count = int(snapshot.get("stop_count") or 0)
        first_stop_step = snapshot.get("first_stop_step")
        step = snapshot.get("step")
        if stop_count <= 0 or first_stop_step is None or step is None:
            return False
        return int(step) == int(first_stop_step) + 2
