#!/usr/bin/env python3
"""
Clone Confluence weekly template pages for the current week.

Usage:
    # Create a .env file in the same directory as this script:
    CONFLUENCE_EMAIL=your-email@example.com
    CONFLUENCE_TOKEN=your-api-token

    # Run:
    python3 clone_weekly_pages.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFLUENCE_BASE = "https://aottws.atlassian.net/wiki"

# Template page IDs to clone, with display labels for the Teams message
TEMPLATE_PAGES = [
    (1402798483, "UQI",      "Core - Shared Platform"),
    (1403191574, "SAFENEST", "KinShield"),
    (1403191452, "KUD",      "KinSense"),
    (1403191481, "UAV",      "SkyTrack"),
    (1403191564, "ZTNA",     "ShieldNet"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_env():
    """Load variables from .env file in the same directory as this script."""
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def get_credentials():
    load_env()
    email = os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_TOKEN")
    if not email or not token:
        env_path = Path(__file__).resolve().parent / ".env"
        print("ERROR: Missing credentials.\n")
        print(f"Create a .env file at: {env_path}\n")
        print("With the following content:")
        print("  CONFLUENCE_EMAIL=your-email@example.com")
        print("  CONFLUENCE_TOKEN=your-api-token\n")
        print("To generate an API token:")
        print("  1. Go to https://id.atlassian.com/manage-profile/security/api-tokens")
        print("  2. Click 'Create API token'")
        print("  3. Copy the token and paste it in the .env file")
        sys.exit(1)
    return email, token


def previous_week_info():
    """Return (week_number, monday_date, friday_date) for the previous ISO week."""
    today = datetime.now()
    prev_monday = today - timedelta(days=today.weekday() + 7)
    prev_friday = prev_monday + timedelta(days=4)
    week_number = prev_monday.isocalendar()[1]
    return week_number, prev_monday, prev_friday


def api_get(endpoint, email, token):
    """GET from Confluence REST API via curl (avoids Python SSL issues on macOS)."""
    url = f"{CONFLUENCE_BASE}/rest/api/{endpoint}"
    result = subprocess.run(
        ["curl", "-s", "-u", f"{email}:{token}", url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl GET failed: {result.stderr}")
    return json.loads(result.stdout)


def api_post(endpoint, payload, email, token):
    """POST to Confluence REST API via curl."""
    url = f"{CONFLUENCE_BASE}/rest/api/{endpoint}"
    payload_json = json.dumps(payload)
    result = subprocess.run(
        [
            "curl", "-s", "-u", f"{email}:{token}",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "-d", payload_json,
            url,
        ],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl POST failed: {result.stderr}")
    return json.loads(result.stdout)


def transform_title(original_title, week_num, monday, friday):
    """
    Transform a template title to the current week.
    - Removes the '[Template] ' prefix
    - Updates the week number (W20 -> W21)
    - Updates the date range (11/05 - 15/05/2026 -> 18/05 - 22/05/2026)
    """
    title = original_title

    # Remove [Template] prefix
    title = re.sub(r'^\[Template\]\s*', '', title)

    # Replace week number: W20 -> W21
    title = re.sub(r'W\d+', f'W{week_num}', title)

    # Replace date range: (dd/mm - dd/mm/yyyy)
    mon_str = monday.strftime("%d/%m")
    fri_str = friday.strftime("%d/%m/%Y")
    title = re.sub(
        r'\(\d{2}/\d{2}\s*-\s*\d{2}/\d{2}/\d{4}\)',
        f'({mon_str} - {fri_str})',
        title
    )

    return title


def find_existing_page(space_key, title, email, token):
    """Check if a page with the given title already exists. Returns its URL or None."""
    import urllib.parse
    encoded_title = urllib.parse.quote(title)
    endpoint = f"content?spaceKey={space_key}&title={encoded_title}&type=page"
    data = api_get(endpoint, email, token)
    if data.get("size", 0) > 0:
        page = data["results"][0]
        tiny = page.get("_links", {}).get("tinyui", "")
        if tiny:
            return f"{CONFLUENCE_BASE}{tiny}"
        return f"{CONFLUENCE_BASE}/spaces/{space_key}/pages/{page['id']}"
    return None


def fetch_page_info(page_id, email, token, week_num, monday, friday):
    """Fetch a template page and return its metadata + planned new title."""
    data = api_get(
        f"content/{page_id}?expand=body.storage,ancestors,space",
        email, token
    )

    original_title = data["title"]
    space_key = data["space"]["key"]
    body_html = data["body"]["storage"]["value"]
    ancestors = data.get("ancestors", [])
    parent_id = ancestors[-1]["id"] if ancestors else None
    parent_title = ancestors[-1]["title"] if ancestors else "N/A"
    new_title = transform_title(original_title, week_num, monday, friday)

    return {
        "page_id": page_id,
        "space_key": space_key,
        "original_title": original_title,
        "new_title": new_title,
        "parent_id": parent_id,
        "parent_title": parent_title,
        "body_html": body_html,
    }


def create_page(info, email, token):
    """Create a cloned page from pre-fetched info. Returns the new page URL or None."""
    space_key = info["space_key"]
    new_title = info["new_title"]

    # Check for duplicates
    existing_url = find_existing_page(space_key, new_title, email, token)
    if existing_url:
        print(f"  [{space_key}] SKIP — already exists: {existing_url}")
        return existing_url

    payload = {
        "type": "page",
        "title": new_title,
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": info["body_html"],
                "representation": "storage"
            }
        }
    }
    if info["parent_id"]:
        payload["ancestors"] = [{"id": str(info["parent_id"])}]

    result = api_post("content", payload, email, token)

    if "id" in result:
        tiny = result.get("_links", {}).get("tinyui", "")
        url = f"{CONFLUENCE_BASE}{tiny}" if tiny else f"{CONFLUENCE_BASE}/spaces/{space_key}/pages/{result['id']}"
        print(f"  [{space_key}] CREATED — {url}")
        return url
    else:
        error_msg = result.get("message", json.dumps(result))
        print(f"  [{space_key}] ERROR — {error_msg}")
        return None


def build_teams_message(results):
    """Build the Teams report message from clone results.

    results: list of (label, url_or_none) tuples
    """
    url_map = {label: url for label, url in results}

    def link(label):
        url = url_map.get(label)
        return url if url else "(not created)"

    lines = [
        "Report update:",
        f"- Core - Shared Platform: {link('Core - Shared Platform')}",
        "- B2C:",
        f"    - KinShield: {link('KinShield')}",
        f"    - KinSense: {link('KinSense')}",
        "- B2B:",
        f"    - SkyTrack: {link('SkyTrack')}",
        f"    - ShieldNet: {link('ShieldNet')}",
    ]
    return "\n".join(lines)


def copy_to_clipboard(text):
    """Copy text to macOS clipboard."""
    proc = subprocess.run(["pbcopy"], input=text.encode(), capture_output=True)
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    email, token = get_credentials()
    week_num, monday, friday = previous_week_info()

    print(f"Confluence Weekly Page Cloner")
    print(f"Previous week: W{week_num} ({monday.strftime('%d/%m')} - {friday.strftime('%d/%m/%Y')})")
    print(f"\nFetching template pages...")

    # Phase 1: Fetch all pages and show plan
    pages = []
    for page_id, space_key_hint, label in TEMPLATE_PAGES:
        info = fetch_page_info(page_id, email, token, week_num, monday, friday)
        info["label"] = label
        pages.append(info)

    print(f"\n{'='*60}")
    print(f"  PLAN: The following pages will be created:\n")
    for i, p in enumerate(pages, 1):
        print(f"  {i}. {p['new_title']}")
        print(f"     Space:  {p['space_key']}")
        print(f"     Parent: {p['parent_title']}")
    print(f"\n{'='*60}")

    # Phase 2: Ask for confirmation
    print(f"\nPress Enter to confirm, or Ctrl+C to cancel: ", end="", flush=True)
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    # Phase 3: Create pages
    print(f"\nCreating pages...\n")
    results = []
    for info in pages:
        url = create_page(info, email, token)
        results.append((info["label"], url))

    created = [(l, u) for l, u in results if u]
    print(f"\n{'='*60}")
    print(f"Done. {len(created)}/{len(pages)} pages created.")

    # Phase 4: Build message and copy to clipboard
    message = build_teams_message(results)
    print(f"\n{message}\n")

    if copy_to_clipboard(message):
        print("Copied to clipboard!")
    else:
        print("Failed to copy to clipboard — copy the message above manually.")


if __name__ == "__main__":
    main()
