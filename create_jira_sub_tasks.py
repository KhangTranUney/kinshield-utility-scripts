#!/usr/bin/env python3

import sys
import re
import tty
import termios
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent
STORIES_FILE = SCRIPTS_DIR / "stories.md"

TEAM_FIELD = "customfield_10361"
DEV_COMPONENTS = {"Android", "iOS"}
EXCLUDE_ISSUE_TYPES = {"Sub-task", "Spike"}


def load_env():
    env_path = SCRIPTS_DIR / ".env"
    if not env_path.exists():
        print(f"[ERROR] .env file not found at {env_path}")
        sys.exit(1)
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def confirm_or_cancel(prompt):
    print(f"\n{prompt}: ", end="", flush=True)
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    print()
                    return
                if ch == "\x1b":
                    print("\nCancelled.")
                    sys.exit(0)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except termios.error:
        response = input()
        if response.lower() in ("n", "no", "cancel"):
            print("Cancelled.")
            sys.exit(0)


def extract_board_id(board_url):
    m = re.search(r"/boards/(\d+)", board_url)
    if not m:
        print(f"[ERROR] Could not extract board ID from JIRA_BOARD_URL: {board_url}")
        sys.exit(1)
    return m.group(1)


# ── Board / sprint helpers ────────────────────────────────────────────────────

def fetch_sprints(base_url, auth, board_id):
    url = f"{base_url}/rest/agile/1.0/board/{board_id}/sprint?maxResults=50"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()["values"]


def fetch_sprint_issues(base_url, auth, sprint_id):
    url = f"{base_url}/rest/agile/1.0/sprint/{sprint_id}/issue?maxResults=200&fields=summary,status,issuetype"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()["issues"]


def fetch_backlog_issues(base_url, auth, board_id):
    url = f"{base_url}/rest/agile/1.0/board/{board_id}/backlog?maxResults=200&fields=summary,status,issuetype"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()["issues"]


def filter_backlog_tasks(issues):
    return [
        i for i in issues
        if i["fields"]["status"]["name"] == "Backlog"
        and i["fields"]["issuetype"]["name"] not in EXCLUDE_ISSUE_TYPES
    ]


# ── Story helpers ─────────────────────────────────────────────────────────────

def fetch_story(base_url, auth, key):
    fields = f"summary,status,labels,components,{TEAM_FIELD},subtasks"
    url = f"{base_url}/rest/api/3/issue/{key}?fields={fields}"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    if response.status_code == 404:
        raise RuntimeError(f"Issue {key} not found.")
    response.raise_for_status()
    return response.json()


def fetch_existing_subtask_titles(base_url, auth, subtasks):
    titles = set()
    for sub in subtasks:
        url = f"{base_url}/rest/api/3/issue/{sub['id']}?fields=summary"
        response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
        if response.status_code == 200:
            titles.add(response.json()["fields"]["summary"])
    return titles


def parse_story(data, base_url):
    fields = data["fields"]
    key = data["key"]
    team_field = fields.get(TEAM_FIELD)
    team_values = [t["value"] for t in team_field] if isinstance(team_field, list) else (
        [team_field["value"]] if isinstance(team_field, dict) else []
    )
    return {
        "key": key,
        "link": f"{base_url}/browse/{key}",
        "summary": fields["summary"],
        "status": fields["status"]["name"],
        "labels": fields.get("labels", []),
        "components": [c["name"] for c in fields.get("components", [])],
        "components_raw": fields.get("components", []),
        "team": team_values,
        "subtasks": fields.get("subtasks", []),
        TEAM_FIELD: fields.get(TEAM_FIELD),
    }


def build_plan(story, qa_assignee_id=""):
    tasks = []
    dev_comps = [c for c in story["components"] if c in DEV_COMPONENTS]

    for comp in dev_comps:
        comp_raw = [c for c in story["components_raw"] if c["name"] == comp]
        tasks.append({
            "summary": f"[{comp}] Implement UI",
            "type": "Dev",
            "components": comp_raw,
            "labels": story["labels"],
            "team": story[TEAM_FIELD],
            "assignee": None,
        })
        tasks.append({
            "summary": f"[{comp}] Integrate API",
            "type": "Dev",
            "components": comp_raw,
            "labels": story["labels"],
            "team": story[TEAM_FIELD],
            "assignee": None,
        })

    if dev_comps:
        tasks.append({
            "summary": f"[QA]{story['summary']}",
            "type": "QA",
            "components": story["components_raw"],
            "labels": story["labels"],
            "team": story[TEAM_FIELD],
            "assignee": qa_assignee_id or None,
        })

    return tasks


def create_sub_task(base_url, auth, project_key, parent_key, task):
    url = f"{base_url}/rest/api/3/issue"
    fields = {
        "project": {"key": project_key},
        "parent": {"key": parent_key},
        "issuetype": {"id": "10003"},  # Sub-task
        "summary": task["summary"],
        **({"components": [{"id": c["id"]} for c in task["components"]]} if task["components"] else {}),
        "labels": task["labels"],
    }
    if task["team"]:
        fields[TEAM_FIELD] = task["team"]
    if task.get("assignee"):
        fields["assignee"] = {"accountId": task["assignee"]}

    response = requests.post(
        url, json={"fields": fields}, auth=auth, headers={"Accept": "application/json"}
    )
    if response.status_code == 201:
        data = response.json()
        return data["key"], f"{base_url}/browse/{data['key']}"
    else:
        raise RuntimeError(f"{response.status_code} {response.text}")


def parse_key(line):
    line = line.strip()
    if "/browse/" in line:
        return line.rstrip("/").split("/browse/")[-1].split("?")[0]
    return line


def read_story_keys():
    if not STORIES_FILE.exists():
        print(f"[ERROR] Stories file not found: {STORIES_FILE}")
        sys.exit(1)
    keys = []
    for line in STORIES_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.append(parse_key(line))
    if not keys:
        print("[ERROR] No story keys found in stories.md")
        sys.exit(1)
    return keys


def write_stories_md(keys):
    lines = [
        "# Stories",
        "# One entry per line. Lines starting with # are ignored.",
        "# Accepts ticket ID or full Jira link, e.g.:",
        "#   SAF-260",
        "#   https://aottws.atlassian.net/browse/SAF-260",
    ] + keys
    STORIES_FILE.write_text("\n".join(lines) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    env = load_env()
    base_url = env.get("JIRA_BASE_URL", "").rstrip("/")
    email = env.get("JIRA_EMAIL", "")
    token = env.get("JIRA_API_TOKEN", "")
    qa_assignee_id = env.get("JIRA_QA_ASSIGNEE_ID", "")
    board_url = env.get("JIRA_BOARD_URL", "")

    if not all([base_url, email, token]):
        print("[ERROR] JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN must all be set in .env")
        sys.exit(1)

    auth = (email, token)

    # ── Step 0: Pick a group from the board ───────────────────────────────────
    board_id = extract_board_id(board_url) if board_url else None

    if board_id:
        print("=== Board Groups ===\n")
        sprints = fetch_sprints(base_url, auth, board_id)
        active_future = [s for s in sprints if s["state"] in ("active", "future")]

        groups = []
        for s in active_future:
            groups.append({"label": f"{s['name']} ({s['state']})", "type": "sprint", "id": s["id"]})
        groups.append({"label": "Backlog (no sprint)", "type": "backlog", "id": board_id})

        for i, g in enumerate(groups, 1):
            print(f"  {i}. {g['label']}")

        print()
        while True:
            choice = input(f"Select a group [1-{len(groups)}]: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(groups):
                selected = groups[int(choice) - 1]
                break
            print(f"  Please enter a number between 1 and {len(groups)}.")

        print(f"\nFetching '{selected['label']}'...")
        if selected["type"] == "sprint":
            issues = fetch_sprint_issues(base_url, auth, selected["id"])
        else:
            issues = fetch_backlog_issues(base_url, auth, board_id)

        tasks = filter_backlog_tasks(issues)
        print(f"Found {len(tasks)} Backlog tasks (sub-tasks excluded).\n")
        for issue in tasks:
            print(f"  [{issue['key']}] [{issue['fields']['issuetype']['name']}] {issue['fields']['summary']}")

        confirm_or_cancel(f"Update stories.md with these {len(tasks)} tasks? Press Enter to continue or Esc to cancel")

        keys = [i["key"] for i in tasks]
        write_stories_md(keys)
        print(f"stories.md updated with {len(keys)} keys.\n")

    # ── Step 1: Fetch and display all stories ─────────────────────────────────
    story_keys = read_story_keys()
    print("=== Fetching Stories ===\n")
    stories = []
    for key in story_keys:
        try:
            data = fetch_story(base_url, auth, key)
            story = parse_story(data, base_url)
            stories.append(story)
            print(f"  [{story['key']}] {story['summary']}")
            print(f"    Link       : {story['link']}")
            print(f"    Status     : {story['status']}")
            print(f"    Team       : {', '.join(story['team']) or 'N/A'}")
            print(f"    Labels     : {', '.join(story['labels']) or 'N/A'}")
            print(f"    Components : {', '.join(story['components']) or 'N/A'}")
            print()
        except RuntimeError as e:
            print(f"  [ERROR] {key}: {e}\n")
            sys.exit(1)

    confirm_or_cancel("Stories look correct? Press Enter to continue with planning or Esc to cancel")

    # ── Step 2: Build and display plan ────────────────────────────────────────
    print("\n=== Sub-task Plan ===\n")
    story_plans = []
    for story in stories:
        plan = build_plan(story, qa_assignee_id)
        existing_titles = fetch_existing_subtask_titles(base_url, auth, story["subtasks"])
        story_plans.append((story, plan, existing_titles))
        if not plan:
            print(f"  [{story['key']}] No sub-tasks to create (no Android/iOS component).")
            continue
        print(f"  [{story['key']}] {story['summary']}")
        for task in plan:
            if task["summary"] in existing_titles:
                print(f"    - {task['summary']}  [skip: already exists]")
            else:
                print(f"    - {task['summary']}")
        print()

    confirm_or_cancel("Proceed with creating sub-tasks? Press Enter to continue or Esc to cancel")

    # ── Step 3: Create sub-tasks ──────────────────────────────────────────────
    print("\n=== Creating Sub-tasks ===\n")
    project_key = story_keys[0].split("-")[0]

    for story, plan, existing_titles in story_plans:
        if not plan:
            continue
        print(f"  [{story['key']}]")
        for task in plan:
            if task["summary"] in existing_titles:
                print(f"    Skipped (already exists): {task['summary']}")
                continue
            try:
                key, link = create_sub_task(base_url, auth, project_key, story["key"], task)
                print(f"    Created [{key}] {task['summary']}")
                print(f"            {link}")
            except RuntimeError as e:
                print(f"    ERROR creating '{task['summary']}': {e}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
