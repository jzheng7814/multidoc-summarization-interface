#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Set

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func

from app.db.models import CaseDocument, CaseRecord, ChecklistItem, ChecklistRecord
from app.db.session import get_session


def _normalize_case_id(case_id: str) -> str:
    try:
        return str(int(case_id))
    except (TypeError, ValueError):
        return str(case_id).strip()


def _resolve_target_case_ids(*, case_ids: Iterable[str], uploaded_only: bool, all_cases: bool) -> List[str]:
    session = get_session()
    try:
        if all_cases:
            rows = session.query(CaseRecord.case_id).all()
            return sorted({_normalize_case_id(row[0]) for row in rows})

        if uploaded_only:
            rows = session.query(CaseRecord.case_id).all()
            resolved: Set[str] = set()
            for row in rows:
                value = _normalize_case_id(row[0])
                try:
                    if int(value) < 0:
                        resolved.add(value)
                except ValueError:
                    continue
            return sorted(resolved)

        explicit = {_normalize_case_id(case_id) for case_id in case_ids if str(case_id).strip()}
        return sorted(explicit)
    finally:
        session.close()


def _count_rows(case_ids: List[str]) -> dict[str, int]:
    if not case_ids:
        return {"cases": 0, "documents": 0, "checklist_records": 0, "checklist_items": 0}

    session = get_session()
    try:
        return {
            "cases": session.query(func.count(CaseRecord.case_id)).filter(CaseRecord.case_id.in_(case_ids)).scalar() or 0,
            "documents": session.query(func.count(CaseDocument.document_id)).filter(CaseDocument.case_id.in_(case_ids)).scalar()
            or 0,
            "checklist_records": session.query(func.count(ChecklistRecord.case_id))
            .filter(ChecklistRecord.case_id.in_(case_ids))
            .scalar()
            or 0,
            "checklist_items": session.query(func.count(ChecklistItem.id)).filter(ChecklistItem.case_id.in_(case_ids)).scalar()
            or 0,
        }
    finally:
        session.close()


def _delete_rows(case_ids: List[str], *, checklists_only: bool) -> dict[str, int]:
    session = get_session()
    try:
        deleted_checklist_items = (
            session.query(ChecklistItem).filter(ChecklistItem.case_id.in_(case_ids)).delete(synchronize_session=False)
        )
        deleted_checklist_records = (
            session.query(ChecklistRecord).filter(ChecklistRecord.case_id.in_(case_ids)).delete(synchronize_session=False)
        )

        deleted_documents = 0
        deleted_cases = 0
        if not checklists_only:
            deleted_documents = (
                session.query(CaseDocument).filter(CaseDocument.case_id.in_(case_ids)).delete(synchronize_session=False)
            )
            deleted_cases = (
                session.query(CaseRecord).filter(CaseRecord.case_id.in_(case_ids)).delete(synchronize_session=False)
            )

        session.commit()
        return {
            "deleted_cases": int(deleted_cases),
            "deleted_documents": int(deleted_documents),
            "deleted_checklist_records": int(deleted_checklist_records),
            "deleted_checklist_items": int(deleted_checklist_items),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear stored documents/checklists for repeatable extraction testing."
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Case ID to clear. Repeat for multiple IDs.",
    )
    parser.add_argument(
        "--uploaded-only",
        action="store_true",
        help="Clear all uploaded cases (negative case IDs only).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear all stored cases.",
    )
    parser.add_argument(
        "--checklists-only",
        action="store_true",
        help="Only clear checklist cache rows for target cases, keep documents.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    selector_count = sum(1 for flag in [bool(args.case_id), args.uploaded_only, args.all] if flag)
    if selector_count != 1:
        print("Error: choose exactly one selector: --case-id, --uploaded-only, or --all.", file=sys.stderr)
        return 2

    case_ids = _resolve_target_case_ids(
        case_ids=args.case_id,
        uploaded_only=bool(args.uploaded_only),
        all_cases=bool(args.all),
    )
    if not case_ids:
        print("No matching cases found. Nothing to clear.")
        return 0

    counts = _count_rows(case_ids)
    print(f"Target cases ({len(case_ids)}): {', '.join(case_ids)}")
    print(
        "Rows that match: "
        f"cases={counts['cases']}, documents={counts['documents']}, "
        f"checklist_records={counts['checklist_records']}, checklist_items={counts['checklist_items']}"
    )

    if not args.yes:
        action = "clear checklist rows" if args.checklists_only else "clear cases, documents, and checklist rows"
        answer = input(f"Proceed to {action}? Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Cancelled.")
            return 1

    deleted = _delete_rows(case_ids, checklists_only=bool(args.checklists_only))
    print(
        "Deleted rows: "
        f"cases={deleted['deleted_cases']}, documents={deleted['deleted_documents']}, "
        f"checklist_records={deleted['deleted_checklist_records']}, "
        f"checklist_items={deleted['deleted_checklist_items']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
