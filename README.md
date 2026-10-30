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

## License

GPL-3.0
