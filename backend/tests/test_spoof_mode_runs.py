from __future__ import annotations

import copy
import unittest

from fastapi import BackgroundTasks

from app.db.models import RunDocument, RunRecord
from app.db.session import get_session, init_db
from app.schemas.checklists import EvidenceCategoryCollection, EvidenceCollection, EvidenceItem, EvidencePointer
from app.schemas.documents import UploadManifestDocument
from app.schemas.runs import RunExtractionConfig
from app.services import runs as run_service


class SpoofModeRunsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        session = get_session()
        try:
            session.query(RunDocument).delete()
            session.query(RunRecord).delete()
            session.commit()
        finally:
            session.close()

    def test_create_empty_run_is_seeded_from_canonical_spoof_scenario(self) -> None:
        response = run_service.create_empty_run()

        self.assertEqual(response.source_type, "spoof_fixture")
        self.assertEqual(response.title, "National Treasury Employees Union v. Trump")
        self.assertEqual(len(response.documents), 12)
        self.assertEqual(response.documents[0].id, 60801)
        self.assertEqual(response.documents[0].title, "Main Docket (1:25-cv-00420)")

    async def test_setup_mutations_are_ignored_in_spoof_mode(self) -> None:
        response = run_service.create_empty_run()
        run_id = response.run_id
        original_document_ids = [doc.id for doc in response.documents]

        title_response = run_service.update_run_title(run_id, "Mutated Title")
        self.assertEqual(title_response.title, response.title)

        add_response = await run_service.add_run_document(
            run_id,
            UploadManifestDocument(
                name="Extra",
                date="2026-01-01",
                type="Complaint",
                file_name="extra.txt",
            ),
            self._upload_file("extra.txt", "extra document"),
        )
        self.assertEqual([doc.id for doc in add_response.documents], original_document_ids)

        delete_response = run_service.delete_run_document(run_id, original_document_ids[0])
        self.assertEqual([doc.id for doc in delete_response.documents], original_document_ids)

        current_extraction = run_service.get_extraction_config(run_id)
        mutated_extraction = RunExtractionConfig.model_validate(
            {
                "focusContext": "changed",
                "checklistSpec": current_extraction.checklist_spec.model_dump(mode="json", by_alias=True),
            }
        )
        extraction_response = run_service.update_extraction_config(run_id, mutated_extraction)
        self.assertEqual(extraction_response.focus_context, current_extraction.focus_context)

    async def test_start_extraction_ignores_frontend_override_config_in_spoof_mode(self) -> None:
        response = run_service.create_empty_run()
        run_id = response.run_id
        current_extraction = run_service.get_extraction_config(run_id)
        mutated_extraction = RunExtractionConfig.model_validate(
            {
                "focusContext": "changed",
                "checklistSpec": current_extraction.checklist_spec.model_dump(mode="json", by_alias=True),
            }
        )

        status = await run_service.start_extraction(run_id, BackgroundTasks(), mutated_extraction)

        self.assertEqual(status.extraction.status, "queued")
        self.assertEqual(
            run_service.get_extraction_config(run_id).focus_context,
            current_extraction.focus_context,
        )

    def test_checklist_updates_are_ignored_in_spoof_mode(self) -> None:
        response = run_service.create_empty_run()
        run_id = response.run_id
        first_category_key = response.extraction_config.checklist_spec.checklist_items[0].key
        first_document_id = response.documents[0].id
        collection = EvidenceCollection(
            items=[
                EvidenceItem(
                    bin_id=first_category_key,
                    value="Original value",
                    evidence=EvidencePointer(document_id=first_document_id, start_offset=0, end_offset=1),
                )
            ]
        )

        run_service._run_store.store_extraction_result(  # pylint: disable=protected-access
            run_id,
            extraction_result=collection.model_dump(mode="json", by_alias=False),
            remote_run_id="fixture_run",
            remote_job_id="fixture_job",
            remote_output_dir=None,
            manifest_path=None,
            result_payload_path=None,
            checklist_ndjson_path=None,
        )

        original_categories = run_service.get_checklist_categories(run_id)
        mutated_payload = EvidenceCategoryCollection.model_validate(copy.deepcopy(original_categories.model_dump()))
        mutated_payload.categories[0].values[0].value = "Changed value"
        mutated_payload.categories[0].values[0].text = "Changed value"

        updated = run_service.update_checklist_categories(run_id, mutated_payload)
        self.assertEqual(updated.model_dump(), original_categories.model_dump())

    @staticmethod
    def _upload_file(filename: str, content: str):
        from io import BytesIO

        from starlette.datastructures import UploadFile

        return UploadFile(BytesIO(content.encode("utf-8")), filename=filename)


if __name__ == "__main__":
    unittest.main()
