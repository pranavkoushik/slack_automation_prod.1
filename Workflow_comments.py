# WORKFLOW OVERVIEW
#
# This file is only for explanation.
# It is not imported or executed by the automation.
#
# ---------------------------------------------------------------------------
# WHAT THIS PROJECT DOES
# ---------------------------------------------------------------------------
# This automation runs once every day at 10:00 AM IST through Vercel Cron.
# The cron route is /api/cron.
#
# When the route is called:
# 1. The request is validated using CRON_SECRET.
# 2. The automation loads environment variables.
# 3. The automation reads the Google Sheet roster.
# 4. The automation checks the current date in Asia/Kolkata timezone.
# 5. Based on the date, it decides which Slack messages need to be sent.
# 6. If the date is in the month-end billing window, it also queries Jira.
#
# ---------------------------------------------------------------------------
# DATA SOURCES USED
# ---------------------------------------------------------------------------
# 1. Google Sheet
#    The sheet contains:
#    - team
#    - employee name
#    - email
#    - Slack user ID
#
#    This data is used to:
#    - identify TechOps users
#    - map Jira emails to readable names
#    - map Jira emails to Slack IDs for direct reminders
#
# 2. Jira
#    Jira is queried for billing tickets that:
#    - belong to the configured project
#    - have the expected billing label
#    - are not Done
#    - are not Closed
#
# 3. Slack
#    Slack is used to:
#    - send shared channel reminders
#    - send direct messages to users
#
# ---------------------------------------------------------------------------
# TIMEZONE LOGIC
# ---------------------------------------------------------------------------
# The code uses Asia/Kolkata explicitly.
# This means all "today", "last day of month", and "1st of month" checks are
# based on IST, even though Vercel Cron itself is scheduled in UTC.
#
# Vercel schedule used:
# - 30 4 * * *
#
# Why this works:
# - 04:30 UTC = 10:00 AM IST
#
# ---------------------------------------------------------------------------
# BILLING LABEL LOGIC
# ---------------------------------------------------------------------------
# The Jira label is generated in this format:
# - Billing-Apr-2026
#
# Label selection rule:
# - If today's date is 1 to 20, the code uses the PREVIOUS month
# - If today's date is 21 onward, the code uses the CURRENT month
#
# Example:
# - If today is May 1, 2026 -> label becomes Billing-Apr-2026
# - If today is May 25, 2026 -> label becomes Billing-May-2026
#
# ---------------------------------------------------------------------------
# DATE-WISE WORKFLOW
# ---------------------------------------------------------------------------
# DAILY
# - The job runs every day at 10:00 AM IST.
# - On many days, nothing will be sent if no date condition matches.
#
# ON THE 20TH OF THE MONTH
# - Send a direct message to every TechOps user:
#   "Please update the month label for billing board."
#
# ON LAST DAY - 6
# - Post in the main Slack channel:
#   "<!here> Reminder to create tickets for cold store."
# - Send a direct message to every TechOps user:
#   "Please create tickets for cold store."
#
# ON LAST DAY - 4
# - Post in the main Slack channel:
#   "<!here> Reminder to create tickets for cold store."
# - Send a direct message to every TechOps user:
#   "Reminder: Please create tickets for cold store."
#
# ON LAST DAY - 2, LAST DAY - 1, LAST DAY, AND 1ST
# - Send direct messages only to people connected to still-open billing tickets.
# - People connected to tickets means:
#   - the assignee
#   - the reporter
# - Message sent:
#   "Reminder: Please update and close cold store tickets"
#
# ON EVERY DATE FROM 27TH TO 1ST
# - Query Jira for open billing tickets using the generated billing label.
# - Build a summary grouped by assignee name.
# - Post the summary in the Slack channel.
#
# If tickets exist, the message looks like:
# *Billing Board Open Tickets Summary:*
#
# *Aman:* JTSE-101, JTSE-102
#
# *Neha:* JTSE-103
#
# *Please update and close your tickets.*
#
# If no tickets exist, the message is:
# "No active Billing ticket today."
#
# ---------------------------------------------------------------------------
# HOW REMINDER RECIPIENTS ARE DECIDED
# ---------------------------------------------------------------------------
# For TechOps reminders:
# - Users are selected from the Google Sheet where team == techops
#
# For closing reminders:
# - Jira issues are read
# - assignee email is collected
# - reporter email is collected
# - both are matched against the sheet
# - if a matching Slack ID exists, that user receives the reminder
#
# This means closing reminders now go to both:
# - assignee
# - reporter
#
# ---------------------------------------------------------------------------
# EXAMPLE: APRIL 2026
# ---------------------------------------------------------------------------
# April has 30 days.
#
# April 20:
# - DM TechOps:
#   "Please update the month label for billing board."
#
# April 24:
# - Channel:
#   "<!here> Reminder to create tickets for cold store."
# - DM TechOps:
#   "Please create tickets for cold store."
#
# April 26:
# - Channel:
#   "<!here> Reminder to create tickets for cold store."
# - DM TechOps:
#   "Reminder: Please create tickets for cold store."
#
# April 27:
# - Post billing summary in channel
#
# April 28:
# - Post billing summary in channel
# - DM assignee and reporter of open tickets:
#   "Reminder: Please update and close cold store tickets"
#
# April 29:
# - Post billing summary in channel
# - DM assignee and reporter of open tickets:
#   "Reminder: Please update and close cold store tickets"
#
# April 30:
# - Post billing summary in channel
# - DM assignee and reporter of open tickets:
#   "Reminder: Please update and close cold store tickets"
#
# May 1:
# - Post billing summary in channel
# - DM assignee and reporter of open tickets:
#   "Reminder: Please update and close cold store tickets"
#
# ---------------------------------------------------------------------------
# WHAT HAPPENS ON A NORMAL NON-TRIGGER DAY
# ---------------------------------------------------------------------------
# Example: April 14
# - The script still runs
# - It loads config
# - It reads the Google Sheet
# - It checks the date
# - No Slack message is sent because no rule matches
# - The function returns a success response
#
# ---------------------------------------------------------------------------
# FINAL SUMMARY
# ---------------------------------------------------------------------------
# This project is now a daily IST-based Slack/Jira automation.
# It sends:
# - month label reminders to TechOps
# - ticket creation reminders to channel + TechOps
# - close-ticket reminders to assignee + reporter
# - billing summaries in the month-end billing window
