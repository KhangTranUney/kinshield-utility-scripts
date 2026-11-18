#!/usr/bin/env python3
"""Start the Telegram relay and keep it running after login on macOS."""

import os
import plistlib
import re
import subprocess
import sys
import time
from collections import deque
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
service = f'{domain}/{label}'
print(f'Waiting for bot. Logs: {logs}', flush=True)


def running_pid():
    result = subprocess.run(['launchctl', 'print', service], capture_output=True, text=True)
    match = re.search(r'^\s*pid = (\d+)\s*$', result.stdout, re.MULTILINE)
    return int(match.group(1)) if result.returncode == 0 and match else None


deadline = time.monotonic() + 15
pid = None
while time.monotonic() < deadline:
    pid = running_pid()
    if pid is not None:
        break
    time.sleep(0.5)
if pid is None:
    raise SystemExit(f'Bot did not start. Check {logs / "error.log"}.')

print(f'Bot running (PID {pid}). Showing recent logs and following new output.', flush=True)
paths = [logs / 'bot.log', logs / 'error.log']
for path in paths:
    path.touch(exist_ok=True)
handles = [path.open('r', encoding='utf-8', errors='replace') for path in paths]
try:
    for path, handle in zip(paths, handles):
        recent = deque(handle, maxlen=50)
        if recent:
            print(f'--- {path.name} (last 50 lines) ---', flush=True)
            print(''.join(recent), end='', flush=True)
    while True:
        for path, handle in zip(paths, handles):
            if path.stat().st_size < handle.tell():
                handle.seek(0)
            output = handle.read()
            if output:
                print(f'[{path.name}] {output}', end='', flush=True)
        if running_pid() != pid:
            raise SystemExit(f'Bot process stopped or restarted. Check {logs / "error.log"}.')
        time.sleep(3)
except KeyboardInterrupt:
    print('\nStopping bot...', flush=True)
    result = subprocess.run(['launchctl', 'bootout', service], capture_output=True, text=True)
    if result.returncode:
        print('Could not stop the bot. Check its launchctl status.', file=sys.stderr, flush=True)
        raise SystemExit(1)
    print('Bot stopped.', flush=True)
finally:
    for handle in handles:
        handle.close()
