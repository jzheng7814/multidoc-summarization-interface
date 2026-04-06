import unittest

from app.services.remote_stage import RemoteStageManager, build_remote_stage_paths


class RemoteStageTests(unittest.TestCase):
    def test_build_remote_stage_paths_uses_backend_run_id(self):
        paths = build_remote_stage_paths("/remote/stages", "backend_run_1")
        self.assertEqual(str(paths.run_dir), "/remote/stages/backend_run_1")
        self.assertEqual(str(paths.interface_agents_dir), "/remote/stages/backend_run_1/interface_agents")
        self.assertEqual(
            str(paths.checklist_base_dir),
            "/remote/stages/backend_run_1/interface_agents/checklist_agent",
        )
        self.assertEqual(
            str(paths.summary_base_dir),
            "/remote/stages/backend_run_1/interface_agents/summary_agent",
        )

    def test_generated_env_files_target_staged_snapshot(self):
        manager = RemoteStageManager()
        manager._settings.cluster_remote_python_path = "/remote/flash/miniconda3/envs/gavel-dev/bin/python"
        manager._settings.cluster_remote_hf_cache_dir = "/remote/flash/hf_cache"
        manager._settings.cluster_remote_slurm_bin_dir = "/remote/slurm/bin"

        paths = build_remote_stage_paths("/remote/stages", "backend_run_2")
        checklist_env = manager._render_checklist_env(paths)
        summary_env = manager._render_summary_env(paths)

        self.assertIn(
            "INTERFACE_AGENT_BASE_DIR=/remote/stages/backend_run_2/interface_agents/checklist_agent",
            checklist_env,
        )
        self.assertIn(
            "INTERFACE_SUMMARY_AGENT_BASE_DIR=/remote/stages/backend_run_2/interface_agents/summary_agent",
            summary_env,
        )
        self.assertIn(
            "INTERFACE_SUMMARY_AGENT_EXTRACTION_BASE_DIR=/remote/stages/backend_run_2/interface_agents/checklist_agent",
            summary_env,
        )
        self.assertIn(
            "INTERFACE_AGENT_HF_HOME=/remote/flash/hf_cache",
            checklist_env,
        )
        self.assertIn(
            "INTERFACE_SUMMARY_AGENT_SLURM_BIN_DIR=/remote/slurm/bin",
            summary_env,
        )


if __name__ == "__main__":
    unittest.main()
