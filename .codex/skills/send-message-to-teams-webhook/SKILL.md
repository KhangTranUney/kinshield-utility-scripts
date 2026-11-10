---
name: send-message-to-teams-webhook
description: Send a requested message to a Microsoft Teams group through its configured Power Automate webhook. Use when the user asks to send a Teams group message using a webhook.
---

# Teams webhook

Send only when the user explicitly requests sending a message. Before sending, read only the names of keys beginning `TEAMS_WEBHOOK_URL_` in the project root `.env` and ask the user to choose or confirm a group from those names. Do not read or display webhook values while listing groups. If the message is missing, ask for it too. Do not send until the user has selected or confirmed the group and explicitly requested the message. Do not send a test message without authorization.

From the project root, run `python3 .codex/skills/send-message-to-teams-webhook/scripts/_send_teams_message.py --group GROUP --count N 'MESSAGE'`. Use `--count N` to send N separate messages with the same content; omit it for one message. The script sends sequentially and stops at the first failure, reporting how many requests were accepted. The script reads `TEAMS_WEBHOOK_URL_GROUP` from the environment or `.env` in the current directory (environment takes precedence). Normalize the group name to uppercase, replacing hyphens and spaces with underscores. For example, group `dev-ops` uses `TEAMS_WEBHOOK_URL_DEV_OPS`. For a single default group, omit `--group` and configure `TEAMS_WEBHOOK_URL`. Use `--env-file PATH` to select another configuration file.

If the relevant webhook is missing, ask the user for the group mapping or URL. Keep webhook URLs out of tracked files and command arguments, and do not print them. The webhook receives JSON with a `text` field; the Power Automate flow must map that field to a Teams message. An HTTP success means the flow accepted the request, not necessarily that Teams delivered the message. On failure report the status and do not automatically retry, since a retry could duplicate a message.
