from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync-main-checkout.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


class SyncMainCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        origin = root / "origin.git"
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(origin)], check=True)
        self.primary = root / "primary"
        subprocess.run(["git", "clone", "--quiet", str(origin), str(self.primary)], check=True, capture_output=True)
        git(self.primary, "config", "user.email", "test@example.com")
        git(self.primary, "config", "user.name", "Test")
        (self.primary / "local-resume-companion-extension").mkdir()
        (self.primary / "local-resume-companion-extension" / "content.js").write_text("main\n")
        git(self.primary, "add", ".")
        git(self.primary, "commit", "--quiet", "-m", "main commit")
        git(self.primary, "push", "--quiet", "origin", "main")
        (self.primary / "config.json").write_text("{}\n")
        (self.primary / "data").mkdir()
        # The primary checkout moves to a feature branch with unmerged work.
        git(self.primary, "checkout", "--quiet", "-b", "feature")
        (self.primary / "feature.txt").write_text("unfinished\n")
        git(self.primary, "add", ".")
        git(self.primary, "commit", "--quiet", "-m", "feature commit")
        self.checkout = root / "pipeline-main"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sync(self) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PRIMARY": str(self.primary), "CHECKOUT": str(self.checkout)}
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_checkout_tracks_origin_main_and_shares_state(self) -> None:
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), git(self.primary, "rev-parse", "origin/main"))
        self.assertFalse((self.checkout / "feature.txt").exists())
        self.assertEqual(git(self.primary, "branch", "--show-current"), "feature")
        for path in ("config.json", "data", "artifacts", "local-resume-companion-extension/attach-target-url.txt"):
            with self.subTest(path=path):
                link = self.checkout / path
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), str(self.primary / path))
        # Writing the résumé queue through the link lands where the native host reads it.
        (self.checkout / "local-resume-companion-extension" / "attach-target-url.txt").write_text("https://x\n")
        self.assertEqual(
            (self.primary / "local-resume-companion-extension" / "attach-target-url.txt").read_text(),
            "https://x\n",
        )
        # A second run is a no-op that still succeeds.
        self.assertEqual(self.sync().returncode, 0)

    def test_refuses_to_reset_local_edits(self) -> None:
        self.assertEqual(self.sync().returncode, 0)
        (self.checkout / "local-resume-companion-extension" / "content.js").write_text("edited\n")
        result = self.sync()
        self.assertEqual(result.returncode, 1)
        self.assertIn("edits to tracked files", result.stderr)
        self.assertEqual(
            (self.checkout / "local-resume-companion-extension" / "content.js").read_text(), "edited\n"
        )


if __name__ == "__main__":
    unittest.main()
