import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml
from scripts.sheets_registry import TARGET_SENDER, save_pending
from scripts.sync_alerts_sheets import main


class WorkflowTests(unittest.TestCase):
    def test_workflow_serializes_and_restricts_production(self):
        workflow = yaml.safe_load(Path(".github/workflows/idap_daily_maps.yml").read_text(encoding="utf-8"))
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        steps = workflow["jobs"]["build"]["steps"]
        by_id = {s["id"]: s for s in steps if "id" in s}
        self.assertIn("SHEETS_CAPTURE_ENABLED", by_id["collect"]["env"])
        self.assertLess(steps.index(by_id["collect"]), steps.index(by_id["sheets_sync"]))
        for name in ("google_auth", "sheets_sync", "persist"):
            self.assertIn("refs/heads/main", by_id[name]["if"])
            self.assertIn("defesacivil-es/Alertas_Idap", by_id[name]["if"])
        self.assertTrue(by_id["google_auth"]["continue-on-error"])
        self.assertTrue(by_id["sheets_sync"]["continue-on-error"])
        self.assertIn("always()", by_id["persist"]["if"])
        auth = by_id["google_auth"]
        self.assertEqual(len(auth["uses"].split("@")[1]), 40)
        self.assertNotIn("credentials_json", auth["with"])
        artifacts = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertTrue(any(".cache/sheets_pending.json" in s["with"]["path"] for s in artifacts))
        self.assertFalse(any("gha-creds" in s["with"]["path"] for s in artifacts))

    def test_dry_run_does_not_authenticate_and_denied_apply_does_not_touch_queue(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pending.json"
            save_pending(path, [{"identifier": "test", "senderName": TARGET_SENDER, "areaDesc": "Serra/ES"}])
            before = path.read_bytes()
            with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/development", "GITHUB_REPOSITORY": "defesacivil-es/Alertas_Idap"}):
                with redirect_stdout(io.StringIO()), patch.dict("sys.modules", {"google.auth": None}):
                    self.assertEqual(main(["--dry-run", "--pending-path", str(path)]), 0)
                    self.assertEqual(main(["--apply", "--pending-path", str(path)]), 1)
            self.assertEqual(before, path.read_bytes())
