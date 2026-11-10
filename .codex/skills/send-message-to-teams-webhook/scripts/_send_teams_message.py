#!/usr/bin/env python3
"""Send a message through a configured Teams Power Automate webhook."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", help="Group name used to select its webhook")
    parser.add_argument("--count", type=int, default=1, help="Number of separate messages to send")
    parser.add_argument("--env-file", type=Path, default=Path.cwd() / ".env")
    parser.add_argument("message", help="Message to send")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("Count must be at least 1")
    if not args.message.strip():
        parser.error("Message must not be empty")
    key = "TEAMS_WEBHOOK_URL"
    if args.group is not None:
        group = re.sub(r"[- ]+", "_", args.group.strip()).upper()
        if not re.fullmatch(r"[A-Z0-9_]+", group):
            parser.error("Group must contain only letters, numbers, spaces, hyphens or underscores")
        key += "_" + group
    url = os.environ.get(key, "").strip()
    try:
        if not url and args.env_file.is_file():
            for line in args.env_file.read_text(encoding="utf-8").splitlines():
                name, separator, value = line.partition("=")
                if separator and name.strip() == key:
                    url = value.strip().strip("\"'")
                    break
    except OSError:
        print("Cannot read the configuration file.", file=sys.stderr)
        return 1
    if not url:
        print(f"Missing {key} in environment or configuration file.", file=sys.stderr)
        return 1
    accepted = 0
    for _ in range(args.count):
        try:
            request = Request(url, data=json.dumps({"text": args.message}, ensure_ascii=False).encode("utf-8"),
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=30):
                accepted += 1
        except HTTPError as exc:
            print(f"Webhook returned HTTP {exc.code}; {accepted} of {args.count} requests accepted.", file=sys.stderr)
            return 1
        except (URLError, OSError, ValueError) as exc:
            print(f"Could not send to webhook ({type(exc).__name__}); {accepted} of {args.count} requests accepted. The failed request may have been received.", file=sys.stderr)
            return 1
    print(f"Webhook accepted {accepted} of {args.count} requests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
