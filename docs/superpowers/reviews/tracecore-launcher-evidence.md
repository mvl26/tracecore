# TraceCore launcher — bằng chứng kiểm tra 23/10/2026

## Điều chỉnh HOME-01 — nhánh feat/tracecore-home

- Thay liên kết bổ sung trên Home bằng chuyển hướng Workspace → `/app/tracecore`
  cho TC/System Manager; tài khoản thường, List/Form và trạm được giữ nguyên.
- Menu quản lý bổ sung phiếu rửa, nhập kho vô khuẩn, vị trí kho, chương trình,
  nhân viên/năng lực, vật tư/lô/phiếu kho, khu-trạm, in nhãn, audit. Từng mục
  tiếp tục kiểm read permission. Không thêm CRM/Customer/Sales Invoice.
- TDD routing: trước sửa **2 failed, 3 passed**; sau sửa **5 passed** bằng
  `node --test scripts/test_tracecore_home.cjs`.
- Playwright Python: **8 passed in 34.97s**, bao gồm 5 tổ hợp role/route.
- Ruff check/format, ESLint và architecture/syntax/diff checks: pass.
- FrappeTestCase mới chưa chạy được: bench FEAT-019 đang merge conflict,
  import `tracecore/v1/_common.py` gặp `SyntaxError` ở marker `<<<<<<< HEAD`.
  Chưa đo lại coverage Python sau mở rộng menu; chưa migrate/build site dev.
- Không sửa/xử lý merge của Claude và không đưa thay đổi vào bench đó.

## Bản launcher ban đầu

Nhánh: `feat/tracecore-launcher` trong clone Windows. Base: `develop` ở `3bb928b`.
Không đổi checkout FEAT-019 của Claude, không migrate/build site dev.

## Kết quả

- FrappeTestCase trên `test_site`, nguồn nạp từ clone riêng bằng
  `scripts/test_launcher_external.py`: **5 tests, OK**.
- Coverage riêng `tracecore/v1/navigation.py`: **19 statements, 0 missed, 100%**.
- `pytest tests_e2e/test_launcher_preview.py -q`: **4 passed in 11.18s**.
  Playwright for Python, Chromium, viewport 1366×768 và 412×915.
  Kiểm ba card, trạm chưa triển khai bị khóa, đích điều hướng có mã trạm động,
  không tràn ngang, lỗi/thử lại, offline/online, Home/sidebar không nhân đôi liên kết.
- Ruff check + format: pass trên Python mới.
- ESLint: pass trên Page và module liên kết Home.
- Prettier: đã format hai JS mới.
- `scripts/check_architecture.py`, `scripts/check_bru_coverage.py`,
  `scripts/build_tokens.py --check`, `node --check`, `git diff --check`: pass.
- Esbuild build thử `tracecore/public/js/tracecore.bundle.js`: **26.8kb, Done**,
  output nằm trong cache riêng, không ghi assets của bench.

## Giới hạn / bước tích hợp còn lại

- Browser tests dùng assets thật, RPC/Workspace giả lập. Chưa xác minh Home → Page
  trên site Frappe đã migrate, chưa chạy full `bench build` hoặc lint toàn repo.
- Chỉ bật T2/T4/T6 theo màn hiện có trên base; khi merge T1/T3 cần cập nhật
  `IMPLEMENTED_STEPS` trong `tracecore/v1/navigation.py`.
- Cổng khoa chưa có nên card chỉ thông báo, không có chức năng giả.
- Chưa đạt điều kiện kết thúc nhánh để merge. Chưa mở PR vào `main` vì base hiện
  chứa 233 commit của `develop` chưa vào `main`; cần xử lý nền tích hợp trước.

## Lệnh chạy lại

Từ `~/tracecore-dev/sites`:

```sh
../env/bin/python /mnt/c/Users/Miyano-desktop/Documents/GitHub/tracecore/scripts/test_launcher_external.py
```

Từ clone này (WSL), Playwright dùng thư viện giải nén riêng nếu hệ thống chưa có:

```sh
LD_LIBRARY_PATH="$PWD/.pytest_cache/launcher-deps/libs/usr/lib/x86_64-linux-gnu" \
  ~/tracecore-dev/env/bin/python -m pytest tests_e2e/test_launcher_preview.py -q
```

Ba gói thư viện local: `libnspr4`, `libnss3`, `libasound2`; chỉ tải/giải nén vào
cache của clone, không cài package hệ thống. Không commit cache hoặc kết quả test.
