"""Shared project selection for Firebase Remote Config scripts."""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helper._interactive_input import read_input

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECTS = {
    "1": (
        "Pyffe",
        {
            "1": (
                "non-prod",
                SCRIPT_DIR / "configs" / "config-pyffe-nonprod.yml",
                SCRIPT_DIR / "credentials" / "service-account-pyffe-nonprod.json",
            ),            "2": (
                "prod",
                SCRIPT_DIR / "configs" / "config-pyffe-prod.yml",
                SCRIPT_DIR / "credentials" / "service-account-pyffe-prod.json",
            ),

        },
    ),
    "2": (
        "KinShield",
        {
            "1": (
                "non-prod",
                SCRIPT_DIR / "configs" / "config-kinshield-nonprod.yml",
                SCRIPT_DIR / "credentials" / "service-account-kinshield-non-prod.json",
            ),            "2": (
                "prod",
                SCRIPT_DIR / "configs" / "config-kinshield-prod.yml",
                SCRIPT_DIR / "credentials" / "service-account-kinshield-prod.json",
            ),

        },
    ),
    "3": (
        "ShieldNet 360",
        {
            "1": (
                "non-prod",
                SCRIPT_DIR / "configs" / "config-shieldnet360-nonprod.yml",
                SCRIPT_DIR / "credentials" / "service-account-shieldnet360-non-prod.json",
            ),            "2": (
                "prod",
                SCRIPT_DIR / "configs" / "config-shieldnet360-prod.yml",
                SCRIPT_DIR / "credentials" / "service-account-shieldnet360-prod.json",
            ),

        },
    ),
}


class ConfigError(ValueError):
    """Raised when a manifest cannot be converted into a safe API request."""


def choose_environment() -> tuple[str, Path, Path]:
    print("Choose the Firebase project:")
    print("  1. Pyffe")
    print("  2. KinShield")
    print("  3. ShieldNet 360")
    try:
        project_choice = read_input("Enter 1, 2 or 3: ").strip()
    except EOFError as exc:
        raise ConfigError("No Firebase project was selected.") from exc
    project = PROJECTS.get(project_choice)
    if project is None:
        raise ConfigError("Invalid project. Choose 1 for Pyffe, 2 for KinShield or 3 for ShieldNet 360.")

    project_name, environments = project
    print("Choose the Firebase environment:")
    print("  1. non-prod")
    print("  2. prod")
    try:
        choice = read_input("Enter 1 or 2: ").strip()
    except EOFError as exc:
        raise ConfigError("No environment was selected.") from exc
    environment = environments.get(choice)
    if environment is None:
        raise ConfigError("Invalid environment. Choose 1 for non-prod or 2 for prod.")
    name, config_path, service_account_path = environment
    if not config_path.is_file():
        raise ConfigError(f"{name} config file does not exist: {config_path}")
    if not service_account_path.is_file():
        raise ConfigError(f"{name} service-account JSON does not exist: {service_account_path}")
    return f"{project_name} {name}", config_path, service_account_path
