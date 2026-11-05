# FEAT-085 Thành phần bộ dạng bảng (T4, T3) — kế hoạch

> Nguồn: yêu cầu của người dùng 05/11/2026 ("xác nhận các thành phần vẫn chưa phải dạng bảng"), Amendment A-121 (`docs/architecture.md`), FR-M2-05, FR-M2-06, FR-M2-07.
> Nhánh: `feat/FEAT-085-bom-table`. Chỉ đổi trình bày; không đổi RPC, DocType, FR, BRU.

## Acceptance criteria (EARS)

- AC-1 (FR-M2-07, SCR-08): Khi T4 hiện thành phần bộ, hệ thống phải hiện `<table>` 5 cột (STT, Vị trí, Dụng cụ, Số lượng trong bộ, Xác nhận), mỗi dòng BOM một `<tr>`, ô tick `.tc-check` có `data-line`, không còn thẻ `.tc-ins`.
- AC-2 (FR-M2-07.2): Tick từng dòng, Xác nhận tất cả, nhãn "Đã xác nhận n/n dòng" và khóa Xác nhận hoàn thành khi chưa tick đủ phải hoạt động như trước; dòng thiếu R02 đã xác nhận bị khóa ô tick, hiện "Thiếu – R02 đã xác nhận" và không tính vào n/n.
- AC-3 (FR-M2-05, FR-M2-06, SCR-07): Khi T3 hiện BOM, hệ thống phải hiện `<table>` 5 cột (STT, Tên dụng cụ, Số lượng trong bộ, Số lượng thực tế, Thao tác); ô nhập `.tc-t3-actual` thay nút −/+: nhập đúng BOM thì ghi Đủ, khác BOM thì mở form Thiếu/Hỏng với số đã nhập, ô trống hoặc âm bị bỏ qua; Đủ, Thiếu/đếm khác, Hỏng/thay vẫn mang đúng `data-action` và `data-instrument`; nút Xác nhận tất cả thành phần và dòng tally giữ nguyên.
- AC-4 (NFR-USAB-01/02, NFR-ACC-01): Bảng có `<th scope="col">`; trạng thái dòng có chữ hoặc ký hiệu, không chỉ màu; chữ ≥ 16 px, ô tick và nút ≥ 48 px; chỉ token `--tc-*`; không cuộn ngang ở 375 px.
- AC-5: Mọi chuỗi mới qua `__()` và có trong `translations/vi.csv`.

## Tasks (TDD)

1. Test JS trong `tracecore/tests/test_station_behavior.py` (`TestT4BomTable`, `TestT3BomTable`) viết trước, thấy fail (AC-1, AC-3).
2. `station_t4.js`: `bomHtml` sinh bảng; `markLine` cập nhật `<tr>` thay `.tc-ins` (AC-1, AC-2).
3. `station_t3.js`: `linesHtml`/`lineHtml` sinh bảng (AC-3).
4. `station.css`: bảng BOM dùng token, trạng thái `is-done`/`is-short`/`is-over` trên `<tr>`, hẹp ≤ 480 px; bỏ CSS thẻ không còn dùng (AC-4).
5. `translations/vi.csv` cho tiêu đề cột mới (AC-5).
6. Chạy test JS, `test_station_page`, `test_station_*assets`, `pre-commit`, `bench build`; xem bằng trình duyệt ở site dev.
