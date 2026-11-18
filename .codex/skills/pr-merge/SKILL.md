---
name: pr-merge
description: Approve and merge one or more GitHub pull requests using the repository's pr-merge script when the user asks to merge PRs.
---

# Approve and merge pull requests

For an explicit request to merge, obtain the GitHub PR URL or URLs from the user. If missing, ask for them. Run `bash local-scripts-backup/pr-merge <PR_URL> [<PR_URL> ...]` from the scripts repository root, passing each URL as a separate shell argument. The script validates URLs and attempts to approve each PR before merging it with a merge commit; it tries the alternate token when appropriate. Do not use this workflow if the user asks for approval only, a different merge method, or explicitly requests no approval.

The script needs `gh` and at least one of `GITHUB_TOKEN_MINE` or `GITHUB_TOKEN_ALT` in its environment. Never display or transmit token values. If credentials or permissions are unavailable, explain the failure without guessing or changing configuration. Report each PR's actual outcome, including failures or an asynchronous merge still pending; do not retry a pending or uncertain merge without checking its status first. Do not claim a PR was merged based only on submitting a request.
