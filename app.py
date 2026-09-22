"""CorkJobHunter — auto job scanning, tracker and CV assistant for Cork."""
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, date, timedelta

from flask import Flask, g, jsonify, render_template, request, Response

import scraper
import cvmatch
import cvbuilder

app = Flask(__name__)
DB = os.environ.get("JOBHUNTER_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")   # set this when deploying publicly!
LOCK = threading.Lock()

SCAN_STATE = {"running": False, "last_run": None, "last_count": 0, "error": None}


@app.before_request
def require_auth():
    if not AUTH_PASSWORD:
        return
    if request.path == "/healthz":
        return
    auth = request.authorization
    if not auth or auth.password != AUTH_PASSWORD:
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": 'Basic realm="CorkJobHunter"'})


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT, ext_id TEXT, title TEXT, company TEXT, location TEXT,
        posted TEXT, url TEXT, description TEXT DEFAULT '', first_seen TEXT,
        salary_min REAL, salary_max REAL,
        UNIQUE(source, ext_id)
    );
    CREATE TABLE IF NOT EXISTS tracker(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER, status TEXT DEFAULT 'Saved', applied_date TEXT,
        followup_date TEXT, notes TEXT DEFAULT '', cv_version TEXT DEFAULT '',
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS profile(
        k TEXT PRIMARY KEY, v TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(
        k TEXT PRIMARY KEY, v TEXT
    );
    CREATE TABLE IF NOT EXISTS cv_versions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER, name TEXT, created TEXT, payload TEXT
    );
    """)
    student_defaults = json.dumps(["", "part time", "retail", "hospitality", "bar", "warehouse"])
    defaults = {"location": "Cork, County Cork, Ireland",
                "searches": student_defaults,
                "part_time": "1",
                "scan_hours": "6",
                "adzuna_id": "", "adzuna_key": ""}
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    # migrate old blank-search default to student/part-time defaults
    row = c.execute("SELECT v FROM settings WHERE k='searches'").fetchone()
    if row and row["v"] == '[""]':
        c.execute("UPDATE settings SET v=? WHERE k='searches'", (student_defaults,))
    c.commit()
    c.close()


def get_setting(c, k, default=""):
    row = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default


def get_profile(c):
    return {r["k"]: r["v"] for r in c.execute("SELECT k,v FROM profile")}


def get_cv_text(c):
    """CV text for analysis: raw paste if present, else flattened master CV."""
    prof = get_profile(c)
    if prof.get("cv_text", "").strip():
        return prof["cv_text"]
    raw = prof.get("cv_master", "")
    if not raw:
        return ""
    m = json.loads(raw)
    parts = [m.get("summary", ""), m.get("skills", ""), m.get("availability", "")]
    for e in m.get("experience", []):
        parts.append(" ".join([e.get("role", ""), e.get("org", ""), " ".join(e.get("bullets", []))]))
    for e in m.get("education", []):
        parts.append(" ".join([e.get("award", ""), e.get("org", "")]))
    return "\n".join(p for p in parts if p)


def run_scan():
    """Fetch new jobs from all sources and upsert into DB."""
    if SCAN_STATE["running"]:
        return 0
    SCAN_STATE.update(running=True, error=None)
    added = 0
    try:
        c = conn()
        location = get_setting(c, "location", "Cork, County Cork, Ireland")
        searches = json.loads(get_setting(c, "searches", '[""]') or '[""]')
        part_time = get_setting(c, "part_time", "0") == "1"
        az_id = get_setting(c, "adzuna_id")
        az_key = get_setting(c, "adzuna_key")

        found = []
        for i, kw in enumerate(searches):
            pages = 15 if i == 0 else 5
            found += scraper.linkedin_search(kw, location, max_pages=pages, part_time=part_time)
        found += scraper.recruitireland_search()
        found += scraper.cpl_search()
        if az_id and az_key:
            loc = "Cork" if "cork" in location.lower() else location
            found += scraper.adzuna_search(az_id, az_key, location=loc)

        now = datetime.now().isoformat(timespec="seconds")
        with LOCK:
            for j in found:
                exists = c.execute("SELECT id FROM jobs WHERE source=? AND ext_id=?",
                                   (j["source"], j["ext_id"])).fetchone()
                if exists:
                    c.execute("UPDATE jobs SET posted=?, url=? WHERE id=?",
                              (j.get("posted", ""), j["url"], exists["id"]))
                else:
                    c.execute(
                        """INSERT INTO jobs(source,ext_id,title,company,location,posted,url,
                                           first_seen,salary_min,salary_max,description)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (j["source"], j["ext_id"], j["title"], j["company"], j["location"],
                         j.get("posted", ""), j["url"], now,
                         j.get("salary_min"), j.get("salary_max"), j.get("description", "")))
                    added += 1
            c.commit()
        c.close()
        SCAN_STATE.update(last_run=now, last_count=added)
    except Exception as e:
        SCAN_STATE["error"] = str(e)
    finally:
        SCAN_STATE["running"] = False
    return added


def scheduler():
    while True:
        try:
            c = conn()
            hours = float(get_setting(c, "scan_hours", "6") or 6)
            c.close()
        except Exception:
            hours = 6
        run_scan()
        time.sleep(max(1, hours) * 3600)


# ---------------- API ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jobs")
def api_jobs():
    q = request.args.get("q", "").strip().lower()
    new_only = request.args.get("new_only") == "1"
    source = request.args.get("source", "")
    d = db()
    rows = d.execute("SELECT * FROM jobs ORDER BY posted DESC, id DESC LIMIT 600").fetchall()
    cutoff = (date.today() - timedelta(days=2)).isoformat()
    out = []
    for r in rows:
        j = dict(r)
        j["is_new"] = (j["first_seen"] or "")[:10] >= cutoff
        if q and q not in (j["title"] + " " + j["company"] + " " + j["location"]).lower():
            continue
        if source and j["source"] != source:
            continue
        if new_only and not j["is_new"]:
            continue
        out.append(j)
    return jsonify(out[:300])


@app.route("/api/stats")
def api_stats():
    d = db()
    total = d.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    cutoff = (date.today() - timedelta(days=2)).isoformat()
    new = d.execute("SELECT COUNT(*) n FROM jobs WHERE substr(first_seen,1,10)>=?", (cutoff,)).fetchone()["n"]
    applied = d.execute("SELECT COUNT(*) n FROM tracker WHERE status IN ('Applied','Interview','Offer')").fetchone()["n"]
    interviews = d.execute("SELECT COUNT(*) n FROM tracker WHERE status IN ('Interview','Offer')").fetchone()["n"]
    followups = d.execute("SELECT COUNT(*) n FROM tracker WHERE followup_date != '' AND followup_date <= ? AND status NOT IN ('Rejected','Offer')",
                          (date.today().isoformat(),)).fetchone()["n"]
    return jsonify({"total": total, "new": new, "applied": applied,
                    "interviews": interviews, "followups": followups, **SCAN_STATE})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    t = threading.Thread(target=run_scan, daemon=True)
    t.start()
    return jsonify({"started": True})


@app.route("/api/job/<int:job_id>")
def api_job(job_id):
    d = db()
    r = d.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return jsonify({"error": "not found"}), 404
    j = dict(r)
    if not j.get("description"):
        if j["source"] == "linkedin":
            desc = scraper.linkedin_description(j["url"])
            if desc:
                d.execute("UPDATE jobs SET description=? WHERE id=?", (desc, job_id))
                d.commit()
                j["description"] = desc
    return jsonify(j)


@app.route("/api/tracker")
def api_tracker():
    d = db()
    rows = d.execute("""SELECT t.*, j.title, j.company, j.url, j.location, j.source
                        FROM tracker t JOIN jobs j ON j.id=t.job_id
                        ORDER BY t.id DESC""").fetchall()
    today = date.today().isoformat()
    out = []
    for r in rows:
        t = dict(r)
        t["followup_due"] = bool(t["followup_date"]) and t["followup_date"] <= today \
            and t["status"] not in ("Rejected", "Offer")
        out.append(t)
    return jsonify(out)


@app.route("/api/tracker", methods=["POST"])
def api_tracker_add():
    data = request.json
    d = db()
    exists = d.execute("SELECT id FROM tracker WHERE job_id=?", (data["job_id"],)).fetchone()
    if exists:
        return jsonify({"ok": True, "already": True})
    d.execute("INSERT INTO tracker(job_id,status,notes,created) VALUES(?, 'Saved', ?, ?)",
              (data["job_id"], data.get("notes", ""), datetime.now().isoformat(timespec="seconds")))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/tracker/<int:tid>", methods=["PATCH"])
def api_tracker_update(tid):
    data = request.json
    d = db()
    fields = {k: v for k, v in data.items() if k in ("status", "applied_date", "followup_date", "notes", "cv_version")}
    if not fields:
        return jsonify({"ok": False})
    sets = ",".join(f"{k}=?" for k in fields)
    d.execute(f"UPDATE tracker SET {sets} WHERE id=?", (*fields.values(), tid))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/tracker/<int:tid>", methods=["DELETE"])
def api_tracker_delete(tid):
    d = db()
    d.execute("DELETE FROM tracker WHERE id=?", (tid,))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/profile", methods=["GET", "POST"])
def api_profile():
    d = db()
    if request.method == "GET":
        return jsonify(get_profile(d))
    data = request.json
    for k, v in data.items():
        d.execute("INSERT INTO profile(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/match", methods=["POST"])
def api_match():
    data = request.json
    d = db()
    prof = get_profile(d)
    cv = get_cv_text(d)
    if not cv.strip():
        return jsonify({"error": "Add your CV in the CV Studio tab first (paste it into the Master CV import box)."}), 400
    job = d.execute("SELECT * FROM jobs WHERE id=?", (data["job_id"],)).fetchone()
    if not job:
        return jsonify({"error": "job not found"}), 404
    j = dict(job)
    j = _ensure_description(d, j)
    if not j.get("description"):
        return jsonify({"error": "Could not fetch the job description (site may be blocking). Try opening the job link directly."}), 422
    analysis = cvmatch.match(cv, j["description"])
    return jsonify({"job": {k: j[k] for k in ("id", "title", "company", "location", "url", "source")},
                    "analysis": analysis})


@app.route("/api/cover-letter", methods=["POST"])
def api_cover_letter():
    data = request.json
    d = db()
    prof = get_profile(d)
    job = d.execute("SELECT * FROM jobs WHERE id=?", (data["job_id"],)).fetchone()
    if not job:
        return jsonify({"error": "job not found"}), 404
    j = dict(job)
    j = _ensure_description(d, j)
    analysis = cvmatch.match(get_cv_text(d), j.get("description", "")) if j.get("description") else {"matched": []}
    letter = cvmatch.cover_letter(prof, j, analysis)
    return jsonify({"letter": letter})


# ---------------- CV builder ----------------

def _ensure_description(d, j):
    """Fetch & cache the full job description if missing. Returns updated dict."""
    if not j.get("description"):
        desc = scraper.fetch_description(j["url"], j["source"])
        if desc:
            d.execute("UPDATE jobs SET description=? WHERE id=?", (desc, j["id"]))
            d.commit()
            j["description"] = desc
    return j


@app.route("/api/cv", methods=["GET", "POST"])
def api_cv_master():
    d = db()
    prof = get_profile(d)
    if request.method == "GET":
        raw = prof.get("cv_master", "")
        return jsonify(json.loads(raw) if raw else {})
    data = request.json
    d.execute("INSERT INTO profile(k,v) VALUES('cv_master',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
              (json.dumps(data),))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/cv/parse", methods=["POST"])
def api_cv_parse():
    text = (request.json or {}).get("text", "")
    return jsonify(cvbuilder.parse_cv_text(text))


@app.route("/api/cv/generate", methods=["POST"])
def api_cv_generate():
    data = request.json
    d = db()
    prof = get_profile(d)
    raw = prof.get("cv_master", "")
    master = json.loads(raw) if raw else {}
    has_content = (master.get("summary") or master.get("skills") or master.get("experience"))
    if not has_content and not prof.get("cv_text", "").strip():
        return jsonify({"error": "Add your master CV first (paste it in the import box or fill the sections)."}), 400
    if not has_content:  # fall back: parse raw CV text into structure on the fly
        master = cvbuilder.parse_cv_text(prof.get("cv_text", ""))
    job = d.execute("SELECT * FROM jobs WHERE id=?", (data["job_id"],)).fetchone()
    if not job:
        return jsonify({"error": "job not found"}), 404
    j = _ensure_description(d, dict(job))
    if not j.get("description"):
        return jsonify({"error": "Could not fetch the job description (site may be blocking)."}), 422

    cv_text_for_analysis = get_cv_text(d)
    analysis = cvmatch.match(cv_text_for_analysis, j["description"])
    tailored = cvbuilder.tailor_cv(prof, master, j, analysis)

    slug = re.sub(r"[^a-z0-9]+", "-", (j.get("company", "") + "-" + j.get("title", "")).lower()).strip("-")[:50]
    vname = f"{slug}-{date.today().isoformat()}"
    now = datetime.now().isoformat(timespec="seconds")
    cur = d.execute("INSERT INTO cv_versions(job_id,name,created,payload) VALUES(?,?,?,?)",
                    (j["id"], vname, now, json.dumps(tailored)))
    vid = cur.lastrowid
    # auto-tag the tracker entry if this job is tracked
    trk = d.execute("SELECT id FROM tracker WHERE job_id=?", (j["id"],)).fetchone()
    if trk:
        d.execute("UPDATE tracker SET cv_version=? WHERE id=?", (vname, trk["id"]))
    d.commit()
    return jsonify({"version_id": vid, "name": vname, "cv": tailored,
                    "html": cvbuilder.render_html(tailored), "analysis": analysis})


@app.route("/api/cv/versions")
def api_cv_versions():
    d = db()
    rows = d.execute("""SELECT v.id, v.name, v.created, v.job_id, j.title, j.company
                        FROM cv_versions v LEFT JOIN jobs j ON j.id=v.job_id
                        ORDER BY v.id DESC LIMIT 50""").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/cv/download/<int:vid>")
def api_cv_download(vid):
    fmt = request.args.get("fmt", "docx")
    d = db()
    row = d.execute("SELECT * FROM cv_versions WHERE id=?", (vid,)).fetchone()
    if not row:
        return "not found", 404
    cv = json.loads(row["payload"])
    if fmt == "txt":
        return Response(cvbuilder.render_txt(cv), mimetype="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="cv-{row["name"]}.txt"'})
    path = f"/tmp/cv-{vid}.docx"
    cvbuilder.render_docx(cv, path)
    with open(path, "rb") as f:
        data = f.read()
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="cv-{row["name"]}.docx"'})


@app.route("/api/jobs/clear", methods=["POST"])
def api_jobs_clear():
    d = db()
    d.execute("DELETE FROM jobs WHERE id NOT IN (SELECT job_id FROM tracker)")
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    d = db()
    if request.method == "GET":
        keys = ("location", "searches", "scan_hours", "part_time", "adzuna_id", "adzuna_key")
        s = {k: get_setting(d, k) for k in keys}
        s["adzuna_key"] = ("*" * 6) if s["adzuna_key"] else ""
        return jsonify(s)
    data = request.json
    for k in ("location", "searches", "scan_hours", "part_time", "adzuna_id", "adzuna_key"):
        if k in data:
            v = data[k]
            if k == "adzuna_key" and v and set(v) == {"*"}:
                continue
            d.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    d.commit()
    return jsonify({"ok": True})


@app.route("/api/export/<what>")
def api_export(what):
    import csv, io
    d = db()
    buf = io.StringIO()
    if what == "jobs":
        w = csv.writer(buf)
        w.writerow(["title", "company", "location", "posted", "source", "url"])
        for r in d.execute("SELECT title,company,location,posted,source,url FROM jobs ORDER BY posted DESC"):
            w.writerow(list(r))
    elif what == "tracker":
        w = csv.writer(buf)
        w.writerow(["title", "company", "status", "applied_date", "followup_date", "notes", "url"])
        for r in d.execute("""SELECT j.title,j.company,t.status,t.applied_date,t.followup_date,t.notes,j.url
                              FROM tracker t JOIN jobs j ON j.id=t.job_id"""):
            w.writerow(list(r))
    else:
        return "bad export", 400
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={what}.csv"})


init_db()
threading.Thread(target=scheduler, daemon=True).start()

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
