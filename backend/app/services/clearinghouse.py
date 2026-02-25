from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.eventing import get_event_producer
from app.schemas.documents import Document

producer = get_event_producer(__name__)

_INLINE_PAYLOAD_LIMIT = 10_000
_PAYLOAD_PREVIEW_LIMIT = 4_000
_BODY_PREVIEW_LIMIT = 2_000


def _safe_json_dump(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)


def _truncate_text(text: Optional[str], *, limit: int = _BODY_PREVIEW_LIMIT) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def _summarize_payload(payload: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    serialized = _safe_json_dump(payload)
    summary["payload_size"] = len(serialized)
    if len(serialized) <= _INLINE_PAYLOAD_LIMIT:
        summary["payload"] = payload
    else:
        preview = serialized[:_PAYLOAD_PREVIEW_LIMIT]
        suffix = f"... (+{len(serialized) - _PAYLOAD_PREVIEW_LIMIT} chars)" if len(serialized) > _PAYLOAD_PREVIEW_LIMIT else ""
        summary["payload_preview"] = f"{preview}{suffix}"
    return summary


def _count_results(payload: Any) -> Optional[int]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return len(results)
        return 1 if payload else 0
    if isinstance(payload, list):
        return len(payload)
    return None


def _log_file(record: Dict[str, Any]) -> None:
    producer.debug("Clearinghouse log record", {"record": record})

_API_BASE_URL = "https://clearinghouse.net/api/v2p1"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class ClearinghouseError(RuntimeError):
    """Base error raised for Clearinghouse integration issues."""


class ClearinghouseNotConfigured(ClearinghouseError):
    """Raised when the API key has not been configured."""


class ClearinghouseNotFound(ClearinghouseError):
    """Raised when a case could not be found on Clearinghouse."""


class ClearinghouseClient:
    """HTTP client for the Clearinghouse API."""

    def __init__(self, api_key: str, *, base_url: str = _API_BASE_URL, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if not api_key:
            raise ClearinghouseNotConfigured("Clearinghouse API key is required.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_case_documents(self, case_id: str) -> tuple[List[Document], Optional[str]]:
        """Return all documents (including docket) for the supplied case identifier."""
        case_detail = self._fetch_case(case_id)
        case_title = case_detail.get("name") if case_detail else None
        if not case_detail:
            raise ClearinghouseNotFound(f"Case not found on Clearinghouse for case_id={case_id}")

        case_documents_url = case_detail.get("case_documents_url")
        case_dockets_url = case_detail.get("case_dockets_url")
        if not case_documents_url or not case_dockets_url:
            raise ClearinghouseError(
                f"Clearinghouse case payload missing documents/dockets URLs for case {case_id}."
            )

        documents_payload = self._fetch_all_pages(case_documents_url)
        dockets_payload = self._fetch_all_pages(case_dockets_url)

        documents: List[Document] = []
        for raw_doc in documents_payload:
            try:
                documents.append(self._convert_document(raw_doc, case_title))
            except Exception:  # pylint: disable=broad-except
                producer.error(
                    "Failed to convert Clearinghouse document",
                    {"case_id": case_id, "document_id": raw_doc.get("id")},
                )

        for raw_docket in dockets_payload:
            try:
                docket_document = self._convert_docket(raw_docket, case_title)
                if docket_document is not None:
                    documents.append(docket_document)
            except Exception:  # pylint: disable=broad-except
                producer.error(
                    "Failed to convert Clearinghouse docket",
                    {"case_id": case_id, "document_id": raw_docket.get("id")},
                )

        _log_file(
            {
                "operation": "clearinghouse.case_documents.summary",
                "case_id": case_id,
                "case_title": case_title,
                "documents_api_count": len(documents_payload),
                "dockets_api_count": len(dockets_payload),
                "converted_count": len(documents),
            }
        )

        if not documents:
            raise ClearinghouseError(f"No documents were returned for case {case_id}.")
        return documents, case_title

    def fetch_case_detail(self, case_id: str) -> Dict[str, Any]:
        """Return raw case detail metadata from Clearinghouse for a single case id."""
        case_detail = self._fetch_case(case_id)
        if not case_detail:
            raise ClearinghouseNotFound(f"Case not found on Clearinghouse for case_id={case_id}")
        return case_detail

    def _headers(self) -> Dict[str, str]:
        return {
        'User-Agent': 'Chrome v22.2 Linux Ubuntu',
        'Authorization': f'Token {self._api_key}',
    }

    def _request(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self._base_url}{path}"
        return self._request_url(url, params=params, path=path)

    def _request_url(self, url: str, *, params: Optional[Dict[str, Any]] = None, path: Optional[str] = None) -> Any:
        request_path = path or url
        _log_file(
            {
                "operation": "clearinghouse.request",
                "path": request_path,
                "url": url,
                "params": params,
                "timeout_seconds": self._timeout,
            }
        )
        start = time.perf_counter()
        try:
            response = httpx.get(url, headers=self._headers(), params=params, timeout=self._timeout)
        except httpx.RequestError as exc:
            _log_file(
                {
                    "operation": "clearinghouse.request_error",
                    "path": request_path,
                    "url": url,
                    "params": params,
                    "error": str(exc),
                }
            )
            raise ClearinghouseError(f"Clearinghouse request error: {exc}") from exc

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        payload: Any = None
        payload_summary: Dict[str, Any] = {}
        parse_error: Optional[str] = None
        body_preview: Optional[str] = None

        try:
            payload = response.json()
            payload_summary = _summarize_payload(payload)
        except ValueError as exc:
            parse_error = str(exc)
            body_preview = _truncate_text(response.text)

        response_record: Dict[str, Any] = {
            "operation": "clearinghouse.response",
            "path": request_path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "params": params,
        }

        if payload is not None:
            result_count = _count_results(payload)
            if result_count is not None:
                response_record["result_count"] = result_count
            response_record.update(payload_summary)

        if parse_error:
            response_record["parse_error"] = parse_error
            if body_preview:
                response_record["body_preview"] = body_preview

        _log_file(response_record)

        if parse_error:
            raise ClearinghouseError(f"Clearinghouse response error: {parse_error}") from None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_record: Dict[str, Any] = {
                "operation": "clearinghouse.http_error",
                "path": request_path,
                "status_code": status,
                "params": params,
                "detail": str(exc),
                "elapsed_ms": elapsed_ms,
            }
            if payload_summary:
                error_record.update(payload_summary)
            elif body_preview:
                error_record["body_preview"] = body_preview
            _log_file(error_record)
            if status == 404:
                raise ClearinghouseNotFound(
                    f"Case not found on Clearinghouse (status 404) for params: {params}"
                ) from exc
            raise ClearinghouseError(f"Clearinghouse request failed with status {status}") from exc

        return payload

    def _fetch_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        # v2.1: /cases/?case_id={id}
        payload = self._request("/cases/", params={"case_id": case_id})
        results = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(results, list) and results:
            first = results[0]
            return first if isinstance(first, dict) else None
        return None

    def _fetch_all_pages(self, url: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        next_url: Optional[str] = url
        while next_url:
            payload = self._request_url(next_url)
            page_results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(page_results, list):
                results.extend([item for item in page_results if isinstance(item, dict)])
            next_url = payload.get("next") if isinstance(payload, dict) else None
        return results

    def _fetch_full_text(self, url: str) -> Optional[str]:
        """Fetch full text from the dedicated text URL."""
        if not url:
            return None
        try:
            # We use custom request logic here because text_url is absolute
            # and might return a large payload we want to handle carefully.
            # Using self._headers() ensures we stay authenticated.
            response = httpx.get(url, headers=self._headers(), timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data.get("text")
            return None
        except Exception: 
            # If fetching fails, we just don't have the text. 
            # Logging implicitly via exceptions if we want, but let's keep it quiet for now 
            # or log a warning.
            return None

    def _convert_document(self, raw: Dict[str, Any], case_title: Optional[str]) -> Document:
        document_id_raw = raw.get("id") or raw.get("document_id")
        if document_id_raw is None:
            raise ClearinghouseError("Clearinghouse document payload missing identifier.")
        try:
            document_id = int(document_id_raw)
        except (TypeError, ValueError) as exc:
            raise ClearinghouseError("Clearinghouse document identifier must be an integer.") from exc

        default_title = f"Document {document_id}"
        title = _normalise_string(raw.get("title")) or _normalise_string(raw.get("description")) or default_title
        description = _normalise_string(raw.get("description")) or case_title
        doc_type = (
            _normalise_string(raw.get("document_type_other"))
            or _normalise_string(raw.get("document_type"))
            or "Document"
        )
        doc_type = doc_type.replace("_", " ").strip().title()

        # Check if we need to fetch text separately
        text_url = raw.get("text_url")
        if not raw.get("text") and text_url:
            producer.info(
                "Fetching full text for document",
                {"document_id": document_id, "url": text_url},
            )
            fetched_text = self._fetch_full_text(text_url)
            if fetched_text:
                raw["text"] = fetched_text

        content = _render_document_content(raw)

        return Document(
            id=document_id,
            title=title,
            type=doc_type or "Document",
            description=description,
            source="clearinghouse",
            court=_normalise_string(raw.get("court")),
            state=_normalise_string(raw.get("state")),
            ecf_number=_normalise_string(raw.get("ecf_number")),
            date=_normalise_string(raw.get("date")),
            date_is_estimate=raw.get("date_is_estimate"),
            date_not_available=raw.get("date_not_available"),
            file_url=_normalise_string(raw.get("file")),
            external_url=_normalise_string(raw.get("external_url")),
            clearinghouse_link=_normalise_string(raw.get("clearinghouse_link")),
            text_url=_normalise_string(raw.get("text_url")),
            content=content,
        )

    def _convert_docket(self, raw: Dict[str, Any], case_title: Optional[str]) -> Optional[Document]:
        entries = raw.get("docket_entries")
        if not isinstance(entries, Iterable):
            return None

        docket_id_raw = raw.get("id")
        if docket_id_raw is None:
            return None
        try:
            docket_id = int(docket_id_raw)
        except (TypeError, ValueError):
            return None

        docket_number = _normalise_string(raw.get("docket_number_manual"))
        title = "Main Docket" if raw.get("is_main_docket") is True else "Docket"
        if docket_number:
            title = f"{title} ({docket_number})"
        description = _normalise_string(raw.get("court")) or case_title
        content = _render_docket_content(entries, raw)

        return Document(
            id=docket_id,
            title=title or "Case Docket",
            type="Docket",
            description=description,
            source="clearinghouse",
            court=_normalise_string(raw.get("court")),
            state=_normalise_string(raw.get("state")),
            is_docket=True,
            content=content,
        )


def _normalise_string(value: Any) -> Optional[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _render_document_content(raw: Dict[str, Any]) -> str:
    lines: List[str] = []
    metadata: List[str] = []

    date = _normalise_string(raw.get("date"))
    if date:
        metadata.append(f"Filed: {date}")
    court = _normalise_string(raw.get("court"))
    if court:
        metadata.append(f"Court: {court}")
    state = _normalise_string(raw.get("state"))
    if state:
        metadata.append(f"State: {state}")
    ecf_number = _normalise_string(raw.get("ecf_number"))
    if ecf_number:
        metadata.append(f"ECF: {ecf_number}")
    source = _normalise_string(raw.get("document_source"))
    if source:
        metadata.append(f"Source: {source}")
    status = _normalise_string(raw.get("document_status"))
    if status:
        metadata.append(f"Status: {status}")

    if metadata:
        lines.append("\n".join(metadata))

    text = raw.get("text")
    has_text = isinstance(text, str) and text.strip()

    if has_text:
        lines.append(text.strip())
    else:
        lines.append("No inline text was provided for this document.")

    return "\n\n".join(part for part in lines if part)


def _number_sort_key(value: Any) -> tuple:
    """Return a sortable key for possibly mixed-type numeric-ish values.

    Avoids comparing int vs str directly by returning a (group, value) tuple.
    """
    if isinstance(value, int):
        return (0, value)
    if isinstance(value, str):
        s = value.strip()
        try:
            return (0, int(s))
        except Exception:
            return (1, s)
    return (2, 0)


def _render_docket_content(entries: Iterable[Dict[str, Any]], docket: Dict[str, Any]) -> str:
    formatted_entries: List[str] = []
    sorted_entries = sorted(
        (entry for entry in entries if isinstance(entry, dict)),
        key=lambda item: (item.get("row_number") is None, item.get("row_number") or 0),
    )

    if not sorted_entries:
        return "No docket entries were returned for this case."

    header_parts: List[str] = []
    court = _normalise_string(docket.get("court"))
    state = _normalise_string(docket.get("state"))
    if court:
        header_parts.append(f"Court: {court}")
    if state:
        header_parts.append(f"State: {state}")
    header = "\n".join(header_parts) if header_parts else ""

    for index, entry in enumerate(sorted_entries, start=1):
        line_parts: List[str] = []

        row_number = entry.get("row_number")
        if row_number is not None:
            line_parts.append(f"Row: {row_number}")

        entry_id = _normalise_string(entry.get("entry_number")) or ""
        if entry_id:
            line_parts.append(f"Entry: {entry_id}")

        docket_entry_id = entry.get("id")
        if docket_entry_id is not None:
            line_parts.append(f"ID: {docket_entry_id}")

        date = _normalise_string(entry.get("date_filed"))
        if date:
            line_parts.append(f"Filed: {date}")

        pacer_doc_id = _normalise_string(entry.get("pacer_doc_id"))
        if pacer_doc_id:
            line_parts.append(f"PACER Doc ID: {pacer_doc_id}")

        description = _normalise_string(entry.get("description")) or "No description provided."
        line_parts.append(f"Description: {description}")

        formatted_entries.append(" | ".join(line_parts))

    if header:
        return "\n\n".join([header, *formatted_entries])
    return "\n\n".join(formatted_entries)
