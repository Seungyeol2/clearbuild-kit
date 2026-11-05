import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "handoff.py"
spec = importlib.util.spec_from_file_location("handoff", SCRIPT)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "worklog"
        with contextlib.redirect_stdout(io.StringIO()):
            handoff.initialize(self.root)

    def run_main(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = handoff.main(["--worklog", str(self.root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def ack_all(self, role):
        for name in handoff.INCOMING[role]:
            digest = handoff.snapshot(self.root, name)["sha256"]
            self.assertEqual(self.run_main("ack", "--role", role, "--file", name, "--sha256", digest)[0], 0)

    def test_init_refuses_overwrite(self):
        before = (self.root / "PROJECT.md").read_bytes()
        self.assertEqual(self.run_main("init")[0], 1)
        self.assertEqual((self.root / "PROJECT.md").read_bytes(), before)
        self.assertEqual(len(list(self.root.iterdir())), 4)

    def test_status_is_read_only_and_role_scoped(self):
        code, out, err = self.run_main("status", "--role", "A", "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)["files"]
        self.assertEqual([r["file"] for r in rows], ["B_HANDOFF.md", "C_HANDOFF.md"])
        self.assertTrue(all(r["state"] == "UNREAD" for r in rows))
        self.assertFalse((self.root / ".clearbuild").exists())
        self.assertEqual(err, "")

    def test_read_ack_and_changed_content(self):
        code, out, _ = self.run_main("read", "--role", "B", "--file", "PROJECT.md")
        self.assertEqual(code, 0)
        self.assertIn("SHA256:", out)
        self.ack_all("B")
        self.assertTrue(all(r["state"] == "READ" for r in handoff.status(self.root, "B")))
        (self.root / "PROJECT.md").write_text("new contract\n", encoding="utf-8")
        self.assertEqual(handoff.status(self.root, "B")[0]["state"], "UNREAD")
        # Each role has its own read state.
        self.assertTrue(all(r["state"] == "UNREAD" for r in handoff.status(self.root, "C")))

    def test_stale_digest_cannot_ack_new_content(self):
        old = handoff.snapshot(self.root, "PROJECT.md")["sha256"]
        (self.root / "PROJECT.md").write_text("v2", encoding="utf-8")
        self.assertEqual(self.run_main("ack", "--role", "C", "--file", "PROJECT.md", "--sha256", old)[0], 1)
        self.assertIsNone(handoff.receipt(self.root, "C", "PROJECT.md"))

    def test_bad_role_file_and_path_traversal_are_rejected(self):
        for name in ("PROJECT.md", "../PROJECT.md", "/tmp/other.md"):
            self.assertEqual(self.run_main("read", "--role", "A", "--file", name)[0], 1)

    def test_deletion_and_missing_are_distinct(self):
        self.ack_all("A")
        (self.root / "B_HANDOFF.md").unlink()
        self.assertEqual(handoff.status(self.root, "A")[0]["state"], "DELETED")
        (self.root / "PROJECT.md").unlink()
        self.assertEqual(handoff.status(self.root, "B")[0]["state"], "MISSING")

    def test_corrupt_receipt_is_not_silently_accepted(self):
        self.ack_all("A")
        handoff.receipt_path(self.root, "A", "B_HANDOFF.md").write_text('{"sha256": false}')
        self.assertEqual(self.run_main("status", "--role", "A")[0], 1)

    def test_same_role_lock_is_respected(self):
        with handoff.role_lock(self.root, "B"):
            digest = handoff.snapshot(self.root, "PROJECT.md")["sha256"]
            self.assertEqual(self.run_main("ack", "--role", "B", "--file", "PROJECT.md", "--sha256", digest)[0], 1)
        self.assertFalse((self.root / ".clearbuild" / "B.lock").exists())

    def test_symlink_handoff_and_state_are_refused(self):
        path = self.root / "PROJECT.md"
        path.unlink()
        path.symlink_to(self.root / "DECISIONS.md")
        self.assertEqual(self.run_main("status", "--role", "B")[0], 1)
        state = self.root / ".clearbuild"
        state.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.run_main("status", "--role", "A")[0], 1)

    def test_watch_returns_immediately_for_unread(self):
        self.assertEqual(self.run_main("watch", "--role", "A", "--timeout", "1")[0], 0)
        self.assertFalse((self.root / ".clearbuild").exists())

    def test_watch_timeout_is_bounded_and_does_not_ack(self):
        self.ack_all("C")
        started = time.monotonic()
        code, _, _ = self.run_main("watch", "--role", "C", "--timeout", "1", "--interval", "1")
        self.assertEqual(code, 3)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(all(r["state"] == "READ" for r in handoff.status(self.root, "C")))

    def test_watch_detects_change_from_another_process(self):
        self.ack_all("B")
        process = subprocess.Popen([sys.executable, str(SCRIPT), "--worklog", str(self.root),
                                    "watch", "--role", "B", "--timeout", "4", "--interval", "1", "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.2)
            replacement = self.root / "ready.tmp"
            replacement.write_text("contract v2\n", encoding="utf-8")
            replacement.replace(self.root / "PROJECT.md")
            out, err = process.communicate(timeout=6)
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(json.loads(out)["files"][0]["state"], "UNREAD")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_watch_rejects_unbounded_or_busy_polling(self):
        for value in ("0", "61", "inf", "nan", "-1"):
            self.assertEqual(self.run_main("watch", "--role", "A", "--timeout", value)[0], 1)
        self.assertEqual(self.run_main("watch", "--role", "A", "--interval", "0.01")[0], 1)

    def test_utf8_and_size_errors(self):
        path = self.root / "PROJECT.md"
        path.write_bytes(b"\xff")
        self.assertEqual(self.run_main("read", "--role", "B", "--file", "PROJECT.md")[0], 1)
        path.write_bytes(b"a" * (handoff.MAX_BYTES + 1))
        self.assertEqual(self.run_main("status", "--role", "B")[0], 1)


if __name__ == "__main__":
    unittest.main()
