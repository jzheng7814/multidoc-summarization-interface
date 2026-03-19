import unittest
from types import SimpleNamespace

from app.schemas.checklists import EvidenceCollection, EvidenceItem, EvidencePointer
from app.schemas.summary import SummaryRequest, SummarySlurmOptions
from app.services.summary_agent_payload import (
    build_summary_agent_checklist_payload,
    build_summary_agent_request_payload,
)


class _SettingsStub:
    cluster_summary_model_name = "unsloth/gpt-oss-20b-BF16"
    cluster_summary_max_steps = 200
    cluster_summary_reasoning_effort = "medium"
    cluster_summary_k_recent_tool_outputs = 5
    cluster_summary_prompt_config = None
    cluster_summary_focus_context_template_path = "app/resources/summary/focus_context.template.txt"
    cluster_summary_slurm_partition = "nlprx-lab"
    cluster_summary_slurm_qos = "short"


class SummaryAgentPayloadTests(unittest.TestCase):
    def test_build_request_payload_uses_defaults_and_full_checklist_shape(self):
        docs = [
            SimpleNamespace(
                id=155313,
                content="Document text",
                title="Complaint",
                type="Complaint",
                date="2025-02-12",
            )
        ]
        checklist = EvidenceCollection(
            items=[
                EvidenceItem(
                    bin_id="Filing_Date",
                    value="2025-02-12",
                    evidence=EvidencePointer(
                        document_id=155313,
                        start_offset=0,
                        end_offset=10,
                    ),
                )
            ]
        )
        checklist_definitions = {
            "Filing_Date": "The date the case was initially filed with the court.",
            "Appeal": "Any appeal or petition for appellate review in the case.",
        }
        request = SummaryRequest(
            summary_constraints=["Keep objective.", "  ", "Use plain narrative paragraphs."],
            slurm=SummarySlurmOptions(partition="nlprx-lab", qos="short"),
        )

        payload = build_summary_agent_request_payload(
            case_id="46110",
            case_title="United States v. Example",
            request_id="summary_46110_req",
            documents=docs,
            checklist_collection=checklist,
            checklist_definitions=checklist_definitions,
            request=request,
            settings=_SettingsStub(),
        )

        self.assertEqual(payload["request_id"], "summary_46110_req")
        self.assertEqual(payload["case"]["case_id"], "46110")
        self.assertEqual(payload["case"]["case_documents_id"], ["155313"])
        self.assertEqual(payload["model"], "unsloth/gpt-oss-20b-BF16")
        self.assertEqual(payload["max_steps"], 200)
        self.assertEqual(payload["reasoning_effort"], "medium")
        self.assertEqual(payload["k_recent_tool_outputs"], 5)
        self.assertEqual(payload["slurm"], {"partition": "nlprx-lab", "qos": "short"})
        self.assertEqual(
            payload["summary_constraints"],
            ["Keep objective.", "Use plain narrative paragraphs."],
        )
        self.assertIn("focus_context", payload)
        self.assertIn("United States v. Example", payload["focus_context"])

        # Canonical checklist payload includes all definition keys.
        self.assertIn("Filing_Date", payload["checklist"])
        self.assertIn("Appeal", payload["checklist"])
        self.assertEqual(payload["checklist"]["Appeal"]["extracted"], [])

        extracted = payload["checklist"]["Filing_Date"]["extracted"][0]
        self.assertEqual(extracted["value"], "2025-02-12")
        self.assertEqual(
            extracted["evidence"][0],
            {"source_document_id": "155313", "start_offset": 0, "end_offset": 10},
        )

    def test_build_checklist_payload_raises_on_missing_offsets(self):
        checklist = EvidenceCollection(
            items=[
                EvidenceItem(
                    bin_id="Filing_Date",
                    value="2025-02-12",
                    evidence=EvidencePointer(
                        document_id=155313,
                        start_offset=None,
                        end_offset=10,
                    ),
                )
            ]
        )

        with self.assertRaises(RuntimeError):
            build_summary_agent_checklist_payload(
                checklist,
                {"Filing_Date": "The date the case was initially filed with the court."},
            )


if __name__ == "__main__":
    unittest.main()
