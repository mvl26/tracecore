# FEAT-083 Mã lệnh cho nút, tab, trạm và tờ in dán tại trạm — kế hoạch

> Nguồn: Amendment A-119 (`docs/architecture.md`), FR-M9-23; mở rộng A-117 (FEAT-080/081, `station.switchStation`, `offerNextStation`) và mã `HOAN-THANH-NAP` có sẵn (`station_t2.js`, `station_t5.js`). Người dùng chốt 04/11/2026: mã lệnh cho nút/tab/trạm; tờ A4 in dán tại trạm.
> Nhánh: `feat/FEAT-083-command-codes` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-119-command-codes` được duyệt và merge.

## Hiện trạng

- Ô quét của màn trạm (`station.js` `scan`) chuyển mã cho màn của bước; chỉ T2/T5 đọc `HOAN-THANH-NAP` trong `scan` của màn. Mã `TR-###` chỉ nhận khi đúng trạm kế đang hiện (A-117).
- Nút trạm (`tc-switch-station`), tab (`Nạp lô`, `Dỡ lô`, `Kiểm tra hằng ngày`) và nút thao tác là phần tử có `data-action`; click đi qua `onAction` của khung hoặc màn.
- Tờ in đã có hạ tầng PDF A4/nhãn qua `core.label_pdf`, `qr.qr_png`, hộp thoại In `tcPrintPdfAndTell` (A-114).

## Việc đầu tiên (rà soát, không code)

- [ ] Liệt kê `data-action` của từng màn T1–T8 (`station_t*.js`, `station.js`) và gán cho mỗi nút một trong ba loại: **điều hướng / hoàn thành** (có mã lệnh), **nguy hiểm** (hủy, bỏ, từ chối, xóa, ghi đè, thu hồi, cần PIN/lý do: không mã), **nhập liệu** (không mã). Kết quả là bảng chốt `COMMANDS` trong `core/command_codes.py`; bảng trong A-119 (c) là bản nháp.

## Acceptance criteria (EARS)

- **AC-1** (FR-M9-23): Khi quét mã tab `CMD-TAB-<khóa màn>` của một tab có ở trạm hiện tại, màn phải chuyển sang tab đó như khi bấm.
- **AC-2** (FR-M9-23): Khi quét `CMD-DO-<LỆNH>` mà nút ứng đang hiện và bật, màn phải thực hiện đúng việc của nút (qua chính `onAction`, không đường tắt) và không ghi sổ gì ngoài việc nút đó vốn ghi.
- **AC-3** (FR-M9-23): Khi quét mã trạm `TR-###` của trạm có trong hàng nút trạm, màn phải đổi trạm như bấm nút trạm (A-90, A-91); khác khu thì vào màn quét thẻ của trạm đích.
- **AC-4** (FR-M9-23): Nếu lệnh không có, không hiện hoặc đang tắt, màn phải hiện `alert-error` inline với mã `COMMAND_NOT_AVAILABLE` (kết quả → lý do → hành động) và không làm gì.
- **AC-5** (FR-M9-23): Hệ thống không được sinh mã lệnh cho nút nguy hiểm hay cần PIN/lý do; quét chuỗi `CMD-DO-` của nút đó phải bị từ chối như AC-4.
- **AC-6** (FR-M9-23): `HOAN-THANH-NAP` phải còn dùng được như trước (bí danh của `CMD-DO-COMPLETE-LOAD`).
- **AC-7** (FR-M9-23): R10 bấm "In tờ mã lệnh" trên Zone Station phải mở hộp thoại In với PDF A4: tên trạm, mỗi lệnh có tên đã dịch, QR giải ra đúng mã lệnh và mã chữ Courier New; chỉ lệnh áp dụng cho chức năng của trạm đó.
- **AC-8** (FR-M9-23): Mã lệnh không được ghi vào ô nhập dữ liệu (không biến thành Set ID, mã lô): ô quét nhận ra chuỗi lệnh trước khi chuyển cho màn.

## Tasks (TDD: viết test `FrappeTestCase` trước, thấy fail, rồi code)

1. **`core.command_codes`** (AC-5, AC-7): bảng `COMMANDS` (khóa, nhãn dịch, loại, chức năng áp dụng), `parse(raw)` trả `{"kind": "station|tab|do", "key"}` hoặc None, `for_station(station)` cho tờ in.
   - [ ] Test: parse từng loại, từ chối chuỗi lạ/nguy hiểm, `for_station` theo chức năng, bí danh `HOAN-THANH-NAP`.
2. **RPC `tracecore.v1.station.command_sheet`** (AC-7): PDF A4 qua `label_pdf` (HTML + QR), role R10/System Manager; mã lỗi `COMMAND_NOT_AVAILABLE` vào catalog mã lỗi.
   - [ ] Test: QR trong PDF giải đúng mã; trạm không tồn tại; quyền.
3. **Bộ nhận lệnh ở ô quét** (AC-1..AC-4, AC-6, AC-8): trong `station.js` `scan` nhận ra mã lệnh trước khi chuyển cho màn; ánh xạ `CMD-DO-*` → `data-action` của nút đang hiện và bật; tab theo khóa màn; trạm qua `switchStation`.
   - [ ] Test node (`test_station_behavior.py`, có node) và test chuỗi: lệnh tab, lệnh thao tác, nút tắt, mã trạm sai khu.
4. **Nút "In tờ mã lệnh" trên Zone Station** (AC-7): `public/js` cho Desk, dùng `tcPrintPdfAndTell`.
5. **Hoàn tất:** test các module trên + `test_station_page`, `test_station_behavior`; `pre-commit`; coverage changed-code ≥ 70 %; không chạy E2E, không tạo PR; ghi rõ rủi ro tờ dán nhầm trạm và máy quét 1D không đọc QR.
