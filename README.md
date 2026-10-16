# Job Scout

A private, local job-search and resume-service assistant. It searches Remote OK's worldwide remote-job feed, scores role matches, drafts tailored resumes and application emails, and can review resumes for people who opted in to your paid service. Emails are never sent automatically: the sender must confirm consent and approve the exact message before sending.

## Setup

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item .env.example .env
```

Remote OK provides a free public API without an account or API key; its API terms require linking to Remote OK and mentioning it as the source, which this app does. Results are limited to the latest listings in Remote OK's feed, and each employer may restrict eligible countries. The app scores at most 50 matching listings per run to limit AI API usage.

Job search itself needs no API credentials. Enter an OpenAI API key in the app to score listings, review resumes, and generate drafts. OpenAI API usage is billed separately from ChatGPT subscriptions. To send an approved email, also enter a Resend API key and a sender address verified with Resend. Resend account limits and pricing apply.

## Run

To open the web interface in your browser:

```powershell
python -m streamlit run webapp.py
```

Streamlit will print a local address, usually `http://localhost:8501`.

- **Job seeker:** enter your resume and roles, find matches, and generate a tailored resume and application email. Sending requires verifying the job listing accepts email applications, confirming the candidate authorized the email, and approving the exact recipient and message.
- **Resume service:** enter a resume only after the owner requested the review and opted in to follow-up. Review the findings and optional service offer, then approve before sending. Payment is not processed in the app; manually verify payment before generating the paid resume improvement.
- OpenAI and Resend credentials are entered in the private local app session and are not saved to project files. Resend requires a verified sender address/domain.

This build is for private local use. It has no user authentication, customer database, or production consent/audit system and must not be exposed as a public service until those are added. Job listings are attributed to [Remote OK](https://remoteok.com/), as required by its API terms.

Alternatively, run the command-line version:

```powershell
python main.py
```

The command-line pipeline fetches Remote OK's latest feed once, matches target roles against listing titles and tags, deduplicates listings by URL, scores up to 50 matching listings, and creates Markdown and JSON drafts under `output/`. `max_jobs_per_run` limits the number of qualifying drafts created in a run. Review each listing and generated letter yourself before applying.

## Tests

The tests use mocked job search and AI responses and do not require API credentials:

```powershell
python -m unittest discover -s tests -v
```
