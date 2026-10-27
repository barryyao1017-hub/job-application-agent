from __future__ import annotations

import contextlib
import io
import json
import ssl
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from job_agent.cli import main
from job_agent.core import connect_db, create_run, ingest_candidates, score_candidate
from job_agent.feeds import (
    DEFAULT_QUERIES,
    SUPPORTED_ATS,
    amazon_posted_at,
    GOOGLE_QUERIES,
    fetch_feeds,
    google_slug,
    greenhouse_location_metadata,
    load_registry,
    run_fetch_feeds,
    ssl_context,
    strip_html,
    workday_posted_at,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "feeds"
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)  # 07:00 in Los Angeles
ZONE = ZoneInfo("America/Los_Angeles")

CONFIG = {
    "approved_resume_path": "/dev/null",
    "notification_email": "barryyao1017@gmail.com",
    "recency_hours": 24,
    "minimum_fit_score": 70,
    "submit_applications": False,
    "approved_resume_filename": "resume.docx",
    "timezone": "America/Los_Angeles",
    "role_keywords": ["machine learning engineer", "data scientist", "applied scientist", "ranking"],
    "preferred_location_terms": ["california", "san francisco", "palo alto", "seattle", "redmond", ", ca", ", wa"],
    "skill_keywords": ["python", "pytorch", "ranking", "machine learning"],
}

GREENHOUSE = {"company": "Acme", "ats": "greenhouse", "token": "acme"}
LEVER = {"company": "Acme Lever", "ats": "lever", "token": "acme"}
ASHBY = {"company": "Acme Ashby", "ats": "ashby", "token": "acme"}
WORKDAY = {
    "company": "Acme Workday",
    "ats": "workday",
    "host": "acme.wd5.myworkdayjobs.com",
    "tenant": "acme",
    "site": "AcmeCareers",
}
AMAZON = {"company": "Amazon", "ats": "amazon"}

WORKDAY_API = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeFetch:
    """Serves canned JSON by URL (query string ignored) and records every request."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, url: str, payload: dict | None = None):
        self.calls.append((url, payload))
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}{parts.path}"
        if key == f"{WORKDAY_API}/jobs":
            key = f"{key}#offset={payload['offset']}"
        try:
            route = self.routes[key]
        except KeyError as exc:
            raise AssertionError(f"unexpected request {url} {payload}") from exc
        if isinstance(route, Exception):
            raise route
        return fixture(route) if isinstance(route, str) else route

    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]


def standard_routes() -> dict[str, object]:
    return {
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": "greenhouse.json",
        "https://api.lever.co/v0/postings/acme": "lever.json",
        "https://api.ashbyhq.com/posting-api/job-board/acme": "ashby.json",
        f"{WORKDAY_API}/jobs#offset=0": "workday-page-0.json",
        f"{WORKDAY_API}/job/US-CA-Santa-Clara/Machine-Learning-Engineer--AI-Safety_JR2021784-1": "workday-detail-JR2021784.json",
        f"{WORKDAY_API}/job/2-Locations/Senior-Deep-Learning-Engineer_JR2021785": "workday-detail-JR2021785.json",
        f"{WORKDAY_API}/job/China-Shanghai/Machine-Learning-Engineer---Humanoid-Robotics_JR2016809": "workday-detail-JR2016809.json",
        "https://www.amazon.jobs/en/search.json": "amazon-page-0.json",
        **{
            f"https://boards-api.greenhouse.io/v1/boards/acme/jobs/{job['id']}": job
            for job in fixture("greenhouse.json")["jobs"]
        },
    }


def run_board(entry: dict, routes: dict[str, object] | None = None, **kwargs):
    fetch = FakeFetch(routes or standard_routes())
    candidates, stats = fetch_feeds([entry], CONFIG, now=NOW, fetch=fetch, **kwargs)
    return candidates, stats[0], fetch


class FeedParserTests(unittest.TestCase):
    def assert_discovered_shape(self, candidate: dict) -> None:
        for key in (
            "source", "source_url", "application_url", "company", "title", "location",
            "remote", "posted_at", "description", "minimum_years", "active", "ats", "ats_job_id",
        ):
            self.assertIn(key, candidate)
        self.assertEqual(candidate["source"], "ats-api")
        self.assertIsNone(candidate["minimum_years"])
        self.assertTrue(candidate["active"])
        self.assertTrue(candidate["source_url"].startswith("https://"))
        self.assertEqual(candidate["application_url"], candidate["source_url"])
        self.assertIsInstance(candidate["remote"], bool)
        datetime.fromisoformat(candidate["posted_at"])

    def test_greenhouse_board(self) -> None:
        candidates, stats, fetch = run_board(GREENHOUSE)

        self.assertEqual(
            fetch.urls(),
            [
                "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                "https://boards-api.greenhouse.io/v1/boards/acme/jobs/5456619008",
            ],
            "the list is fetched without content; details only for kept postings",
        )
        self.assertEqual(sorted(c["ats_job_id"] for c in candidates), ["5456619008"])
        ranking = next(c for c in candidates if c["ats_job_id"] == "5456619008")
        self.assert_discovered_shape(ranking)
        self.assertEqual(ranking["company"], "Acme")
        self.assertEqual(ranking["ats"], "greenhouse")
        self.assertEqual(ranking["source_url"], "https://job-boards.greenhouse.io/acme/jobs/5456619008")
        self.assertEqual(ranking["location"], "San Francisco, CA | Seattle, WA")
        self.assertFalse(ranking["remote"])
        self.assertEqual(ranking["posted_at"], "2026-07-30T10:00:00+00:00")
        self.assertNotIn("posted_at_precision", ranking)
        self.assertEqual(ranking["description"], "Build ranking models with PyTorch.\n2+ years of experience")
        self.assertEqual(stats["fetched"], 6)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(
            stats["skipped"],
            {"title": 2, "stale": 1, "location": 2, "undated": 0},
            "London on-site and Toronto remote are both outside the US",
        )
        self.assertEqual(stats["errors"], [])

    def test_lever_board(self) -> None:
        candidates, stats, fetch = run_board(LEVER)

        self.assertEqual(fetch.urls(), ["https://api.lever.co/v0/postings/acme?mode=json"])
        self.assertEqual(sorted(c["title"] for c in candidates), ["Data Scientist, Product"])
        product = next(c for c in candidates if c["title"] == "Data Scientist, Product")
        self.assert_discovered_shape(product)
        self.assertEqual(product["ats"], "lever")
        self.assertEqual(product["ats_job_id"], "6ed76ce8-4156-4b60-b120-403538bd66cd")
        self.assertEqual(product["source_url"], "https://jobs.lever.co/acme/6ed76ce8-4156-4b60-b120-403538bd66cd")
        self.assertEqual(product["location"], "Palo Alto, CA | New York, NY")
        self.assertEqual(product["posted_at"], "2026-07-30T12:00:00+00:00")
        self.assertIn("What you'll do", product["description"])
        self.assertIn("Build models", product["description"])
        self.assertIn("Benefits apply.", product["description"])
        self.assertEqual(
            stats["skipped"],
            {"title": 1, "stale": 1, "location": 1, "undated": 0},
            "a remote posting located in Singapore is not a US remote option",
        )

    def test_ashby_board(self) -> None:
        candidates, stats, fetch = run_board(ASHBY)

        self.assertEqual(fetch.urls(), ["https://api.ashbyhq.com/posting-api/job-board/acme"])
        self.assertEqual(sorted(c["title"] for c in candidates), ["Applied AI Engineer"])
        applied = next(c for c in candidates if c["title"] == "Applied AI Engineer")
        self.assert_discovered_shape(applied)
        self.assertEqual(applied["ats"], "ashby")
        self.assertEqual(applied["location"], "San Francisco | Seattle")
        self.assertEqual(applied["source_url"], "https://jobs.ashbyhq.com/acme/8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3")
        self.assertEqual(applied["description"], "ABOUT\n\nShip LLM features.")
        self.assertEqual(stats["fetched"], 3, "unlisted postings are not counted")
        self.assertEqual(stats["skipped"]["title"], 1)
        self.assertEqual(stats["skipped"]["location"], 1, "Paris with isRemote is not a US remote option")

    def test_workday_board_maps_relative_dates_and_fetches_details_for_kept_only(self) -> None:
        candidates, stats, fetch = run_board(WORKDAY)

        self.assertEqual([c["ats_job_id"] for c in candidates], ["JR2021784", "JR2021785"], "newest first")
        today = candidates[0]
        self.assert_discovered_shape(today)
        self.assertEqual(today["ats"], "workday")
        self.assertEqual(
            today["source_url"],
            "https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers/job/US-CA-Santa-Clara/Machine-Learning-Engineer--AI-Safety_JR2021784-1",
        )
        self.assertEqual(today["posted_at"], "2026-07-30T14:00:00+00:00", "Posted Today is capped at fetch time")
        self.assertEqual(today["posted_at_precision"], "day")
        self.assertEqual(today["description"], "NVIDIA is seeking machine learning engineers for content safety.\n2+ years of experience")
        yesterday = candidates[1]
        self.assertEqual(yesterday["posted_at"], "2026-07-30T06:59:59+00:00", "end of yesterday in Los Angeles")
        self.assertEqual(yesterday["location"], "US, TX, Austin | US, WA, Redmond", "multi-location comes from the detail")

        self.assertEqual(stats["fetched"], 6)
        self.assertEqual(stats["skipped"], {"title": 1, "stale": 2, "location": 1, "undated": 0})
        page_requests = [payload for url, payload in fetch.calls if url.endswith("/jobs")]
        self.assertEqual(page_requests, [{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}])
        detail_urls = sorted(url for url in fetch.urls() if "/job/" in url)
        self.assertEqual(len(detail_urls), 3, "details only for title-matched recent postings")
        self.assertFalse(any("JR2021786" in url for url in detail_urls), "stale posting detail is never fetched")

    def test_workday_pagination_stops_when_a_page_has_nothing_recent(self) -> None:
        recent_page = {
            "jobPostings": [
                {"title": f"Machine Learning Engineer {index}", "externalPath": f"/job/US-CA/MLE_{index}", "locationsText": "US, CA, Santa Clara", "postedOn": "Posted Today", "bulletFields": [f"JR{index}"]}
                for index in range(20)
            ]
        }
        old_page = {
            "jobPostings": [
                {"title": "Machine Learning Engineer Old", "externalPath": "/job/US-CA/MLE_old", "locationsText": "US, CA, Santa Clara", "postedOn": "Posted 9 Days Ago", "bulletFields": ["JROLD"]}
            ]
            * 20
        }
        routes: dict[str, object] = {
            f"{WORKDAY_API}/jobs#offset=0": recent_page,
            f"{WORKDAY_API}/jobs#offset=20": old_page,
            f"{WORKDAY_API}/jobs#offset=40": old_page,
            f"{WORKDAY_API}/jobs#offset=60": recent_page,
        }
        routes.update({f"{WORKDAY_API}/job/US-CA/MLE_{index}": {"jobPostingInfo": {"jobDescription": "x", "location": "US, CA, Santa Clara", "jobReqId": f"JR{index}"}} for index in range(20)})

        candidates, stats, fetch = run_board(WORKDAY, routes, max_pages=10)

        offsets = [payload["offset"] for url, payload in fetch.calls if url.endswith("/jobs")]
        self.assertEqual(offsets, [0, 20, 40], "walk stops after two pages in a row with nothing recent")
        self.assertEqual(stats["kept"], 20)

    def test_workday_walk_continues_past_one_stale_first_page(self) -> None:
        stale = {"jobPostings": [{"title": "Machine Learning Engineer Old", "externalPath": "/job/US-CA/MLE_old", "locationsText": "US, CA, Santa Clara", "postedOn": "Posted 30+ Days Ago", "bulletFields": ["JROLD"]}] * 20}
        fresh = {"jobPostings": [{"title": "Machine Learning Engineer", "externalPath": "/job/US-CA/MLE_new", "locationsText": "US, CA, Santa Clara", "postedOn": "Posted Today", "bulletFields": ["JRNEW"]}]}
        routes: dict[str, object] = {
            f"{WORKDAY_API}/jobs#offset=0": stale,
            f"{WORKDAY_API}/jobs#offset=20": fresh,
            f"{WORKDAY_API}/job/US-CA/MLE_new": {"jobPostingInfo": {"jobDescription": "x", "location": "US, CA, Santa Clara", "jobReqId": "JRNEW"}},
        }
        candidates, stats, _ = run_board(WORKDAY, routes, max_pages=10)
        self.assertEqual([c["ats_job_id"] for c in candidates], ["JRNEW"])

    def test_greenhouse_location_custom_fields(self) -> None:
        places, workplace = greenhouse_location_metadata(
            {"metadata": [
                {"name": "Job Posting Location", "value": ["San Francisco, CA", "New York, NY"]},
                {"name": "Workplace Type", "value": "Remote"},
                {"name": "Location Type", "value": "On-Site"},
                {"name": "Department", "value": "AI"},
            ]}
        )
        self.assertEqual(places, ["San Francisco, CA", "New York, NY"])
        self.assertEqual(workplace, ["Remote", "On-Site"])

    def test_workday_detail_failure_keeps_the_posting(self) -> None:
        routes = standard_routes()
        routes[f"{WORKDAY_API}/job/US-CA-Santa-Clara/Machine-Learning-Engineer--AI-Safety_JR2021784-1"] = OSError("timed out")

        candidates, stats, _ = run_board(WORKDAY, routes)

        self.assertIn("JR2021784", [c["ats_job_id"] for c in candidates])
        safety = next(c for c in candidates if c["ats_job_id"] == "JR2021784")
        self.assertEqual(safety["description"], "")
        self.assertEqual(safety["location"], "US, CA, Santa Clara")
        self.assertEqual(len(stats["errors"]), 1)
        self.assertIn("timed out", stats["errors"][0])

    def test_amazon_board(self) -> None:
        candidates, stats, fetch = run_board(AMAZON, queries=["applied scientist", "data scientist"])

        self.assertEqual(len(candidates), 1)
        scientist = candidates[0]
        self.assert_discovered_shape(scientist)
        self.assertEqual(scientist["ats"], "amazon")
        self.assertEqual(scientist["ats_job_id"], "10578465")
        self.assertEqual(scientist["source_url"], "https://www.amazon.jobs/en/jobs/10578465/applied-scientist-search-relevance")
        self.assertEqual(scientist["location"], "US, GA, Atlanta | US, WA, Seattle")
        self.assertEqual(scientist["posted_at"], "2026-07-30T06:59:59+00:00")
        self.assertEqual(scientist["posted_at_precision"], "day")
        self.assertEqual(
            scientist["description"],
            "Improve search relevance.\nWork with ranking models.\nBasic qualifications:\n- 2+ years of experience\n- Python\nPreferred qualifications:\n- PyTorch",
        )
        self.assertEqual(stats["fetched"], 3, "the second query's identical results are deduplicated")
        self.assertEqual(stats["skipped"], {"title": 1, "stale": 1, "location": 0, "undated": 0})
        params = [parse_qs(urlsplit(url).query) for url in fetch.urls()]
        self.assertEqual([p["base_query"][0] for p in params], ["applied scientist", "data scientist"])
        self.assertEqual({p["sort"][0] for p in params}, {"recent"})
        self.assertEqual({p["loc_query"][0] for p in params}, {"USA"})
        self.assertEqual({p["offset"][0] for p in params}, {"0"}, "a short page ends the walk")

    def test_google_board(self) -> None:
        pages: list[str] = []

        def fetch_text(url: str) -> str:
            pages.append(url)
            return (FIXTURES / "google-results.html").read_text(encoding="utf-8")

        candidates, stats = fetch_feeds(
            [{"company": "Google", "ats": "google", "queries": ["ranking"]}],
            CONFIG,
            now=NOW,
            fetch=FakeFetch({}),
            fetch_text=fetch_text,
        )

        self.assertEqual(len(candidates), 1)
        job = candidates[0]
        self.assert_discovered_shape(job)
        self.assertEqual(job["ats"], "google")
        self.assertEqual(job["ats_job_id"], "111111111111111111")
        self.assertEqual(
            job["source_url"],
            "https://www.google.com/about/careers/applications/jobs/results/111111111111111111-software-engineer-iii-aiml-search-ranking",
        )
        self.assertEqual(job["location"], "Mountain View, CA, USA")
        self.assertEqual(job["posted_at"], "2026-07-30T10:00:00+00:00")
        self.assertNotIn("posted_at_precision", job)
        self.assertTrue(job["description"].startswith("Minimum qualifications:"), "qualifications come first")
        self.assertIn("Responsibilities:\nBuild ranking models for Search.", job["description"])
        self.assertEqual(stats[0]["skipped"], {"title": 1, "stale": 1, "location": 1, "undated": 0})
        self.assertEqual(len(pages), 1, "the page holds the search's whole total")
        query = parse_qs(urlsplit(pages[0]).query)
        self.assertEqual(query["q"], ["ranking"])
        self.assertEqual(query["sort_by"], ["date"])
        self.assertIn("Mountain View, CA, USA", query["location"])

    def test_google_slug_matches_the_careers_site(self) -> None:
        self.assertEqual(google_slug("Software Engineer III, AI/ML, Search Ads"), "software-engineer-iii-aiml-search-ads")
        self.assertEqual(google_slug("Research Scientist, Gemini Post-Training"), "research-scientist-gemini-posttraining")
        self.assertIn('"Software Engineer III" recommendations', GOOGLE_QUERIES)

    def test_workday_posted_at_mapping(self) -> None:
        self.assertEqual(workday_posted_at("Posted Today", NOW, ZONE), NOW)
        self.assertEqual(workday_posted_at("Posted Yesterday", NOW, ZONE).isoformat(), "2026-07-30T06:59:59+00:00")
        self.assertEqual(workday_posted_at("Posted 3 Days Ago", NOW, ZONE).isoformat(), "2026-07-28T06:59:59+00:00")
        self.assertEqual(workday_posted_at("Posted 30+ Days Ago", NOW, ZONE).isoformat(), "2026-07-01T06:59:59+00:00")
        self.assertIsNone(workday_posted_at("", NOW, ZONE))
        self.assertIsNone(workday_posted_at("Open until filled", NOW, ZONE))

    def test_amazon_posted_at_mapping(self) -> None:
        self.assertEqual(amazon_posted_at("July 30, 2026", NOW, ZONE), NOW)
        self.assertEqual(amazon_posted_at("July 29, 2026", NOW, ZONE).isoformat(), "2026-07-30T06:59:59+00:00")
        self.assertIsNone(amazon_posted_at("soon", NOW, ZONE))

    def test_strip_html_handles_escaped_greenhouse_content(self) -> None:
        escaped = "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;li&gt;Two&lt;/li&gt;&lt;/ul&gt;"
        self.assertEqual(strip_html(escaped), "Hello & welcome\nOne\nTwo")
        self.assertEqual(strip_html("plain text"), "plain text")
        self.assertEqual(strip_html(None), "")


class FeedRunTests(unittest.TestCase):
    def test_all_boards_run_together_and_a_failing_board_is_reported(self) -> None:
        routes = standard_routes()
        routes["https://api.lever.co/v0/postings/acme"] = OSError("connection refused")
        fetch = FakeFetch(routes)

        with mock.patch("job_agent.feeds.RETRY_DELAY_SECONDS", 0):
            candidates, stats = fetch_feeds([GREENHOUSE, LEVER, ASHBY, WORKDAY, AMAZON], CONFIG, now=NOW, fetch=fetch)

        by_company = {entry["company"]: entry for entry in stats}
        self.assertEqual(by_company["Acme Lever"]["errors"], ["OSError: connection refused"])
        self.assertEqual(by_company["Acme Lever"]["kept"], 0)
        self.assertEqual(
            {c["company"] for c in candidates}, {"Acme", "Acme Ashby", "Acme Workday", "Amazon"}
        )
        self.assertEqual(len(candidates), 1 + 1 + 2 + 1)
        self.assertEqual(candidates, sorted(candidates, key=lambda c: c["posted_at"], reverse=True))
        for entry in stats:
            self.assertIn("seconds", entry)

    def test_a_failed_board_is_retried_once(self) -> None:
        class FlakyFetch(FakeFetch):
            failures = 1

            def __call__(self, url, payload=None):
                if self.failures:
                    self.failures -= 1
                    self.calls.append((url, payload))
                    raise OSError("nodename nor servname provided")
                return super().__call__(url, payload)

        with mock.patch("job_agent.feeds.RETRY_DELAY_SECONDS", 0):
            candidates, stats = fetch_feeds([GREENHOUSE], CONFIG, now=NOW, fetch=FlakyFetch(standard_routes()))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(stats[0]["errors"], [])
            self.assertTrue(stats[0]["retried"])

            routes = standard_routes()
            routes["https://api.lever.co/v0/postings/acme"] = OSError("connection refused")
            fetch = FakeFetch(routes)
            _, stats = fetch_feeds([LEVER], CONFIG, now=NOW, fetch=fetch)
            self.assertEqual(fetch.urls(), ["https://api.lever.co/v0/postings/acme?mode=json"] * 2, "one retry, no more")
            self.assertEqual(stats[0]["errors"], ["OSError: connection refused"])

    def test_board_hours_widen_only_the_named_board(self) -> None:
        narrow = {**CONFIG, "recency_hours": 2}
        fetch = FakeFetch(standard_routes())
        candidates, stats = fetch_feeds(
            [GREENHOUSE, ASHBY], narrow, now=NOW, fetch=fetch, board_hours={"Acme": 6}
        )
        by_company = {entry["company"]: entry for entry in stats}
        self.assertEqual(by_company["Acme"]["kept"], 1, "the 4-hour-old posting is inside Acme's 6h window")
        self.assertEqual(by_company["Acme"]["recency_hours"], 6)
        self.assertNotIn("recency_hours", by_company["Acme Ashby"])
        self.assertEqual({c["company"] for c in candidates}, {"Acme"})

    def test_candidates_are_deduplicated_by_url(self) -> None:
        fetch = FakeFetch(standard_routes())
        candidates, _ = fetch_feeds([GREENHOUSE, {**GREENHOUSE, "company": "Acme Again"}], CONFIG, now=NOW, fetch=fetch)
        self.assertEqual(len(candidates), 1)

    def test_output_is_accepted_by_the_ledger_and_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "registry.json"
            registry.write_text(json.dumps([GREENHOUSE, WORKDAY, AMAZON]), encoding="utf-8")
            out = root / "artifacts" / "2026-07-30" / "discovered.json"

            payload = run_fetch_feeds(
                CONFIG, registry_path=registry, out_path=out, now=NOW, fetch=FakeFetch(standard_routes())
            )

            self.assertEqual(payload["out"], str(out))
            self.assertEqual(payload["kept"], 4)
            self.assertEqual(payload["boards_with_errors"], 0)
            self.assertEqual(payload["queries"], list(DEFAULT_QUERIES))
            self.assertEqual([b["company"] for b in payload["boards"]], ["Acme", "Acme Workday", "Amazon"])
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(written), 4)

            connection = connect_db(root / "ledger.sqlite3")
            run_id = create_run(connection)
            ingested = ingest_candidates(connection, written, run_id)
            self.assertEqual(len(ingested["inserted"]), 4)
            self.assertEqual(ingested["duplicates"], [])
            rows = connection.execute("SELECT source, ats_job_id, company FROM jobs ORDER BY company, ats_job_id").fetchall()
            self.assertEqual([row[0] for row in rows], ["ats-api"] * 4)
            self.assertIn(("ats-api", "JR2021784", "Acme Workday"), [tuple(row) for row in rows])
            self.assertIn(("ats-api", "10578465", "Amazon"), [tuple(row) for row in rows])

            ranking = next(c for c in written if c["ats_job_id"] == "5456619008")
            result = score_candidate(ranking, CONFIG, now=NOW)
            self.assertIsNone(result.skip_reason)
            self.assertGreaterEqual(result.score, 70)

    def test_cli_fetch_feeds_prints_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "resume.docx"
            resume.write_bytes(b"resume")
            config_path = root / "config.json"
            config_path.write_text(json.dumps({**CONFIG, "approved_resume_path": str(resume)}), encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(json.dumps([ASHBY]), encoding="utf-8")
            out = root / "discovered.json"
            buffer = io.StringIO()
            with mock.patch("job_agent.feeds.fetch_json", FakeFetch(standard_routes())), mock.patch(
                "job_agent.feeds.utc_now", return_value=NOW
            ):
                with contextlib.redirect_stdout(buffer):
                    status = main(
                        [
                            "--config", str(config_path),
                            "--db", str(root / "ledger.sqlite3"),
                            "fetch-feeds", "--registry", str(registry), "--out", str(out),
                            "--queries", "machine learning engineer",
                        ]
                    )
            self.assertEqual(status, 0)
            printed = json.loads(buffer.getvalue())
            self.assertEqual(printed["kept"], 1)
            self.assertEqual(printed["queries"], ["machine learning engineer"])
            self.assertEqual(printed["boards"][0]["company"], "Acme Ashby")
            self.assertEqual(len(json.loads(out.read_text(encoding="utf-8"))), 1)

    def test_cli_reports_missing_registry_as_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "resume.docx"
            resume.write_bytes(b"resume")
            config_path = root / "config.json"
            config_path.write_text(json.dumps({**CONFIG, "approved_resume_path": str(resume)}), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                status = main(
                    ["--config", str(config_path), "--db", str(root / "l.sqlite3"), "fetch-feeds",
                     "--registry", str(root / "missing.json"), "--out", str(root / "out.json")]
                )
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(buffer.getvalue())["type"], "FileNotFoundError")


class SslContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        ssl_context.cache_clear()

    def test_falls_back_to_a_system_bundle_when_python_has_none(self) -> None:
        empty = ssl.DefaultVerifyPaths(None, None, "SSL_CERT_FILE", "", "SSL_CERT_DIR", "")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "cert.pem"
            bundle.write_text(ssl.DER_cert_to_PEM_cert(b"x"))
            ssl_context.cache_clear()
            with mock.patch("job_agent.feeds.ssl.get_default_verify_paths", return_value=empty), mock.patch(
                "job_agent.feeds.FALLBACK_CA_FILES", ("/nonexistent/cert.pem", str(bundle))
            ), mock.patch.object(ssl.SSLContext, "load_verify_locations") as load:
                ssl_context()
        load.assert_called_once_with(cafile=str(bundle))

    def test_keeps_python_defaults_when_it_has_a_bundle(self) -> None:
        found = ssl.DefaultVerifyPaths("/some/cert.pem", None, "SSL_CERT_FILE", "", "SSL_CERT_DIR", "")
        ssl_context.cache_clear()
        with mock.patch("job_agent.feeds.ssl.get_default_verify_paths", return_value=found), mock.patch.object(
            ssl.SSLContext, "load_verify_locations"
        ) as load:
            ssl_context()
        load.assert_not_called()


class RegistryTests(unittest.TestCase):
    def write(self, root: Path, entries) -> Path:
        path = root / "registry.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def test_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(load_registry(self.write(root, {"companies": [AMAZON]})), [AMAZON])
            self.assertEqual(load_registry(self.write(root, [{"company": " Acme ", "ats": "Greenhouse", "token": "acme"}]))[0]["company"], "Acme")
            with self.assertRaisesRegex(ValueError, "unsupported ats"):
                load_registry(self.write(root, [{"company": "X", "ats": "taleo"}]))
            with self.assertRaisesRegex(ValueError, "board token"):
                load_registry(self.write(root, [{"company": "X", "ats": "lever"}]))
            with self.assertRaisesRegex(ValueError, "workday host, site"):
                load_registry(self.write(root, [{"company": "X", "ats": "workday", "tenant": "x"}]))
            with self.assertRaisesRegex(ValueError, "missing company"):
                load_registry(self.write(root, [{"ats": "amazon"}]))
            with self.assertRaisesRegex(ValueError, "JSON array"):
                load_registry(self.write(root, {"nope": 1}))

    def test_example_registry_is_valid_and_seeded(self) -> None:
        entries = load_registry(ROOT / "company-registry.example.json")
        companies = {entry["company"]: entry for entry in entries}
        for company in ("NVIDIA", "Amazon", "Anthropic", "OpenAI", "Palantir", "Broadcom", "Salesforce"):
            self.assertIn(company, companies)
        self.assertEqual(companies["NVIDIA"]["site"], "NVIDIAExternalCareerSite")
        self.assertEqual(companies["Anthropic"], {"company": "Anthropic", "ats": "greenhouse", "token": "anthropic"})
        self.assertEqual(companies["OpenAI"]["ats"], "ashby")
        self.assertTrue({entry["ats"] for entry in entries} <= set(SUPPORTED_ATS))

    def test_registry_file_is_private_but_example_is_tracked(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("\n/data\n", ignore, "data/ stays untracked so the daily checkout can link it")
        self.assertNotIn("company-registry", ignore)
        self.assertTrue((ROOT / "company-registry.example.json").is_file(), "template lives at the repo root")

    def test_command_is_documented_and_allowed_in_scheduled_runs(self) -> None:
        self.assertIn("fetch-feeds", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        script = (ROOT / "scripts" / "run-automation.sh").read_text(encoding="utf-8")
        self.assertIn("Bash(python3 -m job_agent:*)", script)
        self.assertIn("fetch-feeds", script)


class TitleFilterTests(unittest.TestCase):
    def test_customer_facing_and_management_titles_are_excluded(self) -> None:
        from job_agent.feeds import title_matches

        for title in (
            "Applied Machine Learning Engineer - AI for VLSI Design",
            "Senior Applied Scientist, Risk",
            "Data Scientist, Product",
            "Forward Deployed Engineer (AI Enablement)",
            "Staff Data Scientist, Marketing Analytics",
            "Senior Software Engineer - Computer Vision",
            "Research Engineer, Robot Learning",
            "Research Scientist / Research Engineer, Search Integrity",
        ):
            self.assertTrue(title_matches(title, CONFIG), title)
        for title in (
            "Business Development Manager, Cloud & AI",
            "Senior Account Executive, AI Labs",
            "Sr. Customer Success Specialist, Applied AI",
            "Senior Technical Program Manager, Ads AI Core Infrastructure",
            "Manager, Software Engineering - AI Infrastructure",
            "FP&A AI Architect",
            "Solutions Architect, AI Infrastructure",
            "Software Engineer, Payments",
        ):
            self.assertFalse(title_matches(title, CONFIG), title)


class LocationFilterTests(unittest.TestCase):
    CONFIG = {"preferred_location_terms": ["california", "seattle", "remote", ", ca", ", wa"]}

    def check(self, location: str, remote: bool = False) -> bool:
        from job_agent.feeds import location_matches

        return location_matches(location, remote, self.CONFIG)

    def test_preferred_and_us_remote_locations_match(self) -> None:
        self.assertTrue(self.check("US, CA, Santa Clara"))
        self.assertTrue(self.check("Seattle, WA | New York, NY"))
        self.assertTrue(self.check("Remote"))
        self.assertTrue(self.check("US, TX, Remote"))
        self.assertTrue(self.check("Austin, TX", remote=True))
        self.assertTrue(self.check(""))

    def test_foreign_locations_do_not_match_even_when_remote(self) -> None:
        self.assertFalse(self.check("Paris, France", remote=True))
        self.assertFalse(self.check("Switzerland, Zurich | UK, Remote | Switzerland, Remote"))
        self.assertFalse(self.check("London, United Kingdom"))
        self.assertFalse(self.check("Toronto, Canada - Remote"))
        self.assertFalse(self.check("Austin, TX"))

    def test_remote_flag_needs_a_us_place_or_a_bare_remote(self) -> None:
        # 2026-10-21: ElevenLabs (Ashby) roles listed only in Europe carried isRemote.
        self.assertFalse(self.check("Budapest, Hungary | Sofia, Bulgaria | Lisbon, Portugal", remote=True))
        self.assertFalse(self.check("Prague", remote=True))
        self.assertFalse(self.check("Remote - Ontario"))
        self.assertFalse(self.check("Remote, Kraków"))
        self.assertTrue(self.check("New York, NY", remote=True))
        self.assertTrue(self.check("Remote-First", remote=True))
        self.assertTrue(self.check("Remote (United States)"))
        # Lower-case "or"/"in" are words, not Oregon/Indiana.
        self.assertFalse(self.check("Canada - Remote (ON, AB, BC, or NS Only)"))

    def test_washington_means_the_state_not_dc(self) -> None:
        config = {"preferred_location_terms": ["washington", "seattle"]}
        from job_agent.feeds import location_matches

        self.assertTrue(location_matches("Redmond, Washington", False, config))
        self.assertFalse(location_matches("Washington, DC", False, config))
        self.assertFalse(location_matches("Washington D.C.", False, config))
        self.assertTrue(location_matches("Washington, DC | Seattle, Washington", False, config))

    def test_semicolon_separated_locations_are_checked_one_by_one(self) -> None:
        self.assertTrue(self.check("Menlo Park, CA; New York, NY; Toronto, ON"))
        self.assertFalse(self.check("Toronto, ON; London, UK", remote=True))

    def test_one_us_option_among_foreign_ones_is_enough(self) -> None:
        self.assertTrue(self.check("UK, Remote | US, CA, Remote"))
        self.assertTrue(self.check("Bangalore, India | San Francisco, CA"))


if __name__ == "__main__":
    unittest.main()
