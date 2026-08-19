#!/usr/bin/env python3
"""Create Kinshield Google Play subscriptions from the fixed Kinshield YAML files.

This Kinshield-specific entry point selects one of the approved Android
configuration files, parses it through the shared normalization layer, and
sends the resulting subscriptions to Google Play.
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from post_subscriptions import InputError, absolute_file_path, post_subscriptions, usd_money


# Google Play's identifier rules. Validate them before an API request so YAML
# mistakes produce a precise local error.
PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{0,39}$")
BASE_PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
# Kinshield YAML plan names mapped to the ISO 8601 periods Google Play expects.
PERIODS = {"monthly": "P1M", "yearly": "P1Y", "annual": "P1Y"}
PRORATION_MODES = {
    "at next billing date": "SUBSCRIPTION_PRORATION_MODE_CHARGE_ON_NEXT_BILLING_DATE",
    "immediately": "SUBSCRIPTION_PRORATION_MODE_CHARGE_FULL_PRICE_IMMEDIATELY",
}
RESUBSCRIBE_STATES = {
    True: "RESUBSCRIBE_STATE_ACTIVE",
    False: "RESUBSCRIBE_STATE_INACTIVE",
}
# These are the only selectable configurations. Add another environment here
# when its Android YAML is ready; callers never enter arbitrary YAML paths.
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATHS = {
    "QA": SCRIPT_DIR / "configs" / "payment-config-kinshield-qa-android.yml",
    "PROD": SCRIPT_DIR / "configs" / "payment-config-kinshield-prod-android.yml",
}
# Credential location is intentionally fixed for the Kinshield workflow.
SERVICE_ACCOUNT_PATH = SCRIPT_DIR / "credentials" / "service-account-kinshield.json"


class ConfigError(ValueError):
    """Raised when a payment-config file cannot safely be used."""


def parse_args() -> argparse.Namespace:
    """Accept only runtime behavior flags; config and credentials are fixed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without Google Play requests.")
    return parser.parse_args()


def parse_kinshield_yaml(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Parse Kinshield Android YAML into the normalized posting-module format."""
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(document, dict) or not document:
        raise ConfigError("The YAML root must be a non-empty mapping of accounts.")

    # Remove the metadata key before treating the remaining keys as accounts.
    package_name = document.pop("package name", None)
    if not isinstance(package_name, str) or not PACKAGE_NAME_RE.fullmatch(package_name):
        raise ConfigError(f"package name must be a valid Android package name: {package_name!r}")

    subscriptions: list[dict[str, Any]] = []
    # IDs must be globally unique within this input batch. Detecting duplicates
    # here prevents a partially-created set of subscriptions in Google Play.
    product_ids: set[str] = set()
    base_plan_ids: set[str] = set()
    for account, tiers in document.items():
        if not isinstance(account, str) or not isinstance(tiers, dict):
            raise ConfigError("Each account must contain a mapping of subscription tiers.")
        for tier, subscription in tiers.items():
            context = f"{account}/{tier}"
            if not isinstance(tier, str) or not isinstance(subscription, dict):
                raise ConfigError(f"{context}: expected a mapping.")
            product_id = subscription.get("subscription id")
            if not isinstance(product_id, str) or not PRODUCT_ID_RE.fullmatch(product_id):
                raise ConfigError(f"{context}: invalid subscription id: {product_id!r}")
            if product_id in product_ids:
                raise ConfigError(f"Duplicate subscription id: {product_id}")
            product_ids.add(product_id)

            title = subscription.get("subscription name") or f"{account} {tier}".title()
            if not isinstance(title, str) or not title.strip():
                raise ConfigError(f"{context}: subscription name must be a non-empty string.")
            plans = subscription.get("plan")
            if not isinstance(plans, dict) or not plans:
                raise ConfigError(f"{context}: plan must be a non-empty mapping.")

            base_plans = []
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
                # Translate friendly YAML values to the exact Google API enums.
                charge_timing = plan.get("android charge")
                if charge_timing not in PRORATION_MODES:
                    valid_values = ", ".join(repr(value) for value in PRORATION_MODES)
                    raise ConfigError(f"{plan_context}: android charge must be one of: {valid_values}.")
                resubscribe = plan.get("android resubscribe")
                if not isinstance(resubscribe, bool):
                    raise ConfigError(f"{plan_context}: android resubscribe must be true or false.")
                # This normalized dictionary is the contract with
                # post_subscriptions.py. Future app-specific parsers should
                # create the same shape, even if their YAML looks different.
                base_plans.append(
                    {
                        "basePlanId": base_plan_id,
                        "billingPeriodDuration": PERIODS[plan_name],
                        "prorationMode": PRORATION_MODES[charge_timing],
                        "resubscribeState": RESUBSCRIBE_STATES[resubscribe],
                        "sourceUsdPrice": usd_money(price),
                        "name": plan.get("name") or base_plan_id,
                    }
                )
            subscriptions.append(
                {
                    "productId": product_id,
                    "listing": {
                        "languageCode": "en-US",
                        "title": title[:55],
                        "description": f"{title} subscription."[:200],
                    },
                    "basePlans": base_plans,
                }
            )
    return package_name, subscriptions


def selected_config_path() -> Path:
    """Prompt for the fixed Kinshield QA or production configuration."""
    print("Choose Kinshield environment:")
    print("  1. QA")
    print("  2. PROD")
    try:
        selection = input("Enter 1 or 2: ").strip()
    except EOFError as exc:
        raise ConfigError("No environment was selected.") from exc
    # Accept either the displayed number or the environment name.
    environments = {"1": "QA", "2": "PROD", "qa": "QA", "prod": "PROD"}
    environment = environments.get(selection.lower())
    if environment is None:
        raise ConfigError("Environment must be QA/1 or PROD/2.")
    return CONFIG_PATHS[environment]


def main() -> int:
    args = parse_args()
    try:
        # Select and parse the app-specific input, then hand only normalized
        # data to the shared Google Play posting module.
        config_path = selected_config_path()
        package_name, subscriptions = parse_kinshield_yaml(config_path)
        service_account_path = absolute_file_path(
            SERVICE_ACCOUNT_PATH, "Kinshield service-account JSON"
        )
    except (ConfigError, InputError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2
    return post_subscriptions(
        package_name,
        subscriptions,
        service_account_path,
        dry_run=args.dry_run,
        source=str(config_path),
    )


if __name__ == "__main__":
    sys.exit(main())
