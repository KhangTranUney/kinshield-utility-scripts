#!/usr/bin/env python3
"""Merge a YAML parameter manifest into a Firebase Remote Config template.

The script previews and validates the merged template, then asks before publishing it.
"""

from __future__ import annotations

import json
import sys
import termios
import tty
from pathlib import Path
from typing import Any

import google.auth.transport.requests
import requests
import yaml
from google.oauth2 import service_account


SCRIPT_DIR = Path(__file__).resolve().parent
API_URL = "https://firebaseremoteconfig.googleapis.com/v1/projects/{project_id}/remoteConfig"
SCOPES = ["https://www.googleapis.com/auth/firebase.remoteconfig"]
TIMEOUT_SECONDS = 30
DATA_TYPES = {"string": "STRING", "number": "NUMBER", "boolean": "BOOLEAN", "json": "JSON"}
PROJECTS = {
    "1": (
        "KinShield",
        {
            "1": (
                "prod",
                SCRIPT_DIR / "config-kinshield-prod.yml",
                SCRIPT_DIR / "credentials" / "kinshield-prod-firebase-adminsdk.json",
            ),
            "2": (
                "non-prod",
                SCRIPT_DIR / "config-kinshield-nonprod.yml",
                SCRIPT_DIR / "credentials" / "kinshield-non-prod-firebase-adminsdk.json",
            ),
        },
    ),
    "2": (
        "ShieldNet 360",
        {
            "1": (
                "prod",
                SCRIPT_DIR / "config-shieldnet360-prod.yml",
                SCRIPT_DIR / "credentials" / "shieldnet360-prod-firebase-adminsdk-fbsvc.json",
            ),
            "2": (
                "non-prod",
                SCRIPT_DIR / "config-shieldnet360-nonprod.yml",
                SCRIPT_DIR / "credentials" / "shieldnet360-nonprod-firebase-adminsdk.json",
            ),
        },
    ),
}


class ConfigError(ValueError):
    """Raised when a manifest cannot be converted into a safe API request."""


def choose_environment() -> tuple[str, Path, Path]:
    print("Choose the Firebase project:")
    print("  1. KinShield")
    print("  2. ShieldNet 360")
    try:
        project_choice = input("Enter 1 or 2: ").strip()
    except EOFError as exc:
        raise ConfigError("No Firebase project was selected.") from exc
    project = PROJECTS.get(project_choice)
    if project is None:
        raise ConfigError("Invalid project. Choose 1 for KinShield or 2 for ShieldNet 360.")

    project_name, environments = project
    print("Choose the Firebase environment:")
    print("  1. prod")
    print("  2. non-prod")
    try:
        choice = input("Enter 1 or 2: ").strip()
    except EOFError as exc:
        raise ConfigError("No environment was selected.") from exc
    environment = environments.get(choice)
    if environment is None:
        raise ConfigError("Invalid environment. Choose 1 for prod or 2 for non-prod.")
    name, config_path, service_account_path = environment
    if not config_path.is_file():
        raise ConfigError(f"{name} config file does not exist: {config_path}")
    if not service_account_path.is_file():
        raise ConfigError(f"{name} service-account JSON does not exist: {service_account_path}")
    return f"{project_name} {name}", config_path, service_account_path


def load_manifest(path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise ConfigError("Config YAML must be a mapping with project_id and params fields.")
    project_id = document.get("project_id")
    if isinstance(project_id, bool) or not isinstance(project_id, (str, int)) or not str(project_id).strip():
        raise ConfigError("project_id must be a non-empty Firebase project ID or project number.")
    params = document.get("params")
    if not isinstance(params, dict) or not params:
        raise ConfigError("params must be a non-empty mapping of Remote Config parameter keys.")
    for key, definition in params.items():
        if not isinstance(key, str) or not key:
            raise ConfigError("Every parameter key must be a non-empty string.")
        if not isinstance(definition, dict):
            raise ConfigError(f"Parameter {key!r} must be a mapping.")
        deleted = definition.get("deleted", False)
        if not isinstance(deleted, bool):
            raise ConfigError(f"Parameter {key!r}: deleted must be true or false.")
        if deleted:
            continue
        data_type = definition.get("data_type")
        if data_type not in DATA_TYPES:
            raise ConfigError(
                f"Parameter {key!r}: data_type must be one of {', '.join(DATA_TYPES)}."
            )
        if "value" not in definition:
            raise ConfigError(f"Parameter {key!r}: value is required unless deleted is true.")
    return str(project_id), params


def parameter_value(key: str, definition: dict[str, Any]) -> dict[str, Any]:
    data_type = definition["data_type"]
    value = definition["value"]
    if data_type == "string":
        if not isinstance(value, str):
            raise ConfigError(f"Parameter {key!r}: string values must be YAML strings.")
        encoded_value = value
    elif data_type == "boolean":
        if not isinstance(value, bool):
            raise ConfigError(f"Parameter {key!r}: boolean values must be true or false.")
        encoded_value = "true" if value else "false"
    elif data_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"Parameter {key!r}: number values must be YAML numbers.")
        encoded_value = str(value)
    else:
        if not isinstance(value, str):
            raise ConfigError(f"Parameter {key!r}: json values must be JSON encoded as a YAML string.")
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Parameter {key!r}: invalid JSON value: {exc.msg}.") from exc
        encoded_value = value
    return {"defaultValue": {"value": encoded_value}, "valueType": DATA_TYPES[data_type]}


def merge_template(
    template: dict[str, Any], manifest: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]]]:
    parameters = template.setdefault("parameters", {})
    if not isinstance(parameters, dict):
        raise ConfigError("The current Firebase template has an invalid parameters field.")

    changes: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []
    for key, definition in manifest.items():
        current = parameters.get(key)
        if current is not None and not isinstance(current, dict):
            raise ConfigError(f"The current Firebase parameter {key!r} is invalid.")
        if definition.get("deleted"):
            if current is not None:
                del parameters[key]
                changes.append(("DELETE", key, current, None))
            continue
        desired = parameter_value(key, definition)
        if current is None:
            parameters[key] = desired
            changes.append(("ADD", key, None, desired))
            continue
        if (
            current.get("defaultValue") == desired["defaultValue"]
            and current.get("valueType", "STRING") == desired["valueType"]
        ):
            continue
        # Keep descriptions, conditional values, and other existing metadata.
        updated = dict(current)
        updated.update(desired)
        parameters[key] = updated
        changes.append(("UPDATE", key, current, updated))
    return template, changes


def parameter_summary(parameter: dict[str, Any] | None) -> str:
    if parameter is None:
        return "<absent>"
    default_value = parameter.get("defaultValue")
    if not isinstance(default_value, dict) or "value" not in default_value:
        value = "<in-app default>"
    else:
        value = json.dumps(default_value["value"], ensure_ascii=False)
    return f"type={parameter.get('valueType', 'STRING')}, default={value}"


def display_changes(changes: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]]) -> None:
    print("\nProposed Firebase Remote Config changes:")
    for action, key, current, desired in changes:
        print(f"\n{action} {key}")
        print(f"  Current: {parameter_summary(current)}")
        print(f"  Desired: {parameter_summary(desired)}")


def confirm_publish() -> bool:
    if not sys.stdin.isatty():
        raise ConfigError("Publishing requires an interactive terminal to confirm with Enter or Esc.")
    print("\nPress Enter to publish these changes, or Esc to cancel: ", end="", flush=True)
    fd = sys.stdin.fileno()
    original_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)
    print()
    if key in ("\r", "\n"):
        return True
    if key == "\x1b":
        return False
    print("Cancelled: only Enter confirms publishing.")
    return False


def response_error(response: requests.Response) -> str:
    try:
        payload = response.json()
        return json.dumps(payload, indent=2)
    except ValueError:
        return response.text


def get_template(session: google.auth.transport.requests.AuthorizedSession, project_id: str) -> tuple[dict[str, Any], str]:
    response = session.get(API_URL.format(project_id=project_id), headers={"Accept-Encoding": "gzip"}, timeout=TIMEOUT_SECONDS)
    if not response.ok:
        raise ConfigError(f"Could not fetch Firebase Remote Config ({response.status_code}):\n{response_error(response)}")
    etag = response.headers.get("ETag")
    if not etag:
        raise ConfigError("Firebase did not return an ETag; cannot safely update the template.")
    try:
        template = response.json()
    except ValueError as exc:
        raise ConfigError("Firebase returned a non-JSON Remote Config template.") from exc
    if not isinstance(template, dict):
        raise ConfigError("Firebase returned an invalid Remote Config template.")
    return template, etag


def put_template(
    session: google.auth.transport.requests.AuthorizedSession,
    project_id: str,
    template: dict[str, Any],
    etag: str,
    validate_only: bool,
) -> requests.Response:
    return session.put(
        API_URL.format(project_id=project_id),
        params={"validate_only": "true"} if validate_only else None,
        headers={
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json; charset=utf-8",
            "If-Match": etag,
        },
        json=template,
        timeout=TIMEOUT_SECONDS,
    )


def main() -> int:
    try:
        environment, config_path, service_account_path = choose_environment()
        print(f"Selected {environment}.")
        project_id, manifest = load_manifest(config_path)
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path, scopes=SCOPES
        )
        session = google.auth.transport.requests.AuthorizedSession(credentials)
        template, etag = get_template(session, project_id)
        print("Fetched the current Firebase Remote Config template.")
        merged_template, changes = merge_template(template, manifest)
        if not changes:
            print("No Remote Config changes are needed.")
            return 0
        display_changes(changes)

        validation = put_template(session, project_id, merged_template, etag, validate_only=True)
        if not validation.ok:
            raise ConfigError(f"Validation failed ({validation.status_code}):\n{response_error(validation)}")
        print("\nFirebase accepted the proposed template during validation.")
        if not confirm_publish():
            print("No changes published.")
            return 0

        response = put_template(session, project_id, merged_template, etag, validate_only=False)
        if response.status_code == 409:
            raise ConfigError("Template changed while publishing. Re-run to merge against the latest version.")
        if not response.ok:
            raise ConfigError(f"Publish failed ({response.status_code}):\n{response_error(response)}")
        version = response.json().get("version", {}).get("versionNumber", "unknown")
        print(f"Published Remote Config version {version}: {len(changes)} change(s).")
        return 0
    except (ConfigError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
