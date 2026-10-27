from __future__ import annotations

import json
import re
import sqlite3
import uuid
import zipfile
from xml.etree import ElementTree
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "job-agent.sqlite3"
DEFAULT_RESUME_TEXT_PATH = PROJECT_ROOT / "data" / "resume.txt"
DEFAULT_COMPANY_POLICIES_PATH = (
    PROJECT_ROOT
    / ".claude"
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
    r"\b(?:ai|ml|machine learning|artificial intelligence|data science|deep learning|computer vision|"
    r"nlp|natural language processing|llms?|robot learning|research (?:scientist|engineer))\b"
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
    config.setdefault("limited_company_minimum_fit_score", 90)
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
                "application_limit": parse_application_limit(policy_id, raw.get("application_limit")),
            }
        )
        policies[-1]["swap"] = parse_swap(policy_id, raw.get("swap"), policies[-1]["application_limit"])
    return policies


def parse_application_limit(policy_id: str, raw: Any) -> dict[str, Any] | None:
    """A policy's ``application_limit``: the ATS caps how many applications one account sends.

    ``max_submissions`` within ``window_days`` is enforced from the ledger's own
    submissions (Ashby: one per company per 90 days). Other caps, such as Amazon's
    ten active applications, are only described: the ledger cannot see them, so
    they take effect when a worker reports one (``block --category application_limit``).
    ``max_active`` records a cap on active applications, which a ``swap`` policy needs.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict) or not str(raw.get("description") or "").strip():
        raise ValueError(f"Company policy {policy_id} application_limit needs a description")
    limit: dict[str, Any] = {"description": str(raw["description"]).strip()}
    for key in ("max_submissions", "window_days", "max_active"):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"Company policy {policy_id} application_limit.{key} must be a positive integer")
        limit[key] = value
    if ("max_submissions" in limit) != ("window_days" in limit):
        raise ValueError(f"Company policy {policy_id} needs both max_submissions and window_days, or neither")
    return limit


def parse_swap(policy_id: str, raw: Any, limit: dict[str, Any] | None) -> dict[str, Any] | None:
    """A policy's ``swap``: withdraw a weaker active application to free a slot for a stronger queued one.

    ``min_fit_gain`` is how much higher the queued job's fit must be than the
    withdrawn one's; ``max_withdrawals_per_run`` bounds the damage of one run.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Company policy {policy_id} swap must be an object")
    if not limit or "max_active" not in limit:
        raise ValueError(f"Company policy {policy_id} swap needs application_limit.max_active")
    swap: dict[str, Any] = {}
    for key in ("min_fit_gain", "max_withdrawals_per_run"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"Company policy {policy_id} swap.{key} must be a positive integer")
        swap[key] = value
    return swap


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


ATS_HOST_MARKERS = (
    ("myworkdayjobs", "workday"),
    ("myworkdaysite", "workday"),
    ("workday", "workday"),
    ("greenhouse", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq", "ashby"),
    ("amazon.jobs", "amazon"),
    ("icims", "icims"),
    ("smartrecruiters", "smartrecruiters"),
    ("successfactors", "successfactors"),
    ("sapsf", "successfactors"),
    ("taleo", "taleo"),
    ("oraclecloud", "oracle"),
    ("eightfold", "eightfold"),
    ("jobvite", "jobvite"),
)


def infer_ats(url: str | None, feed_ats: str | None = None) -> str:
    """The applicant tracking system behind an application URL.

    A known ATS host wins, then a Greenhouse embed's ``gh_jid`` parameter on a
    company careers page, then the feed's ATS, then the bare host.
    """
    parts = urlsplit(url or "")
    host = parts.netloc.lower()
    for marker, ats in ATS_HOST_MARKERS:
        if marker in host:
            return ats
    if "gh_jid=" in parts.query.lower():
        return "greenhouse"
    if feed_ats:
        return str(feed_ats).strip().lower()
    return host.removeprefix("www.") or "unknown"


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


def parse_skill_score(value: Any) -> int | None:
    """Return job-fit-scorer's 0-25 skill score, clamped, or None when it is missing or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        score = round(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(25, score))


def resume_text(path: Path | str) -> str:
    """Plain text of the résumé, so read-only agents can read a .docx."""
    resume = Path(path).expanduser()
    suffix = resume.suffix.lower()
    if suffix in (".txt", ".md"):
        return resume.read_text(encoding="utf-8").strip()
    if suffix != ".docx":
        raise ValueError(f"Cannot extract text from {resume.name}; use a .docx, .txt or .md résumé")
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(resume) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    lines = []
    for paragraph in root.iter(f"{word}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{word}t":
                parts.append(node.text or "")
            elif node.tag == f"{word}tab":
                parts.append("\t")
            elif node.tag in (f"{word}br", f"{word}cr"):
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def location_term_pattern(term: str) -> re.Pattern[str]:
    """Match ``term`` as whole words, so ", ca" matches "San Mateo, CA" but not "Toronto, Canada"."""
    term = term.lower()
    start = r"\b" if term[:1].isalnum() else ""
    end = r"\b" if term[-1:].isalnum() else ""
    return re.compile(start + re.escape(term) + end)


NON_US_LOCATION_PATTERN = re.compile(
    r"\b(?:uk|u\.k\.|united kingdom|england|scotland|wales|london|manchester|edinburgh|ireland|dublin|"
    r"france|paris|germany|berlin|munich|hamburg|switzerland|zurich|geneva|netherlands|amsterdam|"
    r"belgium|brussels|luxembourg|austria|vienna|spain|madrid|barcelona|portugal|lisbon|italy|milan|"
    r"rome|sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|iceland|estonia|tallinn|"
    r"latvia|riga|lithuania|vilnius|poland|warsaw|krakow|czechia|czech republic|prague|slovakia|"
    r"hungary|budapest|romania|bucharest|bulgaria|sofia|greece|athens|croatia|zagreb|serbia|belgrade|"
    r"slovenia|ukraine|kyiv|kiev|turkey|t[uü]rkiye|istanbul|cyprus|malta|israel|tel aviv|uae|"
    r"united arab emirates|dubai|abu dhabi|saudi arabia|riyadh|qatar|doha|egypt|cairo|nigeria|lagos|"
    r"kenya|nairobi|south africa|cape town|johannesburg|india|bangalore|bengaluru|hyderabad|pune|"
    r"chennai|mumbai|delhi|gurgaon|gurugram|noida|pakistan|china|shanghai|beijing|shenzhen|hong kong|"
    r"taiwan|taipei|japan|tokyo|korea|seoul|singapore|malaysia|kuala lumpur|indonesia|jakarta|"
    r"philippines|manila|vietnam|ho chi minh|hanoi|thailand|bangkok|australia|sydney|melbourne|"
    r"new zealand|auckland|canada|toronto|vancouver|montreal|ottawa|calgary|waterloo|ontario|quebec|"
    r"british columbia|alberta|brazil|s[aã]o paulo|mexico|argentina|buenos aires|colombia|bogot[aá]|"
    r"chile|santiago|peru|lima|costa rica|uruguay|emea|apac|latam|europe|european union|eu)\b"
)
US_STATE_NAMES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|"
    "idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|"
    "minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    "new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|"
    "south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    "wisconsin|wyoming|district of columbia"
)
US_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|"
    "NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
US_LOCATION_PATTERN = re.compile(
    rf"\b(?:us|u\.s\.?|usa|u\.s\.a\.|united states|north america|americas|{US_STATE_NAMES}|"
    r"nyc|boston|chicago|austin|dallas|houston|denver|boulder|atlanta|miami|pittsburgh|philadelphia|"
    r"phoenix|salt lake city|portland|minneapolis|detroit|raleigh|durham|nashville|baltimore|"
    r"san francisco|bay area|silicon valley|los angeles|seattle)\b"
)
# Upper case only, matched against the original text: ", or" and ", in" are words, ", OR" and ", IN" are states.
US_STATE_CODE_PATTERN = re.compile(rf",\s*(?:{US_STATE_CODES})\b")
# Words that say how the work is done rather than where; a location made only of
# these (plus punctuation) is a bare "Remote".
WORK_MODE_PATTERN = re.compile(
    r"\b(?:remote|virtual|hybrid|anywhere|fully|work from home|wfh|flexible|first|friendly|"
    r"optional|option|or|and|in|the|based|location|locations|multiple)\b|[^a-z]"
)
REMOTE_TERMS = ("remote", "virtual")
# Workday and Snowflake write "US-CA-Menlo Park"; read the state code as ", CA".
HYPHENATED_STATE_PATTERN = re.compile(rf"\b(US|USA)-({US_STATE_CODES})\b")
WASHINGTON_DC_PATTERN = re.compile(r"\bwashington,?\s*d\.?\s?c\b\.?|\bdistrict of columbia\b")


def location_matches(location: str, remote: bool, config: dict[str, Any]) -> bool:
    """True when at least one listed location is a preferred one or a US remote option.

    Boards list several locations separated by " | " (some use "; "). A part naming a non-US place
    never counts. A remote part (the posting's remote flag, or "remote" in the
    text) counts only when it also names the US (a state, a state code after a
    comma, a major US city, "US"), names a preferred place, or is a bare
    "Remote": Ashby flags Europe-only roles as remote, so ``"Prague"`` with a
    remote flag is rejected while ``"Austin, TX"`` with one is accepted.
    """
    if not location.strip():
        return True
    places = [
        location_term_pattern(str(term))
        for term in config.get("preferred_location_terms", ())
        if str(term).strip().lower() not in REMOTE_TERMS
    ]
    for original in (piece.strip() for piece in re.split(r"[|;]", location)):
        if not original:
            continue
        original = HYPHENATED_STATE_PATTERN.sub(r"\1, \2,", original)
        part = original.lower()
        us = bool(US_LOCATION_PATTERN.search(part) or US_STATE_CODE_PATTERN.search(original))
        if NON_US_LOCATION_PATTERN.search(part) and not us:
            continue
        # "washington" in preferred_location_terms means the state, not Washington, DC.
        place_text = WASHINGTON_DC_PATTERN.sub(" ", part)
        if any(pattern.search(place_text) for pattern in places):
            return True
        is_remote = remote or any(term in part for term in REMOTE_TERMS)
        if is_remote and (us or not WORK_MODE_PATTERN.sub("", part)):
            return True
    return False


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

    remote = bool(candidate.get("remote"))
    location_match = location_matches(location, remote, config) if location else remote
    if location and not location_match:
        return ScoreResult(0, [], "location is outside California, Washington, or US remote")

    role_points = 30
    # job-fit-scorer reads the post against the résumé and sets skill_score;
    # the keyword count is only a fallback for jobs ingested without one.
    llm_skill_score = parse_skill_score(candidate.get("skill_score"))
    if llm_skill_score is not None:
        skill_points = llm_skill_score
        skill_detail = f"job-fit-scorer: {str(candidate.get('skill_rationale') or '').strip() or 'no rationale'}"
    else:
        skills = sorted({term for term in config["skill_keywords"] if term.lower() in combined})
        skill_points = min(25, round(len(skills) / 8 * 25))
        skill_detail = f"keyword fallback: {', '.join(skills[:8]) or 'no explicit overlap'}"
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
        f"skills {skill_points}/25 ({skill_detail})",
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
    ats TEXT,
    title TEXT NOT NULL,
    location TEXT,
    remote INTEGER NOT NULL DEFAULT 0,
    posted_at TEXT,
    discovered_at TEXT NOT NULL,
    description TEXT,
    minimum_years INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    skill_score INTEGER,
    skill_rationale TEXT,
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
    withdrawn_at TEXT,
    withdrawal_evidence TEXT,
    withdrawn_run_id TEXT,
    replaced_by TEXT,
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

-- Application caps a site reported for a company (Amazon's ten active
-- applications, Ashby's one per 90 days). While one is active (not cleared,
-- until unset or in the future) claim skips the company and leaves its jobs
-- queued. company_key is the policy id when a policy matches, else the
-- normalized company name.
CREATE TABLE IF NOT EXISTS company_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    company_key TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    until TEXT,
    cleared_at TEXT,
    job_id TEXT REFERENCES jobs(id),
    message TEXT NOT NULL
);

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
    for name, column_type in (
        ("company_policy_id", "TEXT"),
        ("company_policy_document", "TEXT"),
        ("submitted_at", "TEXT"),
        ("confirmation_evidence", "TEXT"),
        ("skill_score", "INTEGER"),
        ("skill_rationale", "TEXT"),
        ("ats", "TEXT"),
        ("withdrawn_at", "TEXT"),
        ("withdrawal_evidence", "TEXT"),
        ("withdrawn_run_id", "TEXT"),
        ("replaced_by", "TEXT"),
    ):
        if name not in existing_columns:
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}")
    for row in connection.execute(
        "SELECT id, application_url, canonical_url FROM jobs WHERE ats IS NULL OR ats LIKE '%.%'"
    ).fetchall():
        connection.execute(
            "UPDATE jobs SET ats=? WHERE id=?",
            (infer_ats(row["application_url"] or row["canonical_url"]), row["id"]),
        )
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


MAX_RECENCY_WINDOW_HOURS = 72


def recency_window_hours(connection: sqlite3.Connection, config: dict[str, Any], before: datetime) -> int:
    """Hours of postings a discovery at ``before`` must cover: back to the previous discovery, plus 2h.

    At least ``recency_hours``; at most three days, so a long gap does not flood the queue.
    The daily run drifts (07:00 one day, 13:00 after a missed run the next), and a fixed 24h
    window then leaves hours that no run ever looks at.
    """
    base = int(config["recency_hours"])
    row = connection.execute(
        """
        SELECT MAX(runs.started_at) AS started_at FROM runs
        WHERE runs.started_at < ? AND EXISTS (
            SELECT 1 FROM run_boards WHERE run_boards.run_id = runs.id AND run_boards.fetched > 0
        )
        """,
        (iso_utc(before),),
    ).fetchone()
    previous = parse_datetime(row["started_at"]) if row else None
    if previous is None:
        return base
    gap_hours = int((before - previous).total_seconds() // 3600) + 1
    return max(base, min(MAX_RECENCY_WINDOW_HOURS, gap_hours + 2))


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
            parse_skill_score(candidate.get("skill_score")),
            str(candidate.get("skill_rationale") or "").strip() or None,
            application_url,
            infer_ats(application_url, candidate.get("ats")),
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
                    description, minimum_years, active, skill_score, skill_rationale,
                    application_url, ats, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted.append(job_id)
        except sqlite3.IntegrityError:
            duplicates.append(canonical_url)
    return {"run_id": run_id, "inserted": inserted, "duplicates": duplicates}


APPLICATION_LIMIT_CATEGORY = "application_limit"


def company_key(company: str, policies: Iterable[dict[str, Any]]) -> str:
    """One key per employer: its policy id when a policy matches (so aliases share it), else its name."""
    policy = match_company_policy(company, policies)
    return f"policy:{policy['id']}" if policy else normalize_company_name(company)


def limited_company_keys(connection: sqlite3.Connection, policies: list[dict[str, Any]]) -> set[str]:
    """Companies with an application limit: one in their policy, or one a site has reported."""
    keys = {f"policy:{policy['id']}" for policy in policies if policy.get("application_limit")}
    keys.update(
        row["company_key"]
        for row in connection.execute("SELECT DISTINCT company_key FROM company_limits").fetchall()
    )
    return keys


def queue_threshold(
    company: str,
    config: dict[str, Any],
    policies: list[dict[str, Any]],
    limited_keys: set[str],
) -> int:
    """Fit needed to queue a job: higher for companies that cap applications, to spend the cap on the best fits."""
    base = int(config["minimum_fit_score"])
    if company_key(company, policies) in limited_keys:
        return max(base, int(config.get("limited_company_minimum_fit_score", 90)))
    return base


def active_limits(
    connection: sqlite3.Connection,
    policies: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Companies whose application cap is in force now, keyed by ``company_key``."""
    current = now or utc_now()
    active: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        "SELECT * FROM company_limits WHERE cleared_at IS NULL ORDER BY reported_at"
    ).fetchall():
        until = parse_datetime(row["until"])
        if until is None or until > current:
            active[row["company_key"]] = {
                "company": row["company"],
                "source": "reported",
                "reason": row["message"],
                "until": row["until"],
            }
    windowed = [policy for policy in policies if (policy.get("application_limit") or {}).get("max_submissions")]
    if not windowed:
        return active
    submissions = connection.execute(
        "SELECT company, submitted_at FROM jobs WHERE status='submitted' AND submitted_at IS NOT NULL"
    ).fetchall()
    for policy in windowed:
        limit = policy["application_limit"]
        window = timedelta(days=limit["window_days"])
        recent = sorted(
            submitted
            for row in submissions
            if normalize_company_name(row["company"]) in policy["normalized_company_names"]
            and (submitted := parse_datetime(row["submitted_at"])) is not None
            and submitted > current - window
        )
        if len(recent) >= limit["max_submissions"]:
            active.setdefault(
                f"policy:{policy['id']}",
                {
                    "company": policy["company_names"][0],
                    "source": "policy",
                    "reason": limit["description"],
                    "until": iso_utc(recent[len(recent) - limit["max_submissions"]] + window),
                },
            )
    return active


def deferred_jobs(
    connection: sqlite3.Connection,
    policies: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Queued jobs that claim passes over because their company's application cap is in force."""
    active = active_limits(connection, policies, now)
    if not active:
        return []
    deferred = []
    for row in connection.execute(
        "SELECT id, company, title, fit_score FROM jobs WHERE status='queued' ORDER BY fit_score DESC"
    ).fetchall():
        limit = active.get(company_key(row["company"], policies))
        if limit:
            deferred.append({**dict(row), "until": limit["until"], "reason": limit["reason"]})
    return deferred


def clear_limits(
    connection: sqlite3.Connection,
    company: str,
    policies: list[dict[str, Any]],
) -> int:
    """Lift a reported cap, e.g. after the user withdrew applications. Returns how many records were cleared."""
    cursor = connection.execute(
        "UPDATE company_limits SET cleared_at=? WHERE company_key=? AND cleared_at IS NULL",
        (iso_utc(), company_key(company, policies)),
    )
    return cursor.rowcount


SWAPPABLE_ATS_STATUS = "SUBMITTED"


def swap_policy(company: str, policies: list[dict[str, Any]]) -> dict[str, Any]:
    policy = match_company_policy(company, policies)
    if not policy or not policy.get("swap"):
        raise ValueError(f"{company} has no swap policy")
    return policy


def withdrawals_in_run(connection: sqlite3.Connection, run_id: str | None, policy: dict[str, Any]) -> int:
    rows = connection.execute(
        "SELECT company FROM jobs WHERE status='withdrawn' AND withdrawn_run_id IS ?", (run_id,)
    ).fetchall()
    return sum(1 for row in rows if normalize_company_name(row["company"]) in policy["normalized_company_names"])


def swap_plan(
    connection: sqlite3.Connection,
    company: str,
    active: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    keep: Iterable[str] = (),
) -> dict[str, Any]:
    """Which active applications to withdraw for stronger queued jobs at a company with a swap policy.

    ``active`` is the site's own list of active applications (``ats_job_id`` and
    ``status``). Only applications the ledger submitted, still in the site's
    plain submitted state and not in ``keep`` (recruiter contact) can be withdrawn;
    the rest hold their slots. Pairs go weakest-for-strongest while the fit gain
    is at least ``min_fit_gain``, up to the run's remaining withdrawals. When the
    site shows a free slot there is nothing to withdraw: ``free_slots`` says so
    and the caller clears the reported limit.
    """
    policy = swap_policy(company, policies)
    full = next(p for p in policies if p["id"] == policy["id"])
    cap = policy["application_limit"]["max_active"]
    swap = policy["swap"]
    aliases = full["normalized_company_names"]
    kept = {str(job_id) for job_id in keep}
    swappable_ids = {
        str(item["ats_job_id"])
        for item in active
        if str(item.get("status") or "").upper() == SWAPPABLE_ATS_STATUS and str(item["ats_job_id"]) not in kept
    }
    rows = connection.execute(
        "SELECT id, company, title, fit_score, ats_job_id, submitted_at, status FROM jobs "
        "WHERE status IN ('submitted', 'queued') ORDER BY fit_score DESC, COALESCE(posted_at, discovered_at) DESC"
    ).fetchall()
    rows = [row for row in rows if normalize_company_name(row["company"]) in aliases]
    queued = [dict(row) for row in rows if row["status"] == "queued"]
    withdrawable = sorted(
        (dict(row) for row in rows if row["status"] == "submitted" and str(row["ats_job_id"]) in swappable_ids),
        key=lambda row: (row["fit_score"] or 0, row["submitted_at"] or ""),
    )
    remaining = max(0, swap["max_withdrawals_per_run"] - withdrawals_in_run(connection, run_id, full))
    free_slots = max(0, cap - len(active))
    pairs = []
    if not free_slots:
        for replacement, withdraw in zip(queued, withdrawable):
            if len(pairs) >= remaining or (replacement["fit_score"] or 0) < (withdraw["fit_score"] or 0) + swap["min_fit_gain"]:
                break
            pairs.append({"withdraw": withdraw, "replacement": replacement})
    return {
        "company": company,
        "active": len(active),
        "max_active": cap,
        "free_slots": free_slots,
        "withdrawals_left_this_run": remaining,
        "min_fit_gain": swap["min_fit_gain"],
        "pairs": pairs,
    }


def withdraw_job(
    connection: sqlite3.Connection,
    job_id: str,
    *,
    replacement_job_id: str,
    evidence: str,
    policies: list[dict[str, Any]],
    run_id: str | None = None,
    submit_applications: bool,
) -> dict[str, Any]:
    """Record a withdrawn application and lift the company's reported cap so its replacement can be claimed."""
    if not submit_applications:
        raise ValueError("Withdrawal is disabled: submit_applications is not true in config")
    if not evidence.strip():
        raise ValueError("Withdrawal requires on-page evidence")
    row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    replacement = connection.execute("SELECT * FROM jobs WHERE id=?", (replacement_job_id,)).fetchone()
    if row is None or replacement is None:
        raise ValueError(f"Unknown job: {job_id if row is None else replacement_job_id}")
    if row["status"] != "submitted":
        raise ValueError(f"Job {job_id} is {row['status']}; only submitted applications can be withdrawn")
    policy = swap_policy(row["company"], policies)
    full = next(p for p in policies if p["id"] == policy["id"])
    if company_key(replacement["company"], policies) != f"policy:{policy['id']}" or replacement["status"] != "queued":
        raise ValueError(f"Replacement {replacement_job_id} is not a queued {row['company']} job")
    if (replacement["fit_score"] or 0) < (row["fit_score"] or 0) + policy["swap"]["min_fit_gain"]:
        raise ValueError(
            f"Replacement fit {replacement['fit_score']} is not {policy['swap']['min_fit_gain']} above {row['fit_score']}"
        )
    if withdrawals_in_run(connection, run_id, full) >= policy["swap"]["max_withdrawals_per_run"]:
        raise ValueError(f"This run already withdrew {policy['swap']['max_withdrawals_per_run']} {row['company']} applications")
    now = iso_utc()
    connection.execute(
        """
        UPDATE jobs SET status='withdrawn', withdrawn_at=?, withdrawal_evidence=?,
            withdrawn_run_id=?, replaced_by=?, updated_at=? WHERE id=?
        """,
        (now, evidence.strip(), run_id, replacement_job_id, now, job_id),
    )
    cleared = clear_limits(connection, row["company"], policies)
    job = dict(connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    return {**job, "limits_cleared": cleared}


def requeue_jobs(connection: sqlite3.Connection, job_ids: Iterable[str]) -> list[str]:
    """Put blocked or ready-for-review jobs back in the queue for a fresh attempt."""
    requeued = []
    for job_id in job_ids:
        row = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown job: {job_id}")
        if row["status"] not in ("blocked", "ready_for_review"):
            raise ValueError(f"Job {job_id} is {row['status']}; only blocked or ready_for_review jobs can be re-queued")
        connection.execute(
            """
            UPDATE jobs SET status='queued', blocker_category=NULL, blocker_message=NULL,
                claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE id=?
            """,
            (iso_utc(), job_id),
        )
        requeued.append(job_id)
    return requeued


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
    # Without an explicit ``now``, a job's age is measured when its run discovered it, against the
    # window that discovery covered, so scoring hours later does not drop what discovery kept.
    windows: dict[str, tuple[dict[str, Any], datetime | None]] = {}
    for row in rows:
        candidate = dict(row)
        if now is None and row["run_id"] not in windows:
            run = connection.execute("SELECT started_at FROM runs WHERE id=?", (row["run_id"],)).fetchone()
            started = parse_datetime(run["started_at"]) if run else None
            windows[row["run_id"]] = (
                {**config, "recency_hours": recency_window_hours(connection, config, started)} if started else config,
                started,
            )
        run_config, reference = windows.get(row["run_id"], (config, now))
        result = score_candidate(candidate, run_config, now=reference)
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

    # Every job at or above its company's threshold is queued; there is no daily cap.
    queue_params: list[Any] = [int(config["minimum_fit_score"])]
    queue_where = "status='scored' AND fit_score >= ?"
    if run_id:
        queue_where += " AND run_id = ?"
        queue_params.append(run_id)
    selected = connection.execute(
        f"""
        SELECT id, company, fit_score FROM jobs WHERE {queue_where}
        ORDER BY fit_score DESC, COALESCE(posted_at, discovered_at) DESC
        """,
        queue_params,
    ).fetchall()
    limited = limited_company_keys(connection, policies)
    queued = [
        row["id"]
        for row in selected
        if row["fit_score"] >= queue_threshold(row["company"], config, policies, limited)
    ]
    held = [row["id"] for row in selected if row["id"] not in set(queued)]
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
        # Scored above minimum_fit_score but below the higher bar for companies with an application limit.
        "held_below_limited_threshold": held,
    }


def claim_next(
    connection: sqlite3.Connection,
    worker_id: str,
    company_policies_path: Path | str = DEFAULT_COMPANY_POLICIES_PATH,
    run_id: str | None = None,
    *,
    limited_minimum_fit_score: int = 90,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Claim the best queued job and log the attempt against ``run_id`` (default: latest running run).

    A company with a job already claimed is passed over, so parallel workers never
    sign in to, or create, the same company's account at the same time. So is a
    company whose application cap is in force (``active_limits``); its jobs stay
    queued. A queued job at a company with an application limit that scores below
    ``limited_minimum_fit_score`` goes back to ``scored``.
    """
    policies = load_company_policies(company_policies_path)
    connection.execute("BEGIN IMMEDIATE")
    try:
        queued_rows = connection.execute(
            "SELECT id, company, fit_score FROM jobs WHERE status='queued'"
        ).fetchall()
        limited = limited_company_keys(connection, policies)
        for queued_row in queued_rows:
            if (
                company_key(queued_row["company"], policies) in limited
                and (queued_row["fit_score"] or 0) < limited_minimum_fit_score
            ):
                connection.execute(
                    "UPDATE jobs SET status='scored', updated_at=? WHERE id=? AND status='queued'",
                    (iso_utc(), queued_row["id"]),
                )
                continue
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
        capped = active_limits(connection, policies, now)
        row = next(
            (
                candidate
                for candidate in connection.execute(
                    """
                    SELECT * FROM jobs WHERE status='queued'
                        AND LOWER(TRIM(company)) NOT IN (
                            SELECT LOWER(TRIM(company)) FROM jobs WHERE status='claimed'
                        )
                    ORDER BY fit_score DESC, COALESCE(posted_at, discovered_at) DESC
                    """
                ).fetchall()
                if company_key(candidate["company"], policies) not in capped
            ),
            None,
        )
        if row is None:
            connection.execute("COMMIT")
            return None
        now = iso_utc()
        connection.execute(
            """
            UPDATE jobs SET status='claimed', claimed_by=?, claimed_at=?,
                blocker_category=NULL, blocker_message=NULL,
                attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'
            """,
            (worker_id, now, now, row["id"]),
        )
        if run_id is None:
            run_id = latest_running_run(connection)
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


def latest_running_run(connection: sqlite3.Connection) -> str | None:
    running = connection.execute(
        "SELECT id FROM runs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return running["id"] if running else None


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


def attempt_breakdown(
    connection: sqlite3.Connection,
    group_by: str,
    *,
    run_id: str | None = None,
    since: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Attempt outcomes, submission rate and blocker categories per ATS (``group_by="ats"``) or company."""
    if group_by not in ("ats", "company"):
        raise ValueError(f"Cannot group attempts by {group_by}")
    clauses = ["attempts.finished_at IS NOT NULL"]
    params: list[Any] = []
    if run_id:
        clauses.append("attempts.run_id=?")
        params.append(run_id)
    if since:
        clauses.append("attempts.claimed_at >= ?")
        params.append(since)
    groups: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        f"""
        SELECT COALESCE(jobs.{group_by}, 'unknown') AS grp, attempts.outcome,
            jobs.blocker_category, COUNT(*) AS count
        FROM attempts JOIN jobs ON jobs.id = attempts.job_id
        WHERE {' AND '.join(clauses)}
        GROUP BY grp, attempts.outcome, jobs.blocker_category
        """,
        params,
    ).fetchall():
        group = groups.setdefault(
            row["grp"],
            {"attempts": 0, "outcomes": {outcome: 0 for outcome in ATTEMPT_OUTCOMES}, "blockers": {}},
        )
        group["attempts"] += row["count"]
        group["outcomes"][row["outcome"]] = group["outcomes"].get(row["outcome"], 0) + row["count"]
        if row["outcome"] == "blocked":
            category = row["blocker_category"] or "uncategorized"
            group["blockers"][category] = group["blockers"].get(category, 0) + row["count"]
    for group in groups.values():
        group["submission_rate_percent"] = round(100 * group["outcomes"]["submitted"] / group["attempts"], 1)
    return dict(sorted(groups.items()))


def outcome_report(
    connection: sqlite3.Connection,
    *,
    run_id: str | None = None,
    since: str | None = None,
    policies: list[dict[str, Any]] | None = None,
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
    skip_params: list[Any] = []
    skip_where = "status='skipped'"
    if run_id:
        skip_where += " AND run_id=?"
        skip_params.append(run_id)
    if since:
        skip_where += " AND updated_at >= ?"
        skip_params.append(since)
    skipped_by_ats = {
        row["ats"]: row["count"]
        for row in connection.execute(
            f"SELECT COALESCE(ats, 'unknown') AS ats, COUNT(*) AS count FROM jobs WHERE {skip_where} GROUP BY 1 ORDER BY 1",
            skip_params,
        ).fetchall()
    }
    policies = policies or []
    return {
        **attempt_stats(connection, run_id=run_id, since=since),
        "counts": counts,
        "submitted": submitted,
        "ready_for_review": ready,
        "blockers": blockers,
        # A blocked attempt's category is the job's latest one; a retried job reports its newest blocker.
        "by_ats": attempt_breakdown(connection, "ats", run_id=run_id, since=since),
        "by_company": attempt_breakdown(connection, "company", run_id=run_id, since=since),
        "skipped_by_ats": skipped_by_ats,
        "application_limits": list(active_limits(connection, policies).values()),
        "deferred": deferred_jobs(connection, policies),
        "withdrawn": withdrawn_jobs(connection, run_id=run_id, since=since),
        "discovery": discovery,
    }


def withdrawn_jobs(
    connection: sqlite3.Connection, *, run_id: str | None = None, since: str | None = None
) -> list[dict[str, Any]]:
    """Applications withdrawn to free a slot, each with the job that replaced it."""
    clauses = ["w.status='withdrawn'"]
    params: list[Any] = []
    if run_id:
        clauses.append("w.withdrawn_run_id=?")
        params.append(run_id)
    if since:
        clauses.append("w.withdrawn_at >= ?")
        params.append(since)
    return [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT w.id AS job_id, w.company, w.title, w.fit_score, w.withdrawn_at,
                r.id AS replacement_job_id, r.title AS replacement_title,
                r.fit_score AS replacement_fit_score, r.status AS replacement_status
            FROM jobs w LEFT JOIN jobs r ON r.id = w.replaced_by
            WHERE {' AND '.join(clauses)} ORDER BY w.withdrawn_at
            """,
            params,
        ).fetchall()
    ]


def block_job(
    connection: sqlite3.Connection,
    job_id: str,
    worker_id: str,
    category: str,
    message: str,
    review_url: str | None = None,
    *,
    policies: list[dict[str, Any]] | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Record a blocked attempt.

    ``application_limit`` means the site refused because the account hit its
    application cap: the cap is recorded for the company and the job goes back to
    ``queued`` (deferred, not blocked) so it is retried once the cap lifts.
    """
    row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown job: {job_id}")
    if row["status"] != "claimed" or row["claimed_by"] != worker_id:
        raise ValueError("Job is not claimed by this worker")
    status = "blocked"
    if category == APPLICATION_LIMIT_CATEGORY:
        if until is not None and parse_datetime(until) is None:
            raise ValueError(f"--until is not an ISO date or timestamp: {until}")
        status = "queued"
        connection.execute(
            """
            INSERT INTO company_limits(company, company_key, reported_at, until, job_id, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["company"],
                company_key(row["company"], policies or []),
                iso_utc(),
                iso_utc(parse_datetime(until)) if until else None,
                job_id,
                message,
            ),
        )
    connection.execute(
        """
        UPDATE jobs SET status=?, blocker_category=?, blocker_message=?,
            review_url=COALESCE(?, review_url),
            claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE id=?
        """,
        (status, category, message, review_url, iso_utc(), job_id),
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
    policies = load_company_policies(
        config.get("company_policies_path", DEFAULT_COMPANY_POLICIES_PATH)
    )
    outcomes = outcome_report(connection, run_id=run_id, policies=policies)
    lines.append("")
    if outcomes["attempts"]:
        lines.append(
            f"Submitted {outcomes['attempt_outcomes']['submitted']} of {outcomes['attempts']} "
            f"application attempts ({outcomes['submission_rate_percent']}%)."
        )
        for category, jobs in sorted(outcomes["blockers"].items()):
            lines.append(f"Blocked — {category}: {len(jobs)}")
        lines.append(
            "By ATS: "
            + ", ".join(
                f"{ats} {group['outcomes']['submitted']}/{group['attempts']}"
                for ats, group in outcomes["by_ats"].items()
            )
        )
    if outcomes["deferred"]:
        deferred: dict[str, int] = {}
        for job in outcomes["deferred"]:
            deferred[job["company"]] = deferred.get(job["company"], 0) + 1
        lines.append(
            "Deferred by an application limit (still queued): "
            + ", ".join(f"{company} ({count})" for company, count in sorted(deferred.items()))
        )
    for job in outcomes["withdrawn"]:
        lines.append(
            f"Withdrew {job['company']} — {job['title']} (fit {job['fit_score']}) for "
            f"{job['replacement_title']} (fit {job['replacement_fit_score']}, now {job['replacement_status']})"
        )
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
