---
name: pyffe-android-release
description: Run the pyffe-android release workflow when asked to release or build the app using the latest release branch or a specified release version.
---

# Pyffe Android release

The repository is `/Users/khang.tm/qualgo-macbook/safenest/pyffe-android`. Read its `AGENTS.md` and use its existing `scripts/release.py` for this workflow.

The script is a release workflow, not a standalone local APK build: it updates branches, runs the version bump and optional changelog, creates commits, pushes, creates or reuses PRs, and may merge them using `pr-merge`. It can delete and recreate the local and remote `feature/SAF-0-bump-version` branch. A request to release or build the app using this skill authorizes the complete script workflow, including commits, pushes, creating and merging PRs, and replacing the bump-version branch. Run it without asking for confirmation when the selection and prerequisites are satisfied. If the user explicitly asks only for a local build, use the repository's build workflow instead. Follow applicable higher-priority instructions and environment permissions.

First change into the repository, then run the appropriate command:

```bash
cd /Users/khang.tm/qualgo-macbook/safenest/pyffe-android
```

Select the release as requested:

- Latest release branch: `python3 scripts/release.py --latest`.
- Exact version: `python3 scripts/release.py --version XX.YY.ZZ`. A branch such as `release/v26.11.10` maps to `26.11.10`; preserve the exact numeric version. The script requires two digits in each component.
- If neither latest nor an exact version is specified, ask which to use; do not guess.

After the `cd`, check the current branch with `git branch --show-current`. If it is not `develop`, switch to `develop` before running the Python command; if the local branch does not exist, create a tracking branch from `origin/develop`. Do not discard or stash user changes to make the switch possible; stop and report any checkout failure. The script requires GitHub CLI authentication and a clean working tree, and queries origin for the latest version.

Stop on errors, report the output and any resulting branches or PRs, and do not blindly retry a partially completed release. Report the selected version and actual outcome; do not claim an APK was built unless verified.
