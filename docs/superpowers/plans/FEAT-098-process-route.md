# FEAT-098 Quy trình xử lý của loại bộ [A-156]

Đầu vào: implementation-plan §3 FEAT-098, AC-098-01..04, FR-M1-03.10, BRU-REP-004. Người dùng chốt ngày 12/11/2026: chỉ đổi trường sẵn có trên loại bộ, không sửa trạm/luồng khác.

| Task | Nội dung | FR / BRU / AC |
| --- | --- | --- |
| 1 | Test `test_set_type_route.py`: meta trường (nhãn, 3 options), `imports.SET_METHODS`, bản dịch theo ngữ cảnh loại bộ, BOM Khử khuẩn nhận dụng cụ không Thiết yếu, chặn Thiết yếu, đổi quy trình kiểm lại BOM, chặn loại chỉ thị 4/5/6 | AC-098-01..03, BRU-REP-004 |
| 2 | Test `test_packing_route.py`: T4 chặn bộ Khử khuẩn `SET_NOT_FOR_STERILIZATION` 409, không tạo Pack | AC-098-04 |
| 3 | `catalog.fits_route` / `route_issue`; nối vào `bom_versions.line_errors`, `set_type.check_method_against_boms`, `set_units._bom_items`, `catalog.bom_usage` | FR-M1-03.10, FR-M1-03.3 |
| 4 | `set_type._validate_route_ci`; JSON `method` nhãn Processing Route + `Disinfection`; `imports.SET_METHODS` | FR-M1-03.10 |
| 5 | `packing._open` chặn bộ Khử khuẩn; mã `SET_NOT_FOR_STERILIZATION` trong `core.errors` (409) và `UNMAPPED_BLOCK_CODES` | AC-098-04 |
| 6 | `vi.csv` theo ngữ cảnh `Instrument Set Type`; chạy test module liên quan, `test_station_page`, pre-commit | — |
