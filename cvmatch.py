"""Local CV-vs-job matching + cover letter generation (no external AI needed)."""
import re
from collections import Counter

STOPWORDS = set("""a an and are as at be but by for from has have if in into is it its
not of on or our that the their them they this to was we will with you your more most
other such can could may might must shall should would about across after again all
also am any because been before being between both each few further get got her here
him his how however just like made make many me my new now off once only out over
per re said same she so some than then there these those through under until up upon
us use used using very via want was were what when where which while who whom why
within without work working years year role roles team teams ability able including
include includes etc ie eg must-have nice-to-have strong excellent good great
candidate candidates applicant applicants job jobs position positions company
companies equal opportunity employer applicant tracking system""".split())

# Curated skill vocabulary covering Cork's big sectors ("any job" search).
SKILLS = [
    # tech
    "python","java","javascript","typescript","c++","c#",".net","sql","nosql","html","css",
    "react","angular","vue","node.js","django","flask","spring","rest api","apis","git",
    "docker","kubernetes","aws","azure","gcp","devops","ci/cd","linux","agile","scrum",
    "machine learning","data analysis","excel","power bi","tableau","cybersecurity",
    "network","helpdesk","it support","troubleshooting","qa","testing","automation",
    # pharma / engineering / manufacturing (big in Cork)
    "gmp","glp"," validation","cleanroom","sop","haccp","iso 9001","lean","six sigma",
    "5s","kaizen","spc","batch record","deviation","capa","quality assurance",
    "quality control","microbiology","chemistry","bioprocessing","aseptic","fpga",
    "cad","solidworks","plc","maintenance","electrical","mechanical","machining",
    "assembly","production","packaging","forklift","warehouse","inventory","logistics",
    "supply chain","procurement","shipping","receiving","picking","packing",
    # hospitality / retail / customer facing
    "customer service","customer experience","cash handling","pos","merchandising",
    "stock control","barista","bartender","bar","bar staff","beverage","food and beverage",
    "drinks","hospitality","guest","guest service","waiting","waiter","waiting staff",
    "server","catering","catering assistant","kitchen","kitchen porter","food prep",
    "dishwasher","food safety","hygiene","chef","reception","front desk","housekeeping",
    "hotel","retail","sales","up-selling","till","checkout","cashier","stocktake",
    "call centre","complaint","query resolution","crm","salesforce","hubspot",
    "delivery","delivery driver","cleaner","cleaning","shop","store","supervisor",
    # finance / admin / general professional
    "bookkeeping","payroll","accounts payable","accounts receivable","invoicing",
    "sage","quickbooks","ms office","word","outlook","data entry","filing","scheduling",
    "administration","receptionist","project management","stakeholder","reporting",
    "kpi","budget","forecasting","compliance","gdpr","audit","risk","hr","recruitment",
    "onboarding","training","coaching","mentoring","supervising","team lead",
    # soft skills
    "communication","teamwork","team player","problem solving","problem-solving",
    "attention to detail","time management","multitasking","organisational",
    "organizational","initiative","adaptable","flexible","reliable","punctual",
    "leadership","negotiation","presentation","analytical","critical thinking",
    "interpersonal","empathy","multitask","fast-paced","deadline","targets",
    # driving / languages
    "driving licence","driver's license","full licence","manual handling","safepass",
    "first aid","irish","spanish","french","german","polish","portuguese","multilingual",
]
SKILLS = [s.strip() for s in SKILLS]


def _tokens(text):
    return re.findall(r"[a-z][a-z0-9+#./-]{1,}", (text or "").lower())


def extract_terms(text):
    """Return important terms: curated skills found + frequent meaningful words."""
    low = (text or "").lower()
    found_skills = sorted({s for s in SKILLS if re.search(r"(?<![a-z])" + re.escape(s) + r"(?![a-z])", low)})
    words = Counter(t for t in _tokens(text) if t not in STOPWORDS and len(t) > 2)
    # frequent words not already covered by a skill phrase
    covered = " ".join(found_skills)
    extra = [w for w, c in words.most_common(40) if c >= 2 and w not in covered][:15]
    return found_skills, extra


def match(cv_text, job_text):
    """Score how well a CV covers a job description. Returns dict."""
    job_skills, job_extra = extract_terms(job_text)
    cv_low = (cv_text or "").lower()
    job_low = (job_text or "").lower()

    matched, missing = [], []
    for s in job_skills:
        (matched if re.search(r"(?<![a-z])" + re.escape(s) + r"(?![a-z])", cv_low) else missing).append(s)

    # coverage of important job vocabulary (word level)
    job_words = {w for w in _tokens(job_text) if w not in STOPWORDS and len(w) > 3}
    cv_words = set(_tokens(cv_text))
    vocab_overlap = len(job_words & cv_words) / max(len(job_words), 1)

    skill_score = len(matched) / max(len(job_skills), 1) if job_skills else 0.5
    overall = int(round(100 * (0.75 * skill_score + 0.25 * min(vocab_overlap * 1.6, 1.0))))
    overall = max(5, min(99, overall))

    # CV keywords NOT mentioned in the job (potential noise to trim)
    cv_skills, _ = extract_terms(cv_text)
    irrelevant = [s for s in cv_skills if s not in job_low][:10]

    return {
        "score": overall,
        "matched": matched,
        "missing": missing,
        "job_extra_terms": job_extra,
        "irrelevant": irrelevant,
        "verdict": ("Strong match — apply!" if overall >= 70 else
                    "Decent match — tailor your CV first." if overall >= 45 else
                    "Weak match — only apply if you're genuinely interested."),
    }


def cover_letter(profile, job, analysis):
    """Generate a plain-text cover letter draft from profile + job + match analysis."""
    name = profile.get("name") or "[Your Name]"
    years = profile.get("years_exp") or ""
    headline = profile.get("headline") or job.get("title", "this role")
    strengths = ", ".join(analysis.get("matched", [])[:6]) or "relevant skills"
    why_lines = profile.get("why") or ""
    today = __import__("datetime").date.today().strftime("%d %B %Y")

    exp_sentence = (f" With {years} years of experience in this area," if years
                    else " Throughout my work history,")

    letter = f"""{name}
{profile.get('phone', '[Your Phone]')} | {profile.get('email', '[Your Email]')}
{profile.get('location', 'Cork, Ireland')}
{today}

Hiring Manager
{job.get('company', 'the Hiring Team')}
{job.get('location', 'Cork')}

Re: Application for {job.get('title', 'the advertised position')}

Dear Hiring Manager,

I am writing to apply for the {job.get('title', 'position')} role at {job.get('company', 'your company')}, as advertised on {job.get('source', 'your careers page')}.{exp_sentence} I am confident I can contribute from day one — particularly through my experience with {strengths}.

What draws me to this role is the opportunity to join {job.get('company', 'your team')} in Cork and apply my skills where they will make a real difference. I am a reliable, motivated worker who enjoys being part of a team and taking ownership of my work.
{chr(10) + why_lines + chr(10) if why_lines else ''}
I would welcome the opportunity to discuss how my background fits your needs. I am available for interview at your convenience and can be reached at {profile.get('phone', '[Your Phone]')} or {profile.get('email', '[Your Email]')}.

Thank you for your time and consideration.

Yours sincerely,
{name}
"""
    return re.sub(r"\n{3,}", "\n\n", letter).strip()
