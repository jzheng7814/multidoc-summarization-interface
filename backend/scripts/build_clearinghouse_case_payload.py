#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.schemas.documents import Document
from app.services.clearinghouse import (
    ClearinghouseClient,
    ClearinghouseError,
    ClearinghouseNotConfigured,
    ClearinghouseNotFound,
)


def _strip_html(raw: Optional[str]) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _document_sort_key(document: Document) -> tuple:
    if document.is_docket:
        return (0, document.id)
    date_value = _parse_date(document.date)
    if date_value is None:
        return (1, 1, 0, document.id)
    return (1, 0, -date_value.timestamp(), document.id)


def _normalize_case_url(case_detail: Dict[str, Any], case_id: str) -> str:
    raw = case_detail.get("clearinghouse_link")
    if isinstance(raw, str) and raw.strip():
        link = raw.strip()
        if link.startswith("http://") or link.startswith("https://"):
            return link
        return f"https://{link}"
    return f"https://clearinghouse.net/case/{case_id}"


def _resolve_case_type(case_detail: Dict[str, Any]) -> str:
    raw = case_detail.get("case_types")
    if isinstance(raw, list):
        labels = [str(item).strip() for item in raw if str(item).strip()]
        if labels:
            return "; ".join(labels)
    return "Unknown"


def _resolve_case_ongoing(case_detail: Dict[str, Any]) -> Optional[str]:
    raw = case_detail.get("case_ongoing")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _total_length_bin(total_tokens: int) -> str:
    if total_tokens >= 240_000:
        return "240K+"
    if total_tokens >= 120_000:
        return "120K"
    if total_tokens >= 32_000:
        return "32K"
    return str(total_tokens)


def build_case_payload(case_id: str) -> Dict[str, Any]:
    settings = get_settings()
    api_key = settings.clearinghouse_api_key
    if not api_key:
        raise ClearinghouseNotConfigured("LEGAL_CASE_CLEARINGHOUSE_API_KEY is not configured.")

    client = ClearinghouseClient(api_key=api_key)
    case_detail = client.fetch_case_detail(case_id)

    documents, _ = client.fetch_case_documents(case_id)
    sorted_documents = sorted(documents, key=_document_sort_key)

    doc_names: List[str] = []
    doc_texts: List[str] = []
    doc_titles: List[str] = []
    doc_types: List[str] = []
    doc_ids: List[int] = []
    doc_dates: List[Optional[str]] = []
    doc_token_counts: List[int] = []

    for index, document in enumerate(sorted_documents):
        doc_names.append(f"{case_id}-{index}")
        doc_texts.append(document.content or "")
        doc_titles.append(document.title or f"Document {document.id}")
        doc_types.append(document.type or "Unknown")
        doc_ids.append(int(document.id))
        doc_dates.append(document.date)
        doc_token_counts.append(_estimate_token_count(document.content or ""))

    total_token_num = sum(doc_token_counts)
    summary_long = _strip_html(case_detail.get("summary"))

    payload: Dict[str, Any] = {
        "case_id": str(case_id),
        "case_documents": doc_names,
        "case_documents_text": doc_texts,
        "case_documents_title": doc_titles,
        "case_documents_doc_type": doc_types,
        "case_documents_id": doc_ids,
        "case_documents_date": doc_dates,
        "case_documents_token_num": doc_token_counts,
        "case_type": _resolve_case_type(case_detail),
        "case_url": _normalize_case_url(case_detail, case_id),
        "filing_date": case_detail.get("filing_date"),
        "summary/long": summary_long,
        "total_length_bin": _total_length_bin(total_token_num),
        "total_token_num": total_token_num,
    }

    case_status = case_detail.get("case_status")
    if case_status is not None and str(case_status).strip():
        payload["case_status"] = str(case_status).strip()

    case_ongoing = _resolve_case_ongoing(case_detail)
    if case_ongoing is not None:
        payload["case_ongoing"] = case_ongoing

    terminating_date = case_detail.get("terminating_date")
    if terminating_date is not None and str(terminating_date).strip():
        payload["terminating_date"] = str(terminating_date).strip()

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one case from Clearinghouse and emit a one-case payload "
            "compatible with gavel full_case_data format."
        )
    )
    parser.add_argument("case_id", help="Clearinghouse case id, for example 46094")
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path. If omitted, print to stdout.",
    )
    parser.add_argument(
        "--object-only",
        action="store_true",
        help="Emit a single case object instead of a one-item list.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_id = str(args.case_id).strip()
    try:
        payload = build_case_payload(case_id)
    except (ClearinghouseNotConfigured, ClearinghouseNotFound, ClearinghouseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result: Any = payload if args.object_only else [payload]
    serialized = json.dumps(result, ensure_ascii=True, indent=None if args.compact else 2)

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote {output_path}")
    else:
        print(serialized)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
