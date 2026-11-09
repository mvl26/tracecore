# FEAT-060 Engine phiếu giám sát (ADR-015) — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-13 (FEAT-060), §6.1 DoD v1.12; `docs/srs.md` FR-M12-01 (.1, .2), FR-M12-03 (.1), FR-M12-04 (.1), FR-M12-06 (.1, .2), FR-M12-08 (.1, .2), FR-M12-09 (.1, .2), FR-M12-10 (.1), FR-M12-11 (.1), FR-M12-14 (.1), BRU-AUD-001, BRU-AUD-004, BRU-AUD-005, NFR-AVAIL-05, NFR-SEC-09, NFR-MAINT-04; `docs/use-cases.md` UC-43, UC-44, UC-45; `docs/architecture.md` ADR-015, §5.3 (M12), §5.3.3, sequence §6 (phiếu PDA), A-131; `docs/ux-foundations.md` SCR-50, SCR-52, SCR-53; ảnh `docs/design-refs/v1.12/SCR-50_MauPhieu.png`, `SCR-52_PDA-PhieuMuc.png`, `SCR-53_BaoCaoTuanThu.png`.
> Phụ thuộc: FEAT-056 (đã merge `develop` e03989a), FEAT-009 (outbox), FEAT-010 (notification), FEAT-030 (Incident CAPA), FEAT-051 (Station Function). Sprint S6. Cỡ L.
> Nhánh: `feat/FEAT-060-audit-engine` (bench phụ `~/tracecore-f043`, site test `test_f043`).
> Song song FEAT-057: file dùng chung (`permission_matrix.csv`, `translations/vi.csv`, `hooks.py`, `ui/ksnk.py`, `core/name_columns.py`) chỉ **nối thêm**, không ghi lại cả file.

## Quyết định thiết kế cần người dùng chốt (mặc định đề xuất)

- **Q1 — Ngưỡng đạt của phiếu Điểm % (tài liệu thiếu).** Ảnh SCR-50 có ô "Ngưỡng đạt 85 %", nhưng architecture §5.3/ADR-015 và FR-M12-06 không có trường này, cũng không nói phiếu Điểm % "Đạt" khi nào. Đề xuất: thêm trường `pass_threshold` (Percent) vào `Audit Template`, kèm một dòng Revision History (amendment nhỏ A-134, chỉ thêm trường). Kết quả = Không đạt nếu có mục trọng yếu Không đạt (BRU-AUD-005); nếu không thì Đạt khi `score_pct ≥ pass_threshold`; ô trống = không xét ngưỡng (Đạt nếu không có mục trọng yếu Không đạt).
- **Q2 — Surface DEPT (Cổng khoa) chưa có trong repo.** Repo chưa có Portal nào. Shell `tc-ksnk` (FEAT-056) đã chuyển R12 sang "Cổng khoa", nhưng Cổng khoa (FR-M9-26) thuộc FEAT-065. Đề xuất cho FEAT-060:
  - SCR-52 DEPT: R12/R08 dùng chính Page `station` (PWA) trên thiết bị của khoa.
  - SCR-53 view DEPT: Script Report "Tuân thủ theo khoa" và danh sách/form `Audit Session` chỉ đọc trên Desk. R12/R08 chỉ thấy khoa mình qua `permission_query_conditions` + `has_permission`. Link trong thông báo phản hồi mở form phiếu.
  - Gom vào Cổng khoa ở FEAT-065.
- **Q3 — Ranh giới với FEAT-061/062 và các FEAT M13/M15.**
  - FEAT-060 tạo đủ schema `Audit Session` theo §5.3, gồm cả child `Hand Hygiene Opportunity`. Kiểm BRU-AUD-004 ở server áp cho `subject_employee` của phiếu và của từng cơ hội.
  - Phương pháp "Theo cơ hội" (tỷ lệ BRU-AUD-002, RPC `record_opportunity`, SCR-51, 8 mẫu khởi tạo FR-M12-02) để FEAT-061 làm. Engine có sổ hàm chấm theo `scoring_method`: FEAT-060 làm "Điểm %" và "Tất cả-hoặc-không" (mục Không áp dụng loại khỏi mẫu số), FEAT-061 đăng ký "Theo cơ hội".
  - Trường `device_episode` (Link M13), `environment_zone`, `next_due` (M15) chưa thêm được vì DocType đích chưa có; FEAT-062 và FEAT M15 sẽ thêm vào JSON `Audit Session`. FEAT-060 thêm `supplier` (ERPNext Supplier đã có).
  - Phần NFR-MAINT-04 ở FEAT-060 chỉ là cơ chế: `compliance_audit.seed.install_templates(rows)` chỉ chèn mẫu còn thiếu theo `template_code` và không ghi đè. Cơ chế này được test bằng fixture giả; nội dung mẫu thật làm ở FEAT-061.

Các mặc định dưới đây sẽ dùng nếu người dùng không phản đối:

- **D1 — Quyền** (R đọc, W ghi, S ghi sổ; giới hạn khoa qua User Permission Department):

  | DocType | R01 | R02 | R08 | R10 | R11 | R12 | R13 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | Audit Template | RWS (duyệt) | R | R | R | RW (soạn nháp) | R | R |
  | Audit Schedule | RW | RW | — | R | R | — | R |
  | Audit Session | RWS (tất cả) | R (tất cả) | RWS (khoa mình) | — | RWS (mọi khoa) | RWS (khoa mình) | — (chỉ báo cáo tổng hợp, UC-45 A2) |

  R03–R07 và R09: không có quyền. Child table: không có dòng trong ma trận. Report "Tuân thủ theo khoa": R01, R02, R08, R11, R12 (khoa mình), R13.
- **D2 — Phiên bản mẫu.**
  - `name` = `MP-<template_code>-V<n>`, sinh bằng hàm mới `core.versioning.make_versioned_code`. Architecture nhắc hàm này nhưng repo chưa có.
  - Ghi sổ = R01 duyệt. Frappe khóa nội dung, và hook `before_update_after_submit` chặn sửa kèm gợi ý "Tạo phiên bản V(n+1)" (FR-M12-01.1).
  - RPC `tracecore.v1.audit.new_version(template)` chép mẫu thành Nháp `version_no + 1`. Không dùng Amend, vì Amend đòi Hủy bản cũ.
  - Khi V(n+1) ghi sổ, V(n) được đặt `superseded_by` (allow_on_submit) và hiện trạng thái "Hết hiệu lực".
  - Phiếu mới dùng bản đã duyệt mới nhất có `effective_from ≤ hôm nay`.
- **D3 — Bản chụp mẫu.** Khi tạo phiếu, server chép từng mục của phiên bản vào child `Audit Answer`: `item_code`, `section`, `question`, `answer_type`, `weight`, `is_critical`. Người dùng chỉ được ghi `answer`, `value`, `photo`, `note`. Mở phiếu cũ thì hiện đúng câu hỏi Vn (FR-M12-01.2).
- **D4 — NC Compliance qua hook, không import M2.**
  - M2 thêm `Compliance` vào `incident_category` và loại `incident_type` mới "Compliance Nonconformity".
  - M12 gọi hook mới `tracecore_compliance_nc` (`reprocessing.incidents.on_compliance_nc`). Hook tạo Incident qua dịch vụ `incidents` với `source_doctype = Audit Session`, `source_name`, `department`, `incident_category = Compliance`.
  - Mỗi phiếu có tối đa một NC.
  - Đóng NC cần `verification_result` theo `incidents.close` đã có; FEAT-060 thêm test cho loại Compliance (FR-M12-09.2).
  - "Đề nghị" nghĩa là hệ thống không tự tạo NC. Khi ghi sổ, R11/R01 nhận thông báo `audit_critical_fail`. SCR-53 có "Mở NC" (RPC `tracecore.v1.audit.open_nc`) và "Bỏ qua (ghi lý do)" (RPC `tracecore.v1.audit.dismiss_nc`, ghi Audit Log), như ảnh.
- **D5 — Phản hồi khoa (FR-M12-08).**
  - Sự kiện `audit_feedback` qua `core.notification.emit` gửi tới người dùng có Role `TC R08` hoặc `TC R12` và User Permission Department = khoa của phiếu. Cách này không phụ thuộc DocType `IC Network Member` của FEAT-057 đang làm song song.
  - Khoa không có R12 nào thì báo thêm R01 (UC-45 A1).
  - Thêm 4 sự kiện vào `EVENTS`: `audit_due`, `audit_coverage_low`, `audit_feedback`, `audit_critical_fail`.
- **D6 — Lịch và độ bao phủ (FR-M12-03).**
  - Kỳ = tuần ISO / tháng / quý theo `frequency`.
  - Job hằng ngày `compliance_audit.schedule.run_daily` gửi `audit_due` cho `assignee` vào ngày đầu kỳ. Vào tuần cuối kỳ (7 ngày cuối; với tuần là ngày cuối), khoa nào chưa đạt `target_count` thì gửi `audit_coverage_low` cho assignee và R02.
  - Độ bao phủ tính lúc đọc: số phiếu đã ghi sổ trong kỳ theo `template_code` × khoa. Với mẫu "Theo cơ hội", đếm số cơ hội; tới FEAT-061 mới có dữ liệu.
  - Không tạo DocType "việc".
  - Lưu lịch gắn mẫu chưa duyệt thì bị chặn (UC-43 E2).
- **D7 — PDA SCR-52.**
  - Màn mới trên Page `station`: Station Function `AUD` "Phiếu giám sát", gắn Zone Type khoa (fixture), file `public/js/station_audit.js`.
  - Đăng nhập dùng thẻ/PIN như hiện có. Function `AUD` không đòi competency CSSD, vì giám sát viên không phải nhân viên CSSD.
  - Luồng ≤ 3 chạm sau khi chọn mẫu: danh sách mục, mỗi mục có 3 nút chữ Đạt / Không / K. áp dụng ≥ 48 px. Mục trọng yếu có nhãn chữ "Trọng yếu". Mục Không đạt bắt buộc có ghi chú hoặc ảnh. Thanh kết quả tạm tính ở đáy, nút Ghi sổ 56 px.
  - Offline: mẫu đã duyệt được cache (snapshot đọc của outbox). Phiếu được xếp hàng với RPC `tracecore.v1.audit.submit_session` (thêm vào `TC_QUEUEABLE`), dùng UUID phiếu làm `X-Idempotency-Key`.
  - Chặn tự đánh giá ngay trên client bằng alert-error inline, và chặn lại ở server.
- **D8 — Báo cáo FR-M12-14.**
  - Script Report "Compliance by Department" (module Compliance Audit) lọc theo kỳ, loại phiếu, mẫu, khoa và nghề nghiệp. Cột gồm khoa, số phiếu, điểm TB, số Đạt, tỷ lệ Đạt, cỡ mẫu n, ghi chú bằng chữ ("Chưa đủ cỡ mẫu", "Không tính"). Xuất Excel/PDF bằng nút có sẵn của Frappe và `tc_report_export.js`.
  - Chỉ đếm phiếu đã ghi sổ (docstatus 1, FR-M12-14.1).
  - Đẩy chỉ số sang M9: đăng ký `compliance_audit.indicators.register` vào hook `tracecore_ic_indicators`, với `audit_pass_rate` (tỷ lệ phiếu Đạt theo khoa/kỳ). Tỷ lệ VST thuộc FEAT-061.
  - Thêm Print Format "Audit Session" cho phiếu.

## Acceptance criteria (EARS)

- **AC-1** (FR-M12-01, BRU-AUD-001): Khi R01 ghi sổ `Audit Template`, hệ thống phải khóa nội dung phiên bản `MP-<code>-V<n>`. Chỉ R01 ghi sổ được.
- **AC-2** (FR-M12-01.1): Nếu người dùng sửa câu hỏi hoặc trọng số của mẫu đã duyệt, thì hệ thống phải chặn và gợi ý tạo V(n+1). `new_version` phải tạo Nháp V(n+1) chép đủ mục. Khi V(n+1) ghi sổ, V(n) phải được đánh dấu bị thay thế.
- **AC-3** (FR-M12-01.2, BRU-AUD-001): Khi mở phiếu đã ghi sổ theo Vn sau khi V(n+1) được duyệt, hệ thống phải hiển thị đúng câu hỏi và trọng số của Vn.
- **AC-4** (BRU-AUD-001): Nếu tạo phiếu hoặc lịch từ mẫu Nháp hoặc đã bị thay thế, thì hệ thống phải chặn.
- **AC-5** (FR-M12-03, .1): Khi lịch tháng có mục tiêu 30 và khoa đã có 12, `coverage()` phải trả "12/30". Job hằng ngày phải gửi `audit_due` vào ngày đầu kỳ, và gửi `audit_coverage_low` vào tuần cuối kỳ cho khoa chưa đạt. Chạy job hai lần trong một ngày không được gửi trùng.
- **AC-6** (FR-M12-06, .1, .2; BRU-AUD-005): Với phiếu Điểm %, điểm = Σ trọng số mục Đạt / Σ trọng số mục áp dụng, và mục K. áp dụng bị loại khỏi mẫu số. Phiếu 95 % có một mục trọng yếu Không đạt phải có `result` = Không đạt. Phiếu không có mục áp dụng nào phải có `score_pct` rỗng, không ghi 0. Với phiếu Tất cả-hoặc-không, phiếu chỉ Đạt khi mọi mục áp dụng đều Đạt.
- **AC-7** (FR-M12-10, .1; BRU-AUD-004): Khi `subject_employee` (của phiếu hoặc của cơ hội) trùng `observer`, server phải chặn bằng lỗi có mã. PDA phải hiện alert-error inline và không lưu.
- **AC-8** (FR-M12-04, .1; NFR-AVAIL-05; ADR-003): `tracecore.v1.audit.submit_session` phải `@idempotent`. Gửi lại cùng key phải trả response cũ và không tạo phiếu thứ hai. Phiếu tạo lúc offline phát lại trong 24 giờ phải được nhận. Test Python phải mô phỏng 20 lần phát lại và kết quả 0 trùng. Không chạy E2E.
- **AC-9** (FR-M12-08, .1, .2; NFR-SEC-09): Khi phiếu được ghi sổ, R08 và R12 của khoa phải nhận `audit_feedback` (điểm, mục không đạt, link). Nếu khoa không có R12, R01 cũng nhận. R12 khoa A không được thấy phiếu khoa B qua list, `get_doc` hay report. Test sinh từ CSV phải kiểm 100 % ô của 3 DocType mới × 13 vai trò.
- **AC-10** (FR-M12-09, .1, .2; BRU-AUD-005): Khi phiếu có mục trọng yếu Không đạt, R11/R01 phải nhận `audit_critical_fail`. `open_nc` phải tạo đúng một `Incident CAPA` với `incident_category` = Compliance, `source_doctype` = Audit Session và `source_name` = phiếu. Đóng NC khi chưa có kết quả xác minh phải bị chặn. `dismiss_nc` phải bắt buộc lý do và ghi Audit Log.
- **AC-11** (FR-M12-11, .1): Khi khoa–kỳ có n < `min_sample`, báo cáo phải hiện "… (n = 8, chưa đủ cỡ mẫu)". Khi n = 0, báo cáo phải hiện "Không tính" (BRU-RPT-001).
- **AC-12** (FR-M12-14, .1): Tổng trên báo cáo phải bằng số tính lại từ phiếu đã ghi sổ trong kỳ, không tính phiếu Nháp hoặc Hủy. Báo cáo phải xuất được Excel/PDF. Hàm `audit_pass_rate` phải có trong registry `core.indicators`.
- **AC-13** (A-131): SCR-50 (`/app/tc-ksnk/mau-phieu`) và SCR-53 (`/app/tc-ksnk/tuan-thu`) phải có trong `SCREENS`, nhóm `compliance`, theo vai trò D1, đủ 4 trạng thái.
  - SCR-50: danh sách mẫu (phiên bản, trạng thái bằng chữ Nháp / Đã duyệt / Hết hiệu lực); bảng mục của mẫu đang chọn (sửa được khi Nháp); Duyệt (R01); Lưu nháp; Tạo phiên bản mới; bảng lịch kỳ hiện tại với độ bao phủ bằng số; Tạo lịch.
  - SCR-53: bộ lọc loại phiếu, kỳ, nghề; thẻ số; bảng theo khoa; phiếu gần đây; khối "Đề nghị mở NC".
  - Badge `tracecore_ksnk_badges` phải đếm NC chờ quyết định.
- **AC-14** (SCR-52, NFR-USAB-03): Màn `AUD` trên Page `station` phải có ô chọn mẫu và khoa ở đầu màn; R12 chỉ thấy khoa của mình. Mỗi mục có 3 nút chữ ≥ 48 px. Nút Ghi sổ 56 px. Màn phải đủ 4 trạng thái loading / empty / error / offline, và có badge số phiếu đang chờ. Chỉ dùng token `--tc-*`. Test JS theo mẫu `tests/test_station_behavior.py`.
- **AC-15** (NFR-MAINT-04, cơ chế): Gọi `install_templates(rows)` hai lần phải không tạo trùng. Mẫu bệnh viện đã sửa hoặc đã duyệt phải giữ nguyên.
- **AC-16**: Mọi chuỗi phải đi qua `_()`/`__()` và có trong `translations/vi.csv`. Toàn bộ test của app phải pass. diff-cover phải ≥ 70 %. `pre-commit run --all-files` phải sạch.

## Tasks (TDD — viết test trước, thấy fail rồi mới code)

1. **Phiên bản dùng chung và quyền** (D1, D2, AC-9 phần ma trận).
   - Tạo `core/versioning.py` (`make_versioned_code`) và test `core/tests/test_versioning.py`.
   - `fixtures/permission_matrix.csv`: nối 3 dòng `DT-AUDTPL`, `DT-AUDSCH`, `DT-AUDSES` cùng report, rồi sinh lại `custom_docperm.json`.
   - Test `tracecore/tests/test_permissions_v112.py`: nối thêm ca.
2. **Audit Template + Audit Template Item** (AC-1..AC-4, Q1).
   - DocType ở `compliance_audit/doctype/`, submittable, autoname bằng `make_versioned_code`. Trường theo §5.3, cộng `pass_threshold` và `superseded_by`.
   - Kiểm hợp lệ: `item_code` không trùng trong mẫu; trọng số ≥ 0; mẫu Gói dự phòng không có mục trọng yếu nào thì chỉ cảnh báo và ghi Audit Log (UC-43 E3).
   - Tạo `compliance_audit/templates.py` với `new_version`, `active_version(code, on)`, `install_templates`.
   - Test `test_audit_template.py` có `@bru("BRU-AUD-001")`.
3. **Audit Schedule + child khoa, scheduler** (AC-5, D6).
   - DocType `LGS-.YYYY.-.###`. Tạo `compliance_audit/schedule.py` với `period_of`, `coverage`, `run_daily`. Thêm job daily vào `hooks.py` (nối thêm) và 4 sự kiện vào `core/notification` `EVENTS`.
   - Test `test_audit_schedule.py`, `tests/test_schedule_jobs.py`.
4. **Audit Session + Audit Answer + Hand Hygiene Opportunity, chấm điểm** (AC-3, AC-4, AC-6, AC-7, Q3).
   - DocType `GS-.YYYY.-.#####`, chụp mẫu khi insert. Tạo `compliance_audit/scoring.py`: sổ phương pháp, "Điểm %", "Tất cả-hoặc-không".
   - Thêm `permission_query_conditions` và `has_permission` theo khoa.
   - Test `test_audit_session.py`, `tests/test_scoring.py` có `@bru("BRU-AUD-004")`, `@bru("BRU-AUD-005")`.
5. **Ghi sổ → phản hồi, đề nghị NC** (AC-9, AC-10, D4, D5).
   - Tạo `compliance_audit/feedback.py` (on_submit). Thêm hook `tracecore_compliance_nc` trong `hooks.py`.
   - Bên M2: thêm `on_compliance_nc` vào `reprocessing/incidents.py`; thêm option `Compliance` và loại mới vào `incident_capa.json`.
   - Tạo `compliance_audit/nc.py` (`open_nc`, `dismiss_nc`, `pending`). Test M12 và test M2 (đóng NC cần xác minh).
6. **RPC `tracecore.v1.audit.*`** (AC-8).
   - Nối vào `v1/audit.py` (file đã có `query`): `templates_for_pda`, `start_context`, `submit_session` `@idempotent` (tạo + ghi sổ trong một giao dịch), `new_version`, `open_nc`, `dismiss_nc`, `coverage`.
   - Test `v1/tests/test_audit_api.py`: idempotency, replay 20 lần, R12 khác khoa bị từ chối.
7. **Báo cáo, chỉ số, Print Format** (AC-11, AC-12, D8).
   - Script Report `compliance_by_department`; `compliance_audit/indicators.py` (`audit_pass_rate`) đăng ký hook (nối thêm); Print Format "Audit Session".
   - Test `test_compliance_by_department.py` có `@bru("BRU-RPT-001")`.
8. **SCR-50, SCR-53 trong `tc-ksnk`** (AC-13).
   - Nối 2 mục vào `ui/ksnk.py` `SCREENS`. Tạo `public/js/ksnk/scr_50_mau_phieu.js`, `scr_53_tuan_thu.js`; CSS trong `tc_ksnk.css` `.tc-ksnk`, chỉ token. Thêm badge hook `compliance_audit.nc.badges`.
   - Test `ui/tests/test_ksnk_nav.py` (nối ca) và test JS.
9. **SCR-52 trên Page `station`** (AC-14, D7).
   - Tạo fixture/patch Station Function `AUD`; `public/js/station_audit.js`; thêm vào `page_js`; thêm `submit_session` vào `TC_QUEUEABLE` của `tc_outbox.js`; snapshot mẫu cho offline.
   - Test JS hành vi (chọn mẫu, 3 nút, chặn tự đánh giá, xếp hàng offline) và test Python cho patch.
10. **Bản dịch, lint, kiểm tra cuối** (AC-15, AC-16).
    - Cập nhật `translations/vi.csv` (nối thêm) và `core/name_columns.py` (nối thêm `Audit Template: title`). Chạy `pre-commit run --all-files`.
    - Chạy toàn app `bench --site test_f043 run-tests --app tracecore --coverage` ở chế độ nền. Trước khi chạy, kiểm `ps` để chắc session FEAT-057 không đang chạy test. Đọc dòng `Ran`/`OK`/`FAILED`, không tin exit code.
    - Chạy `diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70`.
    - Push `feat/FEAT-060-audit-engine` lên GitHub. Không tạo PR, không merge.

## Ghi chú triển khai (lệch so với mặc định ở trên)

- Người dùng duyệt plan ngày 09/11/2026 theo mặc định Q1–Q3. Đã ghi amendment A-134 vào Revision History của `docs/architecture.md`.
- **D1:** `Audit Session` cho R01 ký hiệu `RWSA`, để R01 hủy được phiếu nhập sai. Báo cáo không tính phiếu Hủy.
- **D7:** Trạm `AUDIT` dùng cơ chế năng lực trạm hiện có. R11/R12/R08 cần `Station Competency` tại trạm PDA như các trạm khác, vì `core.station_auth` chưa có ngoại lệ theo chức năng. Không sửa `core` cho việc này.
- **Audit Log:** trường `action` của Audit Log chỉ nhận danh sách cố định. Vì vậy:
  - Cảnh báo "gói không có mục trọng yếu" ghi `Submit` kèm `reason` có tiền tố `[NO_CRITICAL_ITEM]`.
  - "Bỏ qua NC" ghi `Update` kèm lý do.
- **Mã lỗi mới** (`AUDIT_*`):
  - Thêm vào `core/errors.HTTP_STATUS`.
  - Thêm vào `UNMAPPED_BLOCK_CODES`, vì đây là lỗi nhập liệu/chứng từ của engine phiếu, không phải kiểm soát an toàn CSSD.
- **Mã chỉ số M9:**
  - `AUDIT_PASS_RATE` cho mọi loại phiếu.
  - Theo loại phiếu: `AUDIT_PASS_PPE`, `AUDIT_PASS_BUNDLE`, `AUDIT_PASS_ENV`, `AUDIT_PASS_VENDOR`, `AUDIT_PASS_FOOD`.
  - R01 tạo `IC Indicator` trỏ tới các khóa này.

## Ngoài phạm vi (FEAT sau)

- FEAT-061: SCR-51, `record_opportunity`, tỷ lệ VST (BRU-AUD-002), 8 mẫu khởi tạo (FR-M12-02).
- FEAT-062: `device_episode`, nhắc gói 10:00 (FR-M12-07).
- FEAT-066: hóa chất và đơn vị thuê ngoài (FR-M12-12/13).
- FEAT-065: Cổng khoa (Portal DEPT).
- E2E Playwright.
