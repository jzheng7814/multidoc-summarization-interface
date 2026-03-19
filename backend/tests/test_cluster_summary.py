import json
import unittest
from pathlib import PurePosixPath
from unittest.mock import patch

from app.services.cluster_summary import ClusterSummaryRunner


class ClusterSummaryRunnerTests(unittest.TestCase):
    def test_build_remote_command_uses_summary_agent_mode(self):
        runner = ClusterSummaryRunner()
        runner._settings.cluster_remote_python_path = "/path/python"
        runner._settings.cluster_summary_remote_controller_script = "controller.py"
        runner._settings.cluster_poll_seconds = 2
        runner._settings.cluster_max_wait_seconds = 60

        command = runner._build_remote_command("/remote/repo")
        self.assertIn("--mode slurm_summarize_agent", command)
        self.assertIn("controller.py", command)

    def test_result_from_completed_event_prefers_summary_path(self):
        runner = ClusterSummaryRunner()
        completed_data = {
            "run_id": "run_1",
            "job_id": "123",
            "result_payload_path": "/remote/runs/run_1/result_payload.json",
            "manifest_path": "/remote/runs/run_1/manifest.json",
            "summary_path": "/remote/runs/run_1/summary.json",
        }

        def _fake_pull(remote_path: PurePosixPath, destination_dir):
            local_path = destination_dir / remote_path.name
            if remote_path.name == "result_payload.json":
                local_path.write_text(
                    json.dumps(
                        {
                            "summary": "Mirror summary text",
                            "completion_stats": {"total": 1},
                        }
                    ),
                    encoding="utf-8",
                )
            elif remote_path.name == "summary.json":
                local_path.write_text(json.dumps({"summary": "Canonical summary text"}), encoding="utf-8")
            else:
                local_path.write_text("{}", encoding="utf-8")
            return local_path

        with patch.object(runner, "_rsync_pull_file", side_effect=_fake_pull):
            result = runner._result_from_completed_event(completed_data, case_id="46110")

        self.assertEqual(result.run_id, "run_1")
        self.assertEqual(result.job_id, "123")
        self.assertEqual(result.summary_text, "Canonical summary text")
        self.assertEqual(result.completion_stats, {"total": 1})
        self.assertTrue(result.summary_path.endswith("/summary.json"))

    def test_result_from_completed_event_falls_back_to_result_payload_summary(self):
        runner = ClusterSummaryRunner()
        completed_data = {
            "run_id": "run_2",
            "job_id": "124",
            "result_payload_path": "/remote/runs/run_2/result_payload.json",
            "manifest_path": "/remote/runs/run_2/manifest.json",
            "summary_path": "/remote/runs/run_2/summary.json",
        }

        def _fake_pull(remote_path: PurePosixPath, destination_dir):
            local_path = destination_dir / remote_path.name
            if remote_path.name == "result_payload.json":
                local_path.write_text(
                    json.dumps(
                        {
                            "summary": "Result payload summary text",
                            "completion_stats": {"total": 1},
                        }
                    ),
                    encoding="utf-8",
                )
            elif remote_path.name == "summary.json":
                local_path.write_text(json.dumps({"not_summary": "missing"}), encoding="utf-8")
            else:
                local_path.write_text("{}", encoding="utf-8")
            return local_path

        with patch.object(runner, "_rsync_pull_file", side_effect=_fake_pull):
            result = runner._result_from_completed_event(completed_data, case_id="46110")

        self.assertEqual(result.summary_text, "Result payload summary text")


if __name__ == "__main__":
    unittest.main()
