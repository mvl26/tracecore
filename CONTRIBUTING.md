# Đóng góp cho TraceCore

Đọc [`CLAUDE.md`](CLAUDE.md) trước. Tóm tắt các quy tắc bắt buộc (F-1, F-2):

## Nhánh, commit, PR

- Làm trên nhánh `feat/FEAT-NNN-<slug>` (hoặc `fix/…`), không commit thẳng `main`.
- Commit theo Conventional Commits: `feat(core): …`, `fix(ui): …`, `test(e2e): …`, `chore(lint): …`.
- PR vào `main` cần CI xanh (`lint`, `test` với diff-cover ≥ 70 %, `e2e`) và 1 review.

## Kiến trúc (lint: `scripts/check_architecture.py`)

- **R1** Không import chéo giữa module nghiệp vụ M1–M10; chỉ đi qua `tracecore.core` hoặc Link/hook.
- **R2** Chỉ `tracecore/core/step_gate.py` được đổi `Set Unit.status`.
- **R3** Mọi chuỗi hiển thị viết tiếng Anh trong `_()` / `__()`; bản dịch ở `tracecore/translations/vi.csv`
  (test `test_vi_translations_cover_source_strings` bắt chuỗi thiếu bản dịch).
- **R4** CSS của Page chỉ dùng biến `--tc-*`; không gõ hex/px. Đổi màu/kích thước = sửa `docs/tokens.json`
  rồi chạy `python3 scripts/build_tokens.py`.
- Module Frappe: xem Amendment A-01 trong `docs/architecture.md` (dịch vụ ở `tracecore/core/`, DocType nền ở module `TraceCore`).
- RPC: `tracecore.v1.<domain>.<action>`; RPC ghi của trạm/agent dùng `@idempotent` + header `X-Idempotency-Key` + `client_ts` có offset.
- `Audit Log` append-only: không thêm quyền write/delete.

## Test (TDD)

- Viết `FrappeTestCase` trước, thấy fail, rồi mới code.
- Test nghiệp vụ gắn marker `@bru("BRU-…")` (`tracecore.tests.utils.bru`); `scripts/check_bru_coverage.py` kiểm marker khớp `docs/srs.md`.
- Dữ liệu test qua `tracecore/tests/factories.py`.

## Bảo mật

- Không commit secrets, `site_config.json`, dữ liệu thật của bệnh viện. Chỉ commit file `*.example`.
- Repo đang public.
