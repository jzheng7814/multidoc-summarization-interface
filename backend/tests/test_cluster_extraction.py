import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.documents import DocumentReference
from app.services.cluster_extraction import ClusterChecklistRunner


class _FakeStream:
    def __init__(self, lines):
        encoded = []
        for line in lines:
            if isinstance(line, str):
                encoded.append((line + "\n").encode("utf-8"))
            else:
                encoded.append(line)
        self._lines = encoded

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeStdin:
    def __init__(self):
        self.buffer = bytearray()
        self.closed = False

    def write(self, data):
        self.buffer.extend(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, stdout_lines, stderr_lines=None, return_code=0):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(stderr_lines or [])
        self._return_code = return_code

    async def wait(self):
        return self._return_code


class ClusterChecklistRunnerTests(unittest.TestCase):
    def test_run_parses_completed_payload_and_maps_document_ids(self):
        completed_event = {
            "event_type": "completed",
            "request_id": "req_1",
            "seq": 4,
            "timestamp": "2026-02-25T00:00:00+00:00",
            "data": {
                "job_id": "100",
                "state": "COMPLETED",
                "output_dir": "/tmp/out",
                "document_map": {
                    "by_source_document_id": {
                        "77": "77",
                    }
                },
                "checklist": {
                    "Appeal": {
                        "extracted": [
                            {
                                "value": "Appeal filed",
                                "evidence": [
                                    {
                                        "source_document_id": "77",
                                        "start_offset": 0,
                                        "end_offset": 6,
                                    }
                                ],
                            }
                        ]
                    }
                },
            },
        }

        stdout_lines = [
            json.dumps(
                {
                    "event_type": "started",
                    "request_id": "req_1",
                    "seq": 1,
                    "timestamp": "2026-02-25T00:00:00+00:00",
                    "data": {"mode": "slurm_extract"},
                }
            ),
            json.dumps(
                {
                    "event_type": "step_completed",
                    "request_id": "req_1",
                    "seq": 2,
                    "timestamp": "2026-02-25T00:00:01+00:00",
                    "data": {"step": 1, "tool_name": None, "success": None},
                }
            ),
            json.dumps(
                {
                    "event_type": "slurm_state",
                    "request_id": "req_1",
                    "seq": 3,
                    "timestamp": "2026-02-25T00:00:02+00:00",
                    "data": {"job_id": "100", "state": "RUNNING"},
                }
            ),
            json.dumps(completed_event),
        ]

        fake_process = _FakeProcess(stdout_lines=stdout_lines, return_code=0)

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return fake_process

        runner = ClusterChecklistRunner()
        runner._settings.cluster_ssh_host = "headnode"
        runner._settings.cluster_remote_stage_root = "/tmp/stages"
        runner._settings.cluster_remote_python_path = "/tmp/python"
        runner._settings.cluster_remote_controller_script = "controller.py"
        runner._settings.cluster_poll_seconds = 2
        runner._settings.cluster_max_wait_seconds = 60

        documents = [
            DocumentReference(
                id=77,
                title="Docket",
                include_full_text=True,
                content="Appeal filed in circuit court.",
            )
        ]

        with (
            patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec),
            patch.object(
                runner._stage_manager,
                "prepare_stage",
                return_value=SimpleNamespace(run_dir="/remote/stage"),
            ) as mocked_prepare_stage,
            patch.object(runner._stage_manager, "build_remote_command", return_value="remote command"),
        ):
            result = asyncio.run(runner.run("backend_run_1", "46210", documents))

        mocked_prepare_stage.assert_called_once_with("backend_run_1")
        self.assertEqual(len(result.collection.items), 1)
        self.assertEqual(result.collection.items[0].bin_id, "Appeal")
        self.assertEqual(result.collection.items[0].value, "Appeal filed")
        self.assertEqual(result.collection.items[0].evidence.document_id, 77)
        self.assertEqual(result.collection.items[0].evidence.start_offset, 0)
        self.assertEqual(result.collection.items[0].evidence.end_offset, 6)

        stdin_payload = json.loads(fake_process.stdin.buffer.decode("utf-8"))
        self.assertEqual(stdin_payload["input"]["corpus_id"], "46210")
        self.assertEqual(stdin_payload["input"]["documents"][0]["document_id"], "77")
        self.assertEqual(stdin_payload["checklist_strategy"], "individual")
        self.assertIn("checklist_spec", stdin_payload)
        self.assertIn("focus_context", stdin_payload)
        self.assertIsInstance(stdin_payload["focus_context"], str)
        self.assertTrue(stdin_payload["focus_context"].strip())
        self.assertNotIn("checklist_config", stdin_payload)
        self.assertNotIn("max_steps", stdin_payload)
        self.assertNotIn("reasoning_effort", stdin_payload)
        checklist_items = stdin_payload["checklist_spec"]["checklist_items"]
        self.assertIsInstance(checklist_items, list)
        self.assertGreater(len(checklist_items), 0)
        first_item = checklist_items[0]
        self.assertIn("key", first_item)
        self.assertIn("description", first_item)
        self.assertIn("user_instruction", first_item)
        self.assertIn("constraints", first_item)
        self.assertIn("max_steps", first_item)
        self.assertIn("reasoning_effort", first_item)

    def test_run_loads_artifacts_when_completed_event_omits_inline_checklist(self):
        completed_event = {
            "event_type": "completed",
            "request_id": "req_3",
            "seq": 4,
            "timestamp": "2026-02-25T00:00:00+00:00",
            "data": {
                "run_id": "run_20260225T000000Z_deadbeef00",
                "run_dir": "/remote/controller/runs/run_20260225T000000Z_deadbeef00",
                "manifest_path": "/remote/controller/runs/run_20260225T000000Z_deadbeef00/manifest.json",
                "job_id": "200",
                "state": "COMPLETED",
                "output_dir": "/tmp/out",
            },
        }

        stdout_lines = [
            json.dumps(
                {
                    "event_type": "started",
                    "request_id": "req_3",
                    "seq": 1,
                    "timestamp": "2026-02-25T00:00:00+00:00",
                    "data": {"mode": "slurm_extract"},
                }
            ),
            json.dumps(
                {
                    "event_type": "slurm_state",
                    "request_id": "req_3",
                    "seq": 2,
                    "timestamp": "2026-02-25T00:00:01+00:00",
                    "data": {"job_id": "200", "state": "RUNNING"},
                }
            ),
            json.dumps(completed_event),
        ]

        fake_process = _FakeProcess(stdout_lines=stdout_lines, return_code=0)

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return fake_process

        runner = ClusterChecklistRunner()
        documents = [
            DocumentReference(
                id=21,
                title="Complaint",
                include_full_text=True,
                content="Complaint text",
            )
        ]
        artifact_checklist = {
            "Remedy_Sought": {
                "extracted": [
                    {
                        "value": "Plaintiff: Injunction",
                        "evidence": [
                            {
                                "source_document_id": "21",
                                "start_offset": 2,
                                "end_offset": 8,
                            }
                        ],
                    }
                ]
            }
        }
        artifact_document_map = {
            "by_source_document_id": {"21": "21"},
            "documents": [{"doc_id": "21"}],
        }

        with (
            patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec),
            patch.object(
                runner._stage_manager,
                "prepare_stage",
                return_value=SimpleNamespace(run_dir="/remote/stage"),
            ),
            patch.object(runner._stage_manager, "build_remote_command", return_value="remote command"),
            patch.object(
                runner,
                "_load_artifact_payload_from_completed_event",
                return_value=(artifact_checklist, artifact_document_map),
            ) as mocked_loader,
        ):
            result = asyncio.run(runner.run("backend_run_2", "400", documents))

        mocked_loader.assert_called_once()
        self.assertEqual(len(result.collection.items), 1)
        self.assertEqual(result.collection.items[0].bin_id, "Remedy_Sought")
        self.assertEqual(result.collection.items[0].evidence.document_id, 21)
        self.assertEqual(result.collection.items[0].evidence.start_offset, 2)

    def test_run_raises_on_failed_terminal_event(self):
        stdout_lines = [
            json.dumps(
                {
                    "event_type": "started",
                    "request_id": "req_2",
                    "seq": 1,
                    "timestamp": "2026-02-25T00:00:00+00:00",
                    "data": {"mode": "slurm_extract"},
                }
            ),
            json.dumps(
                {
                    "event_type": "failed",
                    "request_id": "req_2",
                    "seq": 2,
                    "timestamp": "2026-02-25T00:00:01+00:00",
                    "data": {"state": "FAILED", "error": "mock failure"},
                }
            ),
        ]
        fake_process = _FakeProcess(stdout_lines=stdout_lines, return_code=1)

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return fake_process

        runner = ClusterChecklistRunner()
        documents = [
            DocumentReference(
                id=10,
                title="Doc",
                include_full_text=True,
                content="text",
            )
        ]

        with (
            patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec),
            patch.object(
                runner._stage_manager,
                "prepare_stage",
                return_value=SimpleNamespace(run_dir="/remote/stage"),
            ),
            patch.object(runner._stage_manager, "build_remote_command", return_value="remote command"),
        ):
            with self.assertRaises(RuntimeError) as exc:
                asyncio.run(runner.run("backend_run_3", "100", documents))

        self.assertIn("mock failure", str(exc.exception))

    def test_validate_remote_run_dir_rejects_unexpected_path(self):
        runner = ClusterChecklistRunner()
        with self.assertRaises(RuntimeError):
            runner._validate_remote_run_dir(
                "/coc/pskynet6/jzheng390/gavel/tmp/run_20260225T000000Z_deadbeef00",
                "run_20260225T000000Z_deadbeef00",
            )


if __name__ == "__main__":
    unittest.main()
