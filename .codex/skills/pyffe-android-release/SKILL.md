---
name: pyffe-android-release
description: Run the pyffe-android release workflow when asked to release or build the app using the latest release branch or a specified release version.
---

# Pyffe Android release

The repository is `/Users/khang.tm/qualgo-macbook/safenest/pyffe-android`. Read its `AGENTS.md` and use its existing `scripts/release.py` for this workflow.

The script is a release workflow, not a standalone local APK build: it updates branches, runs the version bump and optional changelog, creates commits, pushes, creates or reuses PRs, and may merge them using `pr-merge`. It can delete and recreate the local and remote `feature/SAF-0-bump-version` branch. A request merely to build an app does not by itself authorize commits, pushes, or PR creation and merging. Explain the workflow and obtain the required explicit authorization before running it; if the user only wants a local build, use the repository's build workflow instead. Respect any applicable instructions governing commits, pushes, and PRs.

First change into the repository, then run the appropriate command:

```bash
cd /Users/khang.tm/qualgo-macbook/safenest/pyffe-android
```

Select the release as requested:

- Latest release branch: `python3 scripts/release.py --latest`.
- Exact version: `python3 scripts/release.py --version XX.YY.ZZ`. A branch such as `release/v26.11.10` maps to `26.11.10`; preserve the exact numeric version. The script requires two digits in each component.
- If neither latest nor an exact version is specified, ask which to use; do not guess.

Run the Python command after the `cd` above. The script requires GitHub CLI authentication, a clean working tree, and the current branch to be `develop` or the selected release branch. It queries origin for the latest version. Do not discard or stash user changes or switch branches merely to bypass a failure without resolving the user's intent.

Stop on errors, report the output and any resulting branches or PRs, and do not blindly retry a partially completed release. Report the selected version and actual outcome; do not claim an APK was built unless verified.
