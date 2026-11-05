# FEAT-093 Gợi ý, chọn tay và quét lô gói thử ở Kiểm tra hằng ngày — kế hoạch

> Nguồn: Amendment A-130 (`docs/architecture.md`), FR-M5-05, UC-23, SCR-23. Người dùng ngày 05/11/2026: "gợi ý lô phù hợp ở chỗ này, đồng thời có thể chọn tay. Lô này có thể in mã QR để quét".
> Người dùng chốt: gợi ý lô gói thử của chương trình; chặn lô không đúng; in QR lô giữ ở Desk.
> Nhánh: `feat/FEAT-093-test-pack-lot-pick`.

## Acceptance criteria (EARS)

- **AC-1** (A-130 e): `daily_test.overview` trả `run_lots` = {loại test: lô Gói test của lần chạy đã kết thúc chưa ghi kết quả}.
- **AC-2** (A-130 d): Khi chương trình test có vật tư `Test Pack`, `record` chỉ nhận lô của đúng vật tư đó, chưa tắt, còn hạn, có tồn ở bệnh viện của máy; sai → `CONSUMABLE_LOT_INVALID`; hạn lô lấy từ Batch; không gửi lô thì dùng lô của lần chạy.
- **AC-3** (A-130 d): Test không có vật tư `Test Pack` giữ cách cũ (gõ số lô + hạn, hết hạn → `TEST_LOT_EXPIRED`).
- **AC-4** (A-130 a, b): Form kết quả hiện nút cho từng lô gợi ý (số lô + hạn), chọn sẵn lô của lần chạy rồi lô hạn gần nhất; chạm nút đổi lô; không còn ô Hạn lô.
- **AC-5** (A-130 c): Form kết quả đang mở thì quét mã không phải `TB-####` điền vào lô.
- **AC-6**: Chuỗi mới có trong `translations/vi.csv`.

## Tasks (TDD)

1. `daily_test.py`: `run_lots` trong `overview`; `record` kiểm lô `Test Pack` bằng `lots.check` (AC-1..AC-3). Test `equipment/tests/test_daily_test_lot_pick.py`.
2. `station_daily_test.js`: nút lô, chọn sẵn, `dt-lot`, quét lô ở form kết quả (AC-4, AC-5). Test JS `tracecore/tests/test_station_behavior.py`.
3. Bản dịch, lint, test, merge develop, cập nhật site dev.
