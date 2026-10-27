"""Render a tailored résumé (Markdown) to a one-page PDF and a résumé-vs-posting screenshot.

The Markdown is the shape the "Resume Working Draft" doc exports: everything
from ``## <name>`` on, then the role line, the contact line, and ``##``
sections of paragraphs, ``*Project*`` lines, ``**Employer** · place · dates``
lines and ``- `` bullets. Only the standard library is used; headless Chrome
prints the PDF and the screenshot, and macOS Quick Look renders the PDF page.
"""

from __future__ import annotations

import html
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_TIMEOUT_SECONDS = 90
PAGE_PATTERN = re.compile(rb"/Type\s*/Page(?![a-z])")

RESUME_CSS = """@page { size: Letter; margin: 0.36in 0.48in; } * { box-sizing: border-box; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 9.3pt; line-height: 1.24; color: #111; margin: 0; }
h1 { font-size: 19pt; margin: 0; text-align: center; letter-spacing: .3px; }
.role { text-align: center; margin: 2px 0 1px; font-size: 10.2pt; } .contact { text-align: center; margin: 0 0 4px; color: #333; }
a { color: #111; text-decoration: none; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: .8px; margin: 7px 0 3px; padding-bottom: 1px; border-bottom: 1px solid #333; }
p { margin: 0 0 4px; } .job { display: flex; justify-content: space-between; margin: 5px 0 2px; }
.dates { white-space: nowrap; padding-left: 12px; } .proj { font-style: italic; font-weight: 600; margin: 5px 0 1px; }
ul { margin: 0 0 3px; padding-left: 15px; } li { margin: 0 0 1.5px; }"""

COMPARE_CSS = """body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background: #eef0f3; color: #111; }
.wrap { display: flex; gap: 18px; padding: 18px; align-items: flex-start; }
.col { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.15); }
.resume { width: 820px; flex: none; } .resume img { width: 100%; display: block; border-radius: 8px; }
.jd { flex: 1; padding: 18px 22px; font-size: 14px; line-height: 1.4; }
.label { font-size: 11px; text-transform: uppercase; letter-spacing: .8px; color: #666; margin: 0 0 6px; }
h2 { font-size: 19px; margin: 0 0 4px; } .url { font-size: 12px; color: #1a56db; word-break: break-all; margin: 0 0 8px; }
h3 { font-size: 14px; margin: 14px 0 4px; text-transform: uppercase; letter-spacing: .6px; color: #333; }
p { margin: 0 0 6px; } .gate { background: #fff6d6; border-left: 3px solid #e0a800; padding: 6px 8px; border-radius: 4px; }"""

# Posting headings whose list gates the application; the comparison highlights it.
GATING_HEADING_PATTERN = re.compile(r"\b(?:minimum|basic|required)\b.*\bqualifications?\b|\brequirements\b", re.IGNORECASE)


def inline(text: str) -> str:
    """Escape, then apply **bold**, *italic* and [text](url)."""
    out = html.escape(text.replace("\\~", "~").replace("\\", ""), quote=False)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", out)


def resume_body(markdown: str) -> tuple[str, str, str, str]:
    """Split the résumé into (name, role, contact, body Markdown), starting at its ``## <name>`` heading."""
    start = re.search(r"^## (?!#)", markdown, flags=re.MULTILINE)
    if start is None:
        raise ValueError("The résumé Markdown has no '## <name>' heading")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", markdown[start.start():].strip())]
    if len(blocks) < 4:
        raise ValueError("The résumé needs a name heading, a role line, a contact line and a body")
    return blocks[0][3:].strip(), blocks[1], blocks[2], "\n\n".join(blocks[3:])


def body_html(markdown: str) -> str:
    parts: list[str] = []
    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = [line.rstrip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith("## "):
            parts.append(f"<h2>{inline(lines[0][3:].strip())}</h2>")
            lines = lines[1:]
            if not lines:
                continue
        if all(line.lstrip().startswith(("- ", "* ")) for line in lines):
            parts.append("<ul>" + "".join(f"<li>{inline(line.lstrip()[2:].strip())}</li>" for line in lines) + "</ul>")
            continue
        text = " ".join(line.strip() for line in lines)
        job = re.fullmatch(r"(\*\*[^*]+\*\*(?: · [^·]+)*) · ([^·]+)", text)
        project = re.fullmatch(r"\*([^*]+)\*", text)
        if job:
            parts.append(f'<p class="job"><span>{inline(job.group(1))}</span><span class="dates">{inline(job.group(2).strip())}</span></p>')
        elif project:
            parts.append(f'<p class="proj">{inline(project.group(1))}</p>')
        else:
            parts.append(f"<p>{inline(text)}</p>")
    return "".join(parts)


def resume_html(markdown: str) -> str:
    name, role, contact, body = resume_body(markdown)
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(name)}, Resume</title>'
        f"<style>{RESUME_CSS}</style></head><body><h1>{inline(name)}</h1>"
        f'<p class="role">{inline(role)}</p><p class="contact">{inline(contact)}</p>{body_html(body)}</body></html>'
    )


def compare_html(resume_png: Path, title: str, url: str, description: str) -> str:
    """The résumé image beside the posting's text, with the gating qualifications highlighted."""
    parts: list[str] = []
    gate: list[str] | None = None
    for raw in description.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith(":") and len(line) <= 60:
            if gate:
                parts.append('<div class="gate">' + "".join(gate) + "</div>")
            gate = [] if GATING_HEADING_PATTERN.search(line) else None
            parts.append(f"<h3>{html.escape(line.rstrip(':'))}</h3>")
            continue
        (gate if gate is not None else parts).append(f"<p>{html.escape(line)}</p>")
    if gate:
        parts.append('<div class="gate">' + "".join(gate) + "</div>")
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{COMPARE_CSS}</style></head><body><div class="wrap">'
        f'<div class="col resume"><img src="{html.escape(resume_png.resolve().as_uri())}"></div>'
        f'<div class="col jd"><p class="label">Job description</p><h2>{html.escape(title)}</h2>'
        f'<p class="url">{html.escape(url)}</p>{"".join(parts)}</div></div></body></html>'
    )


def pdf_pages(pdf: Path) -> int:
    return len(PAGE_PATTERN.findall(pdf.read_bytes()))


def chrome(*args: str) -> None:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}", *args],
            check=True,
            capture_output=True,
            timeout=CHROME_TIMEOUT_SECONDS,
        )


def render_resume(
    markdown_path: Path,
    out_dir: Path,
    *,
    pdf_name: str,
    title: str,
    url: str,
    description: str,
) -> dict[str, Any]:
    """Write the PDF, its page image, and the comparison screenshot into ``out_dir``.

    Returns the paths and the page count; the caller refuses anything but one page.
    """
    out = out_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    resume_page = out / "resume.html"
    resume_page.write_text(resume_html(markdown_path.read_text(encoding="utf-8")), encoding="utf-8")
    pdf = out / pdf_name
    chrome("--no-pdf-header-footer", f"--print-to-pdf={pdf}", resume_page.as_uri())
    pages = pdf_pages(pdf)
    subprocess.run(["qlmanage", "-t", "-s", "1400", "-o", str(out), str(pdf)], check=True, capture_output=True, timeout=60)
    image = out / f"{pdf.name}.png"
    compare_page = out / "compare.html"
    compare_page.write_text(compare_html(image, title, url, description), encoding="utf-8")
    compare = out / "Resume_vs_JD.png"
    chrome("--hide-scrollbars", "--window-size=1900,1420", f"--screenshot={compare}", compare_page.as_uri())
    return {"resume_path": str(pdf), "pages": pages, "resume_image": str(image), "compare_path": str(compare)}
