# Project Rules

1. Never commit or push automatically. Commit and push only when explicitly requested by the user; an explicit request to push is sufficient confirmation. Exception: a request to release or build Pyffe Android using the `pyffe-android-release` skill explicitly authorizes the commits and pushes performed by `pyffe-android/scripts/release.py` as part of that release. Do not ask for separate confirmation for those operations.
2. Private scripts and internal helper modules must use a filename prefixed with `_` (for example, `_interactive_input.py`).
