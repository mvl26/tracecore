# FEAT-080 Mã vạch sang trạm kế tiếp (khung dùng chung) — kế hoạch

> Nguồn: Amendment A-117 (`docs/architecture.md`), FR-M9-22. Người dùng chốt 04/11/2026: mã vạch là phím tắt chuyển trạm cạnh nút Hoàn thành; quét chỉ chuyển sang trạm kế (không tự hoàn thành bước); áp dụng mọi bước T1→T8.
> Nhánh: `feat/FEAT-080-next-station-barcode` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-117-handoff-code` được duyệt và merge. Phạm vi FEAT-080: khung dùng chung + T1→T2 + T3→T4; các bước còn lại ở FEAT-081.

## Hiện trạng

- Mỗi trạm là địa chỉ riêng `/app/station?station=TR-00x`; không có đường nối T1→T2. Chỉ T3 có `goNext()` (`station_t3.js`) dùng `next_station` do `assembly._next_station` trả (trạm có chức năng đóng gói cùng khu, ưu tiên chính nó).
- `core.gs1.parse_scan` nhận mã trạm `TR-\d{3}`; `core.qr` dựng PNG QR của mã đối tượng; `zones.stations_with_function`, `zones.station_has_function` chọn trạm theo chức năng.

## Acceptance criteria (EARS)

- **AC-1** (FR-M9-22): Khi T1 xong lượt nhận và có trạm có chức năng rửa đang hoạt động cùng khu, RPC xong bước phải trả `next_station`, và màn T1 phải hiện mã vạch của trạm đó cạnh nút chính cùng nút bấm tay "Sang T2".
- **AC-2** (FR-M9-22): Khi người dùng quét đúng mã trạm kế đang hiện, màn phải mở `/app/station?station=<mã>` và không gọi RPC ghi nào.
- **AC-3** (FR-M9-22): Khi người dùng quét mã trạm khác trạm kế đang hiện, màn phải hiện `alert-error` inline (kết quả → lý do → hành động), mã lỗi `NEXT_STATION_MISMATCH`, và không chuyển trang.
- **AC-4** (FR-M9-22): Nếu bước chưa xong (T3 kết luận Không đạt, T1 chưa hoàn tất), hệ thống không được hiện mã vạch.
- **AC-5** (FR-M9-22): Nếu không có trạm nào cho bước kế, hệ thống không được hiện mã, phải hiện thông báo `NEXT_STATION_NOT_FOUND` kèm hành động liên hệ R10.
- **AC-6** (FR-M9-22): Nút "Sang <trạm kế>" phải dùng được khi không quét (không hover-only, ≥ 48 px); chữ ≥ 16 px.
- **AC-7** (A-117 e): Khi offline, mã vạch phải ẩn nếu chưa có, và nút bấm tay vẫn mở trạm kế đã biết.

## Tasks (TDD: viết test `FrappeTestCase` trước, thấy fail, rồi code)

1. **`core.next_station`** (AC-1, AC-4, AC-5)
   - [ ] Test: `test_next_in_same_zone`, `test_prefers_itself_when_it_also_does_the_next_step`, `test_none_when_no_station_has_the_function`, `test_inactive_station_is_skipped`. Thấy fail.
   - [ ] `core/next_station.py`: bảng bước → chức năng của bước kế; `of(station, step)` dùng `zones.stations_with_function`. Chuyển `assembly._next_station` sang gọi hàm này (giữ test hiện có).
2. **RPC `tracecore.v1.station.next_barcode`** (AC-1, AC-3, AC-5)
   - [ ] Test API: trả `next_station`, `png_b64` giải ra đúng mã trạm (`qr.decode_png`); `NEXT_STATION_NOT_FOUND`. Đăng ký mã lỗi trong catalog mã lỗi (A-71).
3. **Khung UI chung** (AC-2, AC-3, AC-6, AC-7)
   - [ ] Test (node, `tests/test_station_behavior.py`): quét đúng mã → `location.assign` tới trạm kế; quét mã khác → alert-error, không chuyển; offline ẩn mã, nút bấm tay còn.
   - [ ] `station.js`/`station_error.js`: `window.tcNextStationBlock(station, next)`, bộ nhận mã trạm kế ở ô quét chung; chuỗi mới vào `translations/vi.csv`; chỉ token `--tc-*`.
4. **Áp dụng T1→T2, T3→T4** (AC-1, AC-4)
   - [ ] T1: RPC hoàn tất lượt trả `next_station`; T3: dùng khối chung thay `goNext()`.
5. **Hoàn tất:** chạy các module test trên, `pre-commit`, coverage changed-code ≥ 70 %; không chạy E2E, không tạo PR. Ghi rủi ro máy quét 1D không đọc QR (A-117) vào báo cáo.
