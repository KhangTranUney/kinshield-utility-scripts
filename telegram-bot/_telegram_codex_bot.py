#!/usr/bin/env python3
"""Relay private Telegram messages from an authorized user to Codex."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'
STATE = Path.home() / 'Library/Application Support/qlg-tasks-bot/state.sqlite3'
CODEX = '/opt/homebrew/bin/codex'


def config():
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    token = values.get('TELEGRAM_BOT_TOKEN', '')
    user_id = values.get('TELEGRAM_ALLOWED_USER_ID', '')
    if not token or not user_id.isdecimal():
        raise ValueError('Set TELEGRAM_BOT_TOKEN and numeric TELEGRAM_ALLOWED_USER_ID in .env')
    return token, int(user_id), values


def api(token, method, data, timeout=45):
    response = requests.post(f'https://api.telegram.org/bot{token}/{method}', json=data, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload.get('ok'):
        raise RuntimeError(f'Telegram API error: {method}')
    return payload['result']


def send(token, chat_id, message):
    for pos in range(0, len(message), 3500):
        api(token, 'sendMessage', {'chat_id': chat_id, 'text': message[pos:pos + 3500]})


def load_github_tokens(env):
    """Source the user's zsh configuration and import only the PR tokens."""
    if not (Path(env['HOME']) / '.zshrc').is_file():
        print('GitHub tokens unavailable: ~/.zshrc does not exist.', flush=True)
        return
    command = ('source "$HOME/.zshrc" >/dev/null 2>&1 || exit 1; '
               'printf "%s\\0%s\\0" "${GITHUB_TOKEN_MINE-}" "${GITHUB_TOKEN_ALT-}"')
    try:
        result = subprocess.run(['/bin/zsh', '-c', command], env={**env, 'TERM': 'dumb'},
                                capture_output=True, timeout=30, check=True)
        parts = result.stdout.split(b'\0')
        if len(parts) != 3 or parts[-1]:
            raise ValueError('Unexpected zsh output')
        for key, value in zip(('GITHUB_TOKEN_MINE', 'GITHUB_TOKEN_ALT'), parts[:2]):
            if value:
                env[key] = value.decode('utf-8')
            else:
                env.pop(key, None)
    except (OSError, subprocess.SubprocessError, ValueError):
        print('Could not load GitHub tokens from ~/.zshrc.', flush=True)


def run_codex(message, thread, env):
    args = [CODEX, 'exec', '--json', '-C', str(ROOT),
            '--dangerously-bypass-approvals-and-sandbox']
    if thread:
        args += ['resume', thread, '-']
    else:
        args += ['-']
    prompt = ('You are answering the authorized user via Telegram. Use the relevant project skill for their request. '
              'Ask for missing information when necessary. Do not expose credentials. '
              'Follow AGENTS.md. Respond concisely in the user’s language.\n\nUser request:\n' + message)
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=ROOT, env=env)
    try:
        stdout, stderr = proc.communicate(prompt, timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return thread, 'Codex đã hết thời gian xử lý. Hãy kiểm tra trạng thái trước khi thử lại.'
    last = ''
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'thread.started':
            thread = event.get('thread_id', thread)
        item = event.get('item', {})
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            last = item.get('text', '')
    if proc.returncode:
        return thread, 'Codex gặp lỗi; kiểm tra log bot trên Mac. Không tự chạy lại tác vụ.'
    return thread, last or 'Codex đã kết thúc nhưng không trả về nội dung.'


def main():
    token, allowed, _ = config()
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(STATE)
    db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.commit()
    def get(key):
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else None
    def put(key, value):
        db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (key, str(value)))
        db.commit()

    env = os.environ.copy()
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    load_github_tokens(env)
    env.pop('TELEGRAM_BOT_TOKEN', None)
    print('Bot started.', flush=True)
    while True:
        try:
            updates = api(token, 'getUpdates', {'offset': int(get('offset') or 0), 'timeout': 30,
                                                'allowed_updates': ['message']})
            for update in updates:
                # Claim before execution: after a crash do not repeat a side effect.
                put('offset', update['update_id'] + 1)
                msg = update.get('message', {})
                chat = msg.get('chat', {})
                if chat.get('type') != 'private' or msg.get('from', {}).get('id') != allowed:
                    continue
                text = msg.get('text', '').strip()
                if not text:
                    continue
                chat_id = chat['id']
                if text == '/start':
                    send(token, chat_id, 'Xin chào! Hãy gửi yêu cầu để tôi chuyển cho Codex.')
                    continue
                if text == '/new':
                    put('thread', '')
                    send(token, chat_id, 'Đã bắt đầu cuộc hội thoại mới.')
                    continue
                send(token, chat_id, 'Đã nhận yêu cầu, Codex đang xử lý.')
                thread, result = run_codex(text, get('thread'), env)
                if thread:
                    put('thread', thread)
                send(token, chat_id, result)
        except (requests.RequestException, RuntimeError, OSError, ValueError) as exc:
            # Do not log request URLs: they contain the bot token.
            print(f'Bot error: {type(exc).__name__}; retrying in 10 seconds.', flush=True)
            time.sleep(10)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        sys.exit(1)
