# FEAT-072 — Cải tiến chất lượng KSNK, tự đánh giá năm, điều tra cắt ngang (kế hoạch)

> Đầu vào: implementation-plan §3 E-12 dòng FEAT-072; SRS FR-M11-12, FR-M11-12.1, FR-M11-13, FR-M11-13.1, FR-M13-14,
> FR-M13-14.1 (liên kết FR-M11-06, FR-M9-29); BRU-AUD-001, BRU-HAI-005, BRU-RPT-001; UC-42 (bước 5, 6), UC-50 (bước 5, 6,
> E2, E3); SCR-49, SCR-58 (WEB) + `docs/design-refs/v1.12/SCR-49_DaoTao.png`, `SCR-58_BaoCaoNKBV.png`; architecture
> §5.3 `IC Improvement Project`, §5.3.3 naming `CI-.YYYY.-.###`, ADR-010 mở rộng, ADR-015. Nhánh
> `feat/FEAT-072-ic-improvement` từ develop 2436b7e, bench `~/tracecore-f026`, site test `test_f026`. Amendment **A-149**.

## Quyết định A-149 (người dùng chọn phương án đề xuất trong chat ngày 10/11/2026)

| # | Lệch / thiếu trong tài liệu | Quyết định |
| --- | --- | --- |
| Q1 | FR-M13-14.1: cắt ngang bằng phiếu M12 loại "Khác" + Device Episode, không DocType mới; nhưng `Audit Session` không có trường mã BN, UC-50 bước 5 cho thêm người bệnh không có Device Episode | Thêm bộ ba `patient_code` (Password) / `patient_code_masked` / `patient_code_hash` vào `Audit Session` (ADR-010 mở rộng, qua `core.patient_code`). Mỗi người bệnh khảo sát = 1 phiếu đã ghi sổ; `device_episode` tùy chọn (có thì chép mã BN đã mã hóa từ đợt). Mẫu cắt ngang nhận diện bằng mục mã `PREV-HAI` (Có/Không NKBV), kèm `PREV-ABX` (Có/Không dùng kháng sinh), kiểu Lựa chọn. Tỷ lệ hiện mắc theo khoa = phiếu `PREV-HAI` = Có / phiếu đã ghi sổ của ngày điều tra; số khảo sát 0 → "Không tính" |
| Q2 | `IC Improvement Project.status` chưa có giá trị, vòng đời | PDCA: Kế hoạch (P) / Thực hiện (D) / Kiểm tra (C) / Hành động (A) / Hoàn thành / Hủy. Không submittable, không ai xóa (dùng Hủy). Hoàn thành bắt buộc `end_date` (không ở tương lai) và `result_summary`; `end_date` ≥ `start_date`. Đếm "số cải tiến/năm" theo năm của `end_date`. Ma trận DT-ICIMP: R01 RW; R10, R11, R13 R |
| Q3 | Mẫu "Tự đánh giá chất lượng" và "Điều tra cắt ngang" chưa có | Seed 2 mẫu Nháp như A-140: `TDG-KSNK` (Quality Self-Assessment, Weighted Score, căn cứ TT 35/2024/TT-BYT) và `CAT-NGANG` (Other, mục `PREV-HAI`, `PREV-ABX`). Nội dung khởi đầu do dev soạn, R01 sửa và duyệt; chỉ chèn mã còn thiếu (NFR-MAINT-04); patch `a149_ic_improvement_seed` cho site đang chạy |
| Q4 | Chỉ tiêu QĐ 38 `QD38-QI` (FEAT-065) chấm tay | Đăng ký check `ic_improvement_completed` vào `tracecore_ic_self_checks`: Đạt khi năm có ≥ 1 dự án Hoàn thành, tham chiếu mã dự án. Seed `QD38-QI` có `check_method`; patch chỉ điền khi bệnh viện chưa đặt |

Ngoài phạm vi: nhập cắt ngang trên PDA (SCR-52; FEAT-072 chỉ WEB theo implementation-plan — mẫu cắt ngang bị loại khỏi
danh sách mẫu PDA để không ghi phiếu thiếu mã BN), R12 ghi cắt ngang khoa mình (UC-50 A2, R12 không mở SCR-58), xóa định
danh mã BN của phiếu cắt ngang theo NFR-PRIV-02 (follow-up cho `hai_surveillance.retention`), nối dự án cải tiến với NC
hay biên bản họp (FR không yêu cầu).

## AC (EARS, suy từ FR)

- AC-1 (FR-M11-12): Khi R01 ghi `IC Improvement Project`, hệ thống phải lưu loại (Cải tiến chất lượng / Đề tài nghiên cứu), tiêu đề, nhóm biện pháp, chủ trì, thời gian, trạng thái PDCA, tóm tắt kết quả, tệp đính kèm, mã `CI-YYYY-###`.
- AC-2 (FR-M11-12, Q2): Nếu chuyển Hoàn thành mà thiếu ngày kết thúc hoặc tóm tắt kết quả, hoặc ngày kết thúc trước ngày bắt đầu / ở tương lai, thì hệ thống phải chặn lưu với lý do và hành động.
- AC-3 (FR-M11-12.1): Hệ thống phải tính chỉ số `ic_improvement_completed` (Count) = số dự án Hoàn thành có `end_date` từ đầu năm đến hết kỳ, đăng ký qua `tracecore_ic_indicators`; theo khoa trả (0, 0, 0).
- AC-4 (Q4, FR-M9-29): Tự đánh giá QĐ 38 chỉ tiêu `QD38-QI` tự điền Đạt khi năm có ≥ 1 dự án Hoàn thành (tham chiếu mã), Không đạt khi không có.
- AC-5 (FR-M11-13, BRU-AUD-001): Phiếu tự đánh giá dùng phiên bản mẫu loại "Quality Self-Assessment" đã duyệt (engine M12); hệ thống lưu kết quả theo năm (`audit_date`), lấy phiếu ghi sổ mới nhất của mỗi năm.
- AC-6 (FR-M11-13.1): Khi có phiếu tự đánh giá của hai năm liền, SCR-49 phải hiện hai năm cạnh nhau theo từng mục (ghép `item_code`) và điểm % mỗi năm; thiếu năm trước → chỉ hiện năm nay và ghi chú.
- AC-7 (FR-M11-06 liên kết): Tổng kết năm (`annual_plan.year_summary`, bản in) có số dự án cải tiến hoàn thành trong năm và điểm tự đánh giá của năm.
- AC-8 (FR-M13-14, UC-50 bước 5): Khi R11 chọn ngày điều tra và khoa, hệ thống phải liệt kê người bệnh có `Device Episode` mở vào ngày đó (mã che) chưa khảo sát, và cho thêm người bệnh khác bằng mã BN (mã hóa, không họ tên).
- AC-9 (FR-M13-14, UC-50 bước 6): Khi R11 ghi một người bệnh có/không NKBV (và có/không dùng kháng sinh), hệ thống phải tạo và ghi sổ một `Audit Session` từ mẫu cắt ngang đang hiệu lực; cùng người bệnh (hash) đã khảo sát cùng ngày → chặn trùng; không có mẫu đã duyệt → chặn với hành động "duyệt mẫu ở SCR-50".
- AC-10 (FR-M13-14, E2, BRU-RPT-001): Hệ thống phải tính tỷ lệ hiện mắc theo khoa và toàn viện cho ngày điều tra (số có NKBV / số khảo sát, % dùng kháng sinh); số khảo sát 0 → "Không tính"; chỉ số `hai_prevalence` theo tháng qua `tracecore_ic_indicators`.
- AC-11 (BRU-HAI-005, NFR-PRIV-01): Phiếu cắt ngang không có trường họ tên; `patient_code` là Password; RPC/màn chỉ trả `patient_code_masked`; phiếu không phải cắt ngang không được có mã BN.
- AC-12 (SCR-49, SCR-58): SCR-49 có khối "Cải tiến chất lượng & đề tài" (bảng mã, tên, giai đoạn PDCA có chữ, kết quả) + thẻ KPI + khối tự đánh giá; SCR-58 có khối "Điều tra cắt ngang" (bảng theo khoa, form ghi cho R01/R11); lỗi chặn hiện `alert-error` inline (kết quả → lý do → hành động); đủ trạng thái loading/empty/error.

## Tasks (TDD — test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Docs A-149** — Revision History architecture/srs/ux-foundations/implementation-plan; architecture §5.3 `IC Improvement Project` (trường, trạng thái), `Audit Session` thêm bộ ba mã BN, hook mới không có; ux SCR-49/58 ghi chú; rtm FR-M11-12/13, FR-M13-14. (Q1–Q4)
2. **DocType `IC Improvement Project`** (module Infection Program, `CI-.YYYY.-.###`, title `title`, không submittable) + `infection_program/improvement.py` (`validate`, `rows`, `completed`, indicator, self check). Test: AC-1, AC-2, AC-3, AC-4. (FR-M11-12, 12.1)
3. **Ma trận quyền** DT-ICIMP (86 → 87), test_permissions, test_permissions_v112, migrate → write_fixture → migrate.
4. **Audit Session mã BN + cắt ngang** — 3 trường mới; `compliance_audit/prevalence.py` (`is_prevalence`, `validate`, `before_submit`) gọi từ `sessions.validate/before_submit/on_submit` (bỏ phản hồi khoa cho phiếu cắt ngang); `pda.active_templates` bỏ mẫu cắt ngang. Test `@bru("BRU-HAI-005")`: không trường họ tên, mã BN Password, phiếu thường có mã BN → chặn; device episode khác khoa/không mở → chặn; trùng người bệnh cùng ngày → chặn; chưa trả lời `PREV-HAI` → chặn. (AC-9, AC-11)
5. **Seed 2 mẫu Nháp + QD38-QI** — `compliance_audit/seed.py` khối FEAT-072, `admin_reports/self_assessment_seed.py` check_method, patch `a149_ic_improvement_seed`. Test: seed chèn mã thiếu, không ghi đè; patch không đè check_method bệnh viện đặt. (Q3, Q4)
6. **Tổng hợp cắt ngang M13** — `hai_surveillance/prevalence.py` (`survey_dates`, `by_department`, `candidates`, indicator `hai_prevalence`). Test `@bru("BRU-RPT-001")`. (AC-8, AC-10)
7. **Tự đánh giá năm M11** — `infection_program/quality_review.py` (`compare(year)`), `annual_plan.year_summary` thêm `improvement` và `self_assessment`; print format tổng kết thêm 2 dòng. Test AC-5..7 với `@bru("BRU-AUD-001")`.
8. **RPC** — `tracecore.v1.ksnk_improvement.status` (GET; SCR-49), `tracecore.v1.hai_prevalence.overview` (GET; SCR-58, số liệu tổng hợp), `.candidates` (GET; R01/R11), `.record` (POST; R01/R11; từ chối trả `{ok:false,error}`). Mã lỗi mới `PREVALENCE_*` vào `core/error_codes` UNMAPPED.
9. **UI** — `scr_49_dao_tao.js` thêm thẻ KPI + khối cải tiến + khối tự đánh giá (gọi thêm RPC); `scr_58_bao_cao_nkbv.js` thêm khối cắt ngang. Test JS-free: test RPC + `tests/test_ksnk_scr49_improvement.py`, `tests/test_ksnk_scr58_prevalence.py` kiểm SCREENS/asset.
10. **vi.csv**, lint, test module lần lượt, diff-cover ≥ 70 %, pre-commit, push `github`.

## File dùng chung (chỉ thêm khối `# FEAT-072`)

hooks.py (doc_events `IC Improvement Project`, `tracecore_ic_indicators`, `tracecore_ic_self_checks`), patches.txt,
permission_matrix.csv, custom_docperm.json, tests/test_permissions.py (87), tests/test_permissions_v112.py,
core/error_codes.py, compliance_audit/sessions.py, compliance_audit/pda.py, compliance_audit/seed.py,
admin_reports/self_assessment_seed.py, infection_program/annual_plan.py, print format tổng kết, translations/vi.csv,
tc_ksnk.css (nếu cần), scr_49_dao_tao.js, scr_58_bao_cao_nkbv.js.

## Test module chạy lần lượt (`--app tracecore --module …`)

infection_program: test_ic_improvement_project, test_quality_review, test_ic_annual_plan; compliance_audit:
test_prevalence, test_audit_session, test_seed, test_pda (nếu có); hai_surveillance: test_prevalence; admin_reports:
test_self_assessment; v1: test_ksnk_improvement_api, test_hai_prevalence_api; tests: test_permissions,
test_permissions_v112, test_name_columns, test_no_internal_codes, test_ksnk_page; ui: test_ksnk_nav; core:
test_error_codes, test_errors.
