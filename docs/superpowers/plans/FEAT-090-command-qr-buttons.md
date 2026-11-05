# FEAT-090 QR mã lệnh cạnh nút xác nhận trên màn trạm — kế hoạch

> Nguồn: Amendment A-127 (`docs/architecture.md`), FR-M9-23. Người dùng yêu cầu ngày 05/11/2026 (kèm ảnh nút "Xác nhận bộ" ở T1): "setting cả những nút xác nhận, sẽ có những mã QR để quét mã vạch bên cạnh, khi quét xong nó tự nhảy sang bước tiếp theo".
> Người dùng chốt: QR hiện cạnh nút trên màn; bật/tắt trong TraceCore Settings.
> Nhánh: `feat/FEAT-090-command-qr-buttons`.

## Acceptance criteria (EARS)

- **AC-1** (A-127 a, b): `command_codes.screen_qr(station)` trả ``{khóa lệnh: data URI PNG}`` chỉ cho các lệnh xác nhận/hoàn thành áp dụng cho trạm; ảnh giải mã ra `CMD-DO-<LỆNH>`.
- **AC-2** (A-127 b, d): RPC `station.commands` trả `show_qr` theo `TraceCore Settings.show_command_qr` (mặc định bật) và `qr` (rỗng khi tắt); `commands` giữ nguyên.
- **AC-3** (A-127 a, c): Màn trạm (STN) gắn một QR ngay sau mỗi nút khớp bộ chọn của lệnh có ảnh, không gắn trùng, gắn lại khi màn vẽ lại; PDA không hiện.
- **AC-4**: Chuỗi mới có trong `translations/vi.csv`; chỉ token `--tc-*`.

## Tasks (TDD)

1. `command_codes.SCREEN_QR`, `screen_qr` (AC-1). Test `core/tests/test_command_codes.py`.
2. `TraceCore Settings.show_command_qr`; `v1.station.commands` trả `show_qr`, `qr` (AC-2). Test `v1/tests/test_station_commands.py`.
3. `station.js` gắn QR (MutationObserver, `decorateCommandButtons`), `station.css` `.tc-cmd-qr` (AC-3). Test đọc nguồn.
4. Bản dịch, lint, test, merge develop, cập nhật site dev.
