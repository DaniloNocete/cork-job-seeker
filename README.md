# 🎯 CorkJobHunter

Personal job-hunting automation for students & part-time job seekers in Cork, Ireland.

- **Auto job scanner** — pulls part-time/student-friendly Cork jobs from LinkedIn's public
  jobs feed (which also carries Indeed / IrishJobs / company-site listings) on a schedule.
  Optional second source via free [Adzuna API](https://developer.adzuna.com) keys.
- **Application tracker** — pipeline statuses, follow-up due alerts, notes, CSV export.
- **CV Studio** — import your CV once (paste → auto-split into sections), then per job:
  - match score % + missing keywords
  - **tailored CV generated on demand** (role-targeted summary, skills & experience
    re-ranked for that job, nothing invented) — downloadable as `.docx` / `.txt`
  - cover letter drafts

All data lives in a local SQLite file (`data.db`). No accounts, no cloud, no tracking.

## Run locally

```bash
pip install -r requirements.txt
python app.py            # → http://localhost:8000
```

## Deploying

Works anywhere that runs Docker or Python. Environment variables:

| Variable | Purpose |
|---|---|
| `AUTH_PASSWORD` | **Set this!** Adds HTTP basic auth (username: anything, password: this). Without it the app is open to anyone with the URL. |
| `PORT` | Listen port (default 8000; platforms like Render set this automatically) |
| `JOBHUNTER_DB` | Path to the SQLite file (default `./data.db`). On platforms with ephemeral disks, point this at a mounted volume or your data resets on each deploy. |

### Render / Railway / Fly.io (Docker)

1. Push this repo to GitHub.
2. New Web Service → point at the repo → runtime **Docker**.
3. Set `AUTH_PASSWORD` (and a persistent disk for `data.db` if available).

### Any VPS

```bash
docker build -t corkjobhunter .
docker run -d --restart unless-stopped -p 8000:8000 \
  -e AUTH_PASSWORD=change-me -v jobhunter-data:/app/data corkjobhunter
```

## Notes & limitations

- Applications are **never auto-submitted** — job sites ban bots and spray-and-pray
  applying doesn't work. This tool prepares everything so each application takes ~2 minutes.
- The LinkedIn guest feed needs no account/key, but be polite: keep the scan interval
  at a few hours (default 6). If scans start failing, the feed may be rate-limiting.
- Tailoring only re-orders/re-frames what's in your master CV; suggestions marked
  "add only if true" are keywords from the ad that your CV lacks.
