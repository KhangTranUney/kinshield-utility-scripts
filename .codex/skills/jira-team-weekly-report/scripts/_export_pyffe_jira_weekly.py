#!/usr/bin/env python3
"""Collect Jira data for a team-wide report for the previous calendar week.

Run: python3 .codex/skills/jira-team-weekly-report/scripts/_export_pyffe_jira_weekly.py [-o report.json]
Dates use the local machine; JQL date boundaries use the Jira account time zone.
"""

import argparse
from datetime import date, datetime, timedelta
import json
import os
import re
from pathlib import Path
import sys

import requests

ENV_FILE = Path(__file__).resolve().parents[4] / ".env"
JQL = """assignee IN (
  currentUser(),
  712020:c12d47ca-0f69-4954-96db-69bd1a6ccc90,
  712020:f6603948-6ad7-47a9-872a-64b9df4ac81d,
  712020:06130f40-90e8-4146-97d7-ad1306b770f8,
  712020:9d36d0ba-7e28-4d2f-a554-a26c1671d8f6
)
AND updated >= "{start}"
AND updated < "{end}"
ORDER BY fixVersion ASC, assignee ASC, key ASC, updated DESC"""

def load_config():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        if key in os.environ:
            values[key] = os.environ[key]
    missing = [key for key in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not values.get(key)]
    if missing:
        raise ValueError(f"Missing configuration: {', '.join(missing)}. Update {ENV_FILE} or set environment variables.")
    return values


def previous_week(today):
    """Return last Monday and this Monday (exclusive end)."""
    end = today - timedelta(days=today.weekday())
    return end - timedelta(days=7), end



FIELDS = ["summary", "description", "status", "assignee", "fixVersions", "updated",
          "created", "issuetype", "priority", "parent", "resolution", "resolutiondate",
          "project", "components", "labels", "duedate"]


def request_json(session, method, url, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    if not response.ok:
        try:
            data = response.json()
            detail = "; ".join(data.get("errorMessages", [])) or str(data.get("errors", ""))
        except ValueError:
            detail = ""
        raise RuntimeError(f"Jira HTTP {response.status_code}: {detail or response.reason}")
    return response.json()


def search_candidates(session, base_url, start):
    # Do not cap updated: issues updated again this week are still candidates.
    jql = JQL.replace('AND updated < "{end}"\n', '').format(start=start.isoformat())
    return search(session, base_url, jql, FIELDS)


def search(session, base_url, jql, fields):
    payload = {"jql": jql, "fields": fields, "maxResults": 100}
    result, seen = [], set()
    while True:
        data = request_json(session, "POST", f"{base_url}/rest/api/3/search/jql", json=payload)
        result.extend(data["issues"])
        token = data.get("nextPageToken")
        if not token:
            if data.get("isLast") is False:
                raise RuntimeError("Jira returned incomplete results without a nextPageToken")
            return result
        if token in seen:
            raise RuntimeError("Jira returned a repeated nextPageToken")
        seen.add(token)
        payload["nextPageToken"] = token


def get_pages(session, url, result_key):
    start_at = 0
    result = []
    while True:
        data = request_json(session, "GET", url, params={"startAt": start_at, "maxResults": 100})
        values = data[result_key]
        result.extend(values)
        start_at += len(values)
        if data.get("isLast") is True or start_at >= data.get("total", float("inf")):
            return result
        if not values:
            raise RuntimeError(f"Pagination did not complete: {url}")


def in_week(value, start, end, tz):
    if not value:
        return False
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None:
        raise ValueError(f"Jira timestamp has no time zone: {value}")
    local = timestamp.astimezone(tz)
    return start <= local.date() < end


def collect(session, base_url, start, end, tz):
    result = []
    for issue in search_candidates(session, base_url, start):
        key = issue["key"]
        url = f"{base_url}/rest/api/3/issue/{key}"
        changes = get_pages(session, f"{url}/changelog", "values")
        comments = get_pages(session, f"{url}/comment", "comments")
        changes = [x for x in changes if in_week(x.get("created"), start, end, tz)]
        # Include older comments edited during the week; retain both timestamps.
        comments = [x for x in comments if in_week(x.get("created"), start, end, tz)
                    or in_week(x.get("updated"), start, end, tz)]
        fields = issue["fields"]
        if not changes and not comments and not in_week(fields.get("created"), start, end, tz) and not in_week(fields.get("updated"), start, end, tz):
            continue
        result.append({"key": key, "url": f"{base_url}/browse/{key}", "fields": fields,
                       "changelog_in_week": changes, "comments_in_week": comments})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=Path("jira_team_weekly_report.json"),
                        help="Output JSON file; overwrites an existing file")
    args = parser.parse_args()
    try:
        config = load_config()
        base_url = config["JIRA_BASE_URL"].rstrip("/")
        start, end = previous_week(date.today())
        # Jira interprets JQL dates in the account time zone; use it for history too.
        with requests.Session() as session:
            session.auth = (config["JIRA_EMAIL"], config["JIRA_API_TOKEN"])
            session.headers.update({"Accept": "application/json"})
            me = request_json(session, "GET", f"{base_url}/rest/api/3/myself")
            from zoneinfo import ZoneInfo
            if not me.get("timeZone"):
                raise RuntimeError("Jira did not return the account time zone; cannot filter history accurately")
            tz = ZoneInfo(me["timeZone"])
            issues = collect(session, base_url, start, end, tz)
            # The weekly search misses open issues without recent updates. Restrict
            # additional candidates to the Pyffe project and the configured assignees.
            fields_metadata = request_json(session, "GET", f"{base_url}/rest/api/3/field")
            start_fields = [field["id"] for field in fields_metadata if field.get("name", "").casefold() == "start date"]
            plan_jql = JQL[:JQL.index("AND updated")] + "AND project = SAF AND statusCategory != Done ORDER BY priority DESC, key ASC"
            plan_candidates = search(session, base_url, plan_jql, FIELDS + start_fields)
        result = {"period": {"start": start.isoformat(), "end_exclusive": end.isoformat(),
                             "jira_timezone": str(tz)},
                  "scope": "Current assignee is in the configured list or currentUser()",
                  "issues": issues,
                  "plan_start_date_fields": start_fields,
                  "plan_candidates": [{"key": i["key"], "url": f"{base_url}/browse/{i['key']}", "fields": i["fields"]} for i in plan_candidates]}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Exported {len(issues)} issues to {args.output} ({start} through {end - timedelta(days=1)}, Jira: {tz})")
    except (ValueError, KeyError, OSError, RuntimeError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
