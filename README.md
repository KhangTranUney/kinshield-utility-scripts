# KinShield utility scripts

## Chuẩn bị

Chạy các lệnh từ thư mục gốc của repo. Cài Python 3, Git và `curl`, sau đó tạo môi trường Python bên ngoài repo:

```sh
python3 -m venv ~/.venvs/kinshield-utility-scripts
source ~/.venvs/kinshield-utility-scripts/bin/activate
python3 -m pip install requests google-auth PyYAML
```

Kích hoạt lại môi trường bằng lệnh `source` ở trên mỗi khi mở terminal mới. Chỉ cần cấu hình credentials cho những chức năng sẽ sử dụng.

## Cấu hình `.env`

Tạo file `.env` tại thư mục gốc repo và điền các giá trị cần dùng:

```dotenv
# Jira
JIRA_BASE_URL=https://aottws.atlassian.net
JIRA_EMAIL=
JIRA_API_TOKEN=

# Tùy chọn cho script tạo Jira sub-task
JIRA_BOARD_URL=
JIRA_QA_ASSIGNEE_ID=

# Confluence
CONFLUENCE_EMAIL=
CONFLUENCE_TOKEN=

# Teams: webhook mặc định hoặc webhook theo nhóm
TEAMS_WEBHOOK_URL=
TEAMS_WEBHOOK_URL_DEV_OPS=

```

- **Jira:** `JIRA_BASE_URL`, `JIRA_EMAIL` và `JIRA_API_TOKEN` cần cho script tạo sub-task và báo cáo Jira. `JIRA_BOARD_URL` cho phép chọn sprint/backlog từ board; `JIRA_QA_ASSIGNEE_ID` là ID người được giao QA tùy chọn.
- **Confluence:** `CONFLUENCE_EMAIL` và `CONFLUENCE_TOKEN` cần để clone weekly pages. Quy trình báo cáo Jira hàng tuần cũng cần các giá trị này vì tạo weekly pages trước khi xuất báo cáo.
- **Teams:** dùng `TEAMS_WEBHOOK_URL` cho nhóm mặc định, hoặc `TEAMS_WEBHOOK_URL_<GROUP>` cho từng nhóm. Tên nhóm viết hoa, thay dấu cách và dấu gạch nối bằng `_`; ví dụ `dev-ops` dùng `TEAMS_WEBHOOK_URL_DEV_OPS`.

Tạo Atlassian API token tại [trang quản lý API token](https://id.atlassian.com/manage-profile/security/api-tokens). Điền giá trị không có dấu nháy: một số script giữ nguyên dấu nháy khi đọc. File `.env` đã được Git bỏ qua; không commit credentials.

## Google service accounts

Đặt JSON service account vào các đường dẫn tương ứng với project và môi trường cần dùng. Các thư mục credentials đã được Git bỏ qua.

Google Billing dùng một file cho cả prod và non-prod của mỗi sản phẩm:

```text
google-billing/credentials/service-account-pyffe.json
google-billing/credentials/service-account-strazee.json
google-billing/credentials/service-account-kinsense.json
google-billing/credentials/service-account-kinshield.json
google-billing/credentials/service-account-ferrous-tine.json
```

File `ferrous-tine` được dùng bởi `get_pubsub_resources.py`. Các file còn lại dùng cho subscription và product catalog. Cấu hình prod/QA nằm trong `google-billing/configs/`.

Firebase Remote Config dùng file riêng theo môi trường:

```text
remote-config/credentials/service-account-pyffe-nonprod.json
remote-config/credentials/service-account-pyffe-prod.json
remote-config/credentials/service-account-kinshield-non-prod.json
remote-config/credentials/service-account-kinshield-prod.json
remote-config/credentials/service-account-shieldnet360-non-prod.json
remote-config/credentials/service-account-shieldnet360-prod.json
```

Cấu hình tương ứng nằm trong `remote-config/configs/`. Service account cần quyền phù hợp với API và project được chọn.

## GitHub và release branches

Nếu cần lưu work GitHub token vào `~/.zshrc`, chạy `python3 utilities/setup_work_github_token.py`, nhập token khi được yêu cầu, rồi chạy `source ~/.zshrc`. Script này không dùng `.env` và không kiểm tra token với GitHub.

`local-scripts-backup/pr-merge` cần GitHub CLI `gh` và ít nhất một biến môi trường `GITHUB_TOKEN_MINE` hoặc `GITHUB_TOKEN_ALT`; script không tự đọc `.env` khi chạy trực tiếp từ terminal. Hai token này khác với `WORK_GITHUB_TOKEN`.

`utilities/create_release_branches.py` tìm các repo `kinshield-android`, `kinshield-core-features-android` và `kinshield-features-version-android` trong cùng thư mục cha với repo này. Script thực hiện các thao tác Git, bao gồm commit và push, sau bước xem trước và xác nhận.

## Chạy script

Ví dụ, từ thư mục gốc repo:

```sh
python3 utilities/clone_weekly_pages.py
python3 utilities/create_jira_sub_tasks.py
python3 google-billing/create_subscriptions.py --dry-run
python3 remote-config/sync_remote_config.py
```

Xem hướng dẫn cụ thể trong `google-billing/billing_setup_guideline.md`, `utilities/create_jira_sub_tasks_stories.md` và các file `.codex/skills/*/SKILL.md` khi dùng những quy trình tương ứng.

## Telegram bot

Thêm các biến sau vào `.env` ở thư mục gốc:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
```

`TELEGRAM_BOT_TOKEN` là token do BotFather cấp; `TELEGRAM_ALLOWED_USER_ID` là ID số của tài khoản Telegram được phép nhắn riêng với bot, không phải username của bot.

Để merge PR qua bot, export ít nhất một trong `GITHUB_TOKEN_MINE` và `GITHUB_TOKEN_ALT` trong `~/.zshrc`. Khi khởi động, bot chạy `source ~/.zshrc` và truyền hai token này vào môi trường của Codex. Script thử token chính trước, sau đó thử token dự phòng khi phù hợp. Token cần quyền review và merge PR trên các repo liên quan. Thay đổi `~/.zshrc` cần khởi động lại bot.

Cài Codex CLI tại `/opt/homebrew/bin/codex` và đăng nhập Codex trên máy. Kích hoạt môi trường Python đã cài `requests`, sau đó chạy:

```sh
python3 telegram-bot/start_telegram_bot.py
```

Để gọi từ bất kỳ thư mục nào, có thể tạo lệnh `start-telegram-bot` trong `~/.local/bin` (thư mục này cần có trong `PATH`):

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/telegram-bot/start_telegram_bot.py" ~/.local/bin/start-telegram-bot
```

Lệnh này cài và khởi động bot bằng macOS `launchd`, dùng Python đang chạy lệnh, rồi hiển thị log liên tục và báo lỗi nếu tiến trình bot dừng hoặc khởi động lại. Nhấn Ctrl+C để dừng bot. Chạy lại lệnh sau khi thay đổi `.env` để bot đọc cấu hình mới. Bot chỉ nhận tin nhắn riêng từ user ID đã cấu hình. Codex chạy với full access và không có sandbox hay bước duyệt lệnh của Codex, nên có thể truy cập các file và dịch vụ mà tài khoản macOS của bạn có quyền truy cập. Gửi `/new` để bắt đầu hội thoại Codex mới.

Kiểm tra trạng thái và log:

```sh
launchctl print gui/$(id -u)/com.qlg.tasks.telegram
tail -n 50 ~/Library/Logs/qlg-tasks-bot/bot.log
tail -n 50 ~/Library/Logs/qlg-tasks-bot/error.log
```

Trạng thái `running` cho biết tiến trình đang chạy; nhắn tin cho bot để kiểm tra kết nối Telegram và Codex.
