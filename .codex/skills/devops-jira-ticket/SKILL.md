---
name: devops-jira-ticket
description: Draft or create Jira tickets for the DevOps team supporting any project from a user's task request.
---

# DevOps Jira tickets

Turn the user's task request into a clear Jira title and description for the DevOps team. Prefix the title with the relevant project names in square brackets, followed by a space and an action-oriented title: `[Project] Title` for one project or `[Project1][Project2] Title` for multiple projects. For example, use `[Pyffe][Strazee] Title` when the task concerns both. Preserve project names as supplied and ask which project is involved if it cannot be determined. Write in English by default, as in the existing ticket, unless the user requests another language.

Every ticket must state the project name, the environment (`production` or `non-production`, including the specific environment name when known), and whether there is an associated pull request. Include the PR link when one exists; otherwise explicitly state that there is no PR. Use information already supplied or available in context, and ask for any missing information rather than guessing. Obtain these details before drafting or creating the ticket.

Follow the concise style of [CI-3539](https://aottws.atlassian.net/browse/CI-3539): start directly with the request stating the action, project, and relevant system, without a greeting; list specific items as bullets when applicable, formatting technical identifiers as inline code. Add a short closing note when useful, such as how sensitive values will be provided separately through a secure channel. Never include secret values in the ticket. Include acceptance criteria when supplied or needed for clarity, without imposing a fixed template. Do not invent infrastructure details, requirements, or outcomes. Ask concise questions when missing information prevents a useful or correctly targeted ticket; otherwise identify assumptions where helpful.

For a draft request, provide the title and description without creating a ticket. When the user asks to create a ticket, create it in Jira project COMMON INFRA (`CI`) on the [COMMON INFRA Kanban board](https://aottws.atlassian.net/jira/software/c/projects/CI/boards/1455), unless the user specifies another destination. Use an available Jira integration or the repository's `.env` credentials (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`) with the Jira API; never display or commit credential values. Determine the issue type and any fields required for the issue to appear on the board. Verify the board's filter and the resulting issue's visibility where the integration permits it. A user request to create the ticket authorizes creation; do not add an extra confirmation unless required by the integration or a higher-priority instruction.

Assign each newly created ticket to the user, who will assign it to DevOps later, unless the user requests another assignee. Resolve the user's Jira account from the authenticated session; if the account cannot be identified or assigned, report the limitation rather than choosing another assignee.

When using the Jira REST API, authenticate with HTTP Basic using `JIRA_EMAIL` and `JIRA_API_TOKEN`, and use `JIRA_BASE_URL` as the base URL. The following endpoints were verified for this board:

- `GET /rest/agile/1.0/board/1455/configuration` returns the board configuration and filter ID. `GET /rest/api/3/filter/{filterId}` returns its JQL; the observed filter selects project `10882` (`CI`). Check the current filter rather than relying on it remaining unchanged.
- `GET /rest/api/3/myself` returns the authenticated Jira user's `accountId`. Use it as the user's assignee ID when the credentials belong to the user.
- `POST /rest/api/3/issue` creates an issue. For a standard Task, the observed issue type ID is `10002`; send `fields.project.key` as `CI`, `fields.issuetype.id` as `10002`, `fields.assignee.accountId` as the user's account ID, `fields.summary` as the title, and `fields.description` as an Atlassian Document Format document. If the API reports changed or required fields, inspect the applicable create metadata and adapt.
- `GET /rest/api/3/issue/{issueKey}?fields=summary,description` reads the existing content before an edit. `PUT /rest/api/3/issue/{issueKey}` updates fields, for example `{"fields":{"description":{...}}}` with the complete revised description as an Atlassian Document Format document. Preserve unrelated existing content; a successful update returns HTTP 204. Use `GET /rest/api/3/issue/{issueKey}/editmeta` if editable fields need to be checked.
- `GET /rest/agile/1.0/board/1455/issue?jql=key%20%3D%20CI-123&fields=summary,status` verifies board visibility; replace `CI-123` with the created key and URL-encode the JQL. Check that the returned issues contain the key. If visibility cannot be verified, report that limitation.

Create the issue only in the identified destination. Return its key and link, title, and a concise description of what was created. If Jira is unavailable or the destination cannot be established, provide the draft and explain what is needed to complete creation; never claim an issue was created without confirmation.
