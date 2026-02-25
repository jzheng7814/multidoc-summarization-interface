#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.documents import Document
from app.services.documents import list_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a case from Clearinghouse path and print one Document object."
    )
    parser.add_argument("--case-id", default="46094", help="Clearinghouse case id (default: 46094)")
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="0-based index in the sorted list returned by backend list_documents (default: 0)",
    )
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="Include full document content in JSON output.",
    )
    return parser.parse_args()


def _print_document(case_id: str, index: int, include_content: bool) -> None:
    documents = list_documents(case_id)
    if not documents:
        raise RuntimeError(f"No documents found for case {case_id}.")

    if index < 0 or index >= len(documents):
        raise IndexError(f"Index {index} out of range for {len(documents)} documents.")

    selected: Document = documents[index]
    payload = selected.model_dump(mode="json")
    if not include_content:
        content = payload.pop("content", "")
        payload["content_chars"] = len(content)

    print(
        json.dumps(
            {
                "case_id": str(case_id),
                "document_count": len(documents),
                "selected_index": index,
                "selected_document": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    args = parse_args()
    _print_document(case_id=str(args.case_id), index=int(args.index), include_content=bool(args.include_content))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
