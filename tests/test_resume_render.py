from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_agent.resume_render import compare_html, pdf_pages, resume_body, resume_html

RESUME = """# Resume Working Draft

Oct 25, 2026 · @Someone

## Pat Example

Machine Learning Engineer · ranking

pat@example.com · [linkedin.com/in/pat](https://www.linkedin.com/in/pat/)

## Experience

**Data Scientist, Acme** · Sunnyvale, CA · Mar 2025 to present

*Neural ranker*

- Lifted conversion +2.45% with a **listwise** ranker.
- Scraped \\~112k sites.

## Skills

- **Languages:** Python, SQL
"""


class ResumeRenderTests(unittest.TestCase):
    def test_body_starts_at_the_name_heading(self) -> None:
        name, role, contact, body = resume_body(RESUME)
        self.assertEqual((name, role), ("Pat Example", "Machine Learning Engineer · ranking"))
        self.assertTrue(contact.startswith("pat@example.com"))
        self.assertTrue(body.startswith("## Experience"))
        with self.assertRaisesRegex(ValueError, "name"):
            resume_body("# Title only\n\ntext")

    def test_resume_layout(self) -> None:
        page = resume_html(RESUME)
        self.assertIn("<h1>Pat Example</h1>", page)
        self.assertIn('<a href="https://www.linkedin.com/in/pat/">linkedin.com/in/pat</a>', page)
        self.assertIn(
            '<p class="job"><span><strong>Data Scientist, Acme</strong> · Sunnyvale, CA</span>'
            '<span class="dates">Mar 2025 to present</span></p>',
            page,
        )
        self.assertIn('<p class="proj">Neural ranker</p>', page)
        self.assertIn("<li>Lifted conversion +2.45% with a <strong>listwise</strong> ranker.</li>", page)
        self.assertIn("~112k", page)
        self.assertNotIn("Resume Working Draft", page)
        self.assertNotIn("@Someone", page)

    def test_comparison_highlights_the_gating_qualifications(self) -> None:
        page = compare_html(
            Path("/tmp/resume.png"),
            "Google — SWE III",
            "https://example.com/job",
            "Minimum qualifications:\nBachelor's degree.\n2 years of Python.\nPreferred qualifications:\nMaster's degree.",
        )
        self.assertIn('<div class="gate"><p>Bachelor&#x27;s degree.</p><p>2 years of Python.</p></div>', page)
        self.assertIn("<h3>Preferred qualifications</h3><p>Master&#x27;s degree.</p>", page)
        self.assertIn(f'src="{Path("/tmp/resume.png").resolve().as_uri()}"', page)

    def test_pdf_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "r.pdf"
            pdf.write_bytes(b"<< /Type /Pages /Count 2 >> << /Type /Page >> << /Type/Page /Parent 1 0 R >>")
            self.assertEqual(pdf_pages(pdf), 2)


class SaveExportTests(unittest.TestCase):
    def test_decodes_the_export_result_or_bare_base64(self) -> None:
        import base64
        import contextlib
        import io
        import json

        from job_agent.cli import main

        encoded = base64.b64encode(RESUME.encode("utf-8")).decode("ascii")
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            resume = folder / "resume.docx"
            resume.write_bytes(b"resume")
            config = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text(encoding="utf-8"))
            config["approved_resume_path"] = str(resume)
            config_path = folder / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            for name, body in (("result.json", json.dumps({"verdict": "allow", "data": {"bytes_b64": encoded}})), ("bare.txt", encoded)):
                (folder / name).write_text(body, encoding="utf-8")
                outs = [folder / f"{name}.md", folder / "copy" / f"{name}.md"]
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(["--config", str(config_path), "--db", str(folder / "db.sqlite3"), "save-export", "--in", str(folder / name), "--out", *map(str, outs)])
                self.assertEqual(code, 0)
                for out in outs:
                    self.assertEqual(out.read_text(encoding="utf-8"), RESUME)


if __name__ == "__main__":
    unittest.main()
