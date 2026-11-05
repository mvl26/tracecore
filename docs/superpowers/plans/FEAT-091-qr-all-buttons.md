# FEAT-091 QR cạnh mọi nút ở màn trạm — kế hoạch

> Nguồn: Amendment A-128 (`docs/architecture.md`), FR-M9-23. Người dùng ngày 05/11/2026: "tao sẽ dùng máy quét mã thay cho dùng chuột, nhân viên sẽ không phải dùng chuột trên màn hình để thao tác, chỉ quét quét. Nên các nút thì hiển thị các mã cho tao". Đã duyệt bản demo (bỏ QR nút chụp ảnh). Nút nguy hiểm có QR, giữ bước xác nhận.
> Nhánh: `feat/FEAT-091-qr-all-buttons`. Chỉ push nhánh, chưa merge (người dùng dặn).

## Acceptance criteria (EARS)

- **AC-1** (A-128 a): Mã nút: `tcButtonCode(action, n)` = `CMD-BTN-<ACTION>` (n = 1) hoặc `CMD-BTN-<ACTION>.<n>`; `tcParseButtonCode` đọc ngược, sai dạng → null.
- **AC-2** (A-128 e): RPC `station.command_qr(token, codes)` trả {mã: ảnh QR PNG data URI} cho mã đúng dạng (`CMD-DO-<lệnh có thật>`, `CMD-BTN-…`), bỏ mã sai dạng, tối đa 80 mã; rỗng khi tắt `show_command_qr`; cần phiên hợp lệ.
- **AC-3** (A-128 d): `TcKeyBurst` gom phím tốc độ máy quét (≤ 50 ms/phím, ≥ 4 ký tự), hết 120 ms hoặc gặp Enter thì trả chuỗi; gõ tay không trả.
- **AC-4** (A-128 d): Luồng phím là mã lệnh mà con trỏ ở ô khác ô quét thì ô đó trở về giá trị trước khi quét và lệnh được chạy.
- **AC-5** (A-128 a, b, c): Màn trạm (STN) gắn QR sau mọi nút `[data-action]`, trừ nút chụp ảnh, `tc-switch-station`, `tc-screen`; quét `CMD-BTN-…` bấm đúng nút thứ n đang hiện và đang bật, không thì `COMMAND_NOT_AVAILABLE`.
- **AC-6**: Chuỗi mới có trong `translations/vi.csv`; chỉ token `--tc-*`; PDA không hiện.

## Tasks (TDD)

1. `tc_scan_burst.js`: `tcButtonCode`, `tcParseButtonCode`, `TcKeyBurst` (AC-1, AC-3). Test JS `tracecore/tests/test_station_behavior.py`.
2. `command_codes.qr_images(codes)` + RPC `v1.station.command_qr` (AC-2). Test `core/tests/test_command_qr.py`.
3. `station.js`: bắt luồng phím ở mọi ô (AC-4); gắn QR mọi nút + nạp ảnh theo lô; `handleCommandScan` nhận `CMD-BTN-…` (AC-5). Test đọc nguồn + JS.
4. Bản dịch, lint, test, push nhánh.
