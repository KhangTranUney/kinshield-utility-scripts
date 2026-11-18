---
name: pull-latest-branches
description: Fetch and fast-forward existing local tracking branches across the configured repositories when the user asks to update or pull the local repositories or branches.
---

# Pull latest branches

For a request to update the configured repositories, run `python3 utilities/pull_latest_branches.py` from the scripts repository root. The script fetches remotes and fast-forwards eligible existing local branches; it may update the working tree of a checked-out branch. It reports branches that cannot be updated and continues with other repositories.

The script operates on all repositories in its configured list, not a selected subset. If the user requests only a specific repository or branch, do not run the full batch; clarify or use a suitable scoped workflow. Report the outcome and the failure summary, including partial failures. Do not commit or push unless explicitly requested, as required by the repository's AGENTS.md.
