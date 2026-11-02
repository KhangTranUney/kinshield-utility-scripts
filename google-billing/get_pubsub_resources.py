#!/usr/bin/env python3
"""Export Pub/Sub topics and subscriptions for the ferrous-tine service account.

Steps:
1. Read the service account credentials and obtain an access token.
2. Fetch all pages of topics and subscriptions in the credential's project.
3. Keep resources whose names contain any value in NAME_FILTERS, ignoring case,
   and sort them.
4. Write the results and fetch metadata to a JSON report.
5. Print the filtered counts and the report location.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import google.auth.transport.requests
import requests
from google.oauth2 import service_account

# Resolve paths relative to this script so it can be run from any directory.
SCRIPT_DIR = Path(__file__).resolve().parent
CREDENTIAL_FILE = SCRIPT_DIR / "credentials" / "service-account-ferrous-tine.json"
BASE_URL = "https://pubsub.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/pubsub"]
# Keep resources whose names contain any of these values, ignoring case.
# Edit this list to change the exported topics and subscriptions.
NAME_FILTERS = ["pyffe", "strazee"]


def list_resources(session: requests.Session, project_id: str, resource: str) -> list:
    # Pub/Sub returns results in pages; collect every page before filtering.
    url = f"{BASE_URL}/projects/{quote(project_id, safe='')}/{resource}"
    items = []
    token = None
    while True:
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        response = session.get(url, params=params, timeout=30)
        if not response.ok:
            raise ValueError(f"{resource} request failed (HTTP {response.status_code}): {response.text}")
        data = response.json()
        # The response field is named after the requested resource type.
        page = data.get(resource, [])
        if not isinstance(page, list):
            raise ValueError(f"Invalid {resource} response")
        items.extend(page)
        token = data.get("nextPageToken")
        if not token:
            return items


def main() -> int:
    # Allow callers to override the default timestamped report path.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output JSON path (defaults to reports with UTC timestamp).")
    args = parser.parse_args()
    try:
        # Authenticate with the configured service account and use its project.
        credentials = service_account.Credentials.from_service_account_file(CREDENTIAL_FILE, scopes=SCOPES)
        if not credentials.project_id:
            raise ValueError("Service account credential has no project_id")
        credentials.refresh(google.auth.transport.requests.Request())
        # Reuse the access token and HTTP session for both resource types.
        with requests.Session() as session:
            session.headers.update({"Authorization": f"Bearer {credentials.token}", "Accept": "application/json"})
            topics = list_resources(session, credentials.project_id, "topics")
            subscriptions = list_resources(session, credentials.project_id, "subscriptions")
        # Match each resource's own name, then sort for predictable output.
        topics = [item for item in topics if any(value.lower() in item.get("name", "").lower() for value in NAME_FILTERS)]
        subscriptions = [item for item in subscriptions if any(value.lower() in item.get("name", "").lower() for value in NAME_FILTERS)]
        topics.sort(key=lambda item: item.get("name", ""))
        subscriptions.sort(key=lambda item: item.get("name", ""))
        # Record when and where the resources were fetched, alongside their data.
        now = datetime.now(timezone.utc)
        report = {"fetchedAt": now.isoformat(), "projectId": credentials.project_id,
                  "serviceAccount": credentials.service_account_email,
                  "topics": topics, "subscriptions": subscriptions}
        # Create the report directory if necessary and write readable JSON.
        output = args.output or SCRIPT_DIR / "reports" / f"pubsub-resources-{credentials.project_id}-{now:%Y%m%dT%H%M%SZ}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Report expected authentication, network, data, and file errors to the caller.
    except (OSError, ValueError, requests.RequestException, google.auth.exceptions.GoogleAuthError) as exc:
        print(f"Failed to export Pub/Sub resources: {exc}", file=sys.stderr)
        return 1
    # Display the filtered counts and report location for interactive use.
    print(f"Project: {credentials.project_id}; topics: {len(topics)}; subscriptions: {len(subscriptions)}")
    print(f"Saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
