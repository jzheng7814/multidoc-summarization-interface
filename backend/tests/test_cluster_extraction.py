import asyncio
import json
import unittest
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
                    "by_source_document": {
                        "Docket": 77,
                    }
                },
                "checklist": {
                    "Appeal": {
                        "extracted": [
                            {
                                "value": "Appeal filed",
                                "evidence": [
                                    {
                                        "source_document": "Docket",
                                        "location": "Page 1",
                                        "text": "Appeal filed in circuit court.",
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
        runner._settings.cluster_remote_repo_dir = "/tmp/gavel"
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

        with patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec):
            collection = asyncio.run(runner.run("46210", documents))

        self.assertEqual(len(collection.items), 1)
        self.assertEqual(collection.items[0].bin_id, "Appeal")
        self.assertEqual(collection.items[0].value, "Appeal filed")
        self.assertEqual(collection.items[0].evidence.document_id, 77)

        stdin_payload = json.loads(fake_process.stdin.buffer.decode("utf-8"))
        self.assertEqual(stdin_payload["case"]["case_id"], "46210")
        self.assertEqual(stdin_payload["case"]["case_documents_id"], ["77"])

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
                        "evidence": [{"source_document": "Complaint", "location": "Page 1", "text": "injunction"}],
                    }
                ]
            }
        }
        artifact_document_map = {
            "by_source_document": {"Complaint": 21},
            "documents": [],
        }

        with (
            patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec),
            patch.object(
                runner,
                "_load_artifact_payload_from_completed_event",
                return_value=(artifact_checklist, artifact_document_map),
            ) as mocked_loader,
        ):
            collection = asyncio.run(runner.run("400", documents))

        mocked_loader.assert_called_once()
        self.assertEqual(len(collection.items), 1)
        self.assertEqual(collection.items[0].bin_id, "Remedy_Sought")
        self.assertEqual(collection.items[0].evidence.document_id, 21)

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

        with patch("app.services.cluster_extraction.asyncio.create_subprocess_exec", _fake_create_subprocess_exec):
            with self.assertRaises(RuntimeError) as exc:
                asyncio.run(runner.run("100", documents))

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
