#!/usr/bin/env python3
"""Create Google Play subscriptions for KinSense or KinShield.

Choose the product and environment interactively. The existing QA Android
configuration is used for the non-production environment.
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from _post_subscriptions import InputError, absolute_file_path, post_subscriptions, usd_money


PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{0,39}$")
BASE_PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
PERIODS = {"monthly": "P1M", "yearly": "P1Y", "annual": "P1Y"}
PRORATION_MODES = {
    "at next billing date": "SUBSCRIPTION_PRORATION_MODE_CHARGE_ON_NEXT_BILLING_DATE",
    "immediately": "SUBSCRIPTION_PRORATION_MODE_CHARGE_FULL_PRICE_IMMEDIATELY",
}
RESUBSCRIBE_STATES = {True: "RESUBSCRIBE_STATE_ACTIVE", False: "RESUBSCRIBE_STATE_INACTIVE"}

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECTS = {
    "1": (
        "KinSense",
        {
            "prod": (SCRIPT_DIR / "configs" / "payment-config-kinsense-prod-android.yml", SCRIPT_DIR / "credentials" / "service-account-kinsense.json"),
            "non-prod": (SCRIPT_DIR / "configs" / "payment-config-kinsense-qa-android.yml", SCRIPT_DIR / "credentials" / "service-account-kinsense.json"),
        },
    ),
    "2": (
        "KinShield",
        {
            "prod": (SCRIPT_DIR / "configs" / "payment-config-kinshield-prod-android.yml", SCRIPT_DIR / "credentials" / "service-account-kinshield.json"),
            "non-prod": (SCRIPT_DIR / "configs" / "payment-config-kinshield-qa-android.yml", SCRIPT_DIR / "credentials" / "service-account-kinshield.json"),
        },
    ),
}


class ConfigError(ValueError):
    """Raised when a payment-config file cannot safely be used."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without Google Play requests.")
    return parser.parse_args()


def choose_config() -> tuple[str, str, Path, Path]:
    print("Choose the Google Play project:")
    print("  1. KinSense")
    print("  2. KinShield")
    try:
        project_choice = input("Enter 1 or 2: ").strip()
    except EOFError as exc:
        raise ConfigError("No project was selected.") from exc
    project = PROJECTS.get(project_choice)
    if project is None:
        raise ConfigError("Invalid project. Choose 1 for KinSense or 2 for KinShield.")

    print("Choose the environment:")
    print("  1. prod")
    print("  2. non-prod (QA)")
    try:
        environment_choice = input("Enter 1 or 2: ").strip().lower()
    except EOFError as exc:
        raise ConfigError("No environment was selected.") from exc
    environment = {"1": "prod", "2": "non-prod", "prod": "prod", "non-prod": "non-prod", "qa": "non-prod"}.get(environment_choice)
    if environment is None:
        raise ConfigError("Invalid environment. Choose 1 for prod or 2 for non-prod (QA).")

    project_name, environments = project
    config_path, service_account_path = environments[environment]
    return project_name, environment, config_path, service_account_path


def parse_yaml(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Parse either supported Android YAML schema into posting-module input."""
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(document, dict) or not document:
        raise ConfigError("The YAML root must be a non-empty mapping.")

    package_name = document.pop("package name", None)
    if not isinstance(package_name, str) or not PACKAGE_NAME_RE.fullmatch(package_name):
        raise ConfigError(f"package name must be a valid Android package name: {package_name!r}")

    subscriptions: list[dict[str, Any]] = []
    product_ids: set[str] = set()
    base_plan_ids: set[str] = set()
    for group, tiers in document.items():
        if not isinstance(group, str) or not isinstance(tiers, dict):
            raise ConfigError("Each group must contain a mapping of subscription tiers.")
        for tier, subscription in tiers.items():
            context = f"{group}/{tier}"
            if not isinstance(tier, str) or not isinstance(subscription, dict):
                raise ConfigError(f"{context}: expected a mapping.")
            product_id = subscription.get("subscription id")
            if not isinstance(product_id, str) or not PRODUCT_ID_RE.fullmatch(product_id):
                raise ConfigError(f"{context}: invalid subscription id: {product_id!r}")
            if product_id in product_ids:
                raise ConfigError(f"Duplicate subscription id: {product_id}")
            product_ids.add(product_id)

            title = subscription.get("subscription name") or f"{group} {tier}".title()
            if not isinstance(title, str) or not title.strip():
                raise ConfigError(f"{context}: subscription name must be a non-empty string.")
            plans = subscription.get("plan")
            if not isinstance(plans, dict) or not plans:
                raise ConfigError(f"{context}: plan must be a non-empty mapping.")

            base_plans = []
            for plan_name, plan in plans.items():
                plan_context = f"{context}/{plan_name}"
                if plan_name not in PERIODS or not isinstance(plan, dict):
                    raise ConfigError(f"{plan_context}: only monthly, yearly, and annual plan mappings are supported.")
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
                    raise ConfigError(f"{plan_context}: android charge must be one of: {valid_values}.")
                resubscribe = plan.get("android resubscribe")
                if not isinstance(resubscribe, bool):
                    raise ConfigError(f"{plan_context}: android resubscribe must be true or false.")
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
                    "listing": {"languageCode": "en-US", "title": title[:55], "description": f"{title} subscription."[:200]},
                    "basePlans": base_plans,
                }
            )
    return package_name, subscriptions


def main() -> int:
    args = parse_args()
    try:
        project_name, environment, config_path, service_account_path = choose_config()
        package_name, subscriptions = parse_yaml(config_path)
        service_account_path = absolute_file_path(service_account_path, f"{project_name} service-account JSON")
    except (ConfigError, InputError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Selected {project_name} {environment}.")
    return post_subscriptions(package_name, subscriptions, service_account_path, dry_run=args.dry_run, source=str(config_path))


if __name__ == "__main__":
    sys.exit(main())
