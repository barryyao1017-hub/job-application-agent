from __future__ import annotations

import json
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "job-agent.sqlite3"
DEFAULT_COMPANY_POLICIES_PATH = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "company-application-policies"
    / "references"
    / "policies.json"
)

TRACKING_QUERY_PREFIXES = (
    "utm_",
    "trk",
    "tracking",
    "ref",
    "source",
    "gh_src",
    "li_",
)
IDENTITY_QUERY_KEYS = {
    "gh_jid",
    "jobid",
    "job_id",
    "jobseqno",
    "jid",
    "id",
    "reqid",
    "requisitionid",
}
MANAGEMENT_TITLE_TERMS = (
    "director",
    "vice president",
    "vp ",
    "head of ",
    "engineering manager",
    "data science manager",
)
INTERNSHIP_TITLE_PATTERN = re.compile(r"\b(?:intern|internship|co-?op)\b")
ML_SIGNAL_PATTERN = re.compile(
    r"\b(?:ai|ml|machine learning|artificial intelligence|data science)\b"
)
CITIZENSHIP_TERMS = (
    "u.s. citizen required",
    "us citizen required",
    "must be a u.s. citizen",
    "must be a us citizen",
    "security clearance required",
    "active security clearance",
    "top secret clearance",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    required = (
        "approved_resume_path",
        "notification_email",
        "recency_hours",
        "minimum_fit_score",
        "approved_resume_filename",
        "role_keywords",
        "preferred_location_terms",
        "skill_keywords",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing configuration keys: {', '.join(missing)}")
    # Older configs carry only review_only; it maps to submit_applications=false.
    config.setdefault("submit_applications", config.get("review_only") is False)
    if not isinstance(config["submit_applications"], bool):
        raise ValueError("submit_applications must be true or false")
    config.setdefault("max_parallel_workers", 2)
    workers = config["max_parallel_workers"]
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 3:
        raise ValueError("max_parallel_workers must be 1, 2 or 3")
    resume_path = Path(config["approved_resume_path"]).expanduser()
    if not resume_path.is_file():
        raise ValueError(f"Approved resume does not exist: {resume_path}")
    policies_path = Path(
        config.get("company_policies_path", DEFAULT_COMPANY_POLICIES_PATH)
    ).expanduser()
    if not policies_path.is_absolute():
        policies_path = PROJECT_ROOT / policies_path
    config["company_policies_path"] = str(policies_path.resolve())
    return config


def normalize_company_name(value: str) -> str:
    normalized = value.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def load_company_policies(path: Path | str = DEFAULT_COMPANY_POLICIES_PATH) -> list[dict[str, Any]]:
    policy_path = Path(path).expanduser().resolve()
    if not policy_path.is_file():
        raise ValueError(f"Company policy registry does not exist: {policy_path}")
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    raw_policies = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(raw_policies, list):
        raise ValueError("Company policy registry requires a policies array")

    policies: list[dict[str, Any]] = []
    aliases_seen: set[str] = set()
    for raw in raw_policies:
        if not isinstance(raw, dict):
            raise ValueError("Each company policy must be an object")
        policy_id = str(raw.get("id") or "").strip()
        handling = str(raw.get("handling") or "").strip()
        names = raw.get("company_names")
        documentation = str(raw.get("documentation") or "").strip()
        if not policy_id or handling not in {"manual_review", "auto_apply"}:
            raise ValueError(f"Invalid company policy: {policy_id or '<missing id>'}")
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(name, str) for name in names)
        ):
            raise ValueError(f"Company policy {policy_id} requires company_names")
        document_path = (policy_path.parent / documentation).resolve()
        if policy_path.parent not in document_path.parents or not document_path.is_file():
            raise ValueError(f"Company policy document is missing or outside the registry: {documentation}")
        aliases = {normalize_company_name(name) for name in names}
        if "" in aliases or aliases_seen.intersection(aliases):
            raise ValueError(f"Company policy {policy_id} has an empty or duplicate company alias")
        aliases_seen.update(aliases)
        policies.append(
            {
                "id": policy_id,
                "company_names": names,
                "normalized_company_names": aliases,
                "handling": handling,
                "documentation": str(document_path),
                "reason": str(raw.get("reason") or "").strip(),
            }
        )
    return policies


def match_company_policy(
    company: str,
    policies: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = normalize_company_name(company)
    for policy in policies:
        if normalized in policy["normalized_company_names"]:
            return {
                key: value
                for key, value in policy.items()
                if key != "normalized_company_names"
            }
    return None


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Not an HTTP(S) URL: {url}")
    host = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lower = key.lower()
        if lower in IDENTITY_QUERY_KEYS:
            kept.append((key, value))
            continue
        if any(lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    kept.sort(key=lambda item: (item[0].lower(), item[1]))
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(kept), ""))


def extract_ats_job_id(url: str) -> str | None:
    parts = urlsplit(url)
    query = {key.lower(): value for key, value in parse_qsl(parts.query)}
    for key in IDENTITY_QUERY_KEYS:
        if query.get(key):
            return query[key]
    patterns = (
        r"/jobs?/(?:view/)?([A-Za-z0-9_-]{4,})",
        r"/job/([A-Za-z0-9_-]{4,})",
        r"/requisitions?/([A-Za-z0-9_-]{4,})",
    )
    for pattern in patterns:
        match = re.search(pattern, parts.path, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def infer_source(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if "linkedin.com" in host:
        return "linkedin"
    if "greenhouse" in host:
        return "greenhouse"
    if "myworkdayjobs" in host or "workday" in host:
        return "workday"
    if "ashbyhq" in host:
        return "ashby"
    if "lever.co" in host:
        return "lever"
    return host.removeprefix("www.")


def infer_minimum_years(description: str) -> int | None:
    match = re.search(
        r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-\s*\d{1,2}\s*)?years?(?:\s+of)?\s+(?:relevant\s+|professional\s+|industry\s+)?experience",
        description,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class ScoreResult:
    score: int
    rationale: list[str]
    skip_reason: str | None = None


def location_term_pattern(term: str) -> re.Pattern[str]:
    """Match ``term`` as whole words, so ", ca" matches "San Mateo, CA" but not "Toronto, Canada"."""
    term = term.lower()
    start = r"\b" if term[:1].isalnum() else ""
    end = r"\b" if term[-1:].isalnum() else ""
    return re.compile(start + re.escape(term) + end)


def score_candidate(candidate: dict[str, Any], config: dict[str, Any], now: datetime | None = None) -> ScoreResult:
    current = now or utc_now()
    title = str(candidate.get("title") or "").strip()
    description = str(candidate.get("description") or "")
    location = str(candidate.get("location") or "").strip()
    title_lower = title.lower()
    combined = f"{title}\n{description}".lower()

    if candidate.get("active") is False:
        return ScoreResult(0, [], "job is no longer active")
    if INTERNSHIP_TITLE_PATTERN.search(title_lower):
        return ScoreResult(0, [], "internship or co-op role")
    if any(term in title_lower for term in MANAGEMENT_TITLE_TERMS):
        return ScoreResult(0, [], "management or director-level role")
    if any(term in combined for term in CITIZENSHIP_TERMS):
        return ScoreResult(0, [], "unsupported citizenship or clearance requirement")

    minimum_years = candidate.get("minimum_years")
    if minimum_years is None:
        minimum_years = infer_minimum_years(description)
    if minimum_years is not None:
        minimum_years = int(minimum_years)
        if minimum_years > 5:
            return ScoreResult(0, [], f"minimum experience is {minimum_years} years")

    posted_at = parse_datetime(candidate.get("posted_at"))
    if posted_at and current - posted_at > timedelta(hours=int(config["recency_hours"])):
        return ScoreResult(0, [], "posting is outside the recency window")

    role_matches = [term for term in config["role_keywords"] if term.lower() in combined]
    general_software = "software engineer" in title_lower and not ML_SIGNAL_PATTERN.search(combined)
    if general_software or not (role_matches or ML_SIGNAL_PATTERN.search(title_lower)):
        return ScoreResult(0, [], "role is outside the ML and Data pilot")

    location_lower = location.lower()
    remote = bool(candidate.get("remote")) or "remote" in location_lower
    location_match = remote or any(
        location_term_pattern(term).search(location_lower)
        for term in config["preferred_location_terms"]
    )
    if location and not location_match:
        return ScoreResult(0, [], "location is outside California, Washington, or US remote")

    role_points = 30
    skills = sorted({term for term in config["skill_keywords"] if term.lower() in combined})
    skill_points = min(25, round(len(skills) / 8 * 25))
    if minimum_years is None:
        experience_points = 15
    elif minimum_years <= 3:
        experience_points = 20
    else:
        experience_points = 15
    location_points = 15 if location_match else 5
    recency_points = 10 if posted_at else 5
    total = role_points + skill_points + experience_points + location_points + recency_points
    rationale = [
        f"role {role_points}/30 ({', '.join(role_matches[:4])})",
        f"skills {skill_points}/25 ({', '.join(skills[:8]) or 'no explicit overlap'})",
        f"experience {experience_points}/20 ({minimum_years if minimum_years is not None else 'unspecified'} years minimum)",
        f"location {location_points}/15 ({location or 'unspecified'})",
        f"recency {recency_points}/10",
    ]
    return ScoreResult(total, rationale)


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    ats_job_id TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    remote INTEGER NOT NULL DEFAULT 0,
    posted_at TEXT,
    discovered_at TEXT NOT NULL,
    description TEXT,
    minimum_years INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    fit_score INTEGER,
    fit_rationale TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    skip_reason TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    blocker_category TEXT,
    blocker_message TEXT,
    application_url TEXT,
    review_url TEXT,
    resume_verified INTEGER NOT NULL DEFAULT 0,
    company_policy_id TEXT,
    company_policy_document TEXT,
    submitted_at TEXT,
    confirmation_evidence TEXT,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS jobs_company_ats_id
ON jobs(lower(company), ats_job_id)
WHERE ats_job_id IS NOT NULL AND ats_job_id <> '';

CREATE INDEX IF NOT EXISTS jobs_status_score
ON jobs(status, fit_score DESC, posted_at DESC);

-- One row per claim, so a retried job counts as two attempts. The submission
-- rate is submitted attempts over finished attempts; it starts from the first
-- row here (the table was added on 2026-10-20, which reset the rate).
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    run_id TEXT REFERENCES runs(id),
    worker_id TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT
);

CREATE INDEX IF NOT EXISTS attempts_run ON attempts(run_id);

-- Per-board discovery stats from fetch-feeds: which companies a run looked at.
CREATE TABLE IF NOT EXISTS run_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    company TEXT NOT NULL,
    ats TEXT NOT NULL,
    fetched INTEGER NOT NULL DEFAULT 0,
    kept INTEGER NOT NULL DEFAULT 0,
    errors TEXT
);

CREATE INDEX IF NOT EXISTS run_boards_run ON run_boards(run_id);

CREATE TABLE IF NOT EXISTS notifications (
    notification_key TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    kind TEXT NOT NULL,
    reserved_at TEXT,
    sent_at TEXT,
    last_error TEXT
);
"""


def connect_db(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    for name in (
        "company_policy_id",
        "company_policy_document",
        "submitted_at",
        "confirmation_evidence",
    ):
        if name not in existing_columns:
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
    return connection


def create_run(connection: sqlite3.Connection, run_id: str | None = None) -> str:
    resolved = run_id or str(uuid.uuid4())
    connection.execute(
        "INSERT OR IGNORE INTO runs(id, started_at, status) VALUES (?, ?, 'running')",
        (resolved, iso_utc()),
    )
    return resolved


def record_discovery(
    connection: sqlite3.Connection,
    run_id: str,
    boards: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Store fetch-feeds' per-board stats for ``run_id``, replacing any earlier record."""
    connection.execute("DELETE FROM run_boards WHERE run_id=?", (run_id,))
    for board in boards:
        connection.execute(
            """
            INSERT INTO run_boards(run_id, company, ats, fetched, kept, errors)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(board["company"]),
                str(board["ats"]),
                int(board.get("fetched") or 0),
                int(board.get("kept") or 0),
                json.dumps(list(board.get("errors") or [])),
            ),
        )
    return discovery_summary(connection, run_id)


def discovery_summary(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """What a run's discovery looked at: companies checked, postings scanned, matches kept."""
    rows = connection.execute(
        "SELECT company, ats, fetched, kept, errors FROM run_boards WHERE run_id=? ORDER BY company",
        (run_id,),
    ).fetchall()
    with_errors = sorted({row["company"] for row in rows if json.loads(row["errors"] or "[]")})
    return {
        "run_id": run_id,
        "companies_checked": len({row["company"] for row in rows}),
        "companies": sorted({row["company"] for row in rows}),
        "postings_scanned": sum(row["fetched"] for row in rows),
        "matches_kept": sum(row["kept"] for row in rows),
        "companies_with_matches": {
            row["company"]: row["kept"] for row in rows if row["kept"]
        },
        "companies_with_errors": with_errors,
    }


def ingest_candidates(
    connection: sqlite3.Connection,
    candidates: Iterable[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    inserted: list[str] = []
    duplicates: list[str] = []
    for candidate in candidates:
        source_url = str(candidate.get("source_url") or candidate.get("url") or "").strip()
        application_url = str(candidate.get("application_url") or candidate.get("canonical_url") or source_url).strip()
        canonical_url = canonicalize_url(application_url)
        ats_job_id = str(candidate.get("ats_job_id") or extract_ats_job_id(canonical_url) or "") or None
        job_id = str(uuid.uuid4())
        now = iso_utc()
        values = (
            job_id,
            run_id,
            str(candidate.get("source") or infer_source(source_url)),
            source_url,
            canonical_url,
            ats_job_id,
            str(candidate.get("company") or "").strip(),
            str(candidate.get("title") or "").strip(),
            str(candidate.get("location") or "").strip(),
            int(bool(candidate.get("remote"))),
            candidate.get("posted_at"),
            now,
            str(candidate.get("description") or ""),
            candidate.get("minimum_years"),
            int(candidate.get("active", True) is not False),
            application_url,
            now,
        )
        if not values[6] or not values[7]:
            raise ValueError("Each candidate requires company and title")
        try:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, run_id, source, source_url, canonical_url, ats_job_id,
                    company, title, location, remote, posted_at, discovered_at,
                    description, minimum_years, active, application_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted.append(job_id)
        except sqlite3.IntegrityError:
            duplicates.append(canonical_url)
    return {"run_id": run_id, "inserted": inserted, "duplicates": duplicates}


def score_jobs(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    params: tuple[Any, ...] = ()
    where = "status = 'discovered'"
    if run_id:
        where += " AND run_id = ?"
        params = (run_id,)
    rows = connection.execute(f"SELECT * FROM jobs WHERE {where}", params).fetchall()
    policies = load_company_policies(
        config.get("company_policies_path", DEFAULT_COMPANY_POLICIES_PATH)
    )
    scored: list[str] = []
    skipped: dict[str, str] = {}
    manual_review: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = dict(row)
        result = score_candidate(candidate, config, now=now)
        if result.skip_reason:
            connection.execute(
                """
                UPDATE jobs SET status='skipped', fit_score=?, fit_rationale=?,
                    skip_reason=?, updated_at=? WHERE id=?
                """,
                (result.score, json.dumps(result.rationale), result.skip_reason, iso_utc(), row["id"]),
            )
            skipped[row["id"]] = result.skip_reason
        else:
            policy = match_company_policy(row["company"], policies)
            if policy and policy["handling"] == "manual_review":
                connection.execute(
                    """
                    UPDATE jobs SET status='manual_review', fit_score=?, fit_rationale=?,
                        skip_reason=NULL, company_policy_id=?,
                        company_policy_document=?, updated_at=? WHERE id=?
                    """,
                    (
                        result.score,
                        json.dumps(result.rationale),
                        policy["id"],
                        policy["documentation"],
                        iso_utc(),
                        row["id"],
                    ),
                )
                manual_review[row["id"]] = policy
            else:
                connection.execute(
                    """
                    UPDATE jobs SET status='scored', fit_score=?, fit_rationale=?,
                        skip_reason=NULL, company_policy_id=?,
                        company_policy_document=?, updated_at=? WHERE id=?
                    """,
                    (
                        result.score,
                        json.dumps(result.rationale),
                        policy["id"] if policy else None,
                        policy["documentation"] if policy else None,
                        iso_utc(),
                        row["id"],
                    ),
                )
                scored.append(row["id"])

    # Every job at or above the threshold is queued; there is no daily cap.
    threshold = int(config["minimum_fit_score"])
    queue_params: list[Any] = [threshold]
    queue_where = "status='scored' AND fit_score >= ?"
    if run_id:
        queue_where += " AND run_id = ?"
        queue_params.append(run_id)
    selected = connection.execute(
        f"""
        SELECT id FROM jobs WHERE {queue_where}
        ORDER BY fit_score DESC, COALESCE(posted_at, discovered_at) DESC
        """,
        queue_params,
    ).fetchall()
    queued = [row["id"] for row in selected]
    if queued:
        placeholders = ",".join("?" for _ in queued)
        connection.execute(
            f"UPDATE jobs SET status='queued', updated_at=? WHERE id IN ({placeholders})",
            (iso_utc(), *queued),
        )
    return {
        "scored": scored,
        "skipped": skipped,
        "manual_review": manual_review,
        "queued": queued,
    }


def claim_next(
    connection: sqlite3.Connection,
    worker_id: str,
    company_policies_path: Path | str = DEFAULT_COMPANY_POLICIES_PATH,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Claim the best queued job and log the attempt against ``run_id`` (default: latest running run).

    A company with a job already claimed is passed over, so parallel workers never
    sign in to, or create, the same company's account at the same time.
    """
    policies = load_company_policies(company_policies_path)
    connection.execute("BEGIN IMMEDIATE")
    try:
        queued_rows = connection.execute(
            "SELECT id, company FROM jobs WHERE status='queued'"
        ).fetchall()
        for queued_row in queued_rows:
            policy = match_company_policy(queued_row["company"], policies)
            if policy and policy["handling"] == "manual_review":
                connection.execute(
                    """
                    UPDATE jobs SET status='manual_review', company_policy_id=?,
                        company_policy_document=?, updated_at=?
                    WHERE id=? AND status='queued'
                    """,
                    (
                        policy["id"],
                        policy["documentation"],
                        iso_utc(),
                        queued_row["id"],
                    ),
                )
        row = connection.execute(
            """
            SELECT * FROM jobs WHERE status='queued'
                AND LOWER(TRIM(company)) NOT IN (
                    SELECT LOWER(TRIM(company)) FROM jobs WHERE status='claimed'
                )
            ORDER BY fit_score DESC, COALESCE(posted_at, discovered_at) DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            connection.execute("COMMIT")
            return None
        now = iso_utc()
        connection.execute(
            """
            UPDATE jobs SET status='claimed', claimed_by=?, claimed_at=?,
                attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'
            """,
            (worker_id, now, now, row["id"]),
        )
        if run_id is None:
            running = connection.execute(
                "SELECT id FROM runs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            run_id = running["id"] if running else None
        connection.execute(
            "INSERT INTO attempts(job_id, run_id, worker_id, claimed_at) VALUES (?, ?, ?, ?)",
            (row["id"], run_id, worker_id, now),
        )
        claimed = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        connection.execute("COMMIT")
        return dict(claimed)
    except Exception:
        connection.execute("ROLLBACK")
        raise


def finish_attempt(connection: sqlite3.Connection, job_id: str, outcome: str) -> None:
    connection.execute(
        "UPDATE attempts SET finished_at=?, outcome=? WHERE job_id=? AND finished_at IS NULL",
        (iso_utc(), outcome, job_id),
    )


def complete_job(
    connection: sqlite3.Connection,
    job_id: str,
    worker_id: str,
    *,
    review_url: str,
    resume_verified: bool,
) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown job: {job_id}")
    if row["status"] != "claimed" or row["claimed_by"] != worker_id:
        raise ValueError("Job is not claimed by this worker")
    if not resume_verified:
        raise ValueError("Approved resume was not visibly verified")
    now = iso_utc()
    connection.execute(
        """
        UPDATE jobs SET status='ready_for_review', review_url=?, resume_verified=1,
            claimed_by=NULL, claimed_at=NULL, updated_at=?
        WHERE id=?
        """,
        (
            canonicalize_url(review_url),
            now,
            job_id,
        ),
    )
    finish_attempt(connection, job_id, "ready_for_review")
    return dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def submit_job(
    connection: sqlite3.Connection,
    job_id: str,
    worker_id: str,
    *,
    confirmation_url: str,
    evidence: str,
    resume_verified: bool,
    submit_applications: bool,
) -> dict[str, Any]:
    if not submit_applications:
        raise ValueError("Submission is disabled: submit_applications is not true in config")
    row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown job: {job_id}")
    if row["status"] != "claimed" or row["claimed_by"] != worker_id:
        raise ValueError("Job is not claimed by this worker")
    if not resume_verified:
        raise ValueError("Approved resume was not visibly verified")
    if not evidence.strip():
        raise ValueError("Submission requires visible confirmation evidence")
    now = iso_utc()
    connection.execute(
        """
        UPDATE jobs SET status='submitted', review_url=?, resume_verified=1,
            submitted_at=?, confirmation_evidence=?,
            claimed_by=NULL, claimed_at=NULL, updated_at=?
        WHERE id=?
        """,
        (canonicalize_url(confirmation_url), now, evidence.strip(), now, job_id),
    )
    finish_attempt(connection, job_id, "submitted")
    return dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


ATTEMPTED_STATUSES = ("submitted", "ready_for_review", "blocked")
ATTEMPT_OUTCOMES = ("submitted", "ready_for_review", "blocked", "abandoned")


def attempt_stats(
    connection: sqlite3.Connection,
    *,
    run_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Submission rate = submitted attempts / finished attempts (each claim is one attempt)."""
    clauses = ["finished_at IS NOT NULL"]
    params: list[Any] = []
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    if since:
        clauses.append("claimed_at >= ?")
        params.append(since)
    outcomes = {outcome: 0 for outcome in ATTEMPT_OUTCOMES}
    for row in connection.execute(
        f"SELECT outcome, COUNT(*) AS count FROM attempts WHERE {' AND '.join(clauses)} GROUP BY outcome",
        params,
    ).fetchall():
        outcomes[row["outcome"]] = row["count"]
    attempts = sum(outcomes.values())
    first = connection.execute("SELECT MIN(claimed_at) AS first FROM attempts").fetchone()["first"]
    return {
        "attempts": attempts,
        "attempt_outcomes": outcomes,
        "submission_rate_percent": (
            round(100 * outcomes["submitted"] / attempts, 1) if attempts else None
        ),
        "rate_counted_since": first,
    }


def outcome_report(
    connection: sqlite3.Connection,
    *,
    run_id: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Submission rate over attempts, the jobs in each outcome, blockers by category, discovery."""
    clauses = [f"status IN ({','.join('?' for _ in ATTEMPTED_STATUSES)})"]
    params: list[Any] = list(ATTEMPTED_STATUSES)
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    if since:
        clauses.append("updated_at >= ?")
        params.append(since)
    rows = connection.execute(
        f"""
        SELECT id, company, title, status, blocker_category, blocker_message,
            COALESCE(review_url, application_url) AS url, submitted_at,
            confirmation_evidence
        FROM jobs WHERE {' AND '.join(clauses)}
        ORDER BY updated_at
        """,
        params,
    ).fetchall()
    counts = {status: 0 for status in ATTEMPTED_STATUSES}
    blockers: dict[str, list[dict[str, Any]]] = {}
    submitted = []
    ready = []
    for row in rows:
        counts[row["status"]] += 1
        if row["status"] == "submitted":
            submitted.append(
                {
                    "job_id": row["id"],
                    "company": row["company"],
                    "title": row["title"],
                    "submitted_at": row["submitted_at"],
                    "confirmation_evidence": row["confirmation_evidence"],
                }
            )
        elif row["status"] == "ready_for_review":
            ready.append({"job_id": row["id"], "company": row["company"], "title": row["title"]})
        elif row["status"] == "blocked":
            blockers.setdefault(row["blocker_category"] or "uncategorized", []).append(
                {
                    "job_id": row["id"],
                    "company": row["company"],
                    "title": row["title"],
                    "message": row["blocker_message"],
                    "url": row["url"],
                }
            )
    if run_id:
        discovery: Any = discovery_summary(connection, run_id)
    else:
        run_params: list[Any] = []
        run_where = ""
        if since:
            run_where = "WHERE runs.started_at >= ?"
            run_params.append(since)
        discovery = [
            {
                "run_id": row["id"],
                "started_at": row["started_at"],
                "companies_checked": row["companies"],
                "postings_scanned": row["fetched"],
                "matches_kept": row["kept"],
            }
            for row in connection.execute(
                f"""
                SELECT runs.id, runs.started_at, COUNT(DISTINCT company) AS companies,
                    SUM(fetched) AS fetched, SUM(kept) AS kept
                FROM runs JOIN run_boards ON run_boards.run_id = runs.id
                {run_where}
                GROUP BY runs.id ORDER BY runs.started_at
                """,
                run_params,
            ).fetchall()
        ]
    return {
        **attempt_stats(connection, run_id=run_id, since=since),
        "counts": counts,
        "submitted": submitted,
        "ready_for_review": ready,
        "blockers": blockers,
        "discovery": discovery,
    }


def block_job(
    connection: sqlite3.Connection,
    job_id: str,
    worker_id: str,
    category: str,
    message: str,
    review_url: str | None = None,
) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown job: {job_id}")
    if row["status"] != "claimed" or row["claimed_by"] != worker_id:
        raise ValueError("Job is not claimed by this worker")
    connection.execute(
        """
        UPDATE jobs SET status='blocked', blocker_category=?, blocker_message=?,
            review_url=COALESCE(?, review_url),
            claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE id=?
        """,
        (category, message, review_url, iso_utc(), job_id),
    )
    finish_attempt(connection, job_id, "blocked")
    return dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def recover_stale_claims(
    connection: sqlite3.Connection,
    timeout_minutes: int,
    now: datetime | None = None,
) -> list[str]:
    cutoff = (now or utc_now()) - timedelta(minutes=timeout_minutes)
    rows = connection.execute(
        "SELECT id FROM jobs WHERE status='claimed' AND claimed_at < ?",
        (iso_utc(cutoff),),
    ).fetchall()
    recovered = [row["id"] for row in rows]
    if recovered:
        placeholders = ",".join("?" for _ in recovered)
        connection.execute(
            f"""
            UPDATE jobs SET status='queued', claimed_by=NULL, claimed_at=NULL,
                updated_at=? WHERE id IN ({placeholders})
            """,
            (iso_utc(now), *recovered),
        )
        for job_id in recovered:
            finish_attempt(connection, job_id, "abandoned")
    return recovered


def mark_notification(
    connection: sqlite3.Connection,
    notification_key: str,
    *,
    sent: bool,
    error: str | None = None,
) -> None:
    if sent:
        connection.execute(
            "UPDATE notifications SET sent_at=?, last_error=NULL WHERE notification_key=?",
            (iso_utc(), notification_key),
        )
    else:
        connection.execute(
            "UPDATE notifications SET reserved_at=NULL, last_error=? WHERE notification_key=?",
            (error or "notification failed", notification_key),
        )


def local_run_date(started_at: str, config: dict[str, Any]) -> str:
    started = parse_datetime(started_at)
    if started is None:
        return started_at[:10]
    return started.astimezone(ZoneInfo(config.get("timezone") or "UTC")).date().isoformat()


def digest_payload(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    run_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"Unknown run: {run_id}")
    counts = {
        row["status"]: row["count"]
        for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM jobs WHERE run_id=? GROUP BY status",
            (run_id,),
        ).fetchall()
    }
    key = f"digest:{run_id}"
    notification = connection.execute(
        "SELECT * FROM notifications WHERE notification_key=?", (key,)
    ).fetchone()
    if notification and notification["sent_at"]:
        return {"eligible": False, "reason": "already sent", "notification_key": key}
    connection.execute(
        """
        INSERT INTO notifications(notification_key, job_id, kind, reserved_at, sent_at, last_error)
        VALUES (?, NULL, 'digest', ?, NULL, NULL)
        ON CONFLICT(notification_key) DO UPDATE SET reserved_at=excluded.reserved_at, last_error=NULL
        """,
        (key, iso_utc(now)),
    )
    review_rows = connection.execute(
        """
        SELECT company, title, status,
            COALESCE(review_url, application_url) AS url,
            company_policy_id
        FROM jobs
        WHERE run_id=? AND status IN ('submitted', 'ready_for_review', 'blocked', 'manual_review')
        ORDER BY fit_score DESC
        """,
        (run_id,),
    ).fetchall()
    discovery = discovery_summary(connection, run_id)
    lines = [
        f"Daily job application run: {run_id}",
        f"Companies checked: {discovery['companies_checked']}",
        f"Postings scanned: {discovery['postings_scanned']}",
        f"Discovered: {sum(counts.values())}",
        f"Submitted: {counts.get('submitted', 0)}",
        f"Ready for review (not submitted): {counts.get('ready_for_review', 0)}",
        f"Blocked: {counts.get('blocked', 0)}",
        f"Manual attention: {counts.get('manual_review', 0)}",
        f"Skipped: {counts.get('skipped', 0)}",
        f"Queued or claimed: {counts.get('queued', 0) + counts.get('claimed', 0)}",
        "",
    ]
    for row in review_rows:
        policy = (
            f" — policy: {row['company_policy_id']}"
            if row["company_policy_id"]
            else ""
        )
        lines.append(
            f"- {row['status']}: {row['company']} — {row['title']} — {row['url']}{policy}"
        )
    outcomes = outcome_report(connection, run_id=run_id)
    lines.append("")
    if outcomes["attempts"]:
        lines.append(
            f"Submitted {outcomes['attempt_outcomes']['submitted']} of {outcomes['attempts']} "
            f"application attempts ({outcomes['submission_rate_percent']}%)."
        )
        for category, jobs in sorted(outcomes["blockers"].items()):
            lines.append(f"Blocked — {category}: {len(jobs)}")
    if discovery["companies_checked"]:
        lines.append("")
        if discovery["companies_with_matches"]:
            lines.append(
                "Companies with new matching roles: "
                + ", ".join(
                    f"{company} ({kept})"
                    for company, kept in sorted(discovery["companies_with_matches"].items())
                )
            )
        if discovery["companies_with_errors"]:
            lines.append("Boards with errors: " + ", ".join(discovery["companies_with_errors"]))
        lines.append("Companies checked: " + ", ".join(discovery["companies"]))
    if not counts.get("submitted"):
        lines.append("No applications were submitted.")
    return {
        "eligible": True,
        "notification_key": key,
        "email": {
            "to": config["notification_email"],
            "subject": f"Daily job application summary — {local_run_date(run['started_at'], config)}",
            "body": "\n".join(lines),
        },
        "counts": counts,
    }


def finish_run(connection: sqlite3.Connection, run_id: str) -> None:
    connection.execute(
        "UPDATE runs SET completed_at=?, status='completed' WHERE id=?",
        (iso_utc(), run_id),
    )
