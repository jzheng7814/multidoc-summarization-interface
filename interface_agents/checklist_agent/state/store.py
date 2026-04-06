"""
JSON-based storage for checklist state and action ledger.
Provides ChecklistStore and Ledger classes for persistent state management.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
from datetime import datetime
import pytz
from threading import Lock

from .schemas import (
    ChecklistItem, ChecklistPatch, Evidence, ExtractedItem,
    DocumentInfo, DocumentCoverage, DocumentReadInfo,
    ReadEvent, SearchEvent, UpdateEvent, LedgerEntry, ToolEvent,
    DerivedState, DerivedStateEntry,
)


class ChecklistStore:
    """
    Manages the checklist state with JSON persistence.
    Thread-safe for concurrent access.
    Supports dynamic checklist keys.
    """
    
    def __init__(self, storage_path: str = "checklist_store.json", checklist_keys: List[str] = None, checklist_config: Dict[str, Any] = None):
        """
        Initialize the checklist store.
        
        Args:
            storage_path: Path to JSON file for persistence
            checklist_keys: List of checklist keys to track (if None, uses empty checklist)
            checklist_config: Full configuration with keys and descriptions
        """
        self.storage_path = Path(storage_path)
        self.lock = Lock()
        self._checklist: Dict[str, ChecklistItem] = {}
        
        # Store checklist configuration
        if checklist_config:
            self.checklist_keys = list(checklist_config.keys())
            self.checklist_config = checklist_config
        elif checklist_keys:
            self.checklist_keys = checklist_keys
            self.checklist_config = {key: {} for key in checklist_keys}
        else:
            # Default empty if no keys provided
            self.checklist_keys = []
            self.checklist_config = {}
        
        self._initialize_checklist()
        self._load()
    
    def _initialize_checklist(self):
        """Initialize empty checklist with all configured keys."""
        for key in self.checklist_keys:
            self._checklist[key] = ChecklistItem(key=key)
    
    def _load(self):
        """Load checklist from JSON file if it exists."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for key, item_data in data.items():
                        if key in self.checklist_keys:
                            # Convert datetime strings back to datetime objects
                            if 'last_updated' in item_data:
                                # Parse the datetime string and ensure it has NYC timezone
                                dt = datetime.fromisoformat(item_data['last_updated'])
                                # If timezone-naive, assume it's NYC time
                                if dt.tzinfo is None:
                                    nyc_tz = pytz.timezone('America/New_York')
                                    dt = nyc_tz.localize(dt)
                                item_data['last_updated'] = dt
                            self._checklist[key] = ChecklistItem(**item_data)
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Could not load checklist from {self.storage_path}: {e}")
                print("Starting with empty checklist.")
    
    def _save(self):
        """Save checklist to JSON file. Should be called from within a lock context."""
        # Don't acquire lock here - this method is always called from within a locked context
        data = {}
        for key, item in self._checklist.items():
            item_dict = item.dict()
            # Convert datetime to ISO format string with timezone info
            if isinstance(item_dict['last_updated'], datetime):
                # Ensure datetime has NYC timezone
                dt = item_dict['last_updated']
                if dt.tzinfo is None:
                    nyc_tz = pytz.timezone('America/New_York')
                    dt = nyc_tz.localize(dt)
                item_dict['last_updated'] = dt.isoformat()
            data[key] = item_dict
        
        # Write with pretty formatting for readability
        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
    
    def get_checklist(self) -> List[ChecklistItem]:
        """
        Get the full checklist state.
        
        Returns:
            List of all checklist items
        """
        with self.lock:
            return list(self._checklist.values())
    
    def get_item(self, key: str) -> Optional[ChecklistItem]:
        """
        Get a specific checklist item.
        
        Args:
            key: The checklist key to retrieve
            
        Returns:
            The checklist item or None if key not found
        """
        with self.lock:
            return self._checklist.get(key)
    
    def update_items(self, patches: List[ChecklistPatch]) -> Tuple[List[str], List[str]]:
        """
        Apply patches to update checklist items.
        
        Args:
            patches: List of patches to apply
            
        Returns:
            Tuple of (updated_keys, validation_errors)
        """
        updated_keys = []
        validation_errors = []
        
        with self.lock:
            for patch in patches:
                if patch.key not in self.checklist_keys:
                    validation_errors.append(f"Unknown key: {patch.key}")
                    continue
                
                item = self._checklist[patch.key]
                
                # Apply the patch
                # Replace entire extracted list if provided
                if patch.extracted is not None:
                    # Validate each extracted item has evidence
                    has_error = False
                    for ext_item in patch.extracted:
                        if not ext_item.evidence:
                            validation_errors.append(
                                f"ExtractedItem for {patch.key} must have evidence"
                            )
                            has_error = True
                            break
                    if not has_error:
                        item.extracted = patch.extracted
                
                # Add to extracted list incrementally
                if patch.add_extracted is not None:
                    for ext_item in patch.add_extracted:
                        if not ext_item.evidence:
                            validation_errors.append(
                                f"ExtractedItem for {patch.key} must have evidence"
                            )
                            continue  # Skip this item but continue with others
                        # Check for duplicates based on value
                        existing_values = {e.value for e in item.extracted}
                        if ext_item.value not in existing_values:
                            item.extracted.append(ext_item)
                
                item.last_updated = datetime.now(pytz.timezone('America/New_York'))
                updated_keys.append(patch.key)
            
            # Save after all updates
            if updated_keys:
                self._save()
        
        return updated_keys, validation_errors
    
    def get_empty_keys(self) -> List[str]:
        """
        Get list of keys that have no extracted values.
        
        Returns:
            List of key names that are empty
        """
        empty_keys = []
        
        with self.lock:
            for key, item in self._checklist.items():
                if not item.extracted:
                    empty_keys.append(key)
        
        return empty_keys
    
    def get_completion_stats(self) -> Dict[str, int]:
        """
        Get completion statistics for the checklist.
        
        Returns:
            Dictionary with counts of filled, empty, and total
        """
        stats = {
            "filled": 0,  # Has extracted items
            "empty": 0,   # No extracted items
            "total": len(self.checklist_keys)
        }
        
        with self.lock:
            for item in self._checklist.values():
                if item.extracted:
                    stats["filled"] += 1
                else:
                    stats["empty"] += 1
        
        return stats
    
    def get_final_output(self) -> Dict[str, Dict[str, List]]:
        """
        Get the checklist in the final output format.
        
        Returns:
            Dictionary with each key mapped to {"extracted": [...]}
        """
        output = {}
        
        with self.lock:
            for key, item in self._checklist.items():
                if item.extracted:  # Only include keys with extracted values
                    output[key] = {
                        "extracted": [
                            {
                                "evidence": [
                                    {
                                        "source_document_id": ev.source_document_id,
                                        "start_sentence": ev.start_sentence,
                                        "end_sentence": ev.end_sentence
                                    }
                                    for ev in ext_item.evidence
                                ],
                                "value": ext_item.value
                            }
                            for ext_item in item.extracted
                        ]
                    }
        
        return output
    
    def reset(self):
        """Reset the checklist to initial empty state."""
        with self.lock:
            self._initialize_checklist()
            self._save()


class DerivedStateStore:
    """Persistent derived-state board for native runtime memory."""

    BUCKETS = ("confirmed_state", "open_questions", "external_refs")
    MAX_PINNED_PER_BUCKET = 5

    def __init__(self, storage_path: str = "derived_state.json"):
        self.storage_path = Path(storage_path)
        self.lock = Lock()
        self._state = DerivedState()
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._state = DerivedState(**(payload or {}))
        except Exception as e:
            print(f"Warning: Could not load derived state from {self.storage_path}: {e}")
            self._state = DerivedState()

    def _save(self) -> None:
        payload = self._state.dict()
        for bucket in self.BUCKETS:
            serialized = []
            for entry in payload.get(bucket, []):
                item = dict(entry)
                ts = item.get("last_updated")
                if isinstance(ts, datetime):
                    item["last_updated"] = ts.isoformat()
                serialized.append(item)
            payload[bucket] = serialized

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def reset(self) -> None:
        with self.lock:
            self._state = DerivedState()
            self._save()

    def get_state(self, include_unpinned: bool = False) -> DerivedState:
        with self.lock:
            if include_unpinned:
                return DerivedState(**self._state.dict())

            filtered: Dict[str, List[Dict[str, Any]]] = {}
            for bucket in self.BUCKETS:
                entries = [
                    entry.dict()
                    for entry in getattr(self._state, bucket, [])
                    if entry.pinned
                ]
                filtered[bucket] = entries
            return DerivedState(**filtered)

    def _normalize_entry_text(self, text: str) -> str:
        return " ".join(text.split()).strip().lower()

    def _build_response(self, updated_buckets: Set[str], validation_errors: List[str]) -> Dict[str, Any]:
        pinned_counts = {
            bucket: sum(1 for e in getattr(self._state, bucket, []) if e.pinned)
            for bucket in self.BUCKETS
        }
        def _serialize_entry(entry: DerivedStateEntry) -> Dict[str, Any]:
            payload = entry.dict()
            ts = payload.get("last_updated")
            if isinstance(ts, datetime):
                payload["last_updated"] = ts.isoformat()
            return payload

        pinned_state = {
            bucket: [
                _serialize_entry(entry)
                for entry in getattr(self._state, bucket, [])
                if entry.pinned
            ]
            for bucket in self.BUCKETS
        }
        return {
            "updated_buckets": sorted(updated_buckets),
            "validation_errors": validation_errors,
            "success": len(validation_errors) == 0,
            "max_pinned_per_bucket": self.MAX_PINNED_PER_BUCKET,
            "pinned_counts": pinned_counts,
            "derived_state": pinned_state,
        }

    def apply_change(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a single derived-state change.

        Contract:
        - action: upsert | remove
        - bucket: confirmed_state | open_questions | external_refs
        - text: entry text
        - source_document_ids: list[str] (required non-empty for confirmed_state upsert)
        """
        validation_errors: List[str] = []
        updated_buckets: Set[str] = set()

        with self.lock:
            if not isinstance(change, dict):
                return self._build_response(set(), ["change must be an object"])

            bucket = str(change.get("bucket") or "").strip()
            if bucket not in self.BUCKETS:
                validation_errors.append(f"bucket must be one of: {', '.join(self.BUCKETS)}")

            action = str(change.get("action") or "").strip().lower()
            if action not in {"upsert", "remove"}:
                validation_errors.append("action must be one of: upsert, remove")

            text = str(change.get("text") or "").strip()
            if not text:
                validation_errors.append("text is required")

            source_document_ids_raw = change.get("source_document_ids", [])
            if source_document_ids_raw is None:
                source_document_ids_raw = []
            if not isinstance(source_document_ids_raw, list):
                validation_errors.append("source_document_ids must be an array")
                source_document_ids_raw = []

            source_document_ids: List[str] = []
            for doc_idx, doc_id in enumerate(source_document_ids_raw):
                doc_val = str(doc_id).strip()
                if not doc_val:
                    validation_errors.append(f"source_document_ids[{doc_idx}] must be non-empty")
                    continue
                source_document_ids.append(doc_val)

            if validation_errors:
                return self._build_response(updated_buckets, validation_errors)

            entries = list(getattr(self._state, bucket))
            normalized_text = self._normalize_entry_text(text)

            matching_indices = [
                i for i, e in enumerate(entries)
                if self._normalize_entry_text(e.text) == normalized_text
            ]

            if action == "remove":
                if matching_indices:
                    for idx in reversed(matching_indices):
                        entries.pop(idx)
                    setattr(self._state, bucket, entries)
                    updated_buckets.add(bucket)
                    self._save()
                return self._build_response(updated_buckets, validation_errors)

            # action == upsert
            if bucket == "confirmed_state" and not source_document_ids:
                validation_errors.append(
                    "confirmed_state upserts require at least one source_document_id"
                )
                return self._build_response(updated_buckets, validation_errors)

            now = datetime.now(pytz.timezone('America/New_York'))
            if matching_indices:
                idx = matching_indices[0]
                existing = entries[idx]
                entries[idx] = DerivedStateEntry(
                    id=existing.id,
                    text=text,
                    source_document_ids=source_document_ids,
                    pinned=True,
                    last_updated=now,
                )
            else:
                pinned_count = sum(1 for e in entries if e.pinned)
                if pinned_count >= self.MAX_PINNED_PER_BUCKET:
                    validation_errors.append(
                        f"`{bucket}` already has {self.MAX_PINNED_PER_BUCKET} pinned entries; remove one first"
                    )
                    return self._build_response(updated_buckets, validation_errors)
                entry_id_seed = f"{bucket}:{normalized_text}"
                entry_id = f"entry_{hashlib.sha1(entry_id_seed.encode('utf-8')).hexdigest()[:12]}"
                entries.append(
                    DerivedStateEntry(
                        id=entry_id,
                        text=text,
                        source_document_ids=source_document_ids,
                        pinned=True,
                        last_updated=now,
                    )
                )

            setattr(self._state, bucket, entries)
            updated_buckets.add(bucket)
            self._save()
            return self._build_response(updated_buckets, validation_errors)

    def apply_operations(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Backward-compatible multi-operation wrapper.
        Prefer apply_change() for single-change calls.
        """
        if not isinstance(operations, list):
            with self.lock:
                return self._build_response(set(), ["operations must be an array"])

        merged_updated: Set[str] = set()
        merged_errors: List[str] = []
        for idx, op in enumerate(operations):
            result = self.apply_change(op)
            merged_updated.update(result.get("updated_buckets", []))
            for err in result.get("validation_errors", []):
                merged_errors.append(f"operations[{idx}]: {err}")

        with self.lock:
            return self._build_response(merged_updated, merged_errors)


class Ledger:
    """
    Append-only ledger for tracking all reads, searches, and updates.
    Provides coverage statistics and audit trail.
    """
    
    def __init__(self, storage_path: str = "ledger.jsonl"):
        """
        Initialize the ledger.
        
        Args:
            storage_path: Path to JSONL file for append-only storage
        """
        self.storage_path = Path(storage_path)
        self.lock = Lock()
        self._document_coverage: Dict[str, DocumentCoverage] = {}
        self._last_reads: Dict[str, DocumentReadInfo] = {}
        self._load_coverage()
    
    def _add_sentence_range(self, doc_id: str, start_sentence: int, end_sentence: int):
        """
        Add a sentence range to document coverage, merging overlapping ranges.
        
        Args:
            doc_id: Document ID
            start_sentence: Inclusive start sentence
            end_sentence: Inclusive end sentence
        """
        if doc_id not in self._document_coverage:
            self._document_coverage[doc_id] = DocumentCoverage()
        
        coverage = self._document_coverage[doc_id]
        new_range = (start_sentence, end_sentence)
        
        # Add new range and merge overlapping ones
        ranges = coverage.sentence_ranges + [new_range]
        coverage.sentence_ranges = self._merge_ranges(ranges)
    
    def _merge_ranges(self, ranges: List[tuple]) -> List[tuple]:
        """
        Merge overlapping sentence ranges.
        
        Args:
            ranges: List of (start, end) tuples
            
        Returns:
            Merged list of non-overlapping ranges
        """
        if not ranges:
            return []
        
        # Sort ranges by start position
        sorted_ranges = sorted(ranges)
        merged = [sorted_ranges[0]]
        
        for current_start, current_end in sorted_ranges[1:]:
            last_start, last_end = merged[-1]
            
            # Check if ranges overlap or are adjacent
            if current_start <= last_end + 1:
                # Merge ranges
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                # Add as separate range
                merged.append((current_start, current_end))
        
        return merged
    
    def _load_coverage(self):
        """Load and compute coverage from existing ledger entries."""
        if not self.storage_path.exists():
            return
        
        try:
            with open(self.storage_path, 'r') as f:
                for line in f:
                    entry_data = json.loads(line)
                    # Only use event_name (actual tool names)
                    event_name = entry_data.get('event_name', '')
                    
                    if event_name == 'read_document':
                        event = entry_data['event']
                        doc_id = event['doc_id']
                        
                        if doc_id not in self._document_coverage:
                            self._document_coverage[doc_id] = DocumentCoverage()
                        
                        # Update coverage
                        self._document_coverage[doc_id].windows_read += 1
                        sentences_read = event['end_sentence'] - event['start_sentence'] + 1
                        self._document_coverage[doc_id].approx_sentences_read += sentences_read
                        
                        # Add sentence range.
                        self._add_sentence_range(doc_id, event['start_sentence'], event['end_sentence'])
                        
                        # Update last read
                        self._last_reads[doc_id] = DocumentReadInfo(
                            start_sentence=event['start_sentence'],
                            end_sentence=event['end_sentence']
                        )
                    
                    elif event_name == 'search_document_regex':
                        event = entry_data['event']
                        # Mark documents as visited and add sentence ranges from matches.
                        for doc_id, match_ranges in event.get('document_matches', {}).items():
                            if match_ranges:
                                if doc_id not in self._document_coverage:
                                    self._document_coverage[doc_id] = DocumentCoverage()
                                for range_data in match_ranges:
                                    if isinstance(range_data, (list, tuple)) and len(range_data) == 2:
                                        self._add_sentence_range(doc_id, range_data[0], range_data[1])
        except Exception as e:
            print(f"Warning: Could not load ledger from {self.storage_path}: {e}")
    
    def _append_entry(self, entry: LedgerEntry):
        """Append an entry to the JSONL ledger file."""
        entry_dict = entry.dict()
        # Convert datetime to ISO format
        if 'event' in entry_dict:
            if 'timestamp' in entry_dict['event']:
                entry_dict['event']['timestamp'] = entry_dict['event']['timestamp'].isoformat()
        
        with open(self.storage_path, 'a') as f:
            f.write(json.dumps(entry_dict) + '\n')
    
    def record_read(self, read_event: ReadEvent, run_id: str):
        """
        Record a document read event.
        
        Args:
            read_event: The read event to record
            run_id: Current run ID
        """
        with self.lock:
            # Update coverage
            doc_id = read_event.doc_id
            if doc_id not in self._document_coverage:
                self._document_coverage[doc_id] = DocumentCoverage()
            
            self._document_coverage[doc_id].windows_read += 1
            self._document_coverage[doc_id].approx_sentences_read += read_event.sentences_read
            
            # Add sentence range to coverage.
            self._add_sentence_range(doc_id, read_event.start_sentence, read_event.end_sentence)
            
            # Update last read
            self._last_reads[doc_id] = DocumentReadInfo(
                start_sentence=read_event.start_sentence,
                end_sentence=read_event.end_sentence
            )
            
            # Append to ledger with tool name
            entry = LedgerEntry(
                event_name="read_document",  # Use actual tool name
                event=read_event,
                run_id=run_id,
                step=read_event.step
            )
            self._append_entry(entry)
    
    def record_search(self, search_event: SearchEvent, run_id: str):
        """
        Record a regex search event (single or multi-document).
        
        Args:
            search_event: The search event to record
            run_id: Current run ID
        """
        with self.lock:
            # Update coverage for each document with matches
            for doc_id, match_ranges in search_event.document_matches.items():
                if match_ranges:  # Has matches
                    # Initialize coverage if needed
                    if doc_id not in self._document_coverage:
                        self._document_coverage[doc_id] = DocumentCoverage()
                    
                    # Add sentence ranges from all matches.
                    for start_sentence, end_sentence in match_ranges:
                        self._add_sentence_range(doc_id, start_sentence, end_sentence)
            
            # Always append single entry to ledger (even if no matches)
            entry = LedgerEntry(
                event_name="search_document_regex",  # Use actual tool name
                event=search_event,
                run_id=run_id,
                step=search_event.step
            )
            self._append_entry(entry)
    
    def record_update(self, update_event: UpdateEvent, run_id: str):
        """
        Record a checklist update event.
        
        Args:
            update_event: The update event to record
            run_id: Current run ID
        """
        with self.lock:
            # Determine tool name based on the update type
            # If patch has add_extracted, it's append_checklist, otherwise update_checklist
            tool_name = "update_checklist"  # Default
            if update_event.patch and len(update_event.patch) > 0:
                first_patch = update_event.patch[0]
                if hasattr(first_patch, 'add_extracted') and first_patch.add_extracted:
                    tool_name = "append_checklist"
            
            entry = LedgerEntry(
                event_name=tool_name,  # Use actual tool name
                event=update_event,
                run_id=run_id,
                step=update_event.step
            )
            self._append_entry(entry)
    
    def record_tool(self, tool_name: str, args: Dict[str, Any], result: Optional[Dict[str, Any]], 
                    step: int, run_id: str, success: bool = True):
        """
        Record a generic tool execution event.
        
        Args:
            tool_name: Name of the tool executed
            args: Arguments passed to the tool
            result: Result returned by the tool
            step: Current step number
            run_id: Current run ID
            success: Whether the tool execution was successful
        """
        with self.lock:
            tool_event = ToolEvent(
                tool_name=tool_name,
                args=args,
                result=result,
                step=step,
                success=success
            )
            
            entry = LedgerEntry(
                event_name=tool_name,
                event=tool_event,
                run_id=run_id,
                step=step
            )
            self._append_entry(entry)
    
    def get_document_coverage(self, doc_id: str) -> Optional[DocumentCoverage]:
        """
        Get coverage statistics for a document.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Coverage statistics or None if document not visited
        """
        with self.lock:
            return self._document_coverage.get(doc_id)
    
    def get_last_read(self, doc_id: str) -> Optional[DocumentReadInfo]:
        """
        Get the last read position for a document.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Last read info or None if document not read
        """
        with self.lock:
            return self._last_reads.get(doc_id)
    
    def get_visited_documents(self) -> Set[str]:
        """
        Get the set of all visited document IDs.
        
        Returns:
            Set of document IDs that have been read
        """
        with self.lock:
            return set(self._document_coverage.keys())
    
    def get_all_events(self) -> List[Dict]:
        """
        Get all events from the ledger.
        
        Returns:
            List of all event records
        """
        if not self.storage_path.exists():
            return []
        
        events = []
        with open(self.storage_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    # Return simplified event
                    event = {
                        "tool": entry.get('event_name', ''),
                        "step": entry.get('step', 0),
                        "timestamp": entry.get('timestamp', '')
                    }
                    if 'event' in entry and isinstance(entry['event'], dict):
                        event.update(entry['event'])
                    events.append(event)
                except:
                    continue
        
        return events
    
    def get_recent_actions(self, limit: int = 10) -> List[Dict]:
        """
        Get the most recent actions from the ledger.
        
        Args:
            limit: Maximum number of actions to return
            
        Returns:
            List of recent action records
        """
        if not self.storage_path.exists():
            return []
        
        actions = []
        with open(self.storage_path, 'r') as f:
            # Read all lines (could optimize with deque for large files)
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    entry = json.loads(line)
                    # Simplified action record
                    # Only use event_name (actual tool names)
                    event_name = entry.get('event_name', '')
                    
                    action = {
                        "tool": event_name,  # Use the actual tool name
                        "step": entry['step'],
                        "timestamp": entry['event'].get('timestamp', '')
                    }
                    
                    # Handle different event types based on actual tool names
                    if event_name == 'read_document':
                        action['target'] = {
                            "doc_id": entry['event']['doc_id'],
                            "start_sentence": entry['event']['start_sentence'],
                            "end_sentence": entry['event']['end_sentence']
                        }
                        if 'purpose' in entry['event']:
                            action['purpose'] = entry['event']['purpose']
                    elif event_name == 'search_document_regex':
                        action['target'] = {
                            "doc_id": entry['event'].get('doc_id'),
                            "doc_ids": entry['event'].get('doc_ids'),
                            "pattern": entry['event']['pattern']
                        }
                        action['hits'] = entry['event']['matches_found']
                    elif event_name in ['update_checklist', 'append_checklist']:
                        action['changed_keys'] = entry['event']['keys_updated']
                    elif event_name == 'list_documents':
                        # For list_documents, just record it was called
                        if 'result' in entry['event'] and 'documents' in entry['event']['result']:
                            action['documents_found'] = len(entry['event']['result']['documents'])
                    elif event_name == 'get_checklist':
                        # For get_checklist, record what was requested
                        if 'args' in entry['event']:
                            action['items_requested'] = entry['event']['args'].get('items') or entry['event']['args'].get('item', 'all')
                    
                    actions.append(action)
                except:
                    continue
        
        return actions
    
    def reset(self):
        """Reset the ledger (creates backup if file exists)."""
        with self.lock:
            if self.storage_path.exists():
                # Create backup
                backup_path = self.storage_path.with_suffix(
                    f".backup_{datetime.now(pytz.timezone('America/New_York')).isoformat()}.jsonl"
                )
                os.rename(self.storage_path, backup_path)
            
            self._document_coverage = {}
            self._last_reads = {}
