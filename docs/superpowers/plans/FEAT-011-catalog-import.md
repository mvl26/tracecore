# FEAT-011 — Import danh mục ban đầu từ Excel mẫu, import ảnh hàng loạt

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (Native). Steps use checkbox (`- [ ]`).

**Goal:** R10/R02 nhập danh mục ban đầu của bệnh viện (khoa, nhân viên, dụng cụ, loại bộ & BOM, Set Unit, thiết bị &
chương trình, vật tư, cơ số) từ Excel mẫu: tải mẫu → kiểm từng dòng (không ghi) → ghi sổ các dòng đúng, báo lỗi theo
dòng; nhập ảnh thực tế hàng loạt từ file zip.

**Architecture:** Khung chung `tracecore/core/importer.py` (mẫu Excel, đọc file, kiểm, ghi từng dòng trong savepoint,
log `Import Batch`), không biết gì về nghiệp vụ. Mỗi module đăng ký "loại import" của mình qua hook
`tracecore_import_kinds` (luật R1: không import chéo M1–M10) và ghi qua service sẵn có (`bom_versions.create_set_type`,
`set_units.issue_batch`, controller DocType), nên mọi luật nghiệp vụ và mã tự sinh (BRU-ID-006) giữ nguyên. RPC
`tracecore.v1.imports.*`; màn Desk Page `tc-import` (SCR-43).

**Tech Stack:** Frappe v15, openpyxl (đã dùng ở FEAT-041), RQ (`frappe.enqueue`, hàng `long`), Desk Page JS.

**Đầu vào:** implementation-plan §3 FEAT-011 (FR-M9-11, FR-M9-11.1; EI-SW-007; NFR-PORT-02; UC-39; SCR-43),
architecture §5.3 (Import Template, Import Batch), mẫu `tracecore/inventory/receipt_import.py` (FEAT-041).
Amendment **A-41** (Task 1).

**Nhánh:** `feat/FEAT-011-catalog-import` từ develop local (bench `~/benches/tracecore-f041`). Không PR; merge develop
local, không push.

## Quyết định đã chốt (người dùng 27/10/2026, ghi A-41)

- **Q1 Phạm vi:** danh mục đã có DocType: Khoa (Department), Nhân viên (Employee + thẻ), Dụng cụ, Loại bộ & BOM, Set
  Unit (cấp Set ID theo lô), Thiết bị, Chương trình xử lý (kèm tham số), Vật tư (Item), Cơ số (Par Level). Chứng chỉ
  (FEAT-036) và loại chất thải / đơn vị xử lý (FEAT-047/049) thêm loại import của mình vào cùng khung khi làm FEAT đó.
- **Q2 Cơ chế:** khung import riêng (mở rộng mẫu FEAT-041), **không** bọc Frappe Data Import; ghi qua service.
  `Import Template` không thành DocType: mẫu sinh từ khai báo loại import trong code (một nguồn sự thật, đổi cột không
  cần migrate dữ liệu mẫu).
- **Q3 Import lại (UC-39 A1):** dòng có mã đã tồn tại → bỏ qua, báo "Đã có"; sửa bản ghi đã có làm trên Desk.

## Quyết định của dev lead (ghi A-41, chờ duyệt)

- **D1 Ghi dòng đúng, bỏ dòng sai (EI-SW-007):** "Kiểm tra" không ghi gì; "Ghi sổ" ghi mọi dòng hợp lệ, mỗi đơn vị
  (một dòng, hoặc một nhóm dòng cùng mã như BOM) trong savepoint riêng; đơn vị lỗi lúc ghi bị hoàn tác riêng và vào
  báo cáo lỗi. Kết quả lưu ở `Import Batch` (ghi sổ, không xóa).
- **D2 Chạy nền:** > 200 dòng → `frappe.enqueue` hàng `long`; `Import Batch.status` Queued → Running → Done/Failed;
  màn SCR-43 hỏi trạng thái 3 giây một lần. ≤ 200 dòng chạy ngay.
- **D3 Mã tự sinh (BRU-ID-006, UC-39 E2):** mẫu Set Unit không có cột Set ID; Thiết bị không có cột TB-; Nhân viên
  không có cột mã NV-; file có cột mã hệ thống (`Set ID`, `Equipment code`, `Employee code`…) → từ chối cả file, nêu
  cột. Thẻ nhân viên có sẵn của bệnh viện nhận qua `code_registry.register_card`.
- **D4 Ảnh hàng loạt (FR-M9-11.1):** zip ≤ 200 MB, ảnh JPEG/PNG/WebP; tên file (bỏ đuôi) = mã dụng cụ → `image`;
  `<mã loại bộ>`, `<mã loại bộ>-2`, `-3` → `tray_image`, `_2`, `_3`; ảnh qua kiểm `instrument.media` như tải tay;
  trả danh sách gắn được / không khớp / ảnh lỗi.
- **D5 Nhóm dòng:** Loại bộ & BOM và Chương trình & tham số dùng nhiều dòng cùng mã: dòng đầu mang thông tin phần
  đầu, mọi dòng mang một dòng BOM / một tham số. Phần đầu khác nhau giữa các dòng cùng mã → lỗi nhóm.

## Global Constraints

- Luật R1: `core.importer` không import module M1–M10; module đăng ký qua hook `tracecore_import_kinds`.
- Ghi chỉ qua service / controller DocType (không `db.insert` thẳng); Set Unit chỉ qua `set_units.issue_batch`; BOM qua
  `bom_versions.create_set_type`.
- Quyền: TC R10, TC R02, System Manager (UC-39). RPC ghi `@idempotent`.
- Mọi chuỗi qua `_()` / `__()`, dịch `translations/vi.csv`; ngày trong Excel nhận `dd/mm/yyyy` và ô ngày của Excel.
- Màn Desk chỉ dùng token `--tc-*`; lỗi chặn là `alert-error` inline (kết quả → lý do → hành động).
- Mỗi BRU có test `@bru`: BRU-ID-006 (mã do hệ thống sinh).

## Review Focus

1. File 1.500 dòng (quy mô UC-39) → chạy nền, không timeout request; một dòng lỗi giữa chừng không làm mất dòng đúng
   (Task 2 `test_large_file_is_queued`, `test_failure_in_one_unit_keeps_others`).
2. Hai người bấm Ghi sổ cùng file / bấm hai lần → không tạo trùng (idempotent + bỏ qua theo mã) (Task 8).
3. Ô Excel kiểu số / ngày / có khoảng trắng / mã viết thường → chuẩn hóa như nhập tay (Task 2 `test_cell_normalization`).
4. Zip có đường dẫn `../`, file không phải ảnh, ảnh quá lớn → bỏ qua và liệt kê, không ghi ra ngoài (Task 9).
5. Cột thừa / thiếu / đổi thứ tự cột → nhận theo tên cột, thiếu cột bắt buộc thì từ chối file nêu cột (Task 2).

---

### Task 1: Amendment A-41 + bản dịch khung

**Files:** `docs/architecture.md` (Revision History A-41: Q1–Q3, D1–D5; §5.3 dòng Import Template → "khai báo trong code
qua hook", Import Batch + Import Batch Row), `docs/implementation-plan.md` không đổi (amendment là nơi ghi).
- [ ] Commit `docs(architecture): Amendment A-41 import danh mục FEAT-011`.

### Task 2: Khung `core.importer` + DocType `Import Batch`

**Files:** Create `tracecore/core/importer.py`, `tracecore/tracecore/doctype/import_batch/` (+ child
`import_batch_row`), `tracecore/core/tests/test_importer.py`. Modify `tracecore/hooks.py` (`tracecore_import_kinds = []`).

**Interfaces (Produces):**
- `Column(field, label, required=False, kind="text"|"int"|"float"|"date"|"check"|"select"|"list", options=None, help=None)`
  (dataclass); `kind="list"` = nhiều giá trị cách nhau dấu phẩy.
- `ImportKind(key, label, doctype, columns, code_field, exists(code)->bool, validate(rows)->list[Issue],
  write(rows)->str|None, group_by=None, forbidden_columns=())` (dataclass); `write` ghi một đơn vị (một dòng hoặc một
  nhóm) và trả tên bản ghi chính.
- `Issue(row, code, field, reason)`; `ParsedRow(row_no, values: dict)`.
- `kinds() -> dict[str, ImportKind]` (gộp từ hook, mỗi hàm hook trả list ImportKind).
- `build_template(key) -> bytes` (sheet "Dữ liệu" hàng tiêu đề nhãn cột, cột bắt buộc in đậm có `*`; sheet "Hướng dẫn"
  liệt kê cột, kiểu, giá trị hợp lệ).
- `parse(key, content) -> list[ParsedRow]`; sai mẫu / thiếu cột / cột mã hệ thống → `ImportFileError` (Block
  `IMPORT_FILE_INVALID`, đã có trong `core.errors`).
- `check(key, content) -> dict` `{"total", "valid", "existing": [codes], "issues": [Issue]}` không ghi gì.
- `run(key, content, file_name) -> str` tên Import Batch; ≤ 200 dòng chạy ngay, > 200 enqueue `execute_batch(name)`.
- DocType `Import Batch` (naming `IMP-.YYYY.-.#####`, submittable, không xóa): `kind`, `file`, `status`
  Queued/Running/Done/Failed, `total`, `created`, `skipped`, `failed`, `started_at`, `finished_at`; child
  `Import Batch Row`: `row_no`, `code`, `result` Created/Existing/Error, `ref_doctype`, `ref_name`, `message`.

- [ ] Test trước (với một loại import giả khai báo trong test): `test_template_has_required_columns_and_help_sheet`,
  `test_parse_by_header_name_any_order`, `test_missing_required_column_rejects_file`,
  `test_system_code_column_rejects_file` (`@bru("BRU-ID-006")`), `test_cell_normalization` (số → chuỗi mã không có
  ".0", ngày Excel và `dd/mm/yyyy`, khoảng trắng, mã viết hoa), `test_check_writes_nothing`,
  `test_existing_codes_are_skipped`, `test_failure_in_one_unit_keeps_others`, `test_group_rows_header_conflict`,
  `test_large_file_is_queued` (patch `frappe.enqueue`), `test_batch_records_row_results`.
- [ ] FAIL → hiện thực → PASS; migrate. Commit `feat(core): khung import danh mục từ Excel (FEAT-011, FR-M9-11)`.

### Task 3: Khoa và Nhân viên — `tracecore/admin_reports/imports.py`

- Khoa: `department_name`*, `parent_department`, `is_ward` (→ `tc_is_ward`), `company` (mặc định Company mặc định).
  Mã = tên khoa. Ghi `Department` qua controller.
- Nhân viên: `first_name`*, `last_name`, `gender`*, `date_of_birth`*, `date_of_joining`*, `department`*,
  `company`, `user_email` (gắn User nếu có), `card_id` (thẻ có sẵn → `register_card`). Không cột mã NV-. "Đã có" = trùng
  `card_id` hoặc trùng `user_email`.
- [ ] Test trước `admin_reports/tests/test_imports.py`: tạo được, bỏ qua trùng, thẻ không hợp lệ → lỗi dòng
  (`CARD_INVALID`), khoa cha không tồn tại → lỗi dòng.
- [ ] Commit `feat(admin): import khoa và nhân viên`.

### Task 4: Dụng cụ — `tracecore/instrument/imports.py`

- Cột theo DocType Instrument: `instrument_code`*, `instrument_name`*, `spaulding_class`*, `compatible_methods`*
  (list Steam/Plasma), `instrument_group`, `manufacturer`, `model`, `maint_interval_cycles`, `maint_type`,
  `max_cycles`, `value`. Mã chuẩn hóa `catalog.normalize_code`; luật mã như nhập tay (`catalog.clean_code`).
- [ ] Test trước `instrument/tests/test_imports.py`: hợp lệ, mã sai luật, phương pháp sai, trùng → "Đã có".
- [ ] Commit.

### Task 5: Loại bộ & BOM, Set Unit — `tracecore/instrument/imports.py`

- Loại bộ & BOM (nhóm theo `type_code`): phần đầu `type_code`*, `set_type_name`*, `method`*, `department`*,
  `default_pack_type`*, `shelf_life_days`, `gtin`, `is_implant`, `assembly_minutes`; mỗi dòng `instrument`*, `qty`*,
  `position`. Ghi `bom_versions.create_set_type(header, lines)`; lỗi `BOM_LINE_INVALID` → lỗi gắn đúng dòng Excel.
- Set Unit: `type_code`*, `count`* (1..100), `department`, `max_cycles`, `origin`, `cycles_used`, `estimate_reason`.
  Ghi `set_units.issue_batch`; không có "Đã có" (mỗi dòng là một lô cấp mới) — kiểm trùng dòng trong cùng file.
- [ ] Test trước: BOM nhiều dòng, dụng cụ không tồn tại → lỗi đúng số dòng, phần đầu mâu thuẫn, Set Unit cấp đúng
  số lượng và Set ID tự sinh (`@bru("BRU-ID-006")`), count 0 / 101 → lỗi dòng.
- [ ] Commit.

### Task 6: Thiết bị & Chương trình — `tracecore/equipment/imports.py`

- Thiết bị: các trường bắt buộc của DocType Equipment (tên, loại, hãng, model, serial, khu vào/ra, giá trị, khấu hao,
  số mẻ/năm…). "Đã có" = trùng `serial_no`. Không cột TB-.
- Chương trình (nhóm theo `program_code`): phần đầu `program_code`*, `program_name`*, `equipment_serial`* (tra máy
  theo serial), `temperature`, `pressure`, `duration_min`, `requires_bi`, `kwh_per_cycle`, `water_l_per_cycle`; mỗi
  dòng một tham số `parameter_name`, `unit`, `min_value`, `max_value`, `required`.
- [ ] Test trước `equipment/tests/test_imports.py`. Commit.

### Task 7: Vật tư và Cơ số

- Vật tư `tracecore/inventory/imports.py`: `item_code`*, `item_name`*, `item_group_cssd`* (→ `tc_item_group_cssd`),
  `stock_uom`*, `compatible_method`, `ci_class`, `shelf_life_days`, `specification`, `min_qty` (Item Reorder nếu có
  luật FEAT-041). Ghi Item qua controller để luật FEAT-041 chạy.
- Cơ số `tracecore/par/imports.py`: `par_kind`*, `target_doctype`*, `target`*, `department`, `max_cycles`, `source`,
  `warn_percent`, `min_qty`, `max_qty`, `over_percent`, `reason`. "Đã có" theo luật trùng của `par.config`.
- [ ] Test trước cho cả hai. Commit.

### Task 8: RPC `tracecore.v1.imports`

**Files:** Create `tracecore/v1/imports.py`, `tracecore/v1/tests/test_imports_api.py`.
- `kinds()` → danh sách loại import (key, nhãn, số cột) theo quyền; `template(kind)` → file xlsx (download);
  `check(kind, file_url)`; `run(kind, file_url)` (`@idempotent`) → `{"batch", "status"}`; `batch(name)` → trạng thái
  + kết quả dòng; `photos(file_url)` (Task 9). Chỉ R10/R02/System Manager; file phải là File riêng tư của người gọi.
- [ ] Test trước: quyền (R04 → 403), idempotent hai lần một key → một Import Batch, file của người khác → 403.
- [ ] Commit.

### Task 9: Ảnh hàng loạt từ zip

**Files:** `tracecore/instrument/photo_import.py` (đăng ký qua hook `tracecore_photo_import`), test.
- Theo D4; đọc zip bằng `zipfile`, chỉ lấy file ở gốc hoặc thư mục con, bỏ tên có `..`/tuyệt đối, giới hạn số file
  2.000 và kích thước giải nén; ảnh qua `media.inspect_content`; tạo File riêng tư gắn bản ghi rồi `refresh_thumbnail`.
- [ ] Test trước: khớp mã dụng cụ, khớp ảnh khay -2/-3, tên không khớp vào danh sách, `../evil.jpg` bị bỏ, file không
  phải ảnh bị bỏ. Commit.

### Task 10: Màn SCR-43 (Desk Page `tc-import`) + e2e

**Files:** `tracecore/ui/page/tc_import/` (json, js, css theo token), `translations/vi.csv`,
`tests_e2e/test_desk_import.py`.
- Chọn loại → Tải mẫu → Chọn file → Kiểm tra (bảng: hợp lệ / đã có / lỗi theo dòng, tải báo cáo lỗi CSV) → Ghi sổ →
  tiến độ khi chạy nền → kết quả. Khối "Ảnh hàng loạt": chọn zip → kết quả gắn / không khớp. Lịch sử Import Batch.
- [ ] e2e: R10 import 3 dụng cụ (1 lỗi) → thấy lỗi đúng dòng, ghi sổ 2; import lại → 2 "Đã có".
- [ ] Commit.

### Task 11: Hoàn tất

- [ ] Full suite (`bench --site test_f041 run-tests --app tracecore --coverage`), diff-cover ≥ 70 % so với develop,
  `pre-commit run --all-files`, e2e desk import; RTM FR-M9-11 → test; review cả nhánh; merge develop local.

## Xong khi

Mọi test trên PASS, full suite không thêm lỗi so với develop, coverage changed-code ≥ 70 %, pre-commit sạch, e2e import
PASS, A-41 ghi đủ.
