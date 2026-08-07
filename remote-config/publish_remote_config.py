#!/usr/bin/env python3
"""Merge a YAML parameter manifest into a Firebase Remote Config template.

The script validates the merged template by default. Add --apply to publish it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import google.auth.transport.requests
import requests
import yaml
from google.oauth2 import service_account


API_URL = "https://firebaseremoteconfig.googleapis.com/v1/projects/{project_id}/remoteConfig"
SCOPES = ["https://www.googleapis.com/auth/firebase.remoteconfig"]
TIMEOUT_SECONDS = 30
DATA_TYPES = {"string": "STRING", "number": "NUMBER", "boolean": "BOOLEAN", "json": "JSON"}


class ConfigError(ValueError):
    """Raised when a manifest cannot be converted into a safe API request."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True, help="Firebase project ID or project number.")
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Absolute path to the Remote Config YAML. Prompts when omitted.",
    )
    parser.add_argument(
        "--service-account-file",
        type=Path,
        help="Absolute path to the service-account JSON. Prompts when omitted.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Publish after validation. Without this flag, only validates the merge.",
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


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {exc}") from exc

    if not isinstance(document, dict) or not document:
        raise ConfigError("Config YAML must be a non-empty mapping of parameter keys.")
    for key, definition in document.items():
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
    return document


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


def merge_template(template: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str], list[str]]:
    parameters = template.setdefault("parameters", {})
    if not isinstance(parameters, dict):
        raise ConfigError("The current Firebase template has an invalid parameters field.")

    updated: list[str] = []
    deleted: list[str] = []
    for key, definition in manifest.items():
        if definition.get("deleted"):
            if key in parameters:
                del parameters[key]
                deleted.append(key)
            continue
        parameters[key] = parameter_value(key, definition)
        updated.append(key)
    return template, updated, deleted


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
    args = parse_args()
    try:
        config_path = requested_file_path(args.config, "Remote Config YAML")
        service_account_path = requested_file_path(args.service_account_file, "service-account JSON")
        manifest = load_manifest(config_path)
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path, scopes=SCOPES
        )
        session = google.auth.transport.requests.AuthorizedSession(credentials)
        template, etag = get_template(session, args.project_id)
        merged_template, updated, deleted = merge_template(template, manifest)

        validation = put_template(session, args.project_id, merged_template, etag, validate_only=True)
        if not validation.ok:
            raise ConfigError(f"Validation failed ({validation.status_code}):\n{response_error(validation)}")
        print(f"Validated {config_path}: {len(updated)} update(s), {len(deleted)} deletion(s).")
        if not args.apply:
            print("No changes published. Re-run with --apply to publish this validated merge.")
            return 0

        # Validation returns a derived ETag; fetch again so the publish uses the live template's ETag.
        template, etag = get_template(session, args.project_id)
        merged_template, updated, deleted = merge_template(template, manifest)
        response = put_template(session, args.project_id, merged_template, etag, validate_only=False)
        if response.status_code == 409:
            raise ConfigError("Template changed while publishing. Re-run to merge against the latest version.")
        if not response.ok:
            raise ConfigError(f"Publish failed ({response.status_code}):\n{response_error(response)}")
        version = response.json().get("version", {}).get("versionNumber", "unknown")
        print(f"Published Remote Config version {version}: {len(updated)} update(s), {len(deleted)} deletion(s).")
        return 0
    except (ConfigError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
