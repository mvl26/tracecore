# FEAT-074 — Gói xuất hồ sơ KSNK cho đoàn kiểm tra theo kỳ (kế hoạch)

> Đầu vào: implementation-plan §3 E-19 dòng FEAT-074; SRS FR-M9-30, FR-M9-30.1 (liên kết FR-M9-12); BRU-RPT-002;
> NFR-PRIV-01; UC-57 bước 8, A1, A4, A5, E5; SCR-66 (WEB) + `docs/design-refs/v1.12/SCR-66_BangChiSoKSNK.png`;
> architecture §5.3 `Archive Export`, `IC Reporting Period`, ADR-001 (hook), ADR-010. Nhánh `feat/FEAT-074-ic-dossier` từ
> develop 3cc2247, bench `~/tracecore-f026`, site test `test_f026`. Amendment **A-152**.

## Ranh giới phạm vi (D3)

- **Làm:** gói PDF + Excel (kèm `manifest.json` SHA-256, dấu thời gian có offset, người xuất) cho R01 chọn dải tháng.
- **Hoãn (D3 chưa mở):** API chỉ đọc `tracecore.v1.ic.*` (implementation-plan "chỉ khi D3 được chủ đầu tư mở", UC-57 A5).
  Không tạo module `v1/ic.py`; RPC của FEAT này dùng domain `archive`.
- **M17 (FEAT-073 đang làm song song, chưa có trên develop):** không có phần ATTP trong gói; hook mở để FEAT-073 hoặc
  FEAT sau đăng ký thêm (follow-up).

## Quyết định A-152 (người dùng chọn phương án đề xuất trong chat ngày 10/11/2026)

| # | Thiếu trong tài liệu | Quyết định |
| --- | --- | --- |
| Q1 | UC-57 bước 8 chỉ ghi "R01 chọn kỳ" | Dải tháng **từ tháng – đến tháng** (kỳ `YYYY-MM`). Gói mang dấu "Tạm" khi có tháng trong dải chưa khóa (`IC Reporting Period.locked` = 0 hoặc chưa có kỳ); tháng chưa khóa thì chỉ số được tạm tính như báo cáo Hội đồng (UC-57 A1) |
| Q2 | Ai tạo gói KSNK (Archive Export cho R01 + R10 tạo) | **Chỉ R01** (và System Manager/Administrator). R10 vẫn xuất hồ sơ tiệt khuẩn như FEAT-012 nhưng không chọn được phạm vi gói KSNK. Không đổi ma trận quyền |
| Q3 | Mức chi tiết NKBV/NKVM/vi sinh (BRU-RPT-002 "tổng hợp hoặc mã che") | Excel có **danh sách** ca NKBV, NKVM, chủng đa kháng, lệnh cách ly với **mã BN che** (`***1234`), không họ tên; PDF chỉ bảng tổng hợp + số dòng từng phần. Phơi nhiễm (M16) **chỉ số liệu tổng hợp** (không tên nhân viên, không mã BN nguồn) |

## Thiết kế

- **Tái dùng `Archive Export`** (FEAT-012, "W: Archive Export"): `scope_type` thêm `IC Dossier`; dùng lại `from_date` /
  `to_date` (ngày đầu tháng đầu – ngày cuối tháng cuối); trường mới `ic_sections` (Small Text JSON, danh sách khóa phần
  đã chọn; trống = tất cả), `ic_months` (Data, chỉ đọc, "2026-01..2026-10"). Phiếu IC Dossier: không chọn `inc_*`, không
  được `full_patient_code` (BRU-RPT-002), chỉ R01. Job RQ `long` cũ (`archive.build`) rẽ sang `ic_dossier.build_files`
  theo phạm vi; ZIP, SHA-256, `verify`, thông báo, Failed giữ nguyên.
- **Hook mới `tracecore_ic_dossier_sections`** (ADR-001): mỗi hàm trả list `core.dossier.DossierSection(key, label,
  order, fields: list[exporter.ExportField], rows: fn(ctx) -> list[dict], in_pdf)`. `ctx` = `{from_date, to_date,
  months, years}`. M9 không import M11–M16; mỗi module tự đóng góp phần của mình trong file `dossier.py` riêng.
- **Chặn lộ dữ liệu (FR-M9-30.1, UC-57 E5):** `core.dossier.check_section` từ chối trường cấm (`exporter.FORBIDDEN_FIELDS`
  + `employee_name`, `source_patient_code*`, `full_name`); cột `*_masked` phải rỗng hoặc dạng che (`***` + ≤ 4 ký tự). Vi
  phạm → `DOSSIER_PERSONAL_DATA` → job Failed, không có file.
- **Phần của gói** (thứ tự): M9 `indicators` (IC Indicator Value theo tháng, toàn viện + khoa), `council_reports`,
  `self_assessment` (năm trong dải); M11 `plan_activities`, `committee_meetings` (biên bản: ngày, nội dung, số dự,
  số nghị quyết), `training` (lớp KSNK: số học viên, số đạt); M12 `compliance` (phiếu giám sát theo tháng × mẫu × khoa:
  số phiếu, điểm TB, số Đạt; cơ hội VST: tổng, tuân thủ); M13 `hai_cases`, `ssi` (danh sách, mã che); M14
  `mdro_isolates`, `isolation_orders` (danh sách, mã che); M15 `environment_samples` (mẫu, kết quả); M16 `exposures`
  (tổng hợp tháng × khoa × loại).
- **File trong ZIP:** `ksnk_dossier.pdf` (bìa: bệnh viện, dải tháng, người xuất, thời điểm có offset, dấu TẠM, mục lục
  có số dòng; bảng các phần `in_pdf`), `ksnk_dossier.xlsx` (mỗi phần một sheet, tiêu đề dịch), `manifest.json`.
- **UI SCR-66 (Page `tc-ksnk`, slug `chi-so`):** khối "Gói hồ sơ KSNK cho đoàn kiểm tra" chỉ cho R01: hai ô tháng,
  danh sách phần (checkbox, mặc định tất cả), nút "Tạo gói hồ sơ", bảng 10 gói gần nhất (mã, dải tháng, trạng thái chữ,
  "Tạm", SHA-256 rút gọn, tải ZIP). Lỗi chặn `alert-error` inline.
- **RPC (domain `archive`, Desk, không `@idempotent`):** `tracecore.v1.archive.ic_dossier_sections` (GET),
  `tracecore.v1.archive.ic_dossier_export` (POST), `tracecore.v1.archive.ic_dossiers` (GET). Quyền R01.

## AC (EARS, suy từ FR)

- AC-1 (FR-M9-30, Q1): Khi R01 chọn dải tháng và tạo gói, hệ thống phải tạo `Archive Export` phạm vi `IC Dossier` và chạy
  job nền sinh ZIP gồm PDF + Excel + `manifest.json` (SHA-256, số byte, số dòng từng file, thời điểm có offset, người xuất).
- AC-2 (FR-M9-30): Gói phải gồm kế hoạch, biên bản Hội đồng, kết quả giám sát (tuân thủ, NKBV/NKVM, vi sinh–cách ly, môi
  trường, phơi nhiễm), chỉ số và đào tạo của các tháng trong dải; R01 có thể bỏ bớt phần.
- AC-3 (FR-M9-30.1, BRU-RPT-002, Q3): Gói không chứa mã BN rõ, họ tên người bệnh, tên nhân viên phơi nhiễm; cột mã chỉ dạng
  che; phần M16 chỉ số liệu tổng hợp.
- AC-4 (UC-57 E5): Nếu một phần đăng ký trường cấm hoặc trả mã không che, thì hệ thống phải chặn xuất (phiếu Failed, không
  file) và ghi lý do.
- AC-5 (Q1, UC-57 A1): Nếu có tháng trong dải chưa khóa, thì gói phải mang dấu "Tạm" (PDF, manifest, phiếu).
- AC-6 (Q2): Nếu người không phải R01 tạo gói KSNK, hoặc gói KSNK yêu cầu mã BN đầy đủ, thì hệ thống phải từ chối.
- AC-7 (FR-M9-12 cơ chế): `verify` so SHA-256 file đang lưu; phiếu không sửa, không xóa sau khi tạo.
- AC-8 (UC-57 A4): Gói luôn chạy job nền và báo người xuất khi xong (chuông + realtime), như FEAT-012.
- AC-9 (SCR-66): R01 thấy khối gói hồ sơ trên SCR-66 với đủ trạng thái loading/empty/error; người khác không thấy khối.

## Tasks (TDD — test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Docs A-152** — Revision History architecture (+ §5.3 `Archive Export` trường mới, hook mới), implementation-plan ghi
   chú FEAT-074, rtm FR-M9-30 → FEAT-074 / test. (Q1–Q3)
2. **`core/dossier.py`** — `DossierSection`, `sections()`, `check_section`, `check_rows`, `months(from, to)`. Test
   `tracecore.tests.test_core_dossier` `@bru("BRU-RPT-002")`: trường cấm bị từ chối, mã không che bị từ chối, dải tháng.
   (AC-3, AC-4)
3. **`Archive Export` mở rộng** — JSON (`IC Dossier`, `ic_sections`, `ic_months`, depends_on), `validate` (chỉ R01, không
   full code, dải tháng hợp lệ, phần hợp lệ). Test trong `admin_reports/tests/test_ic_dossier.py`. (AC-6, AC-7)
4. **`admin_reports/ic_dossier.py`** — `build_files(doc)`: ctx, tạm tính tháng chưa khóa, gom phần, kiểm, PDF
   (`print/ic_dossier.html`), xlsx nhiều sheet, provisional; `archive.build` rẽ nhánh. M9 tự đăng ký 3 phần. Test: ZIP có
   PDF/xlsx/manifest; phần chọn; Tạm/Chính thức; phần lộ mã → Failed. (AC-1, AC-2, AC-4, AC-5, AC-8)
5. **Phần của module** — `infection_program/dossier.py`, `compliance_audit/dossier.py`, `hai_surveillance/dossier.py`,
   `microbiology/dossier.py`, `environmental_hygiene/dossier.py`, `occupational_safety/dossier.py`; đăng ký hook. Test
   mỗi module (`tests/test_dossier.py` trong module): lọc theo dải ngày, mã che, M16 không có trường cá nhân. (AC-2, AC-3)
6. **RPC** `v1/archive.py` thêm 3 hàm + test `TestIcDossierRpc` trong `admin_reports/tests/test_ic_dossier.py`. (AC-1,
   AC-6)
7. **UI** `public/js/ksnk/scr_66_chi_so.js` khối gói hồ sơ (R01). Test `tests/test_ksnk_scr66_dossier.py` (JS harness):
   trạng thái bằng chữ, dấu Tạm, phần chỉ Excel, danh sách trống. (AC-9)
8. **vi.csv**, lint, test module lần lượt, diff-cover ≥ 70 %, pre-commit, push `github`.

## File dùng chung (chỉ thêm khối `# FEAT-074`)

hooks.py (`tracecore_ic_dossier_sections`), admin_reports/archive.py (rẽ nhánh build + `related` cho phạm vi mới),
archive_export.json/.py, v1/archive.py, scr_66_chi_so.js, tc_ksnk.css (nếu cần), translations/vi.csv.
Không đổi ma trận quyền (95 dòng giữ nguyên).

## Test module chạy lần lượt (`flock /tmp/tc-moduletest.lock … run-tests --module …`)

`tracecore.tests.test_core_dossier`, `tracecore.admin_reports.tests.test_ic_dossier`,
`tracecore.admin_reports.tests.test_archive`, `tracecore.infection_program.tests.test_dossier`,
`tracecore.compliance_audit.tests.test_dossier`, `tracecore.hai_surveillance.tests.test_dossier`,
`tracecore.microbiology.tests.test_dossier`, `tracecore.environmental_hygiene.tests.test_dossier`,
`tracecore.occupational_safety.tests.test_dossier`, `tracecore.tests.test_ksnk_scr66_dossier`,
`tracecore.tests.test_ksnk_scr66`; vì đổi DocType: `tracecore.tests.test_permissions`,
`tracecore.tests.test_permissions_v112`, `tracecore.tests.test_name_columns` và test có gọi `ksnk.nav`.
