#!/usr/bin/env python3

import os
import subprocess
import sys
import re
import tty
import termios
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent

REPOS = [
    "kinshield-android",
    "kinshield-companion-android",
    "kinshield-core-features-android",
    "kinshield-features-version-android",
]


def run(cmd, cwd, check=True):
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def get_latest_release_branch(repo_path):
    """Fetch remote and return the latest release/vYY.MM.DD branch, or None."""
    run(["git", "fetch", "--all", "--prune"], cwd=repo_path)
    result = run(
        ["git", "branch", "-r", "--list", "origin/release/v*"], cwd=repo_path
    )
    branches = [
        line.strip().removeprefix("origin/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    release_pattern = re.compile(r"^release/v(\d{2})\.(\d{2})\.(\d+)$")
    versioned = []
    for b in branches:
        m = release_pattern.match(b)
        if m:
            versioned.append((tuple(int(x) for x in m.groups()), b))

    if not versioned:
        return None

    versioned.sort(key=lambda x: (x[0][0], x[0][1], x[0][2]), reverse=True)
    return versioned[0][1]


def is_develop_behind(repo_path, release_branch):
    """Return True if develop is strictly behind the release branch tip."""
    release_ref = f"origin/{release_branch}"
    result = run(
        ["git", "rev-list", "--count", f"origin/develop..{release_ref}"],
        cwd=repo_path,
    )
    ahead = int(result.stdout.strip())
    return ahead > 0


def confirm_or_cancel(prompt):
    """Print prompt and wait for Enter (continue) or Escape (cancel)."""
    print(f"\n{prompt} (Press Enter to continue or Esc to cancel): ", end="", flush=True)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                print()
                return
            if ch == "\x1b":
                print("\nCancelled.")
                sys.exit(0)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def check_clean_workspace(repo_path):
    """Raise if there are uncommitted changes or untracked files."""
    result = run(["git", "status", "--porcelain"], cwd=repo_path)
    if result.stdout.strip():
        raise RuntimeError(
            f"Workspace is not clean:\n{result.stdout.strip()}\n"
            "Please commit, stash, or discard changes before proceeding."
        )


def pull_latest_develop(repo_path):
    check_clean_workspace(repo_path)
    run(["git", "checkout", "develop"], cwd=repo_path)
    run(["git", "pull", "origin", "develop"], cwd=repo_path)


def bump_version_properties(repo_path, version_name):
    """Update config/version/version.properties: set VERSION_NAME and bump VERSION_CODE to next 100."""
    props_path = repo_path / "config" / "version" / "version.properties"
    content = props_path.read_text()

    # Update VERSION_NAME
    content = re.sub(r"(?m)^VERSION_NAME\s*=.*$", f"VERSION_NAME={version_name}", content)

    # Bump VERSION_CODE to next multiple of 100
    match = re.search(r"(?m)^VERSION_CODE\s*=\s*(\d+)$", content)
    if not match:
        raise RuntimeError(f"VERSION_CODE not found in {props_path}")
    current_code = int(match.group(1))
    new_code = (current_code // 100 + 1) * 100
    content = re.sub(r"(?m)^VERSION_CODE\s*=\s*\d+$", f"VERSION_CODE={new_code}", content)

    props_path.write_text(content)
    print(f"  Updated {props_path.relative_to(repo_path)}: VERSION_NAME={version_name}, VERSION_CODE {current_code} -> {new_code}")


def bump_gradle_properties(repo_path, version_name):
    """Update gradle.properties: set VERSION to version_name."""
    props_path = repo_path / "gradle.properties"
    content = props_path.read_text()
    content = re.sub(r"(?m)^VERSION\s*=.*$", f"VERSION={version_name}", content)
    props_path.write_text(content)
    print(f"  Updated gradle.properties: VERSION={version_name}")


def create_and_push_branch(repo, repo_path, branch_name, release_version):
    result = run(["git", "branch", "-r", "--list", f"origin/{branch_name}"], cwd=repo_path)
    if result.stdout.strip():
        print(f"  Branch '{branch_name}' already exists on remote, skipping.")
        return
    run(["git", "checkout", "develop"], cwd=repo_path)
    run(["git", "checkout", "-b", branch_name], cwd=repo_path)

    if repo in ("kinshield-android", "kinshield-companion-android"):
        bump_version_properties(repo_path, release_version)
        run(["git", "add", "config/version/version.properties"], cwd=repo_path)
        run(["git", "commit", "-m", f"Set release version {release_version}"], cwd=repo_path)
    elif repo == "kinshield-core-features-android":
        bump_gradle_properties(repo_path, release_version)
        run(["git", "add", "gradle.properties"], cwd=repo_path)
        run(["git", "commit", "-m", f"Set release version {release_version}"], cwd=repo_path)

    run(["git", "push", "-u", "origin", branch_name], cwd=repo_path)


def main():
    print("=== Release Branch Creator ===\n")

    repo_paths = {}
    for repo in REPOS:
        path = BASE_DIR / repo
        if not path.exists():
            print(f"[ERROR] Repo not found: {path}")
            sys.exit(1)
        repo_paths[repo] = path

    # Step 1: Pull latest develop and check against latest release branch
    print("Checking repos...\n")
    repo_info = {}  # repo -> latest_release_branch

    for repo in REPOS:
        path = repo_paths[repo]
        print(f"[{repo}] Pulling latest develop...")
        try:
            pull_latest_develop(path)
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

        print(f"[{repo}] Looking for latest release branch...")
        latest_release = get_latest_release_branch(path)

        if latest_release is None:
            print(
                f"  Could not detect a release branch for '{repo}'.\n"
                f"  Enter the latest release branch name (format: release/vYY.MM.xx, e.g. release/v26.04.10),\n"
                f"  or leave blank to skip the behind-check: ",
                end="",
            )
            user_input = input().strip()
            latest_release = user_input if user_input else None

        repo_info[repo] = latest_release

        if latest_release:
            print(f"  Latest release branch: {latest_release}")
            try:
                behind = is_develop_behind(path, latest_release)
            except RuntimeError as e:
                print(f"  WARNING: Could not compare branches: {e}")
                behind = False

            if behind:
                print(
                    f"  WARNING: develop is BEHIND {latest_release}. "
                    f"Consider merging before cutting a new release."
                )
            else:
                print(f"  develop is up-to-date relative to {latest_release}.")
        else:
            print("  Skipping behind-check (no release branch reference).")

    # Summary + confirmation
    print("\n--- Summary ---")
    all_ok = True
    for repo in REPOS:
        latest = repo_info[repo]
        if latest:
            path = repo_paths[repo]
            try:
                behind = is_develop_behind(path, latest)
                status = "WARNING: develop is BEHIND latest release" if behind else "OK: develop is up-to-date"
                if behind:
                    all_ok = False
            except RuntimeError:
                status = "UNKNOWN (could not compare)"
        else:
            status = "SKIPPED (no release branch reference)"
        print(f"  {repo}")
        print(f"    Latest release : {latest or 'N/A'}")
        print(f"    Status         : {status}")

    if not all_ok:
        print("\nOne or more repos have develop BEHIND the latest release branch.")

    confirm_or_cancel("Proceed with creating the release branch?")

    # Step 2: Ask for the new release branch name
    print()
    while True:
        release_version = input(
            "Enter the release version (format: YY.MM.xx, e.g. 26.04.20): "
        ).strip()
        if re.match(r"^\d{2}\.\d{2}\.\d+$", release_version):
            break
        print("  Invalid format. Expected: YY.MM.xx")
        print("  xx is 10/20/30 for regular releases, or 11/12/24/etc for hotfix/adhoc")
    branch_name = f"release/v{release_version}"

    # Step 3: Create and push release branch for each repo
    print()
    errors = []
    for repo in REPOS:
        path = repo_paths[repo]
        print(f"[{repo}] Creating and pushing '{branch_name}'...")
        try:
            create_and_push_branch(repo, path, branch_name, release_version)
            print(f"  Done.")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            errors.append(repo)

    print()
    if errors:
        print(f"Finished with errors in: {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"Release branch '{branch_name}' created and pushed for all repos.")


if __name__ == "__main__":
    main()
