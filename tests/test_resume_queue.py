from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


EXTENSION = Path(__file__).resolve().parents[1] / "local-resume-companion-extension"


@unittest.skipUnless(shutil.which("cc") and shutil.which("node"), "needs cc and node")
class ResumeQueueTests(unittest.TestCase):
    """The native host serves several queued workers without crossing them."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        resume = root / "resume.docx"
        resume.write_bytes(b"approved resume bytes")
        config = root / "config.json"
        config.write_text(json.dumps({"approved_resume_path": str(resume)}))
        self.queue = root / "attach-queue"
        self.legacy = root / "attach-target-url.txt"
        self.host = root / "resume-native-host"
        subprocess.run(
            [
                "cc", "-O2",
                f'-DCONFIG_PATH="{config}"',
                f'-DQUEUE_DIR="{self.queue}"',
                f'-DQUEUE_PATH="{self.legacy}"',
                str(EXTENSION / "native-host" / "resume_native_host.c"),
                "-o", str(self.host),
            ],
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def enqueue(self, url: str) -> None:
        subprocess.run(
            ["node", str(EXTENSION / "enqueue-attach.js"), url],
            env={**os.environ, "RESUME_QUEUE_DIR": str(self.queue)},
            check=True,
            capture_output=True,
        )

    def claim(self, url: str) -> dict:
        message = json.dumps({"type": "claim-attachment", "url": url}).encode()
        result = subprocess.run(
            [str(self.host)], input=struct.pack("<I", len(message)) + message, capture_output=True, check=True
        )
        (length,) = struct.unpack("<I", result.stdout[:4])
        return json.loads(result.stdout[4 : 4 + length])

    def entries(self) -> list[Path]:
        return sorted(self.queue.glob("*.url"))

    def test_each_page_claims_only_its_own_entry(self) -> None:
        self.enqueue("https://jobs.ashbyhq.com/a/1/application")
        self.enqueue("https://job-boards.greenhouse.io/b/jobs/2")
        self.assertEqual(len(self.entries()), 2)

        self.assertIn("error", self.claim("https://jobs.lever.co/c/3/apply"))
        self.assertEqual(len(self.entries()), 2)

        reply = self.claim("https://job-boards.greenhouse.io/b/jobs/2")
        self.assertEqual(reply["fileName"], "Jiayi_Yao_resume.docx")
        remaining = self.entries()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].read_text(), "https://jobs.ashbyhq.com/a/1/application")
        self.assertIn("error", self.claim("https://job-boards.greenhouse.io/b/jobs/2"))

        self.assertIn("base64", self.claim("https://jobs.ashbyhq.com/a/1/application"))
        self.assertEqual(self.entries(), [])
        self.assertEqual(list(self.queue.iterdir()), [])

    def test_racing_hosts_serve_one_entry_once(self) -> None:
        url = "https://jobs.ashbyhq.com/a/1/application"
        self.enqueue(url)
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: self.claim(url), range(8)))
        self.assertEqual(sum("base64" in reply for reply in replies), 1)
        self.assertEqual(list(self.queue.iterdir()), [])

    def test_stale_entry_is_dropped(self) -> None:
        url = "https://jobs.ashbyhq.com/a/1/application"
        self.enqueue(url)
        old = time.time() - 31 * 60
        os.utime(self.entries()[0], (old, old))
        self.assertIn("error", self.claim(url))
        self.assertEqual(self.entries(), [])

    def test_legacy_single_slot_file_is_still_served(self) -> None:
        url = "https://jobs.ashbyhq.com/a/1/application"
        self.legacy.write_text(url)
        self.assertIn("base64", self.claim(url))
        self.assertFalse(self.legacy.exists())


if __name__ == "__main__":
    unittest.main()
