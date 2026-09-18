"""Job source scrapers: LinkedIn guest API + optional Adzuna API."""
import re
import time
import requests
from bs4 import BeautifulSoup

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-IE,en;q=0.9",
}

TIMEOUT = 20


def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def linkedin_search(keywords: str, location: str, max_pages: int = 10, freshness: str = "r604800",
                    part_time: bool = False):
    """Scrape LinkedIn guest jobs API. freshness: r86400 (24h), r604800 (7d), '' (any)."""
    jobs, seen = [], set()
    base = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    for page in range(max_pages):
        params = {
            "keywords": keywords,
            "location": location,
            "start": page * 10,
            "f_DD": "",           # sort by most recent
        }
        if freshness:
            params["f_TPR"] = freshness
        if part_time:
            params["f_JT"] = "P"   # part-time job type
        try:
            r = requests.get(base, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(20)
                break
            if r.status_code != 200:
                break
        except requests.RequestException:
            break
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.find_all("div", class_="base-card")
        if not cards:
            break
        for c in cards:
            try:
                link_a = c.find("a", class_="base-card__full-link")
                if not link_a:
                    continue
                href = link_a["href"].split("?")[0]
                m = re.search(r"-(\d+)$", href)
                ext_id = m.group(1) if m else href
                if ext_id in seen:
                    continue
                seen.add(ext_id)
                title = _clean(c.find("h3", class_="base-search-card__title").get_text())
                sub = c.find("h4", class_="base-search-card__subtitle")
                a = sub.find("a") if sub else None
                company = _clean((a or sub).get_text()) if (a or sub) else ""
                loc_el = c.find("span", class_="job-search-card__location")
                loc = _clean(loc_el.get_text()) if loc_el else ""
                t = c.find("time")
                posted = t.get("datetime", "")[:10] if t else ""
                jobs.append({
                    "source": "linkedin",
                    "ext_id": ext_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "posted": posted,
                    "url": href,
                })
            except Exception:
                continue
        if len(cards) < 5:
            break
        time.sleep(1.2)
    return jobs


def linkedin_description(url: str):
    """Fetch the full description HTML/text of a LinkedIn job view page."""
    try:
        r = requests.get(url.split("?")[0], headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        d = soup.find("div", class_="show-more-less-html__markup")
        if not d:
            return ""
        # keep line breaks for readability
        for br in d.find_all("br"):
            br.replace_with("\n")
        text = d.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)[:20000]
    except requests.RequestException:
        return ""


def adzuna_search(app_id: str, app_key: str, location: str = "Cork", what: str = "",
                  max_pages: int = 3):
    """Optional source — requires free keys from https://developer.adzuna.com."""
    if not app_id or not app_key:
        return []
    jobs = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                "https://api.adzuna.com/v1/api/jobs/ie/search/%d" % page,
                params={
                    "app_id": app_id, "app_key": app_key,
                    "where": location, "what": what,
                    "max_days_old": 10, "results_per_page": 50,
                    "sort_by": "date",
                },
                headers=UA, timeout=TIMEOUT,
            )
            if r.status_code != 200:
                break
            data = r.json()
            results = data.get("results", [])
            if not results:
                break
            for j in results:
                jobs.append({
                    "source": "adzuna",
                    "ext_id": str(j.get("id")),
                    "title": _clean(j.get("title")),
                    "company": _clean(j.get("company", {}).get("display_name")),
                    "location": _clean(j.get("location", {}).get("display_name")),
                    "posted": (j.get("created") or "")[:10],
                    "url": j.get("redirect_url", ""),
                    "salary_min": j.get("salary_min"),
                    "salary_max": j.get("salary_max"),
                    "description": (j.get("description") or "")[:20000],
                })
            if len(results) < 20:
                break
            time.sleep(0.8)
        except Exception:
            break
    return jobs
