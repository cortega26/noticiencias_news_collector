import os
import unittest


import pytest

@pytest.mark.skip(reason="Meta test dependent on specific environment artifacts out of scope for standard system tests")
class TestDocsArtifactsExist(unittest.TestCase):
    def setUp(self):
        # We need to know where the artifacts are.
        # In this env, they are in /home/cortega26/.gemini/antigravity/brain/a8d070cf-df1a-49e7-a1cd-71de6800d261/
        # But for portability, maybe we should search or expect an env var?
        # The prompt implies we know where they are.
        # I'll use the absolute path used in previous steps for now,
        # but ideally this should be relative to project root if artifacts were inside project.
        # Since artifacts are external, I'll use the specific path provided in user context.
        import glob
        brain_dir = "/home/carlos/.gemini/antigravity/brain"
        dirs = [d for d in glob.glob(os.path.join(brain_dir, "*")) if os.path.isdir(d) and os.path.exists(os.path.join(d, "walkthrough.md"))]
        self.artifact_dir = max(dirs, key=os.path.getmtime) if dirs else "/tmp/fallback"
        self.task_md = os.path.join(self.artifact_dir, "task.md")
        self.walkthrough_md = os.path.join(self.artifact_dir, "walkthrough.md")

    def test_walkthrough_exists_and_updated(self):
        """Assert walkthrough.md exists and contains Continuous Autonomous Operation section."""
        self.assertTrue(
            os.path.exists(self.walkthrough_md), "walkthrough.md does not exist"
        )

        with open(self.walkthrough_md, "r") as f:
            content = f.read()

        self.assertIn(
            "Continuous Autonomous Operation",
            content,
            "walkthrough.md missing Continuous Operation section",
        )
        self.assertIn(
            "Auto-Locking", content, "walkthrough.md missing Auto-Locking details"
        )

    def test_task_md_exists_and_complete(self):
        """Assert task.md exists and Phase 42 is marked complete."""
        self.assertTrue(os.path.exists(self.task_md), "task.md does not exist")

        with open(self.task_md, "r") as f:
            content = f.read()

        # Check for Phase 42 completion
        self.assertIn(
            "- [x] Generate `PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md`",
            content,
            "Phase 42 not marked complete in task.md",
        )


if __name__ == "__main__":
    unittest.main()
