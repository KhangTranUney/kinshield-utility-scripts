#!/usr/bin/env python3
"""Create Google Play subscriptions from a payment-config YAML file.

The command creates subscriptions and auto-renewing base plans in DRAFT state
by default. Use --dry-run to preview the work without contacting Google Play.
This script never activates a base plan or changes an existing subscription.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import termios
import tty
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import google.auth.transport.requests
import requests
import yaml
from google.oauth2 import service_account


SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_DIR = SCRIPT_DIR / "reports"
BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
TIMEOUT_SECONDS = 30

PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{0,39}$")
BASE_PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
PERIODS = {"monthly": "P1M", "yearly": "P1Y", "annual": "P1Y"}
PRORATION_MODES = {
    "at next billing date": "SUBSCRIPTION_PRORATION_MODE_CHARGE_ON_NEXT_BILLING_DATE",
    "immediately": "SUBSCRIPTION_PRORATION_MODE_CHARGE_FULL_PRICE_IMMEDIATELY",
}


class ConfigError(ValueError):
    """Raised when a payment-config file cannot safely be used."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Absolute path to payment-config YAML. Prompts when omitted.",
    )
    parser.add_argument(
        "--service-account-file",
        type=Path,
        help="Absolute path to the service-account JSON. Prompts when omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned subscriptions without making Google Play requests.",
    )
    return parser.parse_args()


def absolute_file_path(value: Path, label: str) -> Path:
    """Validate a user-supplied absolute path to a regular file."""
    if not value.is_absolute():
        raise ConfigError(f"{label} must be an absolute path: {value}")
    if not value.is_file():
        raise ConfigError(f"{label} does not exist or is not a file: {value}")
    return value


def requested_file_path(value: Path | None, label: str) -> Path:
    if value is None:
        try:
            raw_value = input(f"Enter the absolute path to the {label}: ").strip()
        except EOFError as exc:
            raise ConfigError(f"No {label} path was provided.") from exc
        value = Path(raw_value)
    return absolute_file_path(value, label)


def usd_money(value: Decimal) -> dict[str, Any]:
    """Format a non-negative Decimal as the API Money representation."""
    nanos_per_unit = Decimal("1000000000")
    units = int(value // 1)
    nanos = int((value - Decimal(units)) * nanos_per_unit)
    return {"currencyCode": "USD", "units": str(units), "nanos": nanos}


def load_config(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(document, dict) or not document:
        raise ConfigError("The YAML root must be a non-empty mapping of families.")

    package_name = document.pop("package name", None)
    if not isinstance(package_name, str) or not PACKAGE_NAME_RE.fullmatch(package_name):
        raise ConfigError(f"package name must be a valid Android package name: {package_name!r}")

    subscriptions: list[dict[str, Any]] = []
    product_ids: set[str] = set()
    base_plan_ids: set[str] = set()

    for family, tiers in document.items():
        if not isinstance(family, str) or not isinstance(tiers, dict):
            raise ConfigError("Each family must contain a mapping of subscription tiers.")
        for tier, subscription in tiers.items():
            context = f"{family}/{tier}"
            if not isinstance(tier, str) or not isinstance(subscription, dict):
                raise ConfigError(f"{context}: expected a mapping.")

            product_id = subscription.get("subscription id")
            if not isinstance(product_id, str) or not PRODUCT_ID_RE.fullmatch(product_id):
                raise ConfigError(f"{context}: invalid subscription id: {product_id!r}")
            if product_id in product_ids:
                raise ConfigError(f"Duplicate subscription id: {product_id}")
            product_ids.add(product_id)

            subscription_name = subscription.get("subscription name")
            if subscription_name is not None and (
                not isinstance(subscription_name, str) or not subscription_name.strip()
            ):
                raise ConfigError(f"{context}: subscription name must be a non-empty string.")

            plans = subscription.get("plan")
            if not isinstance(plans, dict) or not plans:
                raise ConfigError(f"{context}: plan must be a non-empty mapping.")

            normalized_plans = []
            for plan_name, plan in plans.items():
                plan_context = f"{context}/{plan_name}"
                if plan_name not in PERIODS or not isinstance(plan, dict):
                    raise ConfigError(
                        f"{plan_context}: only monthly, yearly, and annual plan mappings are supported."
                    )
                base_plan_id = plan.get("android id")
                if not isinstance(base_plan_id, str) or not BASE_PLAN_ID_RE.fullmatch(base_plan_id):
                    raise ConfigError(f"{plan_context}: invalid android id: {base_plan_id!r}")
                if base_plan_id in base_plan_ids:
                    raise ConfigError(f"Duplicate android id: {base_plan_id}")
                base_plan_ids.add(base_plan_id)

                try:
                    price = Decimal(str(plan.get("price")))
                except (InvalidOperation, ValueError) as exc:
                    raise ConfigError(f"{plan_context}: price must be a positive USD amount.") from exc
                if not price.is_finite() or price <= 0 or price.as_tuple().exponent < -9:
                    raise ConfigError(f"{plan_context}: invalid USD price: {price}")

                charge_timing = plan.get("android charge")
                if charge_timing not in PRORATION_MODES:
                    valid_values = ", ".join(repr(value) for value in PRORATION_MODES)
                    raise ConfigError(
                        f"{plan_context}: android charge must be one of: {valid_values}."
                    )
                plan_display_name = plan.get("name")
                if plan_display_name is not None and (
                    not isinstance(plan_display_name, str) or not plan_display_name.strip()
                ):
                    raise ConfigError(f"{plan_context}: name must be a non-empty string.")

                normalized_plans.append(
                    {
                        "name": plan_name,
                        "base_plan_id": base_plan_id,
                        "billing_period": PERIODS[plan_name],
                        "price": price,
                        "proration_mode": PRORATION_MODES[charge_timing],
                        "name": plan_display_name,
                    }
                )

            subscriptions.append(
                {
                    "family": family,
                    "tier": tier,
                    "product_id": product_id,
                    "name": subscription_name,
                    "plans": normalized_plans,
                }
            )
    return package_name, subscriptions


def listing_for(subscription: dict[str, Any]) -> dict[str, Any]:
    title = subscription.get("name") or f"{subscription['family']} {subscription['tier']}".title()
    return {
        "languageCode": "en-US",
        "title": title[:55],
        "description": f"{title} subscription."[:200],
    }


def payload_template(package_name: str, subscription: dict[str, Any]) -> dict[str, Any]:
    """Create the payload shape shown in dry run; regional prices are added on apply."""
    return {
        "packageName": package_name,
        "productId": subscription["product_id"],
        "listings": [listing_for(subscription)],
        "basePlans": [
            {
                "basePlanId": plan["base_plan_id"],
                "autoRenewingBasePlanType": {
                    "billingPeriodDuration": plan["billing_period"],
                    "prorationMode": plan["proration_mode"],
                },
                "sourceUsdPrice": usd_money(plan["price"]),
                "sourcePlanName": plan["name"],
                "stateNote": "Created by Google Play as DRAFT; this script never activates it.",
            }
            for plan in subscription["plans"]
        ],
    }


def credentials_headers(service_account_file: Path) -> dict[str, str]:
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
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
    url = f"{BASE_URL}/applications/{package_name}/subscriptions/{product_id}"
    status, body = request_json("GET", url, headers)
    if status == 200:
        return True
    if status == 404:
        return False
    raise RuntimeError(f"Could not check {product_id}: HTTP {status}: {json.dumps(body)}")


def converted_pricing(
    package_name: str, price: Decimal, headers: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    url = f"{BASE_URL}/applications/{package_name}/pricing:convertRegionPrices"
    status, body = request_json("POST", url, headers, json={"price": usd_money(price)})
    if status != 200:
        raise RuntimeError(f"Could not convert USD {price} price: HTTP {status}: {json.dumps(body)}")

    regional_configs = []
    for region_code, converted in body.get("convertedRegionPrices", {}).items():
        region_price = converted.get("price")
        if not region_price:
            raise RuntimeError(f"Google returned no price for region {region_code}.")
        regional_configs.append(
            {"regionCode": region_code, "newSubscriberAvailability": True, "price": region_price}
        )
    other_regions = body.get("convertedOtherRegionsPrice")
    region_version = body.get("regionVersion")
    if not regional_configs or not other_regions or not region_version:
        raise RuntimeError("Google returned incomplete converted regional pricing.")
    return regional_configs, {**other_regions, "newSubscriberAvailability": True}, region_version


def build_apply_payload(
    package_name: str, subscription: dict[str, Any], headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_plans = []
    regions_version = None
    for plan in subscription["plans"]:
        regional_configs, other_regions, current_version = converted_pricing(
            package_name, plan["price"], headers
        )
        if regions_version and current_version != regions_version:
            raise RuntimeError("Google returned different region versions while preparing one subscription.")
        regions_version = current_version
        base_plans.append(
            {
                "basePlanId": plan["base_plan_id"],
                "regionalConfigs": regional_configs,
                "otherRegionsConfig": other_regions,
                "autoRenewingBasePlanType": {
                    "billingPeriodDuration": plan["billing_period"],
                    "prorationMode": plan["proration_mode"],
                },
            }
        )
    return (
        {
            "packageName": package_name,
            "productId": subscription["product_id"],
            "listings": [listing_for(subscription)],
            "basePlans": base_plans,
        },
        regions_version,
    )


def create_subscription(
    package_name: str, subscription: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    payload, regions_version = build_apply_payload(package_name, subscription, headers)
    url = f"{BASE_URL}/applications/{package_name}/subscriptions"
    status, body = request_json(
        "POST", url, headers, params={"productId": subscription["product_id"], "regionsVersion.version": regions_version["version"]}, json=payload
    )
    if status not in (200, 201):
        raise RuntimeError(f"Create failed: HTTP {status}: {json.dumps(body)}")
    return body


def write_report(report: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_DIR / f"create-subscriptions-{timestamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return path


def print_creation_plan(package_name: str, subscriptions: list[dict[str, Any]]) -> None:
    print(f"\nCreation plan for {package_name}")
    print("All subscriptions and base plans will be created in DRAFT state.")
    for subscription in subscriptions:
        name = subscription.get("name") or subscription["product_id"]
        print(f"\n- Subscription: {name} ({subscription['product_id']})")
        for plan in subscription["plans"]:
            price = f"USD {plan['price']:.2f}"
            timing = (
                "charge immediately"
                if plan["proration_mode"].endswith("IMMEDIATELY")
                else "charge at next billing date"
            )
            plan_name = plan.get("name") or plan["base_plan_id"]
            print(
                f"  - {plan_name}: {plan['base_plan_id']} | {plan['billing_period']} | "
                f"{price} | {timing}"
            )


def confirm_creation() -> bool:
    """Return True only when the user presses Enter; Esc cancels creation."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("Creation requires an interactive terminal confirmation (Enter or Esc).")

    print("\nPress Enter to create these DRAFT subscriptions, or Esc to cancel: ", end="", flush=True)
    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        while True:
            key = sys.stdin.read(1)
            if key in ("\r", "\n"):
                print("\nConfirmed.")
                return True
            if key == "\x1b":
                print("\nCancelled. No Google Play changes were made.")
                return False
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, previous_settings)


def main() -> int:
    args = parse_args()
    try:
        config_path = requested_file_path(args.config, "payment configuration YAML")
        service_account_path = requested_file_path(
            args.service_account_file, "service-account JSON"
        )
        package_name, subscriptions = load_config(config_path)
    except ConfigError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry-run" if args.dry_run else "apply",
        "packageName": package_name,
        "config": str(config_path),
        "created": [],
        "skippedExisting": [],
        "failures": [],
        "planned": [payload_template(package_name, subscription) for subscription in subscriptions],
    }

    if args.dry_run:
        print("DRY RUN: no Google Play requests will be made. Omit --dry-run to create DRAFT subscriptions.")
        print(json.dumps(report["planned"], indent=2))
        report_path = write_report(report)
        print(f"Report: {report_path}")
        return 0

    print_creation_plan(package_name, subscriptions)
    try:
        if not confirm_creation():
            report["cancelled"] = True
            report_path = write_report(report)
            print(f"Report: {report_path}")
            return 0
    except RuntimeError as exc:
        print(f"Confirmation failed: {exc}", file=sys.stderr)
        return 1

    try:
        headers = credentials_headers(service_account_path)
    except Exception as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1

    for subscription in subscriptions:
        product_id = subscription["product_id"]
        try:
            if subscription_exists(package_name, product_id, headers):
                report["skippedExisting"].append(product_id)
                print(f"SKIP existing: {product_id}")
                continue
            create_subscription(package_name, subscription, headers)
            report["created"].append(product_id)
            print(f"CREATED DRAFT: {product_id}")
        except Exception as exc:
            report["failures"].append({"productId": product_id, "error": str(exc)})
            print(f"FAILED {product_id}: {exc}", file=sys.stderr)

    report_path = write_report(report)
    print(f"Summary: created={len(report['created'])}, skipped={len(report['skippedExisting'])}, failed={len(report['failures'])}")
    print(f"Report: {report_path}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
