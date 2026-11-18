#!/usr/bin/env python3
"""Start the Telegram relay and keep it running after login on macOS."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _telegram_codex_bot import config

try:
    config()
except (OSError, ValueError) as exc:
    raise SystemExit(f'Invalid Telegram configuration: {exc}') from None
if not Path('/opt/homebrew/bin/codex').is_file():
    raise SystemExit('Codex CLI not found at /opt/homebrew/bin/codex.')
label = 'com.qlg.tasks.telegram'
agents = Path.home() / 'Library/LaunchAgents'
logs = Path.home() / 'Library/Logs/qlg-tasks-bot'
agents.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True, mode=0o700)
plist = agents / f'{label}.plist'
settings = {
    'Label': label,
    'ProgramArguments': [sys.executable, str(root / 'telegram-bot/_telegram_codex_bot.py')],
    'WorkingDirectory': str(root),
    'RunAtLoad': True,
    'KeepAlive': True,
    'StandardOutPath': str(logs / 'bot.log'),
    'StandardErrorPath': str(logs / 'error.log'),
}
with plist.open('wb') as handle:
    plistlib.dump(settings, handle)
domain = f'gui/{os.getuid()}'
subprocess.run(['launchctl', 'bootout', f'{domain}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
print(f'Bot started. Logs: {logs}')
