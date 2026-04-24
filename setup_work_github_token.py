#!/usr/bin/env python3
import getpass
import os
import subprocess
import sys


ZSHRC_PATH = os.path.expanduser("~/.zshrc")
TOKEN_KEY = "WORK_GITHUB_TOKEN"
EXPORT_LINE = f'export {TOKEN_KEY}='


def ask_for_token() -> str:
    print(f"Enter your {TOKEN_KEY} (input hidden):")
    token = getpass.getpass("> ").strip()
    if not token:
        print("Error: token cannot be empty.")
        sys.exit(1)
    return token


def write_to_zshrc(token: str) -> None:
    try:
        with open(ZSHRC_PATH, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    new_line = f'{EXPORT_LINE}"{token}"\n'
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(EXPORT_LINE):
            lines[i] = new_line
            updated = True
            break

    if not updated:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(new_line)

    with open(ZSHRC_PATH, "w") as f:
        f.writelines(lines)

    action = "Updated" if updated else "Added"
    print(f"{action} {TOKEN_KEY} in {ZSHRC_PATH}")


def source_zshrc() -> None:
    # Only export the single variable into the current process environment,
    # avoiding a full zsh startup (which loads plugins and is slow).
    result = subprocess.run(
        ["zsh", "-c", f"source {ZSHRC_PATH} > /dev/null 2>&1; echo ${TOKEN_KEY}"],
        capture_output=True,
        text=True,
        env={**os.environ, "TERM": "dumb"},
    )
    token_value = result.stdout.strip()
    if token_value:
        os.environ[TOKEN_KEY] = token_value
        masked = token_value[:4] + "*" * (len(token_value) - 8) + token_value[-4:]
        print(f"Token applied to current session: {masked}")
    else:
        print("Warning: could not read token back. Run 'source ~/.zshrc' manually.")


def verify_written(token: str) -> None:
    with open(ZSHRC_PATH, "r") as f:
        content = f.read()
    if f'{EXPORT_LINE}"{token}"' in content:
        masked = token[:4] + "*" * (len(token) - 8) + token[-4:]
        print(f"Verified in {ZSHRC_PATH}: {TOKEN_KEY}={masked}")
    else:
        print(f"Warning: could not verify token in {ZSHRC_PATH}.")


def main():
    token = ask_for_token()
    write_to_zshrc(token)
    verify_written(token)
    source_zshrc()


if __name__ == "__main__":
    main()
