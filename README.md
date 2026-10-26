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
| `tracecore_agent/` | Station Agent (Python stdlib): `/health`, `/print`, hàng đợi SQLite |
| `scripts/` | `build_tokens.py`, lint kiến trúc/BRU, `install_dev.sh`, `install_prod.sh`, `restore.sh`, `e2e_prepare.sh` |
| `deploy/` | Pin phiên bản, cấu hình mẫu (`*.example`), systemd agent |
| `tests_e2e/` | Playwright smoke cho kiosk |

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

E2E kiosk (Playwright):

```bash
scripts/e2e_prepare.sh test_site                 # Setup Wizard dữ liệu test, user trạm, Set Unit demo
bench --site test_site serve --port 8001 --noreload
cd tests_e2e && set -a && . ~/.tracecore-e2e.env && set +a && TC_BASE_URL=http://127.0.0.1:8001 python -m pytest
```

Kiosk: mở `/app/station?station=TR-004`. Set ID demo: `bench --site <site> execute tracecore.setup.devdata.ensure_demo_set`.

## Station Agent

```bash
bench --site <site> execute tracecore.setup.provision.agent_user \
  --kwargs "{'station': 'TR-004', 'config_path': '~/.tracecore-agent/agent.ini', 'server_url': 'http://127.0.0.1:8000'}"
python3 -m tracecore_agent --config ~/.tracecore-agent/agent.ini hello   # in 1 nhãn thử -> Print Job "Printed"
python3 -m tracecore_agent --config ~/.tracecore-agent/agent.ini serve   # dịch vụ 127.0.0.1:8765
```

Chưa có máy in (`[printer] host` trống): nhãn được ghi ra `~/.tracecore-agent/labels/<job>.zpl` và `<job>.png`.

## TraceCore Admin (Vue)

Giao diện độc lập tại `/tracecore`, với các không gian R01–R10. Backend tiếp tục dùng Frappe session và quyền theo bản ghi; mở không gian của role khác không thay danh tính hoặc cấp thêm quyền dữ liệu.

```bash
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
bench --site <site> clear-cache
```

Build tạo `tracecore/public/admin/` (không commit assets sinh tự động). Khi triển khai phải build frontend trước khi khởi động web worker; `/tracecore/R02/instruments` và các deep link dùng chung SPA entry. Server HTML chứa CSRF token và không cache; nếu chưa build, trang báo thiếu build rõ ràng.

`Administrator` có đủ 10 không gian. Người dùng khác thấy các role `TC R01`…`TC R10` đã được cấp. Có thể cấp role `TC Admin Overview` để xem menu của mọi role; quyền đọc/ghi DocType và phạm vi khoa vẫn bắt buộc. Chỉ quản trị có thẩm quyền mới cấp role này. Không tự cấp System Manager cho người dùng nghiệp vụ.

Bản đầu có danh sách/chi tiết theo quyền, dashboard với nguồn cảnh báo đang hỗ trợ, form tạo/sửa dụng cụ, form loại bộ và BOM có phiên bản, phiếu kiểm đếm PDF, cấp Set ID hàng loạt, lịch sử, xem nhãn, CSV và yêu cầu in lại. Các nguồn chưa được hiện thực đánh dấu chưa sẵn sàng; không đưa dữ liệu demo vào runtime. Các màn trạm hiện hữu tiếp tục dùng cơ chế thẻ/PIN riêng; bản này chưa thay thế toàn bộ luồng vận hành kiosk, PDA, Portal, duyệt ghi đè, hồ sơ tài khoản và các phân hệ chưa có backend. Không bật chuyển hướng Desk đại trà trước khi chuyển đủ các màn người dùng cần.

Cờ site `tracecore_admin_rollout` mặc định tắt. Khi đã đủ điều kiện cutover, bật cờ sẽ chuyển người không có quyền kỹ thuật từ `/app/*` về `/tracecore`, ngoại lệ `/app/station`. `Administrator` và người được gán rõ role `TraceCore Desk Access` vẫn vào Desk. Tắt cờ để khôi phục điều hướng cũ; không đổi dữ liệu nghiệp vụ. Bản này không tự bật cờ hoặc sửa tài khoản hiện hữu.

Kiểm thử backend: `bench --site test_site run-tests --module tracecore.tests.test_admin_ui`. Kiểm thử trình duyệt: nạp môi trường dev E2E hiện hữu, rồi chạy `pytest tests_e2e/test_admin_ui.py`; không dùng tài khoản hoặc dữ liệu production. Tài khoản với OTP được kiểm tra bằng challenge thật từ Frappe. Đăng ký OTP lần đầu dùng liên kết thiết lập an toàn tới luồng xác thực chuẩn.

## License

GPL-3.0
