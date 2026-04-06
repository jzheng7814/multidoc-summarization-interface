import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.schemas.checklists import EvidenceCollection, EvidenceItem, EvidencePointer
from app.schemas.documents import Document, DocumentReference
from app.schemas.summary import SummaryRequest
from app.services.checklist_engines import SpoofChecklistExtractionEngine
from app.services.summary_engines import SpoofSummaryGenerationEngine, SummaryRunInput


class SpoofEnginesTests(unittest.IsolatedAsyncioTestCase):
    async def test_spoof_checklist_engine_rejects_fixture_document_mismatch(self):
        with TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir)
            self._write_json(
                fixture_dir / "request.json",
                {"input": {"corpus_id": "46110", "documents": [{"document_id": "99"}]}},
            )
            self._write_events(
                fixture_dir / "events.ndjson",
                [
                    {"event_type": "completed", "data": {"state": "COMPLETED"}},
                ],
            )
            self._write_json(fixture_dir / "manifest.json", {})
            self._write_json(fixture_dir / "result_payload.json", {})
            self._write_json(fixture_dir / "checklist.json", {})
            self._write_json(fixture_dir / "document_map.json", {})

            settings = SimpleNamespace(
                cluster_spoof_extraction_fixture_dir=str(fixture_dir),
                cluster_spoof_event_delay_seconds=0.0,
            )
            engine = SpoofChecklistExtractionEngine(settings)

            with self.assertRaises(RuntimeError):
                await engine.run(
                    "backend_run_1",
                    "46110",
                    [
                        DocumentReference(
                            id=77,
                            title="Docket",
                            include_full_text=True,
                            content="Appeal filed.",
                        )
                    ],
                )

    async def test_spoof_checklist_engine_replays_events_and_returns_collection(self):
        with TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir)
            self._write_json(
                fixture_dir / "request.json",
                {"input": {"corpus_id": "46110", "documents": [{"document_id": "77"}]}},
            )
            self._write_events(
                fixture_dir / "events.ndjson",
                [
                    {"event_type": "started", "data": {"run_id": "run_1"}},
                    {"event_type": "slurm_state", "data": {"state": "RUNNING"}},
                    {"event_type": "completed", "data": {"run_id": "run_1", "state": "COMPLETED"}},
                ],
            )
            self._write_json(fixture_dir / "manifest.json", {})
            self._write_json(fixture_dir / "result_payload.json", {})
            self._write_json(
                fixture_dir / "checklist.json",
                {
                    "Appeal": {
                        "extracted": [
                            {
                                "value": "Appeal filed",
                                "evidence": [
                                    {"source_document_id": "77", "start_offset": 0, "end_offset": 6}
                                ],
                            }
                        ]
                    }
                },
            )
            self._write_json(
                fixture_dir / "document_map.json",
                {"by_source_document_id": {"77": "77"}, "documents": [{"doc_id": "77"}]},
            )

            seen_events = []
            settings = SimpleNamespace(
                cluster_spoof_extraction_fixture_dir=str(fixture_dir),
                cluster_spoof_event_delay_seconds=0.0,
            )
            engine = SpoofChecklistExtractionEngine(settings)
            result = await engine.run(
                "backend_run_2",
                "46110",
                [
                    DocumentReference(
                        id=77,
                        title="Docket",
                        include_full_text=True,
                        content="Appeal filed in circuit court.",
                    )
                ],
                progress_callback=lambda event_type, _: seen_events.append(event_type),
            )

            self.assertEqual(seen_events, ["started", "slurm_state", "completed"])
            self.assertEqual(len(result.collection.items), 1)
            self.assertEqual(result.collection.items[0].bin_id, "Appeal")
            self.assertEqual(result.collection.items[0].value, "Appeal filed")
            self.assertEqual(result.collection.items[0].evidence.document_id, 77)

    async def test_spoof_summary_engine_replays_events_and_returns_summary_result(self):
        with TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir)
            self._write_json(
                fixture_dir / "request.json",
                {"input": {"corpus_id": "46110", "documents": [{"document_id": "77"}]}},
            )
            self._write_events(
                fixture_dir / "events.ndjson",
                [
                    {"event_type": "started", "data": {"run_id": "run_1"}},
                    {"event_type": "slurm_submitted", "data": {"job_id": "123"}},
                    {
                        "event_type": "completed",
                        "data": {"run_id": "run_1", "job_id": "123", "state": "COMPLETED"},
                    },
                ],
            )
            self._write_json(fixture_dir / "manifest.json", {})
            self._write_json(
                fixture_dir / "result_payload.json",
                {"job_id": "123", "summary_stats": {"steps": 1}, "summary": "Mirror summary"},
            )
            self._write_json(
                fixture_dir / "summary.json",
                {"run_id": "run_1", "summary": "Canonical summary text", "summary_stats": {"steps": 1}},
            )

            seen_events = []
            settings = SimpleNamespace(
                cluster_spoof_summary_fixture_dir=str(fixture_dir),
                cluster_spoof_event_delay_seconds=0.0,
            )
            engine = SpoofSummaryGenerationEngine(settings)
            result = await engine.run(
                SummaryRunInput(
                    backend_run_id="backend_run_3",
                    corpus_id="46110",
                    run_title="Example Run",
                    documents=[
                        Document(
                            id=77,
                            title="Docket",
                            type=None,
                            description=None,
                            source=None,
                            ecf_number=None,
                            date=None,
                            is_docket=False,
                            content="Canonical text",
                        )
                    ],
                    checklist_collection=EvidenceCollection(
                        items=[
                            EvidenceItem(
                                bin_id="Appeal",
                                value="Appeal filed",
                                evidence=EvidencePointer(document_id=77, start_offset=0, end_offset=6),
                            )
                        ]
                    ),
                    checklist_definitions={"Appeal": "Whether an appeal was filed."},
                    request=SummaryRequest(),
                ),
                progress_callback=lambda event_type, _: seen_events.append(event_type),
            )

            self.assertEqual(seen_events, ["started", "slurm_submitted", "completed"])
            self.assertEqual(result.run_id, "run_1")
            self.assertEqual(result.job_id, "123")
            self.assertEqual(result.summary_text, "Canonical summary text")
            self.assertEqual(result.completion_stats, {"steps": 1})

    def _write_json(self, path: Path, payload) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _write_events(self, path: Path, events) -> None:
        lines = [json.dumps(event) for event in events]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
