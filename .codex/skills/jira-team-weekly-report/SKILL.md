---
name: jira-team-weekly-report
description: Create a team-wide Jira activity report for the previous calendar week, summarizing outcomes, notable work, and blockers by topic rather than by individual.
---

# Team weekly report

When asked for a weekly report, run `python3 .codex/skills/jira-team-weekly-report/scripts/_export_jira_team_weekly_report.py -o <json-path>` from the scripts root, then read the JSON and write the report in English to a Markdown file. Use the user-specified path if provided; otherwise write `report/jira-team-weekly-report/jira-team-weekly-report-YYYY-MM-DD.md` under the scripts root, where the date is the Monday at the start of the reporting period; create the directory if needed. Return a link to the file. The script requires `requests` and Jira settings in the scripts root `.env` file or environment variables; do not print credentials. The JSON contains internal ticket content and comments: use a temporary file for the raw JSON unless the user requests a saved copy; do not share it externally unless requested.

Report the previous calendar week, Monday through Sunday. The script filters by the current assignee in the configured list or the Jira account running it; do not assume it captures all team activity if tickets changed assignee. It searches for tickets updated since the start of last week, including those updated again afterward, and filters their history and comments to the reporting week. Jira permissions may limit results; descriptions and issue fields reflect their current state, which may differ from the reporting week.

Group work by topic, product, or version. Identify outcomes completed during the week when supported by history or resolution date, and distinguish these from ongoing work. Summarize blockers only when supported by evidence. Group sub-tasks under their parent where appropriate to avoid double-counting, and link relevant tickets as evidence. State when evidence is insufficient. Include the date range, completed work, notable ongoing activity, problems or blockers, and relevant data limitations; omit empty sections. Do not organize the report by individual unless requested. Do not send or publish the report externally unless requested.

After the narrative, include a list of all Jira tickets cited in the report, with each ticket key linked to Jira, its summary, current status, and current assignee display name. Label status and assignee as current because they may have changed since the reporting period. Sort the list by assignee display name (case-insensitively), then by ticket key; place unassigned tickets last and label them Unassigned. Do not expose account IDs. This reference list does not change the team-wide organization of the report.

Start the report with a single Markdown heading containing the report title and date range. Follow it with a top-level Summary bullet and nested bullets for the summary. Use top-level bullets for the remaining section labels and nested bullets for their content; keep the referenced-ticket table nested under its section bullet. Do not use additional headings.

Keep the narrative concise: use a short summary and brief, outcome-focused bullets, combining related work and avoiding repeated details. Preserve essential evidence, blockers, and data limitations.
