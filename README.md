# TraceCore

Truy xuất dụng cụ và quản lý khoa KSNK/CSSD trên Frappe v15 (app `tracecore` chạy cùng `erpnext`, `hrms`).
Tài liệu nguồn sự thật nằm trong [`docs/`](docs/); quy ước làm việc ở [`CLAUDE.md`](CLAUDE.md) và [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Cấu trúc

| Đường dẫn | Nội dung |
| --- | --- |
| `tracecore/core/` | Dịch vụ xuyên suốt: `gs1` (GIAI, DataMatrix, ZPL), `code_registry`, `audit`, `idempotency`, `print` |
| `tracecore/tracecore/` | Module `TraceCore`: Audit Log, Code Registry, Idempotency Key, Print Job |
| `tracecore/<module>/` | Module nghiệp vụ M1–M10 (`instrument`, `reprocessing`, … `waste`), `ui` (Page `station`) |
| `tracecore/v1/` | RPC `tracecore.v1.<domain>.<action>` |
| `frontend/` | React/TypeScript Home độc lập; build vào `tracecore/public/home/` |
| `tracecore_agent/` | Station Agent (Python stdlib): `/health`, `/print`, hàng đợi SQLite |
| `scripts/` | `build_tokens.py`, lint kiến trúc/BRU, `install_dev.sh`, `install_prod.sh`, `restore.sh`, `e2e_prepare.sh` |
| `deploy/` | Pin phiên bản, cấu hình mẫu (`*.example`), systemd agent |
| `tests_e2e/` | Playwright cho Home desktop/PDA, kiosk và Desk fallback |

## Môi trường dev

Phiên bản được ghim trong [`deploy/pins.env`](deploy/pins.env) (Frappe/ERPNext v15.123, HRMS v15.64, Python 3.11, Node 18, MariaDB 10.6, Redis 7).

```bash
scripts/install_dev.sh            # dựng bench ~/tracecore-dev, site dev + test_site (idempotent)
scripts/install_dev.sh --dry-run  # chỉ in các bước
```

Mật khẩu DB root / Administrator đọc từ biến môi trường hoặc `~/.tracecore-dev-secrets` (không commit).

## Lệnh thường dùng

```bash
# Test toàn app (CI=1 để exit code phản ánh kết quả)
CI=1 bench --site test_site run-tests --app tracecore --coverage
python -m pytest tracecore_agent                 # test Station Agent
pre-commit run --all-files                       # ruff, prettier, eslint, bandit, kiến trúc, BRU, tokens
python3 scripts/build_tokens.py                  # sinh lại tracecore/public/css/tokens.css từ docs/tokens.json
```

## Home độc lập: build và chạy local

Chạy trong WSL `Ubuntu-22.04`, tại checkout app của bench (không dùng chung `node_modules` giữa Windows và WSL):

```bash
cd ~/tracecore-dev/apps/tracecore/frontend
npm ci
npm test
npm run build
cd ~/tracecore-dev
bench --site tracecore-dev.local migrate
bench start
```

Từ PowerShell có thể chạy lệnh bench bằng `wsl -d Ubuntu-22.04 -- bash -lc 'cd ~/tracecore-dev && bench --site tracecore-dev.local migrate && bench start'`.
Mở [http://tracecore-dev.local:8000/tracecore](http://tracecore-dev.local:8000/tracecore) (hostname phải trỏ tới localhost).
Đăng nhập web thành công sẽ về `/tracecore`; `Frappe Admin` chỉ xuất hiện với System Manager/Administrator.
Home dùng cookie session Frappe và asset đã build, không cần chạy Vite dev server.

Test backend Home trên site unit test riêng, trước khi chuẩn bị dữ liệu E2E:

```bash
cd ~/tracecore-dev
bench --site test_site migrate
for module in tracecore.v1.tests.test_home_api tracecore.tests.test_home_page tracecore.core.tests.test_account; do
  CI=1 bench --site test_site run-tests --module "$module" || break
done
```

## E2E Home và kiosk (Playwright)

Giữ các dịch vụ Redis/worker của `bench start` hoạt động. Trong terminal WSL khác, chuẩn bị **site dev** và phục vụ riêng trên cổng 8001:

```bash
cd ~/tracecore-dev
env/bin/python -m pip install pytest-playwright pyotp
env/bin/python -m playwright install --with-deps chromium
cd apps/tracecore
bash scripts/e2e_prepare.sh tracecore-dev.local
cd ~/tracecore-dev
bench --site tracecore-dev.local serve --port 8001 --noreload
```

URL E2E/browser là [http://127.0.0.1:8001/tracecore](http://127.0.0.1:8001/tracecore); `--site` chọn đúng site dev dù dùng IP.
Script tạo dữ liệu và tài khoản demo, ghi mật khẩu/OTP vào `~/.tracecore-e2e.env` quyền 600.
Không chạy prepare trên `test_site` hoặc site bật `allow_tests`: script từ chối để giữ sạch dữ liệu unit test.
Ngoại lệ `TC_E2E_ALLOW_TEST_SITE=1` chỉ dành cho site CI dùng một lần.

Trong terminal WSL thứ ba:

```bash
cd ~/tracecore-dev/apps/tracecore
set -a
. ~/.tracecore-e2e.env
set +a
TC_BASE_URL=http://127.0.0.1:8001 ../../env/bin/python -m pytest tests_e2e/test_home.py -q -rs
# Toàn bộ Home + kiosk + Desk (prepare lại trước những test tiêu thụ dữ liệu demo):
TC_BASE_URL=http://127.0.0.1:8001 ../../env/bin/python -m pytest tests_e2e -q
```

Home tests dùng `TC_E2E_USER/PASSWORD` (operator), `TC_E2E_OTP_SECRET` khi có OTP,
và `TC_E2E_INSTR_USER/PASSWORD/OTP_SECRET` (TC R02 với shortcut Set Unit) từ file prepare.
Viewport mặc định 1366×768; test menu PDA dùng 412×915.
Để chạy case Frappe Admin, export thêm `TC_E2E_HOME_MANAGER_USER` và `TC_E2E_HOME_MANAGER_PASSWORD`
của một tài khoản System Manager/Administrator trên cùng site, cùng `TC_E2E_HOME_MANAGER_OTP_SECRET` nếu bật OTP App.
Prepare không tạo manager; thiếu fixture sẽ hiển thị skip với `-rs`. Không ghi secrets vào repo.
Các case kiểm tra login tương tác, shortcut được cấp quyền, quyền Admin, menu PDA, refresh deep route,
logout/session và không có Desk toolbar/sidebar trên Home. Kiểm tra trực quan màu sắc, khoảng cách và focus vẫn cần mở browser.

Kiosk: mở `/app/station?station=TR-004`. Set ID demo: `bench --site <site> execute tracecore.setup.devdata.ensure_demo_set`.

## Station Agent

```bash
bench --site <site> execute tracecore.setup.provision.agent_user \
  --kwargs "{'station': 'TR-004', 'config_path': '~/.tracecore-agent/agent.ini', 'server_url': 'http://127.0.0.1:8000'}"
python3 -m tracecore_agent --config ~/.tracecore-agent/agent.ini hello   # in 1 nhãn thử -> Print Job "Printed"
python3 -m tracecore_agent --config ~/.tracecore-agent/agent.ini serve   # dịch vụ 127.0.0.1:8765
```

Chưa có máy in (`[printer] host` trống): nhãn được ghi ra `~/.tracecore-agent/labels/<job>.zpl` và `<job>.png`.

## License

GPL-3.0
