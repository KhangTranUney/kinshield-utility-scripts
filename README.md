# KinShield utility scripts

## 1. Chuẩn bị

### 1.1 Công cụ và môi trường Python

Chạy các lệnh từ thư mục gốc của repo. Cài Python 3, Git và `curl`, sau đó tạo môi trường Python bên ngoài repo:

```sh
python3 -m venv ~/.venvs/kinshield-utility-scripts
source ~/.venvs/kinshield-utility-scripts/bin/activate
python3 -m pip install requests 'urllib3<2' google-auth PyYAML
```

Kích hoạt lại môi trường bằng lệnh `source` ở trên mỗi khi mở terminal mới. `urllib3<2` tương thích với Python macOS dùng LibreSSL 2.8.3. Chỉ cần cấu hình credentials cho những chức năng sẽ sử dụng.

## 2. Cấu hình `.env`

Tạo file `.env` tại thư mục gốc repo và điền các giá trị cần dùng:

### 2.1 Jira và Confluence

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
```

`JIRA_BASE_URL`, `JIRA_EMAIL` và `JIRA_API_TOKEN` cần cho script tạo sub-task và báo cáo Jira. `JIRA_BOARD_URL` cho phép chọn sprint/backlog từ board; `JIRA_QA_ASSIGNEE_ID` là ID người được giao QA tùy chọn.

`CONFLUENCE_EMAIL` và `CONFLUENCE_TOKEN` cần để clone weekly pages. Quy trình báo cáo Jira hàng tuần cũng cần các giá trị này vì tạo weekly pages trước khi xuất báo cáo.

Tạo Atlassian API token tại [trang quản lý API token](https://id.atlassian.com/manage-profile/security/api-tokens).

### 2.2 Teams

```dotenv
# Teams: webhook mặc định hoặc webhook theo nhóm
TEAMS_WEBHOOK_URL=
TEAMS_WEBHOOK_URL_DEV_OPS=
```

Dùng `TEAMS_WEBHOOK_URL` cho nhóm mặc định, hoặc `TEAMS_WEBHOOK_URL_<GROUP>` cho từng nhóm. Tên nhóm viết hoa, thay dấu cách và dấu gạch nối bằng `_`; ví dụ `dev-ops` dùng `TEAMS_WEBHOOK_URL_DEV_OPS`.

### 2.3 Lưu ý về credentials

Điền giá trị không có dấu nháy: một số script giữ nguyên dấu nháy khi đọc. File `.env` đã được Git bỏ qua; không commit credentials. Cấu hình Telegram được trình bày trong mục Telegram bot bên dưới.

## 3. Google service accounts

Đặt JSON service account vào các đường dẫn tương ứng với project và môi trường cần dùng. Các thư mục credentials đã được Git bỏ qua.

### 3.1 Google Billing

Google Billing dùng một file cho cả prod và non-prod của mỗi sản phẩm:

```text
google-billing/credentials/service-account-pyffe.json
google-billing/credentials/service-account-strazee.json
google-billing/credentials/service-account-kinsense.json
google-billing/credentials/service-account-kinshield.json
google-billing/credentials/service-account-ferrous-tine.json
```

File `ferrous-tine` được dùng bởi `get_pubsub_resources.py`. Các file còn lại dùng cho subscription và product catalog. Cấu hình prod/QA nằm trong `google-billing/configs/`.

### 3.2 Firebase Remote Config

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

## 4. Các script và cách chạy

Chạy các lệnh dưới đây từ thư mục gốc repo, sau khi cấu hình credentials cần thiết.

### 4.1 Tạo Jira sub-task

Tạo các sub-task trong Jira:

```sh
python3 utilities/create_jira_sub_tasks.py
```

Xem `utilities/create_jira_sub_tasks_stories.md` để biết chi tiết về sub-task.

### 4.2 Báo cáo tuần

Clone các weekly pages trên Confluence để chuẩn bị cho báo cáo:

```sh
python3 utilities/clone_weekly_pages.py
```

Script này chỉ tạo hoặc dùng lại các trang, chưa tổng hợp nội dung báo cáo.

### 4.3 Google Billing

Xem trước các subscription sẽ tạo:

```sh
python3 google-billing/create_subscriptions.py --dry-run
```

Xem `google-billing/billing_setup_guideline.md` để biết các script và bước cấu hình Google Billing.

### 4.4 Firebase Remote Config

Đồng bộ Remote Config về file cấu hình local:

```sh
python3 remote-config/sync_remote_config.py
```

### 4.5 GitHub và release branches

**Work GitHub token:** Lưu token vào `~/.zshrc` bằng lệnh sau, nhập token khi được yêu cầu, rồi chạy `source ~/.zshrc`. Script không dùng `.env` và không kiểm tra token với GitHub.

```sh
python3 utilities/setup_work_github_token.py
```

**Pull branch:** Fetch và fast-forward các branch có upstream trong các repo đã cấu hình:

```sh
python3 utilities/pull_latest_branches.py
```

**Tạo release branches:** Script tìm các repo `kinshield-android`, `kinshield-core-features-android` và `kinshield-features-version-android` trong cùng thư mục cha với repo này. Script thực hiện các thao tác Git, bao gồm commit và push, sau bước xem trước và xác nhận.

```sh
python3 utilities/create_release_branches.py
```

## 5. Codex skills

Các skill trong `.codex/skills/` hướng dẫn Codex thực hiện những workflow có sẵn. Có thể yêu cầu bằng ngôn ngữ tự nhiên hoặc gọi tên skill trực tiếp:

- `devops-jira-ticket`: soạn hoặc tạo Jira ticket cho đội DevOps.
- `jira-team-weekly-report`: chạy `utilities/clone_weekly_pages.py` để tạo hoặc dùng lại các trang, sau đó tổng hợp báo cáo Jira tuần và xuất bản lên Confluence. Chạy riêng script clone chỉ chuẩn bị các trang, chưa tạo nội dung báo cáo.
- `pr-merge`: approve và merge một hoặc nhiều GitHub PR.
- `pull-latest-branches`: chạy `utilities/pull_latest_branches.py` để cập nhật các branch local có upstream trong các repo đã cấu hình.
- `send-message-to-teams-webhook`: gửi tin nhắn tới nhóm Microsoft Teams qua webhook.

Xem `SKILL.md` trong từng thư mục skill để biết chi tiết workflow và cấu hình.

## 6. Telegram bot

### 6.1 Token và tài khoản Telegram

Thêm các biến sau vào `.env` ở thư mục gốc:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
```

`TELEGRAM_BOT_TOKEN` là token do BotFather cấp; `TELEGRAM_ALLOWED_USER_ID` là ID số của tài khoản Telegram được phép nhắn riêng với bot, không phải username của bot.

### 6.2 GitHub token cho PR merge

Để merge PR qua bot, cài GitHub CLI `gh` và export ít nhất một trong `GITHUB_TOKEN_MINE` và `GITHUB_TOKEN_ALT` trong `~/.zshrc`. Các token này khác với `WORK_GITHUB_TOKEN`. Khi khởi động, bot chạy `source ~/.zshrc` và truyền hai token này vào môi trường của Codex. Script thử token chính trước, sau đó thử token dự phòng khi phù hợp. Token cần quyền review và merge PR trên các repo liên quan. Thay đổi `~/.zshrc` cần khởi động lại bot.

### 6.3 Khởi động bot

Cài Codex CLI tại `/opt/homebrew/bin/codex` và đăng nhập Codex trên máy. Tạo môi trường Python như phần Chuẩn bị, sau đó chạy:

```sh
python3 telegram-bot/start_telegram_bot.py
```

### 6.4 Tạo lệnh global

Để gọi từ bất kỳ thư mục nào, có thể tạo lệnh `start-telegram-bot` trong `~/.local/bin` (thư mục này cần có trong `PATH`):

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/telegram-bot/start_telegram_bot.py" ~/.local/bin/start-telegram-bot
```

### 6.5 Vận hành và quyền truy cập

Lệnh khởi động dùng môi trường `~/.venvs/kinshield-utility-scripts` nếu có, cài và khởi động bot bằng macOS `launchd`, rồi hiển thị log liên tục và báo lỗi nếu tiến trình bot dừng hoặc khởi động lại. Nhấn Ctrl+C để dừng bot. Chạy lại lệnh sau khi thay đổi `.env` để bot đọc cấu hình mới.

Bot chỉ nhận tin nhắn riêng từ user ID đã cấu hình. Codex chạy với full access và không có sandbox hay bước duyệt lệnh của Codex, nên có thể truy cập các file và dịch vụ mà tài khoản macOS của bạn có quyền truy cập. Gửi `/new` để bắt đầu hội thoại Codex mới.

### 6.6 Kiểm tra trạng thái và log

```sh
launchctl print gui/$(id -u)/com.qlg.tasks.telegram
tail -n 50 ~/Library/Logs/qlg-tasks-bot/bot.log
tail -n 50 ~/Library/Logs/qlg-tasks-bot/error.log
```

Trạng thái `running` cho biết tiến trình đang chạy; nhắn tin cho bot để kiểm tra kết nối Telegram và Codex.
