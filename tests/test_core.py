from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_agent.core import (
    block_job,
    canonicalize_url,
    claim_next,
    complete_job,
    connect_db,
    create_run,
    digest_payload,
    extract_ats_job_id,
    ingest_candidates,
    load_company_policies,
    mark_notification,
    match_company_policy,
    recover_stale_claims,
    score_candidate,
    score_jobs,
)


NOW = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)


def config(resume: Path) -> dict:
    return {
        "approved_resume_path": str(resume),
        "notification_email": "barryyao1017@gmail.com",
        "daily_limit": 5,
        "recency_hours": 24,
        "minimum_fit_score": 70,
        "review_only": True,
        "approved_resume_filename": "Jiayi_Yao_resume.docx",
        "role_keywords": ["machine learning engineer", "data scientist", "ranking"],
        "preferred_location_terms": ["california", "seattle", "remote"],
        "skill_keywords": ["python", "sql", "machine learning", "ranking", "pytorch"],
    }


def candidate(**overrides) -> dict:
    base = {
        "source_url": "https://www.linkedin.com/jobs/view/123456/?trackingId=abc",
        "application_url": "https://job-boards.greenhouse.io/acme/jobs/123456?gh_src=abc&utm_source=linkedin",
        "company": "Acme",
        "title": "Machine Learning Engineer, Ranking",
        "location": "California",
        "remote": False,
        "posted_at": (NOW - timedelta(hours=2)).isoformat(),
        "description": "Build ranking models using Python, SQL, PyTorch and machine learning. 2+ years of experience.",
        "minimum_years": 2,
        "active": True,
    }
    base.update(overrides)
    return base


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resume = self.root / "Jiayi_Yao_resume.docx"
        self.resume.write_bytes(b"resume")
        self.cfg = config(self.resume)
        self.policy_root = self.root / "company-policies"
        self.policy_root.mkdir()
        (self.policy_root / "google.md").write_text("# Google\n", encoding="utf-8")
        (self.policy_root / "policies.json").write_text(
            """{
  "policies": [
    {
      "id": "google",
      "company_names": ["Google", "Google LLC", "Google DeepMind"],
      "handling": "manual_review",
      "documentation": "google.md",
      "reason": "Preserve the user's limited application allowance."
    }
  ]
}
""",
            encoding="utf-8",
        )
        self.cfg["company_policies_path"] = str(self.policy_root / "policies.json")
        self.connection = connect_db(self.root / "jobs.sqlite3")
        self.run_id = create_run(self.connection, "run-1")

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def test_canonicalize_removes_tracking_but_keeps_identity(self) -> None:
        url = canonicalize_url(
            "https://JOB-BOARDS.greenhouse.io/acme/jobs/123/?utm_source=x&gh_jid=123&source=LinkedIn"
        )
        self.assertEqual(url, "https://job-boards.greenhouse.io/acme/jobs/123?gh_jid=123")
        self.assertEqual(extract_ats_job_id(url), "123")

    def test_ingest_deduplicates_canonical_url(self) -> None:
        first = ingest_candidates(self.connection, [candidate()], self.run_id)
        second = ingest_candidates(self.connection, [candidate()], self.run_id)
        self.assertEqual(len(first["inserted"]), 1)
        self.assertEqual(len(second["duplicates"]), 1)

    def test_score_and_queue_good_fit(self) -> None:
        result = score_candidate(candidate(), self.cfg, now=NOW)
        self.assertGreaterEqual(result.score, 70)
        ingest_candidates(self.connection, [candidate()], self.run_id)
        scored = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(scored["queued"]), 1)

    def test_company_policy_alias_matches_exactly(self) -> None:
        policies = load_company_policies(self.cfg["company_policies_path"])
        self.assertEqual(match_company_policy("Google LLC", policies)["id"], "google")
        self.assertIsNone(match_company_policy("Google Fiber Vendor", policies))

    def test_manual_review_company_is_never_queued_or_claimed(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google",
                    application_url="https://careers.google.com/jobs/results/123456",
                )
            ],
            self.run_id,
        )
        result = score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(len(result["manual_review"]), 1)
        self.assertEqual(result["queued"], [])
        self.assertIsNone(claim_next(self.connection, "worker-1"))
        row = self.connection.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["status"], "manual_review")
        self.assertEqual(row["company_policy_id"], "google")
        self.assertEqual(
            row["company_policy_document"],
            str((self.policy_root / "google.md").resolve()),
        )

    def test_claim_reroutes_preexisting_manual_review_company(self) -> None:
        ingested = ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google DeepMind",
                    application_url="https://careers.google.com/jobs/results/654321",
                )
            ],
            self.run_id,
        )
        self.connection.execute(
            "UPDATE jobs SET status='queued' WHERE id=?",
            (ingested["inserted"][0],),
        )
        claimed = claim_next(
            self.connection,
            "worker-1",
            self.cfg["company_policies_path"],
        )
        self.assertIsNone(claimed)
        status = self.connection.execute(
            "SELECT status FROM jobs WHERE id=?",
            (ingested["inserted"][0],),
        ).fetchone()["status"]
        self.assertEqual(status, "manual_review")

    def test_hard_filters(self) -> None:
        cases = (
            (candidate(title="Machine Learning Intern"), "internship"),
            (candidate(title="Director of Data Science"), "management"),
            (candidate(minimum_years=7), "minimum experience"),
            (candidate(location="London, UK"), "location"),
            (candidate(description="Machine learning role. U.S. citizen required."), "citizenship"),
        )
        for value, expected in cases:
            with self.subTest(expected=expected):
                result = score_candidate(value, self.cfg, now=NOW)
                self.assertIn(expected, result.skip_reason or "")

    def test_filters_use_word_boundaries(self) -> None:
        internal = candidate(title="AI/ML Engineer, Internal Platforms")
        self.assertIsNone(score_candidate(internal, self.cfg, now=NOW).skip_reason)

        ml_software = candidate(
            title="Software Engineer III, AI/ML, Google Cloud AI",
            description="Python or C++ and end-to-end ML model deployment.",
        )
        self.assertIsNone(score_candidate(ml_software, self.cfg, now=NOW).skip_reason)

        general = candidate(title="Software Engineer", description="Build email delivery services.")
        self.assertIn("outside the ML", score_candidate(general, self.cfg, now=NOW).skip_reason or "")

    def test_atomic_claim_and_recovery(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        self.assertIsNotNone(claimed)
        self.assertIsNone(claim_next(self.connection, "worker-2"))
        self.connection.execute(
            "UPDATE jobs SET claimed_at=? WHERE id=?",
            ((NOW - timedelta(hours=3)).isoformat(), claimed["id"]),
        )
        recovered = recover_stale_claims(self.connection, 120, now=NOW)
        self.assertEqual(recovered, [claimed["id"]])

    def test_completion_requires_resume_verification(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        completed = complete_job(
            self.connection,
            claimed["id"],
            "worker-1",
            review_url=claimed["application_url"],
            resume_verified=True,
        )
        self.assertEqual(completed["status"], "ready_for_review")
        self.assertEqual(completed["resume_verified"], 1)

    def test_block_records_one_concise_message(self) -> None:
        ingest_candidates(self.connection, [candidate()], self.run_id)
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        claimed = claim_next(self.connection, "worker-1")
        blocked = block_job(
            self.connection,
            claimed["id"],
            "worker-1",
            "captcha",
            "CAPTCHA shown",
            claimed["application_url"],
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blocker_category"], "captcha")
        self.assertEqual(blocked["blocker_message"], "CAPTCHA shown")

    def test_digest_is_idempotent(self) -> None:
        payload = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertTrue(payload["eligible"])
        mark_notification(self.connection, payload["notification_key"], sent=True)
        again = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertFalse(again["eligible"])

    def test_digest_surfaces_manual_attention_policy(self) -> None:
        ingest_candidates(
            self.connection,
            [
                candidate(
                    company="Google",
                    application_url="https://careers.google.com/jobs/results/789012",
                )
            ],
            self.run_id,
        )
        score_jobs(self.connection, self.cfg, self.run_id, now=NOW)
        payload = digest_payload(self.connection, self.cfg, self.run_id, now=NOW)
        self.assertEqual(payload["counts"]["manual_review"], 1)
        self.assertIn("Manual attention: 1", payload["email"]["body"])
        self.assertIn("policy: google", payload["email"]["body"])


if __name__ == "__main__":
    unittest.main()
