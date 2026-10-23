#!/usr/bin/env python3
"""Fetch all Google Play subscriptions over the REST API.

Examples:
    python google-billing/get_google_product_list.py
    python google-billing/get_google_product_list.py --output /tmp/catalog.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import google.auth.transport.requests
import requests
from google.oauth2 import service_account


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helper.interactive_input import InputCancelled, read_input


# Flow: select product/environment -> authenticate the service account -> fetch all
# subscription pages -> write full JSON and print a summary. Google Play access is read-only.
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
PAGE_SIZE = 1000
TIMEOUT_SECONDS = 30


class CatalogError(RuntimeError):
    """Raised when authentication or a catalog request fails."""


class CatalogCancelled(CatalogError):
    """Raised when the user cancels interactive selection."""


@dataclass(frozen=True)
class Target:
    display_name: str
    product_key: str
    environment: str
    package_name: str
    credential_file: Path


PROJECTS = {
    "pyffe": {
        "display_name": "Pyffe",
        "packages": {"prod": "com.pyffe", "non-prod": "com.pyffe.qa"},
        "credential": SCRIPT_DIR / "credentials" / "service-account-pyffe.json",
    },
    "strazee": {
        "display_name": "Strazee",
        "packages": {"prod": "com.strazee", "non-prod": "com.strazee.qa"},
        "credential": SCRIPT_DIR / "credentials" / "service-account-strazee.json",
    },
    "kinsense": {
        "display_name": "KinSense",
        "packages": {"prod": "com.kinsense", "non-prod": "com.kinsense.qa"},
        "credential": SCRIPT_DIR / "credentials" / "service-account-kinsense.json",
    },
    "kinshield": {
        "display_name": "KinShield",
        "packages": {"prod": "com.kinshield", "non-prod": "com.kinshield.qa"},
        "credential": SCRIPT_DIR / "credentials" / "service-account-kinshield.json",
    },
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output path. Defaults to google-billing/reports with a UTC timestamp.",
    )
    return parser.parse_args()


def prompt_choice(prompt: str, choices: dict[str, tuple[str, str]]) -> str:
    choice_labels = " or ".join(choices)
    print(prompt)
    for key, (_, label) in choices.items():
        print(f"  {key}. {label}")
    print("  Press Esc to cancel.")
    try:
        value = read_input(f"Enter {choice_labels}, then press Enter: ").strip().lower()
    except InputCancelled as exc:
        raise CatalogCancelled("Selection cancelled.") from exc
    except EOFError as exc:
        raise CatalogError("No selection was provided. Use the numbered menu in an interactive terminal.") from exc
    if value == "\x1b":
        raise CatalogCancelled("Selection cancelled.")
    if value in choices:
        return choices[value][0]
    raise CatalogError(f"Invalid selection: {value!r}. Choose {choice_labels}.")


def select_target() -> Target:
    # Resolve the selected prod/QA package and its credentials from PROJECTS.
    product_key = prompt_choice(
        "Choose the Google Play product:",
        {"1": ("pyffe", "Pyffe"), "2": ("strazee", "Strazee"), "3": ("kinsense", "KinSense"), "4": ("kinshield", "KinShield")},
    )
    environment = prompt_choice(
        "Choose the environment:",
        {"1": ("prod", "prod"), "2": ("non-prod", "non-prod (QA)")},
    )
    project = PROJECTS[product_key]
    return Target(
        display_name=project["display_name"],
        product_key=product_key,
        environment=environment,
        package_name=project["packages"][environment],
        credential_file=project["credential"],
    )


def authenticate(credential_file: Path) -> tuple[dict[str, str], str]:
    if not credential_file.is_file():
        raise CatalogError(f"Credential file does not exist: {credential_file}")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            credential_file, scopes=SCOPES
        )
        credentials.refresh(google.auth.transport.requests.Request())
    except Exception as exc:  # Google auth exposes several exception types.
        raise CatalogError(f"Could not authenticate with {credential_file.name}: {exc}") from exc
    return (
        {
            "Authorization": f"Bearer {credentials.token}",
            "Accept": "application/json",
        },
        credentials.service_account_email,
    )


def response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": response.text}
    return payload if isinstance(payload, dict) else {"response": payload}


def request_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, str | int],
    resource_name: str,
) -> dict[str, Any]:
    try:
        response = session.get(url, headers=headers, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise CatalogError(f"{resource_name} request failed: {exc}") from exc
    payload = response_json(response)
    if response.status_code != 200:
        detail = json.dumps(payload, ensure_ascii=False)
        raise CatalogError(f"{resource_name} request failed with HTTP {response.status_code}: {detail}")
    return payload


def list_page_paginated(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    response_key: str,
    resource_name: str,
) -> list[dict[str, Any]]:
    """List a current monetization resource using pageSize/pageToken."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    # Accumulate results until nextPageToken is absent; any page failure aborts the export.
    while True:
        params: dict[str, str | int] = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        payload = request_page(session, url, headers, params, resource_name)
        page_items = payload.get(response_key, [])
        if not isinstance(page_items, list):
            raise CatalogError(f"{resource_name} returned an invalid {response_key} field.")
        items.extend(item for item in page_items if isinstance(item, dict))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items


def title_from_listings(product: dict[str, Any]) -> str:
    # Prefer en-US, then the first listing; support both list and dictionary schemas.
    listings = product.get("listings")
    if isinstance(listings, list):
        preferred = next((item for item in listings if item.get("languageCode") == "en-US"), None)
        listing = preferred or (listings[0] if listings else {})
    elif isinstance(listings, dict):
        listing = listings.get("en-US") or next(iter(listings.values()), {})
    else:
        listing = {}
    return listing.get("title", "Untitled") if isinstance(listing, dict) else "Untitled"


def default_output(target: Target) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return SCRIPT_DIR / "reports" / f"google-product-catalog-{target.product_key}-{target.environment}-{timestamp}.json"


def fetch_catalog(target: Target) -> tuple[dict[str, Any], str]:
    headers, service_account_email = authenticate(target.credential_file)
    package_path = quote(target.package_name, safe="")
    application_url = f"{BASE_URL}/applications/{package_path}"

    with requests.Session() as session:
        subscriptions = list_page_paginated(
            session,
            f"{application_url}/subscriptions",
            headers,
            "subscriptions",
            "Subscriptions",
        )

    return (
        {
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "product": target.display_name,
            "environment": target.environment,
            "packageName": target.package_name,
            "serviceAccount": service_account_email,
            "subscriptions": subscriptions,
        },
        service_account_email,
    )


def print_summary(catalog: dict[str, Any]) -> None:
    subscriptions = catalog["subscriptions"]
    print(f"Found {len(subscriptions)} subscriptions.")
    for subscription in subscriptions:
        print(f"- {subscription.get('productId', 'UNKNOWN')} | {title_from_listings(subscription)}")


def main() -> int:
    args = parse_args()
    try:
        target = select_target()
        output_path = args.output or default_output(target)
        catalog, _ = fetch_catalog(target)
        # Write only after all pages are fetched; --output overwrites an existing destination.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except CatalogCancelled:
        print("Cancelled. No Google Play requests were made.")
        return 0
    except (CatalogError, OSError) as exc:
        print(f"Failed to fetch Google Play products: {exc}", file=sys.stderr)
        return 1

    print(f"Fetched {catalog['product']} {catalog['environment']} ({catalog['packageName']}).")
    print_summary(catalog)
    print(f"Full JSON saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
