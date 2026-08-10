#!/usr/bin/env python3
"""Post parsed subscriptions to Google Play.

This module deliberately has no YAML parsing or YAML-layout knowledge. App
scripts parse their own configuration and call :func:`post_subscriptions`.
"""

from __future__ import annotations

import json
import sys
import termios
import tty
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import google.auth.transport.requests
import requests
from google.oauth2 import service_account


SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "reports"
BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
TIMEOUT_SECONDS = 30


class InputError(ValueError):
    """Raised when normalized creator input is invalid."""


def usd_money(value: Decimal) -> dict[str, Any]:
    """Format a non-negative Decimal as the Google Play API Money representation."""
    nanos_per_unit = Decimal("1000000000")
    units = int(value // 1)
    nanos = int((value - Decimal(units)) * nanos_per_unit)
    return {"currencyCode": "USD", "units": str(units), "nanos": nanos}


def absolute_file_path(value: Path, label: str) -> Path:
    if not value.is_absolute():
        raise InputError(f"{label} must be an absolute path: {value}")
    if not value.is_file():
        raise InputError(f"{label} does not exist or is not a file: {value}")
    return value


def money_to_decimal(value: Any, context: str) -> Decimal:
    if not isinstance(value, dict) or value.get("currencyCode") != "USD":
        raise InputError(f"{context}: sourceUsdPrice must be a USD Money object.")
    try:
        units = Decimal(str(value["units"]))
        nanos = Decimal(str(value.get("nanos", 0)))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise InputError(f"{context}: invalid sourceUsdPrice.") from exc
    if (
        units != units.to_integral_value()
        or nanos != nanos.to_integral_value()
        or not 0 <= nanos < 1_000_000_000
    ):
        raise InputError(f"{context}: invalid sourceUsdPrice.")
    price = units + nanos / Decimal("1000000000")
    if price <= 0:
        raise InputError(f"{context}: sourceUsdPrice must be positive.")
    return price


def credentials_headers(service_account_file: Path) -> dict[str, str]:
    credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    credentials.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}


def request_json(
    method: str, url: str, headers: dict[str, str], **kwargs: Any
) -> tuple[int, dict[str, Any]]:
    response = requests.request(method, url, headers=headers, timeout=TIMEOUT_SECONDS, **kwargs)
    try:
        body = response.json()
    except ValueError:
        body = {"raw_response": response.text}
    return response.status_code, body


def subscription_exists(package_name: str, product_id: str, headers: dict[str, str]) -> bool:
    status, body = request_json("GET", f"{BASE_URL}/applications/{package_name}/subscriptions/{product_id}", headers)
    if status == 200:
        return True
    if status == 404:
        return False
    raise RuntimeError(f"Could not check {product_id}: HTTP {status}: {json.dumps(body)}")


def converted_pricing(
    package_name: str, price: Decimal, headers: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    status, body = request_json(
        "POST",
        f"{BASE_URL}/applications/{package_name}/pricing:convertRegionPrices",
        headers,
        json={"price": usd_money(price)},
    )
    if status != 200:
        raise RuntimeError(f"Could not convert USD {price} price: HTTP {status}: {json.dumps(body)}")
    regional_configs = []
    for region_code, converted in body.get("convertedRegionPrices", {}).items():
        if not converted.get("price"):
            raise RuntimeError(f"Google returned no price for region {region_code}.")
        regional_configs.append(
            {
                "regionCode": region_code,
                "newSubscriberAvailability": True,
                "price": converted["price"],
            }
        )
    other_regions, region_version = body.get("convertedOtherRegionsPrice"), body.get("regionVersion")
    if not regional_configs or not other_regions or not region_version:
        raise RuntimeError("Google returned incomplete converted regional pricing.")
    return regional_configs, {**other_regions, "newSubscriberAvailability": True}, region_version


def build_apply_payload(
    package_name: str, subscription: dict[str, Any], headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_plans, regions_version = [], None
    for plan in subscription["basePlans"]:
        regional_configs, other_regions, current_version = converted_pricing(
            package_name,
            money_to_decimal(plan["sourceUsdPrice"], plan["basePlanId"]),
            headers,
        )
        if regions_version and current_version != regions_version:
            raise RuntimeError("Google returned different region versions while preparing one subscription.")
        regions_version = current_version
        base_plans.append(
            {
                "basePlanId": plan["basePlanId"],
                "regionalConfigs": regional_configs,
                "otherRegionsConfig": other_regions,
                "autoRenewingBasePlanType": {
                    "billingPeriodDuration": plan["billingPeriodDuration"],
                    "prorationMode": plan["prorationMode"],
                    "resubscribeState": plan["resubscribeState"],
                },
            }
        )
    return (
        {
            "packageName": package_name,
            "productId": subscription["productId"],
            "listings": [subscription["listing"]],
            "basePlans": base_plans,
        },
        regions_version,
    )


def create_subscription(package_name: str, subscription: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    payload, regions_version = build_apply_payload(package_name, subscription, headers)
    status, body = request_json(
        "POST",
        f"{BASE_URL}/applications/{package_name}/subscriptions",
        headers,
        params={
            "productId": subscription["productId"],
            "regionsVersion.version": regions_version["version"],
        },
        json=payload,
    )
    if status not in (200, 201):
        raise RuntimeError(f"Create failed: HTTP {status}: {json.dumps(body)}")
    return body


def write_report(report: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"create-subscriptions-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path


def print_creation_plan(package_name: str, subscriptions: list[dict[str, Any]]) -> None:
    print(
        f"\nCreation plan for {package_name}\n"
        "All subscriptions and base plans will be created in DRAFT state."
    )
    for subscription in subscriptions:
        print(f"\n- Subscription: {subscription['listing']['title']} ({subscription['productId']})")
        for plan in subscription["basePlans"]:
            price = money_to_decimal(plan["sourceUsdPrice"], plan["basePlanId"])
            resubscribe = "resubscribe enabled" if plan["resubscribeState"].endswith("ACTIVE") else "resubscribe disabled"
            print(
                f"  - {plan.get('name', plan['basePlanId'])}: {plan['basePlanId']} | "
                f"{plan['billingPeriodDuration']} | USD {price:.2f} | {resubscribe}"
            )


def confirm_creation() -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("Creation requires an interactive terminal confirmation (Enter or Esc).")
    print("\nPress Enter to create these DRAFT subscriptions, or Esc to cancel: ", end="", flush=True)
    fd = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(fd)
    confirmed = False
    try:
        tty.setraw(fd)
        while True:
            key = sys.stdin.read(1)
            if key in ("\r", "\n"):
                confirmed = True
                break
            if key == "\x1b":
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous_settings)
    print("\nConfirmed." if confirmed else "\nCancelled. No Google Play changes were made.")
    return confirmed


def post_subscriptions(
    package_name: str,
    subscriptions: list[dict[str, Any]],
    service_account_path: Path | None,
    *,
    dry_run: bool,
    source: str,
) -> int:
    """Create parsed subscriptions, or preview them when ``dry_run`` is true."""
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry-run" if dry_run else "apply",
        "packageName": package_name,
        "source": source,
        "created": [],
        "skippedExisting": [],
        "failures": [],
        "planned": subscriptions,
    }
    if dry_run:
        print("DRY RUN: no Google Play requests will be made. Omit --dry-run to create DRAFT subscriptions.")
        print(json.dumps(subscriptions, indent=2))
        print(f"Report: {write_report(report)}")
        return 0
    if service_account_path is None:
        raise InputError("A service-account file is required unless --dry-run.")
    print_creation_plan(package_name, subscriptions)
    try:
        if not confirm_creation():
            report["cancelled"] = True
            print(f"Report: {write_report(report)}")
            return 0
        headers = credentials_headers(service_account_path)
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    for subscription in subscriptions:
        product_id = subscription["productId"]
        try:
            if subscription_exists(package_name, product_id, headers):
                report["skippedExisting"].append(product_id)
                print(f"SKIP existing: {product_id}")
            else:
                create_subscription(package_name, subscription, headers)
                report["created"].append(product_id)
                print(f"CREATED DRAFT: {product_id}")
        except Exception as exc:
            report["failures"].append({"productId": product_id, "error": str(exc)})
            print(f"FAILED {product_id}: {exc}", file=sys.stderr)
    print(f"Summary: created={len(report['created'])}, skipped={len(report['skippedExisting'])}, failed={len(report['failures'])}")
    print(f"Report: {write_report(report)}")
    return 1 if report["failures"] else 0
