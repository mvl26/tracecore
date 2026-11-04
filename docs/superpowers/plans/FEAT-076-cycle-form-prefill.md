# FEAT-076 Điền sẵn form nhập tay dữ liệu chu trình T2/T5 — kế hoạch

> Nguồn: Amendment A-115 (`docs/architecture.md`), FR-M2-10, FR-M2-10.3, FR-M2-10.5, BRU-REP-015. Người dùng chốt ngày 04/11/2026: mặc định chương trình trước, rồi điểm giữa dải; không điền sẵn "Kết quả chu trình của máy".
> Nhánh: `feat/FEAT-076-cycle-form-prefill` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-115-cycle-form-prefill` được duyệt và merge. Không bắt đầu khi session FEAT-075 còn chạy test trong clone WSL (kiểm `pgrep -af run-tests`, `git branch --show-current`).

## Hiện trạng (khảo sát code 04/11/2026)

- `reprocessing/cycle_defaults.py`: `parameter_schema(program)` tính `default_value` = `Program Parameter.default_value` → giá trị đầu chương trình (nhiệt độ, áp suất, thời lượng) nếu nằm trong dải → `None`. `defaults_of(doc)` gom thành `prefill`; `trace()` so giá trị lưu với mặc định, trả `edited_fields`.
- Dùng chung T2 (`washing.py` :1111 `unload_context`, :1359 `save_manual_data`) và T5 (`sterilizing.py` :1012, :1128).
- JS: `station_t2.js` `fetchContext` :766 và `manualFormHtml` :1940; `station_t5.js` :948 và :1821. Hint "Program default: {0}" chỉ hiện khi `param.default_value != null`. Giờ bắt đầu lấy từ `context.started_at`, không dùng `prefill.started_at`.
- Tham số số không có mặc định (Thời gian giữ nhiệt 5-10, A0 3000-12000, Nhiệt độ sấy 100-120) nên còn trống.

## Acceptance criteria (EARS)

- **AC-1** (FR-M2-10.5, BRU-REP-015): Khi tham số có `default_value` của chương trình, hệ thống phải điền sẵn giá trị đó, không thay bằng điểm giữa dải.
- **AC-2** (FR-M2-10.5): Khi tham số không có mặc định (kể cả giá trị đầu chương trình ngoài dải) và có đủ hai cận min, max khác 0, hệ thống phải điền sẵn `(min + max) / 2` với `default_source = midpoint`.
- **AC-3** (FR-M2-10.5): Khi tham số chỉ có một cận hoặc không có dải, hệ thống phải để trống, `default_value = None`.
- **AC-4** (FR-M2-10.5): Form phải hiện dưới mọi trường điền sẵn dòng nguồn: `Mặc định theo chương trình: X` (`program`) hoặc `Điền sẵn theo điểm giữa dải: X` (`midpoint`).
- **AC-5** (FR-M2-10.5): Hệ thống không được điền sẵn ô "Kết quả chu trình của máy"; nút xác nhận vẫn tắt/không lưu khi chưa tick xác nhận (FR-M2-10.1) và vẫn bắt buộc ảnh khi máy `has_printout` (FR-M2-10.2).
- **AC-6** (FR-M2-10.5): Giờ bắt đầu phải điền sẵn từ `started_at` của lô/mẻ hoặc `prefill.started_at`; giờ kết thúc giữ như A-89.
- **AC-7** (FR-M2-10.3, A-115 f): Khi lưu, `cycle_defaults.trace` phải trả thêm `kept_fields` (tham số, `started_at`, `ended_at` còn đúng giá trị điền sẵn) và ghi vào Audit Log cùng `edited_fields`; `data_source = Manual Default` khi có giá trị điền sẵn.
- **AC-8** (A-89): Điểm giữa nằm trong dải nên không tự gây `outside_range`; dữ liệu đã lưu hoặc máy đẩy dữ liệu (`data_source` có giá trị) thì `prefill = None`.

## Tasks (TDD: viết test `FrappeTestCase`, thấy fail, rồi code)

1. **Server — điểm giữa** (AC-1, AC-2, AC-3, AC-8; BRU-REP-015)
   - [ ] Test trong `reprocessing/tests/test_cycle_defaults.py` gắn `@bru("BRU-REP-015")`: `test_midpoint_when_no_default`, `test_program_default_beats_midpoint`, `test_no_midpoint_with_single_bound`, `test_header_default_outside_range_falls_to_midpoint`, `test_saved_data_has_no_prefill`. Thấy fail.
   - [ ] `cycle_defaults.parameter_schema`: thêm bước điểm giữa và `default_source`; `defaults_of` trả thêm `sources: {tên: nguồn}`. Làm tròn `flt(..., 6)`.
2. **Server — truy vết** (AC-7)
   - [ ] Test: `test_kept_fields_listed`, `test_kept_and_edited_are_disjoint`, `test_source_manual_default_with_midpoint_only` (T2 và T5). Thấy fail.
   - [ ] `cycle_defaults.trace`: thêm `kept_fields`; xác nhận `washing.save_manual_data` / `sterilizing.save_manual_data` ghi `trace` đầy đủ vào Audit Log (kiểm chỗ đang ghi `edited_fields`, thêm khóa mới).
3. **UI T2 và T5** (AC-4, AC-5, AC-6)
   - [ ] Test trong `tests/test_station_behavior.py` (node): giờ bắt đầu lấy từ `prefill.started_at` khi `started_at` trống; hint theo `default_source`; `reported` mặc định rỗng.
   - [ ] `station_t2.js`, `station_t5.js`: dùng `prefill.started_at`; `manualFormHtml` hiện hint theo nguồn; không đổi ô kết quả, tick, ảnh.
   - [ ] Thêm chuỗi vào `translations/vi.csv` ("Prefilled from the midpoint of the range: {0}" → "Điền sẵn theo điểm giữa dải: {0}"). Không đổi `tokens.css`; chỉ dùng class sẵn có `tc-hint`.
4. **Hoàn tất**
   - [ ] Chạy `run-tests` module `reprocessing.tests.test_cycle_defaults`, `test_washing_result`, `test_sterilizing_manual`, `v1.tests.test_wash_api`, `test_load_api`, `tests.test_station_behavior`; đọc OK/FAILED trong log (exit code không tin được). Coverage changed-code ≥ 70 %, `pre-commit run --all-files` sạch. Không chạy E2E, không tạo PR; push nhánh.
