# FEAT-053 Chương trình theo máy của loại bộ — kế hoạch

> Nguồn: ticket #1865, Amendment A-110 (`docs/architecture.md`), FR-M1-03.7, FR-M1-03.8, FR-M5-02.5, FR-M2-03.7, FR-M2-03.8, FR-M2-09.7, FR-M2-09.8, BRU-REP-017. Người dùng duyệt phạm vi trong chat ngày 03/11/2026.
> Nhánh: `feat/FEAT-053-set-type-program` trong `apps/tracecore`.

## Acceptance criteria (EARS)

- AC-1 (FR-M1-03.7, BRU-REP-017): Khi R10 lưu Loại bộ có hai dòng Mặc định cho cùng một máy, hệ thống phải từ chối lưu.
- AC-2 (FR-M1-03.8, BRU-REP-004): Nếu dòng trỏ tới chương trình tiệt khuẩn khác phương pháp của Loại bộ, chương trình test, chương trình ngừng dùng, chương trình của máy không phải máy rửa/tiệt khuẩn hoặc dòng trùng, thì hệ thống phải từ chối lưu và nêu dòng sai.
- AC-3 (FR-M5-02.5): Khi mở Process Program, hệ thống phải liệt kê các loại bộ dùng chương trình (Mặc định/Cho phép).
- AC-4 (FR-M2-03.7, FR-M2-09.7): Khi quét bộ/gói đầu tiên ở T2/T5 và chưa tự đổi chương trình, màn phải chọn chương trình mặc định của loại bộ cho máy đó.
- AC-5 (FR-M2-03.7, FR-M2-09.7): Khi các bộ có mặc định khác nhau, màn phải cảnh báo kèm chương trình chung hoặc gợi ý tách lô/mẻ.
- AC-6 (FR-M2-03.8, FR-M2-09.8): Mức `Block`: bộ/gói ngoài danh sách bị từ chối `PROGRAM_NOT_FOR_SET`; mức `Override`: Hoàn thành nạp thiếu lý do bị từ chối `PROGRAM_OVERRIDE_REASON_REQUIRED`; mức `Warn`: nhận.
- AC-7 (FR-M2-03.8, FR-M2-09.8): Lô/mẻ lưu `suggested_program`, `program`, `program_override_by`, `program_override_reason`.
- AC-8: Tên hiển thị tiếng Việt qua `_()` và `translations/vi.csv`.

## Tasks (TDD: test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Dữ liệu** (FR-M1-03.7, A-110): child DocType `Set Type Program` (module Instrument), trường `programs` trên Instrument Set Type; `TraceCore Settings.program_control`; trường truy vết trên Wash Batch, Sterilization Load; `Process Program.set_types_html`.
2. **`core.program_match`** (BRU-REP-017): `stage_of`, `validate_rows` (AC-1, AC-2), `machine_map`, `fit`, `suggest` (AC-5), `control_level`, `review` (AC-6, AC-7). Test `tracecore/core/tests/test_program_match.py`.
3. **Instrument Set Type.validate** gọi `validate_rows`; **Process Program.onload** trả `set_types` (AC-3).
4. **T2 server** (FR-M2-03.7/.8): `scan_machine` trả `default_program`, `set_programs`; `admit_set(..., program)` trả `program_fit`, `program_default`, chặn mức Block; `start(..., override_reason)` ghi truy vết. Test `reprocessing/tests/test_wash_set_program.py`.
5. **T5 server** (FR-M2-09.7/.8): `scan_machine` trả `set_programs`; `admit_pack` thêm `program_fit`, chặn mức Block (cả `recheck`); `complete(..., override_reason)`. Test `reprocessing/tests/test_load_set_program.py`.
6. **RPC v1** `wash.add_set` (`program`), `wash.complete`, `load.complete` (`program_override_reason`).
7. **Mã lỗi**: `PROGRAM_NOT_FOR_SET`, `PROGRAM_OVERRIDE_REASON_REQUIRED` (422) trong `core.errors`, nhóm danh mục của `PROGRAM_INVALID`; patch thêm vào site đang chạy.
8. **UI T2/T5** (AC-4, AC-5, AC-6): tự chọn, nhãn chữ theo dòng, cảnh báo chương trình chung, ô lý do ghi đè; form Desk Process Program hiện danh sách loại bộ.
9. **Bản dịch, devdata mẫu**, chạy test module, coverage changed-code, `pre-commit`.
