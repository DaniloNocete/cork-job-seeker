"""CI scanner: refresh docs/jobs.json incrementally (runs in GitHub Actions)."""
import json
import os
import sys
import time
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scraper  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "jobs.json")

LOCATION = os.environ.get("CJH_LOCATION", "Cork, County Cork, Ireland")
SEARCHES = json.loads(os.environ.get("CJH_SEARCHES",
    '["", "part time", "retail", "hospitality", "bar", "warehouse"]'))
PART_TIME = os.environ.get("CJH_PART_TIME", "1") == "1"
MAX_DESC_PER_RUN = 60
KEEP_DAYS = 14
MAX_JOBS = 800


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
        return {j["id"]: j for j in data.get("jobs", [])}
    except Exception:
        return {}


def main():
    old = load_existing()
    found = []
    for i, kw in enumerate(SEARCHES):
        pages = 15 if i == 0 else 5
        found += scraper.linkedin_search(kw, LOCATION, max_pages=pages, part_time=PART_TIME)
    print(f"listings found: {len(found)}")

    now = datetime.now().isoformat(timespec="seconds")
    jobs = dict(old)
    new_ids = []
    for j in found:
        jid = f"{j['source']}:{j['ext_id']}"
        if jid in jobs:
            jobs[jid]["posted"] = j.get("posted") or jobs[jid].get("posted")
            jobs[jid]["url"] = j["url"]
        else:
            jobs[jid] = {"id": jid, "source": j["source"], "title": j["title"],
                         "company": j["company"], "location": j["location"],
                         "posted": j.get("posted", ""), "url": j["url"],
                         "desc": "", "first_seen": now}
            new_ids.append(jid)

    # fetch descriptions for newest missing ones (bounded so the Action stays quick)
    missing = [jid for jid in new_ids if not jobs[jid]["desc"]][:MAX_DESC_PER_RUN]
    print(f"new: {len(new_ids)}, fetching {len(missing)} descriptions")
    for jid in missing:
        desc = scraper.linkedin_description(jobs[jid]["url"])
        if desc:
            jobs[jid]["desc"] = desc[:8000]
        time.sleep(1.0)

    # prune old jobs
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    keep = [j for j in jobs.values()
            if (j.get("posted") or "9999") >= cutoff or (j.get("first_seen") or "")[:10] >= cutoff]
    keep.sort(key=lambda j: j.get("posted") or "", reverse=True)
    keep = keep[:MAX_JOBS]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {"meta": {"generated": now, "count": len(keep),
                        "location": LOCATION, "part_time": PART_TIME},
               "jobs": keep}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {OUT}: {len(keep)} jobs, {sum(1 for j in keep if j['desc'])} with descriptions")


if __name__ == "__main__":
    main()
