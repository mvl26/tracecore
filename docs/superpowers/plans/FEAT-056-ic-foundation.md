# FEAT-056 Nền v1.12 — vai trò R11–R13, 7 module, chỉ số KSNK, hồ sơ ánh xạ cột, màn quản lý `tc-ksnk` — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-19 (FEAT-056), F-21, F-22, §6.1 DoD v1.12; `docs/srs.md` FR-M9-27, FR-M9-27.1, FR-M9-28, FR-M9-28.1, BRU-RPT-001, BRU-RPT-003, NFR-SEC-09, EI-SW-010; `docs/use-cases.md` UC-57; `docs/architecture.md` A-113 (§5.2, §5.3.1, §5.3.3, §6.10, §8), A-131 (Page `tc_ksnk`); `docs/ux-foundations.md` SCR-66, SCR-43; bản giao diện `docs/design-refs/v1.12/SCR-66_BangChiSoKSNK.png`.
> Phụ thuộc: FEAT-001, 009, 010, 015 (đã có trên `develop`). Sprint S6. Cỡ M.
> Nhánh: `feat/FEAT-056-ic-foundation`.
> Không đụng: Page `station`, `tracecore-theme.css`, Portal, màn M1–M10. Phần dùng chung chỉ được **thêm** (hook, fixtures Role/DocPerm, cột ma trận quyền, loại import).

## Quyết định thiết kế cần người dùng chốt (mặc định đề xuất)

- **D1 — Kỳ của chỉ số trước khi có `IC Reporting Period`.** `IC Reporting Period` (khóa kỳ) thuộc M13, làm ở FEAT-063. Đề xuất: `IC Indicator Value.period` là Data dạng `YYYY-MM`; FEAT-056 cung cấp engine `indicator.compute_period(period)`, `indicator.lock_period(period)`, `indicator.unlock_period(period, reason)` gọi trực tiếp được; FEAT-063 chỉ gọi engine khi R01 khóa/mở kỳ. Không Link sang DocType M13 chưa có.
- **D2 — Loại import cụ thể (mẫu số, phẫu thuật, vi sinh, hóa chất).** DocType đích chưa có. Đề xuất: FEAT-056 làm **cơ chế** hồ sơ ánh xạ cột trong `core.importer` (đổi tên cột, định dạng ngày, encoding, nhận CSV) và test bằng một loại import giả trong test; mỗi loại import thật đăng ký qua hook `tracecore_import_kinds` ở FEAT của nó (062 mẫu số, 064 phẫu thuật, 066 hóa chất, 067 vi sinh).
- **D3 — Quyền mặc định cho DocType mới** (ký hiệu SEC: R đọc, W ghi, S ghi sổ; ô trống = không quyền):

  | DocType | R01 | R10 | R11 | R12 | R13 | R02–R09 |
  | --- | --- | --- | --- | --- | --- | --- |
  | IC Program Settings (Single) | R | RW | R | — | R | — |
  | IC Indicator (danh mục, R01 duyệt nội dung chuyên môn — D10) | RW | RW | R | R | R | — |
  | IC Indicator Value (hệ thống ghi) | R | R | R | R (khoa mình + toàn viện) | R | — |
  | Import Mapping Profile | R | RW | RW | — | — | — |

  R11–R13 trên 53 DocType cũ: để trống (không quyền). `Import Batch` thêm quyền tạo cho R11 theo đường quyền hiện có của FEAT-011.
- **D4 — Đăng nhập R12.** Theo cách của R08 (người dùng có quyền Desk tối thiểu, giới hạn Department qua User Permission); vào `/app/tc-ksnk` thì chuyển sang Cổng khoa. 2FA bật cho R11, R13 (architecture A-113 a).
- **D5 — Hai trường lưu định danh** (`patient_data_retention_months`, `exposure_retention_months`) có trong `IC Program Settings` ngay ở FEAT-056 (architecture §8.2), để trống = chưa áp dụng; job xóa định danh làm ở FEAT-063/071.

## Acceptance criteria (EARS)

- **AC-1** (A-113 a; F-22): Hệ thống có 3 Role `TC R11`, `TC R12`, `TC R13` (fixtures) và 3 Role Profile tương ứng; `ROLE_CODES` gồm R01–R13; fixture `custom_docperm.json` sinh lại từ `permission_matrix.csv` có cột R11–R13.
- **AC-2** (A-113 a): `modules.txt` có 7 Module Def mới `Infection Program`, `Compliance Audit`, `HAI Surveillance`, `Microbiology`, `Environmental Hygiene`, `Occupational Safety`, `Food Safety`, mỗi module một package Python; 7 package nằm trong `BUSINESS` của `scripts/check_architecture.py` và lint bắt được import chéo giữa chúng.
- **AC-3** (FR-M11-01 nền; §5.3.1; D5): `IC Program Settings` (Single, module Infection Program) có `bed_count`, `facility_level` (Chuyên sâu / Cơ bản / Ban đầu), `has_inpatient`, `surveillance_ratio_beds` (mặc định 150), `doc_review_months` (mặc định 12), `patient_data_retention_months`, `exposure_retention_months`; số âm bị từ chối.
- **AC-4** (§5.3.1): `IC Indicator` (module Infection Program, tên = `code`) có `indicator_name`, `measure_group` (14 nhóm), `kind` (Tỷ lệ % / Tỷ suất ‰ / Số đếm), `source_method`, `frequency`, `national_target`, `target_ref`, `min_sample`, `is_active`; `source_method` phải là khóa đã đăng ký qua hook `tracecore_ic_indicators` khi bật `is_active`.
- **AC-5** (FR-M9-27; §6.10; D1): Khi gọi `compute_period(period)` rồi `lock_period(period)`, hệ thống ghi một `IC Indicator Value` (`IV-.YYYY.-.######`) cho mỗi chỉ số đang dùng × (toàn viện + từng khoa có dữ liệu), gồm tử số, mẫu số, giá trị, `sample_note`, `computed_on`, `locked = 1`.
- **AC-6** (BRU-RPT-003, FR-M9-27): Khi kỳ đã khóa, gọi lại `compute_period` hoặc dữ liệu nguồn đổi thì giá trị đã lưu không đổi.
- **AC-7** (FR-M9-27.1, BRU-RPT-003): Khi R01 gọi `unlock_period(period, reason)` có lý do rồi khóa lại, hệ thống tính lại và ghi Audit Log trước/sau; không có lý do hoặc không phải R01 → từ chối.
- **AC-8** (BRU-RPT-001, BRU-HAI-006): Mẫu số 0 → `value` rỗng và `sample_note` "Không tính", không lưu 0; dưới `min_sample` → `sample_note` "Chưa đủ mẫu".
- **AC-9** (FR-M9-27; NFR-SEC-09): RPC chỉ đọc `tracecore.v1.indicator.values(period, department=None)` trả giá trị đã lưu, không tính lại; R12 chỉ nhận dòng khoa mình và dòng toàn viện; vai trò không có quyền đọc → từ chối.
- **AC-10** (FR-M9-28, F-21, EI-SW-010): `Import Mapping Profile` (+ child `Import Mapping Profile Column`: cột nguồn → cột đích, bắt buộc) gắn loại import, `date_format`, `encoding`; khi R11/R10 nhập file kèm hồ sơ, khung import đổi tên cột theo hồ sơ, nhận `.xlsx` và `.csv`, kiểm từng dòng như FR-M9-11.
- **AC-11** (FR-M9-28.1): Khi file 500 dòng có 3 dòng lỗi, hệ thống ghi 497 dòng và báo 3 dòng lỗi kèm số dòng; nhập lại cùng file không tạo trùng.
- **AC-12** (A-131 a–c, e): Page `tc-ksnk` (`/app/tc-ksnk/<màn>`): rail trái 250 px chia 5 nhóm như bản giao diện, crumb, tiêu đề + tag SCR/UC, bộ lọc năm/kỳ/khoa giữ trong URL, đủ 4 trạng thái (đang tải, rỗng, lỗi, không có quyền); CSS chỉ trong `.tc-ksnk`, chỉ token `--tc-*`.
- **AC-13** (A-131 b): RPC chỉ đọc `tracecore.v1.ksnk.nav` trả mục menu theo vai trò người gọi và số badge (hook `tracecore_ksnk_badges`) trong một lần gọi; mục chưa có màn (FEAT sau) không hiện.
- **AC-14** (A-131 e): R13 mở Page → vào SCR-66, không có nút ghi; R12 mở Page → chuyển sang Cổng khoa.
- **AC-15** (A-131 g): Màn SCR-66 tối thiểu: bảng giá trị chỉ số đã khóa (mã, tên, nhóm, mục tiêu, 3 kỳ gần nhất, trạng thái bằng chữ "Đạt / Chưa đạt / Không tính / Chưa đủ mẫu"), đọc qua `indicator.values`.
- **AC-16** (NFR-SEC-09; F-22): Test sinh từ CSV kiểm 100 % ô của 4 DocType mới × 13 vai trò; R12 khoa A không đọc được `IC Indicator Value` của khoa B; test cũ của R01–R10 vẫn pass.
- **AC-17**: Chuỗi hiển thị qua `_()`/`__()` và có trong `translations/vi.csv`; toàn bộ test của app (không chỉ test mới) pass trên `test_site`.

## Tasks (TDD — viết test trước, thấy fail rồi mới code)

1. **Vai trò và ma trận quyền** (AC-1, AC-16, D3, D4). `setup/permissions.py`: `ROLE_CODES` R01–R13. `fixtures/permission_matrix.csv`: thêm cột R11, R12, R13 (trống cho 53 dòng cũ) và 4 dòng `DT-ICSET`, `DT-ICIND`, `DT-ICVAL`, `DT-IMPMAP`. `fixtures/role.json` + Role Profile. Sửa `tests/test_permissions.py` (13 vai trò, 57 dòng). Test mới `tracecore/tests/test_permissions_v112.py`.
2. **Module Def và lint kiến trúc** (AC-2). `modules.txt` + 7 package `__init__.py`; `scripts/check_architecture.py` BUSINESS thêm 7 package. Test `tracecore/tests/test_check_architecture.py` (thêm ca import chéo `infection_program` → `hai_surveillance` bị báo R1).
3. **IC Program Settings** (AC-3, D5). DocType Single module Infection Program, controller kiểm số không âm. Test `infection_program/doctype/ic_program_settings/test_ic_program_settings.py`.
4. **IC Indicator** (AC-4). DocType danh mục, autoname `field:code`, kiểm `source_method` có trong registry khi `is_active`. Test `infection_program/doctype/ic_indicator/test_ic_indicator.py`.
5. **Engine chỉ số** (AC-5..AC-8, D1). DocType `IC Indicator Value` (module Admin Reports, naming `IV-.YYYY.-.######`, index `indicator, period, department`). `admin_reports/indicator.py`: `registry()` đọc hook `tracecore_ic_indicators` (mỗi hàm trả `{source_method: callable(period, department) -> (numerator, denominator, sample_n)}`), `compute_period`, `lock_period`, `unlock_period` (R01, lý do bắt buộc, Audit Log). Test `admin_reports/tests/test_indicator.py` với hàm tính giả đăng ký qua `frappe.get_hooks` patch; marker `@bru("BRU-RPT-001")`, `@bru("BRU-RPT-003")`.
6. **RPC chỉ đọc** (AC-9). `v1/indicator.py`: `values(period, department=None, periods=3)`; R12 lọc khoa theo User Permission; `permission_query_conditions` cho `IC Indicator Value`. Test `v1/tests/test_indicator_api.py`.
7. **Hồ sơ ánh xạ cột** (AC-10, AC-11, D2). DocType `Import Mapping Profile` + child `Import Mapping Profile Column` (module TraceCore). `core/importer.py`: tham số `profile` → đổi tên cột trước `parse`, `date_format`, đọc CSV (`encoding`). Test `core/tests/test_importer_profile.py` (loại import giả, file 500 dòng / 3 lỗi, nhập lại không trùng, CSV UTF-8 và Windows-1258); test hồi quy `core/tests/test_importer.py` giữ nguyên pass.
8. **Màn quản lý `tc-ksnk`** (AC-12..AC-14). Page `ui/page/tc_ksnk/` (`tc_ksnk.json` tên `tc-ksnk`, roles R01, R10, R11, R12, R13, System Manager). `ui/ksnk.py`: registry màn (slug, SCR, UC, nhãn, nhóm, vai trò, file JS) và `nav(user)`; hook `tracecore_ksnk_badges`. `v1/ksnk.py`: `nav()`. JS: `public/js/ksnk/shell.js` (rail, router, bộ lọc trong URL, 4 trạng thái), `public/css/ksnk.css` (`.tc-ksnk`, chỉ `--tc-*`). Test Python `ui/tests/test_ksnk_nav.py` (menu theo vai trò, badge, R12 bị chuyển); test JS theo mẫu `tests/test_station_behavior.py` cho router và trạng thái.
9. **Màn SCR-66 tối thiểu** (AC-15). `public/js/ksnk/scr_66_chi_so.js` đăng ký trong registry; trạng thái bằng chữ, không chỉ màu. Test JS.
10. **Bản dịch, lint, kiểm tra cuối** (AC-17). `translations/vi.csv`; `pre-commit run --all-files`; `bench --site test_site run-tests --app tracecore --coverage` (đọc OK/FAILED trong log, không tin exit code); `diff-cover … --fail-under=70`; `bench --site tracecore-dev.local migrate`, `bench build --app tracecore` (nvm). Không chạy E2E. Đối chiếu từng AC rồi báo người dùng; merge `develop` khi người dùng bảo.

## Ngoài phạm vi (FEAT sau)

- Loại import thật (062, 064, 066, 067), khóa kỳ trên giao diện (063), bảng chỉ số đầy đủ, KPI, báo cáo Hội đồng, Cổng khoa, tự đánh giá QĐ 38 (065), job xóa định danh (063, 071), mọi màn SCR-47..65.
