# FEAT-092 QR cạnh nút dùng mã toàn số, báo bộ gõ tiếng Việt — kế hoạch

> Nguồn: Amendment A-129 (`docs/architecture.md`), FR-M9-23. Người dùng thử trên site dev 05/11/2026: quét QR "Ghi sổ phiếu" ra `CMD-DO-SUBMIT-RÊCIPT` (Unikey Telex đang bật). Người dùng: "làm luôn đi".
> Nhánh: `feat/FEAT-092-qr-numeric-ime`.

## Acceptance criteria (EARS)

- **AC-1** (A-129 a): `TcQrAlias` cấp `99-0001`, `99-0002`… theo thứ tự cho từng mã nút, cùng mã thì cùng số trong phiên; `code(alias)` đọc ngược; số lạ → null.
- **AC-2** (A-129 a): Màn trạm hiện QR có nội dung `99-NNNN`; quét số đó = bấm nút của mã tương ứng; số không có trong phiên → `COMMAND_NOT_AVAILABLE`.
- **AC-3** (A-129 b): RPC `station.command_qr` trả ảnh cho mã `99-NNNN` (giải ra đúng chuỗi).
- **AC-4** (A-129 c): Chuỗi quét có chữ có dấu tiếng Việt → `alert-error` `SCAN_IME_ON`, không đưa cho màn của bước.
- **AC-5**: Chuỗi mới qua `__()` và có trong `translations/vi.csv`.

## Tasks (TDD)

1. `tc_scan_burst.js`: `TcQrAlias`, `tcHasVietnameseMarks` (AC-1, AC-4). Test JS `tracecore/tests/test_station_behavior.py`.
2. `command_codes.qr_images` nhận `99-NNNN` (AC-3). Test `core/tests/test_command_qr.py`.
3. `station.js`: gắn QR theo alias, `handleCommandScan` đổi alias → mã, chặn chuỗi có dấu (AC-2, AC-4).
4. Bản dịch, lint, test, merge develop, cập nhật site dev.
