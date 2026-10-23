#!/usr/bin/env python3

# Luồng chạy: đọc .env → chọn nguồn ticket → lưu/đọc danh sách ticket
# → lấy thông tin cha → lập kế hoạch và kiểm tra trùng → xác nhận → tạo trên Jira.
# Android: 1 Dev + 2 QA; iOS: chỉ 2 QA; có cả Android + iOS hoặc không có: bỏ qua.
# Các bước xác nhận cho phép dừng trước khi ghi file hoặc tạo sub-task.

import sys

import re
import requests
from pathlib import Path

# Thêm thư mục gốc scripts vào đường dẫn import để dùng helper khi chạy trực tiếp.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helper.interactive_input import confirm_input, read_input

SCRIPTS_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPTS_DIR.parent / ".env"
STORIES_FILE = SCRIPTS_DIR / "create_jira_sub_tasks_stories.md"

# ID field Team, component QA và issue type Sub-task phụ thuộc cấu hình Jira này.
TEAM_FIELD = "customfield_10361"
# Tách điều kiện Dev/QA để iOS vẫn có QA nhưng không sinh Dev sub-task.
DEV_COMPONENTS = {"Android"}
QA_COMPONENTS = {"Android", "iOS"}
QA_COMPONENT = {"id": "11175", "name": "QA"}
EXCLUDE_ISSUE_TYPES = {"Sub-task", "Spike"}


def _check_response(response, context=""):
    """Check a requests response for errors and exit with a clear message."""
    # Lỗi HTTP sẽ dừng toàn bộ script; sub-task đã tạo trước đó không được hoàn tác.
    if response.ok:
        return
    status = response.status_code
    try:
        body = response.json()
        message = body.get("message") or body.get("errorMessages", [response.text])[0]
    except Exception:
        message = response.text or "Unknown error"
    label = f" ({context})" if context else ""
    print(f"\nERROR: Jira API returned {status}{label}")
    print(f"  {message}")
    if status == 401:
        print("\n  Your credentials are invalid. Check JIRA_EMAIL and JIRA_API_TOKEN in .env")
    elif status == 403:
        print("\n  Your account does not have permission for this action.")
        print("  Check that your API token is still valid at:")
        print("    https://id.atlassian.com/manage-profile/security/api-tokens")
    elif status == 404:
        print("\n  The requested resource was not found. Check that the issue key or board ID is correct.")
    sys.exit(1)


def load_env():
    # Đọc .env ở thư mục gốc scripts, bỏ dòng trống/comment và tách tại dấu '=' đầu tiên.
    # Đây là parser đơn giản: giữ nguyên dấu nháy trong value, không đọc os.environ.
    env_path = ENV_FILE
    if not env_path.exists():
        print(f"[ERROR] .env file not found at {env_path}")
        sys.exit(1)
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def confirm_or_cancel(prompt):
    # Người dùng không đồng ý thì thoát bình thường, không chạy các bước tiếp theo.
    if not confirm_input(prompt):
        sys.exit(0)



def extract_board_id(board_url):
    # Lấy phần số sau /boards/ trong JIRA_BOARD_URL để gọi Jira Agile API.
    m = re.search(r"/boards/(\d+)", board_url)
    if not m:
        print(f"[ERROR] Could not extract board ID from JIRA_BOARD_URL: {board_url}")
        sys.exit(1)
    return m.group(1)


# ── Board / sprint helpers ────────────────────────────────────────────────────
# Các hàm lấy danh sách chỉ gọi một trang: tối đa 50 sprint hoặc 200 issue;
# chưa lấy tiếp các trang còn lại nếu Jira có nhiều dữ liệu hơn.

def fetch_sprints(base_url, auth, board_id):
    url = f"{base_url}/rest/agile/1.0/board/{board_id}/sprint?maxResults=50"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    _check_response(response, f"fetching sprints for board {board_id}")
    return response.json()["values"]


def fetch_sprint_issues(base_url, auth, sprint_id):
    url = f"{base_url}/rest/agile/1.0/sprint/{sprint_id}/issue?maxResults=200&fields=summary,status,issuetype"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    _check_response(response, f"fetching issues for sprint {sprint_id}")
    return response.json()["issues"]


def fetch_backlog_issues(base_url, auth, board_id):
    url = f"{base_url}/rest/agile/1.0/board/{board_id}/backlog?maxResults=200&fields=summary,status,issuetype"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    _check_response(response, f"fetching backlog for board {board_id}")
    return response.json()["issues"]


INCLUDE_STATUSES = {"Backlog", "Ready for Development"}


def filter_backlog_tasks(issues):
    # Áp dụng cho cả nguồn sprint và backlog: chỉ giữ Backlog/Ready for Development,
    # loại Sub-task và Spike. Các issue type khác vẫn có thể làm ticket cha.
    return [
        i for i in issues
        if i["fields"]["status"]["name"] in INCLUDE_STATUSES
        and i["fields"]["issuetype"]["name"] not in EXCLUDE_ISSUE_TYPES
    ]


# ── Story helpers ─────────────────────────────────────────────────────────────

def fetch_story(base_url, auth, key):
    # Chỉ yêu cầu các field phục vụ hiển thị, kế thừa dữ liệu và kiểm tra sub-task cũ.
    fields = f"summary,status,labels,components,{TEAM_FIELD},subtasks"
    url = f"{base_url}/rest/api/3/issue/{key}?fields={fields}"
    response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    _check_response(response, f"fetching issue {key}")
    return response.json()


def fetch_existing_subtask_titles(base_url, auth, subtasks):
    # Đọc summary từng sub-task và gom thành set để tra cứu tiêu đề trùng.
    # So sánh chính xác chuỗi, không xét component, trạng thái hoặc người phụ trách.
    titles = set()
    for sub in subtasks:
        url = f"{base_url}/rest/api/3/issue/{sub['id']}?fields=summary"
        response = requests.get(url, auth=auth, headers={"Accept": "application/json"})
        _check_response(response, f"fetching subtask {sub['id']}")
        titles.add(response.json()["fields"]["summary"])
    return titles


def parse_story(data, base_url):
    # Chuẩn hóa dữ liệu để hiển thị và lập kế hoạch. Team có thể là list hoặc dict.
    # Giữ cả tên component/team cho phần hiển thị và dữ liệu gốc cho payload tạo task.
    fields = data["fields"]
    key = data["key"]
    team_field = fields.get(TEAM_FIELD)
    team_values = [t["value"] for t in team_field] if isinstance(team_field, list) else (
        [team_field["value"]] if isinstance(team_field, dict) else []
    )
    return {
        "key": key,
        "link": f"{base_url}/browse/{key}",
        "summary": fields["summary"],
        "status": fields["status"]["name"],
        "labels": fields.get("labels", []),
        "components": [c["name"] for c in fields.get("components", [])],
        "components_raw": fields.get("components", []),
        "team": team_values,
        "subtasks": fields.get("subtasks", []),
        TEAM_FIELD: fields.get(TEAM_FIELD),
    }


def parse_summary_tag(summary):
    """Extract leading [Tag] from summary, e.g. '[Droid] Some title' -> ('[Droid]', 'Some title')."""
    m = re.match(r'(\[[^\]]+\])\s*(.*)', summary)
    if m:
        return m.group(1), m.group(2)
    return "", summary


def build_plan(story, qa_assignee_id=""):
    # Chỉ xây dựng dữ liệu trong bộ nhớ; hàm này không gọi API hay tạo issue.
    # Chỉ xử lý ticket có đúng một nền tảng Android hoặc iOS.
    # Component khác có thể đi kèm, nhưng có cả hai nền tảng thì bỏ qua toàn bộ.
    mobile_components = set(story["components"]) & QA_COMPONENTS
    if len(mobile_components) != 1:
        return []

    tasks = []
    dev_comps = [c for c in story["components"] if c in DEV_COMPONENTS]

    for comp in dev_comps:
        # Chỉ Android thuộc DEV_COMPONENTS. Dev giữ tiêu đề cha với tiền tố [Dev],
        # component tương ứng, labels và Team; không truyền assignee khi tạo.
        comp_raw = [c for c in story["components_raw"] if c["name"] == comp]
        tasks.append({
            "summary": f"[Dev]{story['summary']}",
            "type": "Dev",
            "components": comp_raw,
            "labels": story["labels"],
            "team": story[TEAM_FIELD],
            "assignee": None,
        })

    if any(c in QA_COMPONENTS for c in story["components"]):
        # Ticket đã qua kiểm tra một nền tảng thì tạo một cặp QA cho ticket cha.
        # QA dùng component QA riêng.
        # Tách tag đầu tiên để giữ tag trước tên công việc, ví dụ:
        # [iOS] Login → [QA][iOS] Execute test - Login.
        # QA kế thừa labels/Team và chỉ gán assignee khi có cấu hình account ID.
        tag, clean_title = parse_summary_tag(story["summary"])
        qa_prefix = f"[QA]{tag} " if tag else "[QA] "
        for action in ("Execute test", "Create test cases"):
            tasks.append({
                "summary": f"{qa_prefix}{action} - {clean_title}",
                "type": "QA",
                "components": [QA_COMPONENT],
                "labels": story["labels"],
                "team": story[TEAM_FIELD],
                "assignee": qa_assignee_id or None,
            })

    return tasks


def create_sub_task(base_url, auth, project_key, parent_key, task):
    # Chuyển kế hoạch thành payload Jira: nối với ticket cha, dùng issue type 10003
    # và chỉ gửi ID của component. Team/assignee được thêm khi có giá trị.
    url = f"{base_url}/rest/api/3/issue"
    fields = {
        "project": {"key": project_key},
        "parent": {"key": parent_key},
        "issuetype": {"id": "10003"},  # Sub-task
        "summary": task["summary"],
        **({"components": [{"id": c["id"]} for c in task["components"]]} if task["components"] else {}),
        "labels": task["labels"],
    }
    if task["team"]:
        fields[TEAM_FIELD] = task["team"]
    if task.get("assignee"):
        fields["assignee"] = {"accountId": task["assignee"]}

    response = requests.post(
        url, json={"fields": fields}, auth=auth, headers={"Accept": "application/json"}
    )
    _check_response(response, f"creating sub-task for {parent_key}")
    data = response.json()
    return data["key"], f"{base_url}/browse/{data['key']}"


def parse_key(line):
    # Chấp nhận mã như SAF-260 hoặc link /browse/SAF-260, bỏ query string của link.
    line = line.strip()
    if "/browse/" in line:
        return line.rstrip("/").split("/browse/")[-1].split("?")[0]
    return line


def read_story_keys():
    # File là nguồn danh sách chung cho mọi chế độ; mỗi dòng là một mã hoặc link.
    # Bỏ dòng trống/comment. Dừng nếu file không tồn tại hoặc không có ticket.
    if not STORIES_FILE.exists():
        print(f"[ERROR] Stories file not found: {STORIES_FILE}")
        sys.exit(1)
    keys = []
    for line in STORIES_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.append(parse_key(line))
    if not keys:
        print(f"[ERROR] No story keys found in {STORIES_FILE.name}")
        sys.exit(1)
    return keys


def write_stories_file(keys):
    # Ghi đè toàn bộ file bằng hướng dẫn định dạng và danh sách vừa lấy từ board.
    # main() hỏi xác nhận trước khi gọi hàm này. read_story_keys() đọc lại file
    # ngay sau đó; người dùng cũng có thể chỉnh tay và dùng lại ở lần chạy sau.
    lines = [
        "# Stories",
        "# One entry per line. Lines starting with # are ignored.",
        "# Accepts ticket ID or full Jira link, e.g.:",
        "#   SAF-260",
        "#   https://aottws.atlassian.net/browse/SAF-260",
    ] + keys
    STORIES_FILE.write_text("\n".join(lines) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Bước chuẩn bị: bắt buộc base URL/email/API token; board URL và QA assignee
    # là tùy chọn. requests dùng cặp email/token làm thông tin xác thực Basic Auth.
    env = load_env()
    base_url = env.get("JIRA_BASE_URL", "").rstrip("/")
    email = env.get("JIRA_EMAIL", "")
    token = env.get("JIRA_API_TOKEN", "")
    qa_assignee_id = env.get("JIRA_QA_ASSIGNEE_ID", "")
    board_url = env.get("JIRA_BOARD_URL", "")

    if not all([base_url, email, token]):
        print("[ERROR] JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN must all be set in .env")
        sys.exit(1)

    auth = (email, token)

    # ── Step 0: Pick a group from the board ───────────────────────────────────
    # Có board URL: hiển thị sprint active/future, backlog và tùy chọn dùng file cũ.
    # Không có board URL: bỏ qua menu và đi thẳng đến bước đọc file hiện có.
    board_id = extract_board_id(board_url) if board_url else None

    if board_id:
        print("=== Board Groups ===\n")
        sprints = fetch_sprints(base_url, auth, board_id)
        active_future = [s for s in sprints if s["state"] in ("active", "future")]

        # Đặt nguồn file thường dùng ở option 1; sprint và backlog nằm phía sau.
        groups = [{
            "label": f"Use {STORIES_FILE.name} directly",
            "type": "stories_file",
            "id": None,
        }]
        for s in active_future:
            groups.append({"label": f"{s['name']} ({s['state']})", "type": "sprint", "id": s["id"]})
        groups.append({"label": "Backlog (no sprint)", "type": "backlog", "id": board_id})

        for i, g in enumerate(groups, 1):
            print(f"  {i}. {g['label']}")

        print()
        while True:
            choice = read_input(f"Select a group [1-{len(groups)}]: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(groups):
                selected = groups[int(choice) - 1]
                break
            print(f"  Please enter a number between 1 and {len(groups)}.")

        if selected["type"] == "stories_file":
            print(f"\nUsing existing {STORIES_FILE.name}...")
        else:
            # Chọn sprint/backlog: lấy issue, lọc status/type, hiển thị kết quả
            # và xin xác nhận trước khi thay nội dung file danh sách ticket.
            print(f"\nFetching '{selected['label']}'...")
            if selected["type"] == "sprint":
                issues = fetch_sprint_issues(base_url, auth, selected["id"])
            else:
                issues = fetch_backlog_issues(base_url, auth, board_id)

            tasks = filter_backlog_tasks(issues)
            print(f"Found {len(tasks)} Backlog / Ready for Development tasks (sub-tasks excluded).\n")
            for issue in tasks:
                print(f"  [{issue['key']}] [{issue['fields']['issuetype']['name']}] {issue['fields']['summary']}")

            confirm_or_cancel(
                f"Update {STORIES_FILE.name} with these {len(tasks)} tasks?"
            )

            keys = [i["key"] for i in tasks]
            write_stories_file(keys)
            print(f"{STORIES_FILE.name} updated with {len(keys)} keys.\n")

    # ── Step 1: Fetch and display all stories ─────────────────────────────────
    # Mọi nhánh đều đọc danh sách từ file, sau đó tải chi tiết từng ticket lên màn hình.
    # Dùng file trực tiếp sẽ không áp dụng lại bộ lọc status/type của nguồn board.
    # Xác nhận ở cuối bước giúp kiểm tra ticket cha trước khi lập kế hoạch.
    story_keys = read_story_keys()
    print("=== Fetching Stories ===\n")
    stories = []
    for key in story_keys:
        data = fetch_story(base_url, auth, key)
        story = parse_story(data, base_url)
        stories.append(story)
        print(f"  [{story['key']}] {story['summary']}")
        print(f"    Link       : {story['link']}")
        print(f"    Status     : {story['status']}")
        print(f"    Team       : {', '.join(story['team']) or 'N/A'}")
        print(f"    Labels     : {', '.join(story['labels']) or 'N/A'}")
        print(f"    Components : {', '.join(story['components']) or 'N/A'}")
        print()

    confirm_or_cancel("Stories look correct? Continue with planning")

    # ── Step 2: Build and display plan ────────────────────────────────────────
    # Lập kế hoạch Dev/QA theo component và chụp danh sách tiêu đề sub-task hiện có.
    # Đánh dấu các tiêu đề trùng để bỏ qua; chưa tạo gì trên Jira ở bước này.
    # Lưu story, plan và existing_titles để bước tạo dùng đúng kế hoạch đã hiển thị.
    print("\n=== Sub-task Plan ===\n")
    story_plans = []
    problem_stories = []
    for story in stories:
        plan = build_plan(story, qa_assignee_id)
        if not plan:
            mobile_components = set(story["components"]) & QA_COMPONENTS
            reason = (
                "Has both Android and iOS components; only one platform is allowed."
                if len(mobile_components) > 1
                else "Missing Android or iOS component."
            )
            problem_stories.append((story, reason))
            continue
        existing_titles = fetch_existing_subtask_titles(base_url, auth, story["subtasks"])
        story_plans.append((story, plan, existing_titles))

    # Gom ticket hợp lệ và ticket có vấn đề thành hai phần để dễ kiểm tra.
    # Ticket có vấn đề không nằm trong story_plans nên không được tạo sub-task.
    print(f"--- OK ({len(story_plans)} tickets) ---\n")
    if not story_plans:
        print("  None.\n")
    for story, plan, existing_titles in story_plans:
        new_count = sum(task["summary"] not in existing_titles for task in plan)
        print(f"  [OK] [{story['key']}] {story['summary']}")
        print(f"    Components: {', '.join(story['components'])}")
        print(f"    Sub-tasks: {new_count} to create, {len(plan) - new_count} already exist")
        for task in plan:
            if task["summary"] in existing_titles:
                print(f"    - {task['summary']}  [skip: already exists]")
            else:
                print(f"    - {task['summary']}  [create]")
        print()

    print(f"--- ISSUES / SKIPPED ({len(problem_stories)} tickets) ---\n")
    if not problem_stories:
        print("  None.\n")
    for story, reason in problem_stories:
        print(f"  [ISSUE] [{story['key']}] {story['summary']}")
        print(f"    Components: {', '.join(story['components']) or 'N/A'}")
        print(f"    Reason: {reason}")
        print()

    confirm_or_cancel("Proceed with creating sub-tasks?")

    # ── Step 3: Create sub-tasks ──────────────────────────────────────────────
    # Chỉ tới đây sau khi người dùng đồng ý tạo. Project được suy ra từ key đầu tiên,
    # nên danh sách đầu vào cần thuộc cùng một project.
    print("\n=== Creating Sub-tasks ===\n")
    project_key = story_keys[0].split("-")[0]

    for story, plan, existing_titles in story_plans:
        if not plan:
            continue
        print(f"  [{story['key']}]")
        for task in plan:
            # Dùng danh sách tiêu đề đã lấy ở bước 2, không tải lại trước mỗi lần tạo.
            # Task trùng được bỏ qua; task mới được POST lần lượt và in key/link.
            if task["summary"] in existing_titles:
                print(f"    Skipped (already exists): {task['summary']}")
                continue
            key, link = create_sub_task(base_url, auth, project_key, story["key"], task)
            print(f"    Created [{key}] {task['summary']}")
            print(f"            {link}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
