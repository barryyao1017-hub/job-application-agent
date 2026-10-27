"""Feed-based job discovery.

Pulls the public job boards of the companies listed in a registry file
(Greenhouse, Lever and Ashby publish official unauthenticated JSON boards;
Workday's ``/wday/cxs`` endpoint and ``amazon.jobs/en/search.json`` are
unofficial but stable), keeps the postings that look like recent ML/Data roles
in the preferred locations, and writes them in the ``discovered.json`` shape
that ``python3 -m job_agent discover`` ingests.

Only the standard library is used. Each board is fetched on its own thread and
a failing board is reported in the stats instead of aborting the run.

Timestamps: Greenhouse, Lever and Ashby give exact publish times. Workday only
says "Posted Today" / "Posted Yesterday" / "Posted N Days Ago" and Amazon gives
a calendar date, so those postings get ``posted_at`` set to the end of that day
in the configured timezone (capped at fetch time) and carry
``"posted_at_precision": "day"``. A posting from yesterday therefore counts as
recent during a morning run, which is the intent of a 24-hour window.
"""

from __future__ import annotations

import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .core import (
    INTERNSHIP_TITLE_PATTERN,
    MANAGEMENT_TITLE_TERMS,
    ML_SIGNAL_PATTERN,
    PROJECT_ROOT,
    iso_utc,
    location_matches,
    parse_datetime,
    utc_now,
)

DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "company-registry.json"
DEFAULT_QUERIES = (
    "machine learning engineer",
    "data scientist",
    "applied scientist",
    "ai engineer",
)
SUPPORTED_ATS = ("greenhouse", "lever", "ashby", "workday", "amazon")
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = "Mozilla/5.0 (compatible; job-application-agent/0.1)"
MAX_DESCRIPTION_CHARS = 6000
MAX_WORKERS = 12
DETAIL_WORKERS = 6
WORKDAY_PAGE_SIZE = 20
AMAZON_PAGE_SIZE = 100
WORKDAY_POSTED_PATTERN = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)
# CA bundles to fall back on when this Python ships none: python.org's macOS
# installer leaves etc/openssl empty until "Install Certificates.command" runs.
FALLBACK_CA_FILES = ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem", "/usr/local/etc/ca-certificates/cert.pem")

Fetch = Callable[[str, dict[str, Any] | None], Any]


# --- HTTP ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """Default certificate verification, with a system CA bundle when Python has none."""
    context = ssl.create_default_context()
    defaults = ssl.get_default_verify_paths()
    if defaults.cafile or defaults.capath:
        return context
    for candidate in FALLBACK_CA_FILES:
        if Path(candidate).is_file():
            context.load_verify_locations(cafile=candidate)
            break
    return context


def fetch_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    """GET ``url`` (or POST ``payload`` as JSON) and parse the JSON response."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(
        request, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context()
    ) as response:
        return json.loads(response.read().decode("utf-8"))


# --- Registry ------------------------------------------------------------------


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    registry_path = Path(path).expanduser()
    with registry_path.open("r", encoding="utf-8") as handle:
        entries = json.load(handle)
    if isinstance(entries, dict):
        entries = entries.get("companies")
    if not isinstance(entries, list):
        raise ValueError("Company registry must be a JSON array of entries")
    validated = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Registry entry {index} is not an object")
        company = str(entry.get("company") or "").strip()
        ats = str(entry.get("ats") or "").strip().lower()
        if not company:
            raise ValueError(f"Registry entry {index} is missing company")
        if ats not in SUPPORTED_ATS:
            raise ValueError(
                f"Registry entry {index} ({company}) has unsupported ats {ats!r}; "
                f"expected one of {', '.join(SUPPORTED_ATS)}"
            )
        if ats in {"greenhouse", "lever", "ashby"} and not entry.get("token"):
            raise ValueError(f"Registry entry {index} ({company}) needs a {ats} board token")
        if ats == "workday":
            missing = [key for key in ("host", "tenant", "site") if not entry.get(key)]
            if missing:
                raise ValueError(
                    f"Registry entry {index} ({company}) needs workday {', '.join(missing)}"
                )
        validated.append({**entry, "company": company, "ats": ats})
    return validated


# --- Text helpers --------------------------------------------------------------


def strip_html(text: str | None) -> str:
    """Turn an HTML fragment (possibly entity-escaped, as Greenhouse sends it) into plain text."""
    if not text:
        return ""
    unescaped = html.unescape(str(text))
    if "<" in unescaped and ">" in unescaped:
        unescaped = re.sub(
            r"(?i)<\s*/?\s*(?:br|p|li|div|h[1-6]|tr|ul|ol|table|section|article|blockquote)\b[^>]*>",
            "\n",
            unescaped,
        )
        unescaped = re.sub(r"(?i)<\s*/?\s*(?:td|th)\b[^>]*>", " ", unescaped)
        unescaped = re.sub(r"<[^>]+>", "", unescaped)
        unescaped = html.unescape(unescaped)
    lines = [" ".join(line.split()) for line in unescaped.replace("\xa0", " ").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def clip_description(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[:MAX_DESCRIPTION_CHARS].rstrip() + "…"


def end_of_day(day: datetime, now: datetime, zone: ZoneInfo) -> datetime:
    """The latest moment a day-granular posting could have appeared, in UTC, never after ``now``."""
    local = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=zone)
    return min(local.astimezone(timezone.utc), now.astimezone(timezone.utc))


def workday_posted_at(posted_on: str | None, now: datetime, zone: ZoneInfo) -> datetime | None:
    """Map Workday's relative text ("Posted Today", "Posted 3 Days Ago") to a timestamp."""
    text = (posted_on or "").strip().lower()
    if not text:
        return None
    today = now.astimezone(zone)
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        match = WORKDAY_POSTED_PATTERN.search(text)
        if not match:
            return None
        days = int(match.group(1))
    return end_of_day(today - timedelta(days=days), now, zone)


def amazon_posted_at(posted_date: str | None, now: datetime, zone: ZoneInfo) -> datetime | None:
    """Map Amazon's "October 14, 2026" to the end of that day."""
    text = (posted_date or "").strip()
    if not text:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            day = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return end_of_day(day, now, zone)
    return None


def epoch_millis(value: Any) -> datetime | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


# --- Filters -------------------------------------------------------------------


NON_ENGINEERING_TITLE_PATTERN = re.compile(
    r"\b(?:manager|account executive|sales|business development|customer success|customer engineer|"
    r"solutions? architect|solutions? engineer|marketing|recruit(?:er|ing)|talent|fp&a|finance|"
    r"accountant|legal|counsel|partnerships?|support engineer|technical writer|designer|evangelist|"
    r"advocate|specialist)\b"
)


def title_matches(title: str, config: dict[str, Any]) -> bool:
    """True when the title reads as an ML/Data individual-contributor role.

    Mirrors the hard filters in ``core.score_candidate`` so that nothing the
    scorer would skip on title alone is fetched in detail or written out.
    """
    lower = " ".join(title.lower().split())
    if not lower:
        return False
    if INTERNSHIP_TITLE_PATTERN.search(lower):
        return False
    if any(term in lower for term in MANAGEMENT_TITLE_TERMS):
        return False
    if NON_ENGINEERING_TITLE_PATTERN.search(lower):
        return False
    if ML_SIGNAL_PATTERN.search(lower):
        return True
    return any(str(term).lower() in lower for term in config.get("role_keywords", ()))


def is_recent(posted_at: datetime | None, now: datetime, config: dict[str, Any]) -> bool:
    if posted_at is None:
        return False
    return now - posted_at <= timedelta(hours=int(config["recency_hours"]))


def join_locations(parts: list[Any]) -> str:
    seen: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if text and text not in seen:
            seen.append(text)
    return " | ".join(seen)


# --- Candidate assembly ----------------------------------------------------------


def make_candidate(
    *,
    company: str,
    ats: str,
    title: str,
    url: str,
    location: str,
    remote: bool,
    posted_at: datetime | None,
    description: str,
    ats_job_id: str | None,
    day_precision: bool = False,
    application_url: str | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "source": "ats-api",
        "source_url": url,
        "application_url": application_url or url,
        "company": company,
        "title": " ".join(title.split()),
        "location": location,
        "remote": bool(remote),
        "posted_at": iso_utc(posted_at) if posted_at else None,
        "description": clip_description(description),
        "minimum_years": None,
        "active": True,
        "ats": ats,
        "ats_job_id": str(ats_job_id) if ats_job_id not in (None, "") else None,
    }
    if day_precision:
        candidate["posted_at_precision"] = "day"
    return candidate


class BoardResult:
    """What one board produced: candidates plus fetch statistics."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self.entry = entry
        self.candidates: list[dict[str, Any]] = []
        self.fetched = 0
        self.errors: list[str] = []
        self.skipped = {"title": 0, "stale": 0, "location": 0, "undated": 0}
        self.seconds = 0.0

    def prefilter(self, config: dict[str, Any], now: datetime, title: str, posted_at: datetime | None) -> bool:
        """Count the posting and apply the filters that need no detail fetch (title, date)."""
        self.fetched += 1
        if not title_matches(title, config):
            self.skipped["title"] += 1
            return False
        if posted_at is None:
            self.skipped["undated"] += 1
            return False
        if not is_recent(posted_at, now, config):
            self.skipped["stale"] += 1
            return False
        return True

    def admit(self, config: dict[str, Any], candidate: dict[str, Any]) -> bool:
        """Apply the location filter to a built candidate and keep it when it passes."""
        if not location_matches(candidate["location"], candidate["remote"], config):
            self.skipped["location"] += 1
            return False
        self.candidates.append(candidate)
        return True

    def consider(
        self,
        config: dict[str, Any],
        now: datetime,
        *,
        title: str,
        posted_at: datetime | None,
        build: Callable[[], dict[str, Any]],
        location: str | None = None,
        remote: bool = False,
    ) -> bool:
        """Apply the shared filters; call ``build`` (which may fetch details) only for survivors.

        Pass ``location``/``remote`` when the listing already carries them so that
        a detail fetch inside ``build`` is skipped for postings outside the preferred
        locations; ``admit`` checks the built candidate's location either way.
        """
        if not self.prefilter(config, now, title, posted_at):
            return False
        if location is not None and not location_matches(location, remote, config):
            self.skipped["location"] += 1
            return False
        return self.admit(config, build())

    def stats(self) -> dict[str, Any]:
        stats = {
            "company": self.entry["company"],
            "ats": self.entry["ats"],
            "fetched": self.fetched,
            "kept": len(self.candidates),
            "skipped": dict(self.skipped),
            "errors": list(self.errors),
            "seconds": round(self.seconds, 2),
        }
        return stats


# --- Per-ATS fetchers ------------------------------------------------------------


def fetch_greenhouse(
    entry: dict[str, Any], config: dict[str, Any], now: datetime, fetch: Fetch, **_: Any
) -> BoardResult:
    result = BoardResult(entry)
    token = urllib.parse.quote(str(entry["token"]))
    board_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    payload = fetch(board_url, None)  # the list omits descriptions; fetched per kept job below
    for job in payload.get("jobs") or []:
        posted_at = parse_datetime(job.get("first_published") or job.get("updated_at"))
        location_name = str((job.get("location") or {}).get("name") or "")
        location = join_locations(
            [location_name]
            + [
                office.get("name")
                for office in job.get("offices") or []
                if str(office.get("name") or "") not in location_name
            ]
        )
        remote = any(
            "remote" in str(item.get("value") or "").lower()
            for item in job.get("metadata") or []
            if isinstance(item, dict) and "location" in str(item.get("name") or "").lower()
        )
        def build(job=job, location=location, remote=remote, posted_at=posted_at) -> dict[str, Any]:
            detail = fetch(f"{board_url}/{urllib.parse.quote(str(job.get('id')))}", None)
            return make_candidate(
                company=entry["company"],
                ats="greenhouse",
                title=str(job.get("title") or ""),
                url=str(job.get("absolute_url") or ""),
                location=location,
                remote=remote,
                posted_at=posted_at,
                description=strip_html(detail.get("content") or job.get("content")),
                ats_job_id=job.get("id"),
            )

        result.consider(
            config,
            now,
            title=str(job.get("title") or ""),
            posted_at=posted_at,
            build=build,
            location=location,
            remote=remote,
        )
    return result


def fetch_lever(
    entry: dict[str, Any], config: dict[str, Any], now: datetime, fetch: Fetch, **_: Any
) -> BoardResult:
    result = BoardResult(entry)
    token = urllib.parse.quote(str(entry["token"]))
    payload = fetch(f"https://api.lever.co/v0/postings/{token}?mode=json", None)
    for job in payload if isinstance(payload, list) else []:
        categories = job.get("categories") or {}
        location = join_locations([categories.get("location")] + list(categories.get("allLocations") or []))
        remote = str(job.get("workplaceType") or "").lower() == "remote"
        posted_at = epoch_millis(job.get("createdAt"))

        def build(job=job, location=location, remote=remote, posted_at=posted_at) -> dict[str, Any]:
            parts = [job.get("descriptionPlain") or strip_html(job.get("description"))]
            for section in job.get("lists") or []:
                parts.append(str(section.get("text") or ""))
                parts.append(strip_html(section.get("content")))
            parts.append(job.get("additionalPlain") or strip_html(job.get("additional")))
            return make_candidate(
                company=entry["company"],
                ats="lever",
                title=str(job.get("text") or ""),
                url=str(job.get("hostedUrl") or ""),
                location=location,
                remote=remote,
                posted_at=posted_at,
                description="\n".join(part for part in parts if part),
                ats_job_id=job.get("id"),
            )

        result.consider(
            config,
            now,
            title=str(job.get("text") or ""),
            posted_at=posted_at,
            build=build,
        )
    return result


def fetch_ashby(
    entry: dict[str, Any], config: dict[str, Any], now: datetime, fetch: Fetch, **_: Any
) -> BoardResult:
    result = BoardResult(entry)
    token = urllib.parse.quote(str(entry["token"]))
    payload = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{token}", None)
    for job in payload.get("jobs") or []:
        if job.get("isListed") is False:
            continue
        location = join_locations(
            [job.get("location")]
            + [secondary.get("location") for secondary in job.get("secondaryLocations") or []]
        )
        remote = bool(job.get("isRemote")) or str(job.get("workplaceType") or "").lower() == "remote"
        posted_at = parse_datetime(job.get("publishedAt"))
        result.consider(
            config,
            now,
            title=str(job.get("title") or ""),
            posted_at=posted_at,
            build=lambda job=job, location=location, remote=remote, posted_at=posted_at: make_candidate(
                company=entry["company"],
                ats="ashby",
                title=str(job.get("title") or ""),
                url=str(job.get("jobUrl") or ""),
                location=location,
                remote=remote,
                posted_at=posted_at,
                description=job.get("descriptionPlain") or strip_html(job.get("descriptionHtml")),
                ats_job_id=job.get("id"),
            ),
        )
    return result


def workday_urls(entry: dict[str, Any]) -> tuple[str, str]:
    host = str(entry["host"]).strip().rstrip("/")
    if "://" in host:
        host = urllib.parse.urlsplit(host).netloc
    tenant = urllib.parse.quote(str(entry["tenant"]).strip("/"))
    site = urllib.parse.quote(str(entry["site"]).strip("/"))
    return f"https://{host}/wday/cxs/{tenant}/{site}", f"https://{host}/en-US/{site}"


def fetch_workday(
    entry: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
    fetch: Fetch,
    *,
    max_pages: int,
    zone: ZoneInfo,
    **_: Any,
) -> BoardResult:
    """Walk the board newest-first (empty search text), stop once a page has nothing recent."""
    result = BoardResult(entry)
    api_base, site_base = workday_urls(entry)
    survivors: list[tuple[dict[str, Any], datetime]] = []
    for page in range(max_pages):
        payload = fetch(
            f"{api_base}/jobs",
            {"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": page * WORKDAY_PAGE_SIZE, "searchText": ""},
        )
        postings = payload.get("jobPostings") or []
        if not postings:
            break
        page_has_recent = False
        for posting in postings:
            posted_at = workday_posted_at(posting.get("postedOn"), now, zone)
            if posted_at is not None and is_recent(posted_at, now, config):
                page_has_recent = True
            if result.prefilter(config, now, str(posting.get("title") or ""), posted_at):
                survivors.append((posting, posted_at))
        if not page_has_recent or len(postings) < WORKDAY_PAGE_SIZE:
            break

    def build(item: tuple[dict[str, Any], datetime]) -> dict[str, Any]:
        posting, posted_at = item
        external_path = str(posting.get("externalPath") or "")
        bullets = posting.get("bulletFields") or []
        location = str(posting.get("locationsText") or "")
        description = ""
        job_id = str(bullets[0]) if bullets else None
        try:
            detail = fetch(f"{api_base}{external_path}", None)
            info = detail.get("jobPostingInfo") or {}
            description = strip_html(info.get("jobDescription"))
            location = join_locations(
                [info.get("location")] + list(info.get("additionalLocations") or [])
            ) or location
            job_id = str(info.get("jobReqId") or job_id or "") or None
        except Exception as exc:  # noqa: BLE001 - one posting's detail must not sink the board
            result.errors.append(f"detail {external_path}: {exc}")
        return make_candidate(
            company=entry["company"],
            ats="workday",
            title=str(posting.get("title") or ""),
            url=f"{site_base}{external_path}",
            location=location,
            remote="remote" in location.lower(),
            posted_at=posted_at,
            description=description,
            ats_job_id=job_id,
            day_precision=True,
        )

    if survivors:
        with ThreadPoolExecutor(max_workers=min(DETAIL_WORKERS, len(survivors))) as pool:
            built = list(pool.map(build, survivors))
        for candidate in built:
            result.admit(config, candidate)
    return result


def fetch_amazon(
    entry: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
    fetch: Fetch,
    *,
    queries: tuple[str, ...],
    max_pages: int,
    zone: ZoneInfo,
    **_: Any,
) -> BoardResult:
    """Search amazon.jobs newest-first for each query; stop once a page has nothing recent."""
    result = BoardResult(entry)

    def walk(query: str) -> list[dict[str, Any]]:
        """Newest-first pages for one query until a page has nothing recent."""
        collected: list[dict[str, Any]] = []
        for page in range(max_pages):
            params = urllib.parse.urlencode(
                {
                    "base_query": query,
                    "loc_query": entry.get("loc_query", "USA"),
                    "sort": "recent",
                    "result_limit": AMAZON_PAGE_SIZE,
                    "offset": page * AMAZON_PAGE_SIZE,
                }
            )
            payload = fetch(f"https://www.amazon.jobs/en/search.json?{params}", None)
            jobs = payload.get("jobs") or []
            collected.extend(jobs)
            page_has_recent = any(
                is_recent(amazon_posted_at(job.get("posted_date"), now, zone), now, config) for job in jobs
            )
            if not page_has_recent or len(jobs) < AMAZON_PAGE_SIZE:
                break
        return collected

    if not queries:
        return result
    with ThreadPoolExecutor(max_workers=min(DETAIL_WORKERS, len(queries))) as pool:
        per_query = list(pool.map(walk, queries))
    seen_paths: set[str] = set()
    for jobs in per_query:
        for job in jobs:
            posted_at = amazon_posted_at(job.get("posted_date"), now, zone)
            path = str(job.get("job_path") or "")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            if job.get("is_intern") or job.get("is_manager"):
                result.fetched += 1
                result.skipped["title"] += 1
                continue
            locations = [job.get("location")]
            for raw in job.get("locations") or []:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    locations.append(parsed.get("location") or parsed.get("normalizedLocation"))
            location = join_locations(locations)
            remote = any(
                "virtual" in str(item).lower() or "remote" in str(item).lower() for item in locations
            )
            result.consider(
                config,
                now,
                title=str(job.get("title") or ""),
                posted_at=posted_at,
                build=lambda job=job, path=path, location=location, remote=remote, posted_at=posted_at: make_candidate(
                    company=entry["company"],
                    ats="amazon",
                    title=str(job.get("title") or ""),
                    url=f"https://www.amazon.jobs{path}",
                    location=location,
                    remote=remote,
                    posted_at=posted_at,
                    description="\n".join(
                        part
                        for part in (
                            strip_html(job.get("description")),
                            "Basic qualifications:\n" + strip_html(job.get("basic_qualifications"))
                            if job.get("basic_qualifications")
                            else "",
                            "Preferred qualifications:\n" + strip_html(job.get("preferred_qualifications"))
                            if job.get("preferred_qualifications")
                            else "",
                        )
                        if part
                    ),
                    ats_job_id=job.get("id_icims") or job.get("id"),
                    day_precision=True,
                ),
            )
    return result


FETCHERS: dict[str, Callable[..., BoardResult]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
    "amazon": fetch_amazon,
}


# --- Orchestration ---------------------------------------------------------------


def fetch_board(
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    now: datetime,
    fetch: Fetch,
    queries: tuple[str, ...],
    max_pages: int,
    zone: ZoneInfo,
) -> BoardResult:
    started = time.monotonic()
    try:
        result = FETCHERS[entry["ats"]](
            entry, config, now, fetch, queries=queries, max_pages=max_pages, zone=zone
        )
    except Exception as exc:  # noqa: BLE001 - a failing board must not abort the run
        result = BoardResult(entry)
        result.errors.append(f"{type(exc).__name__}: {exc}")
    result.seconds = time.monotonic() - started
    return result


def fetch_feeds(
    registry: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    queries: tuple[str, ...] | list[str] | None = None,
    max_pages: int = 10,
    now: datetime | None = None,
    fetch: Fetch | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch every registry board concurrently. Returns (candidates, per-board stats)."""
    current = now or utc_now()
    zone = ZoneInfo(config.get("timezone") or "UTC")
    query_tuple = tuple(str(query) for query in (queries or DEFAULT_QUERIES) if str(query).strip())
    fetcher = fetch or fetch_json
    if not registry:
        return [], []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(registry))) as pool:
        results = list(
            pool.map(
                lambda entry: fetch_board(
                    entry,
                    config,
                    now=current,
                    fetch=fetcher,
                    queries=query_tuple,
                    max_pages=max(1, int(max_pages)),
                    zone=zone,
                ),
                registry,
            )
        )
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for result in results:
        for candidate in result.candidates:
            url = candidate["application_url"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item.get("posted_at") or "", item["company"], item["title"]), reverse=True)
    return candidates, [result.stats() for result in results]


def run_fetch_feeds(
    config: dict[str, Any],
    *,
    registry_path: Path | str,
    out_path: Path | str,
    queries: list[str] | None = None,
    max_pages: int = 10,
    now: datetime | None = None,
    fetch: Fetch | None = None,
) -> dict[str, Any]:
    """CLI entry point: load the registry, fetch, write ``out_path``, return the stats payload."""
    registry = load_registry(registry_path)
    candidates, boards = fetch_feeds(
        registry, config, queries=queries, max_pages=max_pages, now=now, fetch=fetch
    )
    output = Path(out_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "out": str(output),
        "registry": str(Path(registry_path).expanduser()),
        "queries": list(queries or DEFAULT_QUERIES),
        "fetched": sum(board["fetched"] for board in boards),
        "kept": len(candidates),
        "boards_with_errors": sum(1 for board in boards if board["errors"]),
        "boards": boards,
    }
