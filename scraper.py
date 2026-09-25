"""Job source scrapers: LinkedIn guest API + optional Adzuna API."""
import datetime
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


# ---------- extra Irish sources ----------

IRE_COUNTIES = ["carlow","cavan","clare","cork","donegal","dublin","galway","kerry","kildare",
                "kilkenny","laois","leitrim","limerick","longford","louth","mayo","meath",
                "monaghan","offaly","roscommon","sligo","tipperary","waterford","westmeath",
                "wexford","wicklow"]


def _county_from_text(text: str):
    """Return the Irish county named in the text, or '' if none."""
    low = text.lower()
    for c in IRE_COUNTIES:
        if re.search(r"(county|co\.)\s+" + c + r"\b", low) or re.search(r"\b" + c + r"\b", low):
            return c
    return ""


def recruitireland_search(location: str = "cork", max_pages: int = 2):
    """RecruitIreland. Their /jobs/cork page also carries national jobs, so every
    listing is checked and non-Cork ones are dropped (this is a Cork-only app)."""
    jobs, seen = [], set()
    for page in range(1, max_pages + 1):
        url = f"https://www.recruitireland.com/jobs/{location}" + (f"?page={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code != 200:
                break
        except requests.RequestException:
            break
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/job/" not in href or href in seen:
                continue
            title = _clean(a.get_text())
            if not title or title.lower() in ("view job", "save job"):
                continue
            seen.add(href)
            full_url = href if href.startswith("http") else "https://www.recruitireland.com" + href
            # decide the real county: from the title, else from the job page itself
            county = _county_from_text(title)
            if not county:
                try:
                    det = requests.get(full_url, headers=UA, timeout=TIMEOUT)
                    if det.status_code == 200:
                        dsoup = BeautifulSoup(det.text, "lxml")
                        # location is usually in the first part of the page - search it
                        county = _county_from_text(dsoup.get_text(" ", strip=True)[:2500])
                    time.sleep(0.6)
                except requests.RequestException:
                    county = "cork"  # page unreadable: trust the /cork section rather than drop
            if county and county != "cork":
                continue  # not a Cork job - skip it entirely
            company = ""
            m = re.search(r"/company/([^/]+)/job/", href)
            if m:
                company = m.group(1).replace("-", " ").title()
            jobs.append({"source": "recruitireland", "ext_id": href.rstrip("/").split("/")[-1],
                         "title": title, "company": company, "location": "Cork, Ireland",
                         "posted": "", "url": full_url})
        if not seen:
            break
        time.sleep(1.0)
    return jobs


def cpl_search(location: str = "cork", max_pages: int = 2):
    """CPL Recruitment job boards (cpl.com). Titles in h3, date in p, salary via euros."""
    towns = ("Cork", "Kinsale", "Mallow", "Midleton", "Cobh", "Youghal", "Bandon", "Clonakilty",
             "Little Island", "Carrigaline", "Ringaskiddy", "Fermoy", "Rathcormac", "Blarney")
    jobs, seen = [], set()
    for page in range(1, max_pages + 1):
        url = f"https://www.cpl.com/jobs/?location={location}" + (f"&paged={page}" if page > 1 else "")
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code != 200:
                break
        except requests.RequestException:
            break
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"/jobs/(JO-|\d)", href) or href in seen:
                continue
            h3 = a.find("h3")
            if not h3:
                continue
            title = _clean(h3.get_text())
            if not title:
                continue
            seen.add(href)
            text = a.get_text(" ", strip=True)
            posted = ""
            m = re.search(r"Posted date\s*-\s*(\d{1,2} \w+ \d{4})", text)
            if m:
                try:
                    posted = datetime.datetime.strptime(m.group(1), "%d %B %Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            sal = re.search(r"€[\d,]+(?:\s*-\s*€[\d,]+)?", text)
            loc = "Cork, Ireland"
            for t in towns:
                if t.lower() in text.lower():
                    loc = t + ", Ireland"
                    break
            jobs.append({"source": "cpl", "ext_id": href.rstrip("/").split("/")[-1],
                         "title": title, "company": "CPL Recruitment", "location": loc,
                         "posted": posted, "salary": sal.group(0) if sal else "",
                         "url": "https://www.cpl.com" + href})
        time.sleep(1.0)
    return jobs


def fetch_description(url: str, source: str):
    """Generic description fetcher for non-LinkedIn sources."""
    if source == "linkedin":
        return linkedin_description(url)
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.find("body")
        text = main.get_text("\n", strip=True) if main else ""
        return re.sub(r"\n{3,}", "\n\n", text)[:12000]
    except requests.RequestException:
        return ""
