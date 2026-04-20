# Slack Automation

Daily Slack/Jira/Google Sheets automation deployed as a Vercel serverless cron job.

Sends billing summaries, ticket-creation reminders, and close-ticket DMs based on
the current IST date and a team roster stored in Google Sheets.

## Architecture

```
api/cron.py        ← Vercel serverless function (HTTP handler)
automation.py      ← Core business logic (imported by both cron and local runner)
Slack_Automation.py ← Local runner for development
vercel.json        ← Cron schedule + function config
```

## Schedule

The cron runs every day at **10:00 AM IST** (`30 4 * * *` UTC).

| Day of month | Action |
|---|---|
| 20th | DM TechOps: update billing label |
| last_day − 6 | Channel + TechOps DM: create cold-store tickets |
| last_day − 4 | Channel + TechOps DM: reminder to create cold-store tickets |
| last_day − 2 … 1st | DM assignees/reporters of open tickets: close cold-store tickets |
| 27th … 1st | Post billing summary in channel |

## Deploy to Vercel

### 1. Import the repository

Connect this GitHub repo to a new Vercel project.

### 2. Set environment variables

In **Vercel → Project → Settings → Environment Variables**, add:

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Slack bot OAuth token (`xoxb-…`) |
| `JIRA_EMAIL` | Yes | Jira account email |
| `JIRA_API_TOKEN` | Yes | Jira API token |
| `JIRA_DOMAIN` | Yes | e.g. `yourteam.atlassian.net` |
| `CRON_SECRET` | Yes | Vercel cron secret (auto-sent as `Authorization: Bearer …`) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Full Google service-account JSON (one line) |
| `GOOGLE_SHEET_ID` | No | Defaults to the built-in sheet ID |
| `SLACK_CHANNEL_ID` | No | Defaults to `CCBQKJD50` |
| `JIRA_PROJECT_KEY` | No | Defaults to `JTSE` |
| `BILLING_LABEL_PREFIX` | No | Defaults to `Billing` |
| `APP_TIMEZONE` | No | Defaults to `Asia/Kolkata` |

### 3. Deploy

Push to `main` — Vercel auto-deploys and registers the cron job.

## Local development

```bash
cp .env.example .env
# Fill in real values in .env
pip install -r requirements.txt
python Slack_Automation.py
```

## Files

| File | Purpose |
|---|---|
| `automation.py` | Core business logic |
| `api/cron.py` | Vercel serverless cron entrypoint |
| `Slack_Automation.py` | Local development runner |
| `Workflow_comments.py` | Workflow documentation (not executed) |
| `vercel.json` | Cron schedule and function configuration |
| `requirements.txt` | Pinned Python dependencies |
