# Job Scout (autonomous-job)

A private, owner-operated remote-job and resume-service assistant. The hosted interface
uses Flask on Vercel, not Streamlit. Job discovery uses [Remote OK](https://remoteok.com/)'s
free public feed; AI drafting uses OpenAI and approved emails use Resend.

## Deploy on Vercel

1. Import this GitHub repository into Vercel, using the repository root.
2. Select **Flask** as the Framework Preset. Remove any old Streamlit start command,
   custom Build Command, Install Command, or Output Directory override. Use Vercel defaults.
   The entry point is the Flask `app` exported by `app.py`; `vercel.json` sets a 60-second
   maximum function duration.
3. In **Settings > Environment Variables**, set these for Production (and Preview if used):
   - `APP_PASSWORD`: a unique private app password, at least 16 characters.
   - `APP_SECRET_KEY`: a random secret, at least 32 characters. Generate one with
     `python -c "import secrets; print(secrets.token_hex(32))"`.
4. Deploy/redeploy. Open the deployment and sign in with the app password. If these
   variables are missing or too short, the setup screen returns HTTP 503 and all
   AI/email operations stay disabled. `/health` still returns HTTP 200 for runtime checks.
5. After signing in, enter your OpenAI key, and optionally a Resend key and verified
   sender address, in the page. Do not commit keys or send them in chat.

Vercel's Python runtime installs `requirements.txt`. Streamlit is excluded from the hosted
dependency set. No persistent server, WebSocket connection, local output files, or worker
is required. Each job scoring/drafting step is a separate request with a bounded upstream
timeout; this avoids trying to score an entire feed inside one serverless request.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` to set `APP_PASSWORD` and `APP_SECRET_KEY` as described above, then:

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000`. Use the Flask development server locally only; Vercel
runs the exported WSGI application in production.

## Workflows

- **Job seeker:** search target roles with no API key, score individual jobs, and create
  tailored resume and application-email drafts. Edit and download the resume. Sending
  requires candidate authorization, verification that the listing accepts applications by
  email, and approval of the exact recipient and message. The edited resume is attached
  as `resume.txt`. No unattended applications or outreach.
- **Resume service:** review only a resume whose owner requested the review and opted in
  to follow-up. Configure the actual service, price, and manual payment instructions.
  Review the optional offer email before sending. Paid resume improvement requires manual
  payment verification; the app does not process or independently verify payments.
- **Sources and cost:** Remote OK requires source attribution and links back to its
  listings; both are included. The feed is limited to recent listings, not every job board
  or every country. Employers may restrict eligible locations. OpenAI and Resend may
  charge for API usage; their account limits apply.
- **Accuracy:** AI resumes are drafts, not independently fact-checked documents. Verify
  all qualifications and claims with the candidate. Never promise guaranteed employment.

## Privacy and sending behavior

The hosted app uses a shared owner password and signed, HTTP-only, same-site session
cookie (secure on Vercel), plus CSRF checks on every POST. Do not give clients the owner
password. This is not a multi-customer SaaS, billing system, or consent/audit database.
For broader access, add individual authentication, rate limiting, persisted consent,
retention controls, and delivery audit records first.

Keys, resumes, and results are held in page memory and sent only when you invoke their
corresponding operation; they are not written to server disk, cookies, localStorage, or
sessionStorage. Refreshing the page loses drafts. OpenAI receives the supplied AI input,
and Resend receives approved email content and attachments. Do not use third-party
resumes without permission. The hosted API passes credentials directly per request and
never replaces process-global API keys.

Emails require explicit approval and consent. Changing recipient/message/attachment resets
approval in the interface; successful sends disable the send button. A content-derived
Resend idempotency key reduces duplicate identical sends within Resend's idempotency
window (24 hours). A network timeout means acceptance is unknown: check the Resend
dashboard before retrying. API acceptance is not proof of delivery.

Private `.env`, `config.json`, `.venv`, and output directories are excluded from Git and
Vercel uploads.

## Legacy local workflows

The original local Streamlit interface remains available with optional dependencies:

```powershell
python -m pip install -r requirements-local.txt
python -m streamlit run webapp.py --server.address 127.0.0.1
```

The command-line pipeline also remains:

```powershell
Copy-Item config.example.json config.json
python main.py
```

For CLI use, edit `config.json` with your profile/roles and set `OPENAI_API_KEY` in `.env`.
It saves Markdown/JSON drafts under `output/`, never emails them, and scores at most 50
matching listings. The legacy interfaces are local-only, not Vercel entry points.

## Tests

```powershell
python -m unittest discover -s tests -v
node --check public\app.js
```

Tests mock paid API calls and email sending; no real applications or emails are sent.
