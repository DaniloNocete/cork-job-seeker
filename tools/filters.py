"""Student job filters for the Cork job scanner.

Why this exists
---------------
The scanner's search keywords ("IT support", "part time", "retail", ...) match on job
TITLES. On LinkedIn and Indeed a title like "IT Support Specialist" also covers pharma
validation engineers, network engineers, cloud engineers and senior/manager roles - and
the allied sources return jobs from other counties. That is why the daily feed kept
producing jobs that were not Cork, not part-time and not a fit for a student.

Rules applied here
------------------
1. Cork only. The dashboard is for Cork student work. Anything whose location does not
   mention Cork is dropped (Killarney, Clonmel, Tipperary, Waterford, Limerick, UK...).
2. Wrong profession. Regulated-industry and specialist-engineering titles are dropped
   (GMP, pharma, LIMS, SCADA, Cisco, CCNA, VMware, AWS, DevOps...).
3. Wrong level. Seniority titles a student will not be hired into are dropped
   (senior, principal, lead, manager, supervisor, director, head of).
4. Student-friendly flag. Jobs mentioning part-time, evening, weekend, night or shift
   work are flagged so they can be surfaced first.

Nothing here changes what the scanner SEARCHES for - it only filters and flags the
results, so it is safe to switch off with CJH_FILTER=0.
"""
import re

CORK_RE = re.compile(r"\bcork\b", re.I)

# Matched against the TITLE only, so a good job is never dropped just because its
# description happens to mention, say, "GMP" once.
TITLE_BLOCK = re.compile(
    r"("
    r"\b(gmp|gamp|pharma|pharmaceutical|biotech|biopharma|lims|empower|scada|dcs|"
    r"historian|mes|ot|operational technology|computer system validation|csv engineer|"
    r"validation|qualified person|qa specialist|qc analyst)\b"
    r"|"
    r"\b(ccna|ccnp|cisco|juniper|vmware|hyper-?v|citrix|azure|aws|gcp|kubernetes|"
    r"terraform|ansible|devops|site reliability|sre|cloud engineer|network engineer|"
    r"field engineer|security engineer|data engineer|data scientist|machine learning)\b"
    r"|"
    r"\b(senior|principal|staff|lead|manager|supervisor|director|head of|vp|chief|"
    r"president)\b"
    r")",
    re.I,
)

# Used to flag jobs worth showing first to a student.
STUDENT_RE = re.compile(
    r"part[\s-]?time|evening|weekend|night\s?shift|night porter|shift work|"
    r"casual|flexible hours|term[\s-]?time|student",
    re.I,
)


def is_cork(job):
    """True when the job's location mentions Cork (or is blank, to stay permissive)."""
    loc = (job.get("location") or "").strip()
    return (not loc) or bool(CORK_RE.search(loc))


def is_blocked(job):
    """True when the job title is a specialist/senior role outside student work."""
    return bool(TITLE_BLOCK.search(job.get("title") or ""))


def is_student_friendly(job):
    """True when the job mentions study-friendly patterns (title or description)."""
    text = (job.get("title") or "") + " " + (job.get("desc") or "")[:1200]
    return bool(STUDENT_RE.search(text))


def keep_job(job):
    """Single decision point used by the scanner."""
    return is_cork(job) and not is_blocked(job)


def apply(jobs):
    """Filter a list of jobs and add the student flag. Returns (kept, stats)."""
    stats = {"total": len(jobs), "off_county": 0, "blocked": 0, "kept": 0, "student": 0}
    kept = []
    for j in jobs:
        if not is_cork(j):
            stats["off_county"] += 1
            continue
        if is_blocked(j):
            stats["blocked"] += 1
            continue
        j["student"] = is_student_friendly(j)
        if j["student"]:
            stats["student"] += 1
        kept.append(j)
    stats["kept"] = len(kept)
    return kept, stats
