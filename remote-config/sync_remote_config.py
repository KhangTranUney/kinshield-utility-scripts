#!/usr/bin/env python3
"""Synchronize Firebase Remote Config metadata into a local YAML manifest.

The script fetches the current Firebase template, shows the differences, and
asks before updating the selected YAML file. Parameters use exactly one of
``value`` or ``condition_value``. Existing local values and data types are
preserved where possible; descriptions, conditions, conditional values, and
parameters that exist only in Firebase are synchronized. Parameters that exist
only locally are marked ``deleted: true``.
"""

from __future__ import annotations

import json
import os
import sys
import termios
import tempfile
from copy import deepcopy
from pathlib import Path
import tty
from typing import Any

import yaml
from google.oauth2 import service_account

import google.auth.transport.requests

import publish_remote_config as publisher


REMOTE_TYPES = {value: key for key, value in publisher.DATA_TYPES.items()}


def load_document(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise publisher.ConfigError(f"Config file does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise publisher.ConfigError(f"Config file is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise publisher.ConfigError("Config YAML must be a mapping.")
    params = document.get("params")
    if not isinstance(params, dict):
        raise publisher.ConfigError("Config YAML must contain a params mapping.")
    return document


def as_local_value(value: str, remote_type: str) -> Any:
    """Convert a Firebase string value to the manifest's native YAML value."""

    data_type = REMOTE_TYPES.get(remote_type, "string")
    if data_type == "boolean":
        return value.lower() == "true"
    if data_type == "number":
        try:
            number = json.loads(value)
        except json.JSONDecodeError:
            return value
        return number if isinstance(number, (int, float)) and not isinstance(number, bool) else value
    return value


def condition_map(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for condition in template.get("conditions", []):
        if not isinstance(condition, dict) or not isinstance(condition.get("name"), str):
            continue
        item: dict[str, Any] = {}
        if "expression" in condition:
            item["expression"] = condition["expression"]
        if "tagColor" in condition:
            item["tag_color"] = condition["tagColor"]
        result[condition["name"]] = item
    return result


def remote_conditional_values(parameter: dict[str, Any]) -> dict[str, Any]:
    remote_type = parameter.get("valueType", "STRING")
    values = parameter.get("conditionalValues", {})
    if not isinstance(values, dict):
        return {}
    result: dict[str, Any] = {}
    for name, conditional_value in values.items():
        if isinstance(name, str) and isinstance(conditional_value, dict) and "value" in conditional_value:
            result[name] = as_local_value(str(conditional_value["value"]), remote_type)
    return result


def local_conditional_values(definition: dict[str, Any]) -> dict[str, Any]:
    values = definition.get("condition_value", [])
    if isinstance(values, dict):
        return values
    if not isinstance(values, list):
        return {}
    result: dict[str, Any] = {}
    for condition_value in values:
        if isinstance(condition_value, dict):
            result.update(condition_value)
    return result


def condition_value_list(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [{condition_name: value} for condition_name, value in values.items()]


def remote_default_value(parameter: dict[str, Any]) -> Any:
    default = parameter.get("defaultValue")
    if not isinstance(default, dict) or "value" not in default:
        return ""
    return as_local_value(str(default["value"]), parameter.get("valueType", "STRING"))


def local_value_summary(key: str, value: Any) -> str:
    text = str(value)
    if len(text) > 80 or any(word in key.lower() for word in ("identity", "token", "secret", "certificate")):
        return f"<{len(text)} characters>"
    return repr(value)


def remote_value_summary(key: str, parameter: dict[str, Any]) -> str:
    default = parameter.get("defaultValue")
    value = default.get("value", "") if isinstance(default, dict) else ""
    return local_value_summary(key, value)


def display_changes(
    document: dict[str, Any], template: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    local_params = document["params"]
    remote_params = template.get("parameters", {})
    if not isinstance(remote_params, dict):
        raise publisher.ConfigError("The current Firebase template has an invalid parameters field.")

    updated = deepcopy(document)
    changes = False

    current_conditions = document.get("conditions", {})
    desired_conditions = condition_map(template)
    if current_conditions != desired_conditions:
        print("\nCONDITIONS")
        print(f"  Local:  {json.dumps(current_conditions, ensure_ascii=False, sort_keys=True)}")
        print(f"  Remote: {json.dumps(desired_conditions, ensure_ascii=False, sort_keys=True)}")
        updated["conditions"] = desired_conditions
        changes = True

    print("\nPARAMETERS")
    remote_only = sorted(set(remote_params) - set(local_params))
    local_only = sorted(set(local_params) - set(remote_params))
    parameter_changes_count = 0

    for key in sorted(set(local_params) & set(remote_params)):
        local_definition = local_params[key]
        remote_definition = remote_params[key]
        if not isinstance(local_definition, dict) or not isinstance(remote_definition, dict):
            continue

        remote_description = remote_definition.get("description") or ""
        local_description = local_definition.get("description") or ""
        remote_conditions_for_parameter = remote_conditional_values(remote_definition)
        local_conditions_for_parameter = local_conditional_values(local_definition)
        parameter_changes: list[str] = []

        if local_description != remote_description:
            parameter_changes.append(f"description: {local_description!r} -> {remote_description!r}")
        if local_conditions_for_parameter != remote_conditions_for_parameter:
            parameter_changes.append(
                "condition_value: "
                f"{json.dumps(local_conditions_for_parameter, ensure_ascii=False, sort_keys=True)} -> "
                f"{json.dumps(remote_conditions_for_parameter, ensure_ascii=False, sort_keys=True)}"
            )

        local_type = local_definition.get("data_type")
        remote_type = REMOTE_TYPES.get(remote_definition.get("valueType"))
        if local_type != remote_type:
            parameter_changes.append(f"type differs: local {local_type!r}, remote {remote_type!r} (not applied)")
        if not local_definition.get("deleted") and "value" in local_definition:
            remote_value = remote_default_value(remote_definition)
            local_value = local_definition.get("value")
            if local_value != remote_value:
                parameter_changes.append(
                    "value differs: "
                    f"local {local_value_summary(key, local_value)}, "
                    f"remote {remote_value_summary(key, remote_definition)} (not applied)"
                )

        if parameter_changes:
            print(f"\n{key}")
            for change in parameter_changes:
                print(f"  - {change}")
        if any("not applied" not in change for change in parameter_changes):
            updated_definition = updated["params"][key]
            updated_definition["description"] = remote_description
            if remote_conditions_for_parameter:
                updated_definition.pop("value", None)
                updated_definition["condition_value"] = condition_value_list(
                    remote_conditions_for_parameter
                )
            else:
                updated_definition.pop("condition_value", None)
                if "value" not in updated_definition:
                    updated_definition["value"] = remote_default_value(remote_definition)
            parameter_changes_count += 1
            changes = True

    for key in remote_only:
        remote_definition = remote_params[key]
        if not isinstance(remote_definition, dict):
            continue
        print(f"\n{key}")
        print("  - exists remotely but is missing locally (will be added)")
        print(f"  - type: {REMOTE_TYPES.get(remote_definition.get('valueType'), 'string')}")
        print(f"  - default: {remote_value_summary(key, remote_definition)}")
        conditional_values = remote_conditional_values(remote_definition)
        if conditional_values:
            print(
                "  - condition_value: "
                f"{json.dumps(conditional_values, ensure_ascii=False, sort_keys=True)}"
            )
        changes = True
        parameter_changes_count += 1
        updated_definition = {
            "description": remote_definition.get("description") or "",
            "deleted": False,
            "data_type": REMOTE_TYPES.get(remote_definition.get("valueType"), "string"),
        }
        if conditional_values:
            updated_definition["condition_value"] = condition_value_list(conditional_values)
        else:
            updated_definition["value"] = remote_default_value(remote_definition)
        updated["params"][key] = updated_definition

    for key in local_only:
        local_definition = local_params[key]
        print(f"\n{key}")
        if isinstance(local_definition, dict) and local_definition.get("deleted") is True:
            print("  - exists locally but not in Firebase (already marked deleted)")
            continue
        print("  - exists locally but not in Firebase (will be marked deleted)")
        updated["params"][key]["deleted"] = True
        parameter_changes_count += 1
        changes = True

    if not changes:
        print("\nNo descriptions, conditions, or conditional values need syncing.")
    else:
        print(f"\n{parameter_changes_count} parameter change(s) will be written.")
    return changes, updated


def write_document(path: Path, document: dict[str, Any]) -> None:
    content = yaml.safe_dump(
        document,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        indent=4,
        width=4096,
    )
    content = indent_condition_values(content)
    directory = path.parent
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as output:
        output.write(content)
        temporary_path = Path(output.name)
    try:
        os.replace(temporary_path, path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def indent_condition_values(content: str) -> str:
    """Use the project's four-space indentation for condition value lists."""

    lines = content.splitlines()
    formatted: list[str] = []
    condition_indent: str | None = None
    for line in lines:
        if line.rstrip().endswith("condition_value:"):
            condition_indent = line[: len(line) - len(line.lstrip())]
            formatted.append(line)
            continue
        if condition_indent is not None and line.startswith(f"{condition_indent}-   "):
            value = line[len(condition_indent) + 4 :]
            formatted.append(f"{condition_indent}    - {value}")
            continue
        condition_indent = None
        formatted.append(line)
    return "\n".join(formatted) + "\n"


def confirm_update(config_path: Path) -> bool:
    if not sys.stdin.isatty():
        raise publisher.ConfigError("Updating requires an interactive terminal to confirm with Enter or Esc.")
    print(f"\nPress Enter to update {config_path.name}, or Esc to cancel: ", end="", flush=True)
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
    print("Cancelled: only Enter confirms the update.")
    return False


def main() -> int:
    try:
        environment, config_path, service_account_path = publisher.choose_environment()
        print(f"Selected {environment}.")
        document = load_document(config_path)
        publisher.load_manifest(config_path)
        project_id = str(document["project_id"])
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path, scopes=publisher.SCOPES
        )
        session = google.auth.transport.requests.AuthorizedSession(credentials)
        template, _ = publisher.get_template(session, project_id)
        print("Fetched the current Firebase Remote Config template.")
        changes, updated_document = display_changes(document, template)
        if not changes:
            return 0

        if not confirm_update(config_path):
            print("No local file was changed.")
            return 0
        write_document(config_path, updated_document)
        print(f"Updated {config_path}.")
        return 0
    except (publisher.ConfigError, OSError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
