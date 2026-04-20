import calendar
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

# Load local `.env` values for development; Vercel injects env vars directly.
load_dotenv()

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

DEFAULT_SHEET_ID = "1wmyuok6tEDRwxGRzCBFGF0pTkVXSSYWXH5hGX3lv_rM"
DEFAULT_CHANNEL_ID = "CCBQKJD50"
DEFAULT_JIRA_PROJECT = "JTSE"
DEFAULT_BILLING_LABEL_PREFIX = "Billing"
DEFAULT_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True)
class AppConfig:
    # This dataclass keeps every runtime setting in one place so the rest of the
    # code can depend on a single typed object instead of repeatedly reading env vars.
    slack_bot_token: str
    jira_email: str
    jira_api_token: str
    jira_domain: str
    sheet_id: str
    slack_channel_id: str
    jira_project_key: str
    billing_label_prefix: str
    timezone_name: str


def normalize_text(value: Any) -> str:
    # Many values come from APIs or sheets and may be None, numbers, or empty.
    # Converting them here gives us one consistent representation everywhere else.
    return str(value or "").strip()


def normalize_email(value: Any) -> str:
    # Email matching should be case-insensitive, so every lookup key is lowered.
    return normalize_text(value).lower()


def get_app_now(timezone_name: str, now: datetime | None = None) -> datetime:
    # The scheduler runs in UTC, but the business rules depend on IST calendar dates.
    # This helper ensures every "today" check is evaluated in the configured timezone.
    timezone = ZoneInfo(timezone_name)

    # All date-based reminders should use IST rather than the runtime default.
    if now is None:
        return datetime.now(timezone)

    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)

    return now.astimezone(timezone)


def load_config() -> AppConfig:
    # Centralizes configuration loading so deployment differences between local
    # runs and Vercel are handled in one place.
    required = ["SLACK_BOT_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_DOMAIN"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    has_json_creds = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    has_file_creds = os.path.exists("credentials.json")
    if not has_json_creds and not has_file_creds:
        raise ValueError("Provide GOOGLE_SERVICE_ACCOUNT_JSON or add credentials.json for Google Sheets access")

    return AppConfig(
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
        jira_domain=os.environ["JIRA_DOMAIN"],
        sheet_id=os.getenv("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID),
        slack_channel_id=os.getenv("SLACK_CHANNEL_ID", DEFAULT_CHANNEL_ID),
        jira_project_key=os.getenv("JIRA_PROJECT_KEY", DEFAULT_JIRA_PROJECT),
        billing_label_prefix=os.getenv("BILLING_LABEL_PREFIX", DEFAULT_BILLING_LABEL_PREFIX),
        timezone_name=os.getenv("APP_TIMEZONE", DEFAULT_TIMEZONE),
    )


def load_google_sheet(sheet_id: str) -> list[dict[str, Any]]:
    # The Google Sheet acts as the source of truth for team membership, names,
    # email mapping, and Slack user IDs used by the reminder workflow.
    scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    # Vercel is easiest to manage with a JSON env var, while local runs can
    # continue using the checked-out credentials file.
    if service_account_json:
        creds_info = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scope)

    client = gspread.authorize(creds)
    sheet = client.open_by_key(sheet_id).sheet1
    return sheet.get_all_records()


def build_team_maps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Converts raw sheet rows into fast lookup tables so later steps can quickly
    # translate between email addresses, display names, teams, and Slack IDs.
    email_to_name: dict[str, str] = {}
    email_to_slack: dict[str, str] = {}
    cs_ids: set[str] = set()
    techops_ids: set[str] = set()

    for row in rows:
        email = normalize_email(row.get("Email"))
        name = normalize_text(row.get("name"))
        slack_id = normalize_text(row.get("slack_id"))
        team = normalize_text(row.get("team")).lower()

        if email and name:
            email_to_name[email] = name

        if email and slack_id:
            email_to_slack[email] = slack_id

        if team == "cs" and slack_id:
            cs_ids.add(slack_id)
        elif team == "techops" and slack_id:
            techops_ids.add(slack_id)

    return {
        "email_to_name": email_to_name,
        "email_to_slack": email_to_slack,
        "cs_ids": sorted(cs_ids),
        "techops_ids": sorted(techops_ids),
    }


def send_slack_message(token: str, channel: str, text: str, retries: int = 3) -> bool:
    # All Slack writes flow through this helper so retries, logging, and API
    # request structure stay consistent for both channel posts and direct messages.
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "channel": channel,
        "text": text,
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                return True

            LOGGER.warning("Slack API returned an error for %s: %s", channel, data)
        except (requests.RequestException, ValueError) as exc:
            LOGGER.warning("Slack send attempt %s failed for %s: %s", attempt, channel, exc)

        if attempt < retries:
            time.sleep(2)

    return False


def build_billing_label(now: datetime, label_prefix: str) -> str:
    # Jira issues are grouped by a billing label like Billing-Apr-2026.
    # The current workflow treats dates up to the 20th as part of the previous cycle.
    # The existing workflow switches to the previous month label until the 20th.
    if now.day <= 20:
        first_day = now.replace(day=1)
        previous_month = first_day - timedelta(days=1)
        month = previous_month.strftime("%b")
        year = previous_month.strftime("%Y")
    else:
        month = now.strftime("%b")
        year = now.strftime("%Y")

    return f"{label_prefix}-{month}-{year}".strip()


def fetch_open_billing_data(
    config: AppConfig,
    now: datetime,
    email_to_name: dict[str, str],
) -> dict[str, Any]:
    # Pulls open billing tickets from Jira and prepares two outputs:
    # 1. A summary grouped by assignee for the channel message.
    # 2. A deduplicated email set used to decide who receives closing reminders.
    label = build_billing_label(now, config.billing_label_prefix)
    jql_query = (
        f'project = {config.jira_project_key} AND labels = "{label}" '
        'AND statusCategory != Done AND statusCategory != Closed'
    )
    url = f"https://{config.jira_domain}/rest/api/3/search/jql"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "jql": jql_query,
        "maxResults": 500,
        "fields": ["assignee", "reporter", "status"],
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=(config.jira_email, config.jira_api_token),
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    summary: dict[str, list[str]] = {}
    active_emails: set[str] = set()

    for issue in data.get("issues", []):
        issue_key = normalize_text(issue.get("key"))
        fields = issue.get("fields", {})
        assignee = fields.get("assignee")
        reporter = fields.get("reporter")

        assignee_email = normalize_email(assignee.get("emailAddress") if assignee else None)
        reporter_email = normalize_email(reporter.get("emailAddress") if reporter else None)

        if assignee_email:
            active_emails.add(assignee_email)
            owner_name = email_to_name.get(
                assignee_email,
                normalize_text(assignee.get("displayName")),
            )
        elif assignee:
            owner_name = normalize_text(assignee.get("displayName")) or "Unassigned"
        else:
            owner_name = "Unassigned"

        # Closing reminders should reach everyone tied to an open ticket.
        if reporter_email:
            active_emails.add(reporter_email)

        if issue_key:
            summary.setdefault(owner_name, []).append(issue_key)

    return {
        "label": label,
        "summary": summary,
        "active_emails": active_emails,
        "issue_count": sum(len(ticket_keys) for ticket_keys in summary.values()),
    }


def build_summary_message(summary: dict[str, list[str]]) -> str:
    # Builds the human-readable Slack message posted in the shared channel during
    # the month-end billing window.
    if not summary:
        return "No active Billing ticket today."

    lines = ["*Billing Board Open Tickets Summary:*", ""]

    for person, tickets in summary.items():
        tickets_str = ", ".join(tickets)
        lines.append(f"*{person}:* {tickets_str}")
        lines.append("")

    lines.append("*Please update and close your tickets.*")
    return "\n".join(lines)


def send_direct_messages(token: str, recipients: list[str], message: str) -> int:
    # Sends one reminder to multiple Slack users and returns the count of
    # successful deliveries so the final run summary is easy to inspect in logs.
    sent = 0

    for slack_id in recipients:
        if send_slack_message(token, slack_id, message):
            sent += 1

    return sent


def run_automation(now: datetime | None = None) -> dict[str, Any]:
    # This is the top-level orchestration function used by both:
    # - local execution through Slack_Automation.py
    # - Vercel cron execution through api/cron.py
    # It gathers configuration, loads roster data, decides what should happen
    # for the current IST date, sends the required messages, and returns a
    # compact status payload for logs and HTTP responses.
    config = load_config()
    current_time = get_app_now(config.timezone_name, now)
    today = current_time.day
    last_day = calendar.monthrange(current_time.year, current_time.month)[1]

    rows = load_google_sheet(config.sheet_id)
    team_maps = build_team_maps(rows)
    email_to_name = team_maps["email_to_name"]
    email_to_slack = team_maps["email_to_slack"]
    techops_ids = team_maps["techops_ids"]

    active_emails: set[str] = set()
    summary_message_sent = False
    reminder_count = 0
    billing_label = None
    issue_count = 0

    if today >= 27 or today <= 1:
        # Only the month-end billing window needs Jira summary generation.
        billing_data = fetch_open_billing_data(config, current_time, email_to_name)
        active_emails = billing_data["active_emails"]
        billing_label = billing_data["label"]
        issue_count = billing_data["issue_count"]
        summary_message = build_summary_message(billing_data["summary"])
        summary_message_sent = send_slack_message(
            config.slack_bot_token,
            config.slack_channel_id,
            summary_message,
        )

    if today == 20:
        # TechOps updates the billing label before the next month-end cycle.
        reminder_msg = "Please update the month label for billing board."
        reminder_count += send_direct_messages(config.slack_bot_token, techops_ids, reminder_msg)

    cs_message = None
    if today == last_day - 6:
        cs_message = "Please create tickets for cold store."
    elif today == last_day - 4:
        cs_message = "Reminder: Please create tickets for cold store."
    elif today in [last_day - 2, last_day - 1, last_day, 1]:
        cs_message = "Reminder: Please update and close cold store tickets"

    if cs_message:
        closing_days = {last_day - 2, last_day - 1, last_day, 1}

        if today in closing_days:
            # Closing reminders go only to users connected to still-open tickets.
            active_slack_ids = sorted(
                {
                    email_to_slack[email]
                    for email in active_emails
                    if email in email_to_slack
                }
            )
            reminder_count += send_direct_messages(config.slack_bot_token, active_slack_ids, cs_message)
        else:
            # Ticket-creation reminders go to the channel and TechOps DMs.
            channel_message = "<!here> Reminder to create tickets for cold store."
            if send_slack_message(config.slack_bot_token, config.slack_channel_id, channel_message):
                reminder_count += 1

            reminder_count += send_direct_messages(config.slack_bot_token, techops_ids, cs_message)

    result = {
        "ok": True,
        "run_at": current_time.isoformat(),
        "timezone": config.timezone_name,
        "billing_label": billing_label,
        "issue_count": issue_count,
        "summary_sent": summary_message_sent,
        "reminders_sent": reminder_count,
    }
    LOGGER.info("Automation completed: %s", result)
    return result
