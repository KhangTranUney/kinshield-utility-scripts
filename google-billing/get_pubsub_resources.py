#!/usr/bin/env python3
"""Export Pub/Sub topics and subscriptions for the ferrous-tine service account."""

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

SCRIPT_DIR = Path(__file__).resolve().parent
CREDENTIAL_FILE = SCRIPT_DIR / "credentials" / "service-account-ferrous-tine.json"
BASE_URL = "https://pubsub.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/pubsub"]


def list_resources(session: requests.Session, project_id: str, resource: str) -> list:
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
        page = data.get(resource, [])
        if not isinstance(page, list):
            raise ValueError(f"Invalid {resource} response")
        items.extend(page)
        token = data.get("nextPageToken")
        if not token:
            return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Output JSON path (defaults to reports with UTC timestamp).")
    args = parser.parse_args()
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIAL_FILE, scopes=SCOPES)
        if not credentials.project_id:
            raise ValueError("Service account credential has no project_id")
        credentials.refresh(google.auth.transport.requests.Request())
        with requests.Session() as session:
            session.headers.update({"Authorization": f"Bearer {credentials.token}", "Accept": "application/json"})
            topics = list_resources(session, credentials.project_id, "topics")
            subscriptions = list_resources(session, credentials.project_id, "subscriptions")
        topics.sort(key=lambda item: item.get("name", ""))
        subscriptions.sort(key=lambda item: item.get("name", ""))
        now = datetime.now(timezone.utc)
        report = {"fetchedAt": now.isoformat(), "projectId": credentials.project_id,
                  "serviceAccount": credentials.service_account_email,
                  "topics": topics, "subscriptions": subscriptions}
        output = args.output or SCRIPT_DIR / "reports" / f"pubsub-resources-{credentials.project_id}-{now:%Y%m%dT%H%M%SZ}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, requests.RequestException, google.auth.exceptions.GoogleAuthError) as exc:
        print(f"Failed to export Pub/Sub resources: {exc}", file=sys.stderr)
        return 1
    print(f"Project: {credentials.project_id}; topics: {len(topics)}; subscriptions: {len(subscriptions)}")
    print(f"Saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
