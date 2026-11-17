import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.persist_idap_state import persist
from scripts.sheets_registry import TARGET_SENDER, load_pending, save_pending


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.STDOUT).decode().strip()


class PersistenceTests(unittest.TestCase):
    def setup_repos(self, root):
        remote = root / "remote.git"
        git(root, "init", "--bare", str(remote))
        left = root / "left"
        git(root, "clone", str(remote), str(left))
        git(left, "checkout", "-b", "main")
        git(left, "config", "user.name", "Tests")
        git(left, "config", "user.email", "tests@example.invalid")
        (left / ".cache").mkdir()
        (left / ".cache/state.json").write_text('{"value": 0}')
        save_pending(left / ".cache/sheets_pending.json", [])
        (left / "code.txt").write_text("base\n")
        git(left, "add", ".")
        git(left, "commit", "-m", "base")
        git(left, "push", "-u", "origin", "main")
        right = root / "right"
        git(root, "clone", "-b", "main", str(remote), str(right))
        git(right, "config", "user.name", "Tests")
        git(right, "config", "user.email", "tests@example.invalid")
        return left, right

    def test_concurrent_generated_data_and_queue_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            left, right = self.setup_repos(Path(d))
            save_pending(left / ".cache/sheets_pending.json", [{"identifier": "left", "senderName": TARGET_SENDER}])
            (left / ".cache/state.json").write_text('{"value": 1}')
            def race(attempt):
                if attempt != 0:
                    return
                save_pending(right / ".cache/sheets_pending.json", [{"identifier": "right", "senderName": TARGET_SENDER}])
                (right / ".cache/state.json").write_text('{"value": 2}')
                git(right, "add", ".")
                git(right, "commit", "-m", "concurrent")
                git(right, "push", "origin", "main")
            persist(left, before_push=race)
            pending = load_pending(left / ".cache/sheets_pending.json")
            self.assertEqual({a["identifier"] for a in pending}, {"left", "right"})
            self.assertEqual(git(left, "rev-parse", "HEAD"), git(left, "ls-remote", "origin", "refs/heads/main").split()[0])

    def test_conflicting_code_is_not_silently_resolved(self):
        with tempfile.TemporaryDirectory() as d:
            left, right = self.setup_repos(Path(d))
            (left / "code.txt").write_text("local feature\n")
            git(left, "add", "code.txt")
            git(left, "commit", "-m", "feature")
            save_pending(left / ".cache/sheets_pending.json", [{"identifier": "safe", "senderName": TARGET_SENDER}])
            def race(attempt):
                if attempt == 0:
                    (right / "code.txt").write_text("remote feature\n")
                    git(right, "add", "code.txt")
                    git(right, "commit", "-m", "other feature")
                    git(right, "push", "origin", "main")
            with self.assertRaises(RuntimeError):
                persist(left, before_push=race)
            self.assertEqual(load_pending(left / ".cache/sheets_pending.json")[0]["identifier"], "safe")

    def test_unrelated_dirty_code_is_never_committed(self):
        with tempfile.TemporaryDirectory() as d:
            left, _ = self.setup_repos(Path(d))
            (left / "code.txt").write_text("user changes\n")
            with self.assertRaises(RuntimeError):
                persist(left)
