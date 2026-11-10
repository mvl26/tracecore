# FEAT-069 — Điều tra ổ dịch, cảnh báo cụm ca, khai báo bệnh truyền nhiễm (kế hoạch)

> Đầu vào: implementation-plan §3 E-15 dòng FEAT-069; SRS FR-M14-09, .1, FR-M14-10, .1, FR-M13-13, .1; BRU-MDR-004,
> BRU-MDR-005, BRU-HAI-005; UC-53, UC-50 (bước 1–4, A1, A3, E1); SCR-61 (WEB) + `docs/design-refs/v1.12/SCR-61_ODich.png`,
> SCR-58 (banner cụm ca) + `SCR-58_BaoCaoNKBV.png`; architecture §5.3 Outbreak Investigation / Notifiable Disease Report,
> §5.3.3 (`OD-.YYYY.-.###`, `KB-.YYYY.-.#####`), ADR-010 mở rộng, ADR-014. OQ-V12-03 (thời hạn khai báo) còn mở → cấu hình.
> Nhánh `feat/FEAT-069-outbreak` từ origin/develop 3cc2247, bench `~/tracecore-f043`, site test `test_f043`. Amendment **A-150**.

## Quyết định A-150 (người dùng chọn phương án đề xuất trong chat ngày 10/11/2026)

| # | Lệch / thiếu trong tài liệu | Quyết định |
| --- | --- | --- |
| Q1 | `disease` là "Link danh mục bệnh, nhóm A/B/C" nhưng §5.3 không có DocType danh mục; thời hạn chưa chốt (OQ-V12-03) | DocType mới **`Communicable Disease`** (tên = `disease_code`; `disease_name`, `disease_group` A/B/C, `legal_ref`, `disabled`), R01/R10 nhập, không seed. Hạn khai báo (giờ) theo nhóm là 3 trường `notifiable_hours_a/b/c` trong `IC Program Settings`, mặc định trống → không tính `due_by`, báo R01/R10 cấu hình (UC-53 E2) |
| Q2 | FR-M13-13 cần nhiều ngưỡng (loại NK/tác nhân, khoa hoặc toàn viện, N ngày, số ca) và trạng thái cảnh báo (mở / ghi lý do không mở / không lặp) | 2 DocType mới ở M14: **`Cluster Alert Rule`** (nguồn: ca NKBV Xác định theo `infection_site` hoặc chủng theo `organism` / chỉ đa kháng; khoa trống = đếm từng khoa; `window_days`, `min_cases`; mặc định không có dòng → không cảnh báo, FR-M13-13.1) và **`Cluster Alert`** (khoa, khóa, danh sách ca, trạng thái New / Investigation Opened / Dismissed + lý do). Job hằng ngày ở M14 đọc `HAI Case` qua `frappe.db` (không import M13) |
| Q3 | `actions` (Link Incident CAPA) — một hay nhiều NC; ảnh có bảng Hành động / Người thực hiện / Hạn / Trạng thái | Hook mới `tracecore_outbreak_nc`: M2 tạo `Incident CAPA` loại mới **Outbreak Control** (`incident_category` **Outbreak**, nguồn = ổ dịch, khoa chính) và thêm `CAPA Action` (mô tả, người, hạn). Child **`Outbreak CAPA`** (`incident_capa`, `open_reason`) gắn NC đó và NC khác có sẵn (vd NC môi trường, UC-53 A2). Kết thúc khi mọi NC gắn Closed/Cancelled hoặc có `open_reason` (BRU-MDR-004) |
| Q4 | UC-53 bước 5: R08/R12 ghi khai báo nhưng SCR-61 chỉ có WEB | Thêm surface DEPT cho SCR-61: Cổng khoa `/ksnk-khoa/khai-bao` (form + danh sách khoa mình); R01/R11 mở link này được chuyển sang `/app/tc-ksnk/o-dich` |
| Q5 | Vòng đời, quyền | Cả hai submittable, tạo = ghi sổ ngay (như Isolation Order). Ổ dịch: chỉ R01 mở / Đã kiểm soát / Kết thúc / Hủy; R11 gắn ca, thêm hành động, sửa định nghĩa ca; R13 không đọc DocType (chỉ số liệu tổng hợp trên SCR-61). Khai báo: R01/R11 mọi khoa, R08/R12 khoa mình; ghi `reported_on` + `report_ref` qua RPC (allow_on_submit); Hủy R01/R11. Ma trận 95 → **100**: DT-OUTBREAK, DT-NOTIFY, DT-CDISEASE, DT-CLRULE, DT-CLALERT |
| Q6 | "Nhắc trước và sau hạn"; mẫu TT 15/2026 chưa có | Job 15 phút: nhắc R11 + R08 của khoa một lần khi qua nửa thời hạn, một lần khi quá hạn, sau đó mỗi ngày một lần đến khi đủ `reported_on` + `report_ref`. Print Format "TC Outbreak Investigation" (Báo cáo ổ dịch), "TC Notifiable Disease Report" (Khai báo bệnh truyền nhiễm): trường hiện có, mã BN che, ghi chú mẫu tạm chờ OQ-V12-03 |

Ngoài phạm vi: phiếu điều tra cắt ngang (FEAT-072 đã làm), `Foodborne Event` → ổ dịch (FEAT-073 Link tới `Outbreak
Investigation`), API `tracecore.v1.ic.*` (D3), gửi khai báo trực tuyến (BRU-MDR-005), chỉ số ổ dịch sang M9.

## AC (EARS, suy từ FR)

- AC-1 (FR-M13-13, UC-50 b2–3): Khi số ca NKBV Xác định cùng `infection_site` (hoặc chủng cùng loài, cùng người bệnh tính
  một) tại một khoa trong `window_days` ngày ≥ `min_cases` của một ngưỡng đang bật, job hằng ngày phải tạo `Cluster Alert`
  và gửi `CLUSTER_ALERT` (Urgent) cho R01, R11 kèm link mở ổ dịch điền sẵn.
- AC-2 (FR-M13-13.1, UC-50 E1): Khi chưa có ngưỡng nào, hệ thống không cảnh báo và SCR-58 hiện nhắc "chưa cấu hình ngưỡng".
- AC-3 (UC-50 b4, A3): R01/R11 ghi lý do "đã xem xét" → cảnh báo Dismissed; cảnh báo không lặp cho cùng cụm đến khi có ca mới.
- AC-4 (FR-M14-09, UC-53 b1): Chỉ R01 mở ổ dịch (tiêu đề, tác nhân/bệnh, khoa, ngày bắt đầu bắt buộc); mở từ cảnh báo điền
  sẵn khoa, tác nhân, ca, và cảnh báo chuyển Investigation Opened.
- AC-5 (FR-M14-09, .1, UC-53 b2, E4): R01/R11 gắn ca từ `HAI Case`, `Microbiology Isolate` hoặc mã BN + ngày khởi phát;
  đường cong dịch đếm theo `onset_date` (Xác định / Nghi ngờ / Loại trừ tách riêng); ca M13 bị Loại trừ hiện nhãn.
- AC-6 (FR-M14-09, UC-53 b3): Thêm hành động tạo (lần đầu) NC Outbreak Control qua hook và một CAPA Action; bảng hành động
  đọc trạng thái từ NC.
- AC-7 (BRU-MDR-004, UC-53 E1): Kết thúc bị chặn khi thiếu tóm tắt hoặc còn NC gắn chưa đóng không có lý do.
- AC-8 (FR-M14-10, .1, UC-53 b5, E2): Ghi khai báo tính `due_by` = `diagnosed_on` + giờ của nhóm bệnh; nhóm chưa cấu hình
  → `due_by` trống, cảnh báo, báo `NOTIFIABLE_CONFIG_MISSING` R01/R10.
- AC-9 (UC-53 b6, E3, BRU-MDR-005): Job nhắc R11 + R08 khoa (nửa hạn, quá hạn, mỗi ngày sau đó) đến khi có cả
  `reported_on` và `report_ref`; chỉ có `reported_on` → "Thiếu số khai báo", vẫn nhắc.
- AC-10 (NFR-SEC-09, Q4, Q5): R08/R12 chỉ ghi/đọc khai báo khoa mình (Cổng khoa); R13 không đọc DocType có người bệnh.
- AC-11 (BRU-HAI-005, NFR-PRIV-01): không trường họ tên; `patient_code` Password; RPC/print chỉ mã che.

## Tasks (TDD — test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Docs A-150** — Revision History architecture/srs; §5.3 (Outbreak Investigation + child Outbreak Case/Department/CAPA,
   Notifiable Disease Report, Communicable Disease, Cluster Alert Rule, Cluster Alert, IC Program Settings, Incident CAPA),
   §5.3.3 naming; ux SCR-61 (+DEPT), SCR-58; rtm FR-M13-13, FR-M14-09/10; implementation-plan dòng FEAT-069. (Q1–Q6)
2. **Communicable Disease + giờ theo nhóm** (`microbiology/notifiable.py` `deadline_hours`). Test: nhóm cấu hình → giờ;
   trống → None. (FR-M14-10.1)
3. **Notifiable Disease Report** (`KB-.YYYY.-.#####`) + `notifiable.create_report / record_reported / cancel_report /
   remind`. Test `@bru("BRU-MDR-005")`: chỉ theo dõi `reported_on`/`report_ref`; `due_by`; E2; E3; nhắc nửa hạn/quá
   hạn/không lặp trong ngày; khoa ngoài phạm vi bị chặn. (AC-8, 9, 10, 11)
4. **Cluster Alert Rule / Cluster Alert** + `microbiology/clusters.py` `run_daily`, `dismiss`. Test: ngưỡng HAI theo
   `infection_site`, chủng theo loài/đa kháng (dedupe hash), khoa trống = từng khoa, không ngưỡng → không cảnh báo, không
   lặp, có ca mới → cảnh báo mới. (AC-1..3)
5. **Outbreak Investigation** (`OD-.YYYY.-.###`) + `microbiology/outbreaks.py` `open / add_case / remove_case / add_action
   / link_nc / set_controlled / end / cancel / epi_curve / detail`. Test `@bru("BRU-MDR-004")`; chỉ R01 mở/kết thúc; ca từ
   M13/M14/thủ công; ca Loại trừ; đường cong. (AC-4..7)
6. **M2 hook** `tracecore_outbreak_nc` → `reprocessing.incidents.on_outbreak_nc` (loại Outbreak Control, nhóm Outbreak,
   thêm CAPA Action). Test ở reprocessing. (AC-6)
7. **Quyền** — `microbiology/permissions.py` thêm query/has_permission cho Notifiable Disease Report; ma trận 95 → 100;
   test_permissions, test_permissions_v112; migrate → write_fixture → migrate. (AC-10)
8. **Thông báo** — EVENTS `CLUSTER_ALERT` (Urgent; R01, R11), `NOTIFIABLE_DUE` (Normal; R11), `NOTIFIABLE_CONFIG_MISSING`
   (R01, R10). Scheduler: daily `clusters.run_daily`, */15 `notifiable.remind`.
9. **RPC `tracecore.v1.outbreak.*`** — `overview`, `candidates`, `cluster_alerts` (GET); `open_outbreak`, `add_case`,
   `remove_case`, `add_action`, `link_nc`, `set_controlled`, `end_outbreak`, `cancel_outbreak`, `dismiss_alert`,
   `create_report`, `record_reported`, `cancel_report` (POST `@idempotent`); `portal_context` (GET). Mã lỗi
   `OUTBREAK_*`, `NOTIFIABLE_*`, `CLUSTER_*` vào `UNMAPPED_BLOCK_CODES`.
10. **SCR-61 WEB** — `ui/ksnk.py` slug `o-dich` (group micro; R01, R11, R13, SM), `public/js/ksnk/scr_61_o_dich.js`:
    danh sách ổ dịch, chi tiết (thông tin, đường cong dịch cột theo ngày có ký hiệu ✓/?/×, ca, hành động), khai báo, nút
    chân trang; R13 chỉ tổng hợp. Badge `o-dich`. **SCR-58**: banner cảnh báo cụm ca + nút "Mở điều tra ổ dịch",
    "Đánh dấu đã xem xét" (khối mới cuối `scr_58_bao_cao_nkbv.js`).
11. **SCR-61 DEPT** — `www/ksnk_khoa/khai_bao.{py,html,js,css}`, route `/ksnk-khoa/khai-bao`, menu `ksnk_khoa_nav.html`.
12. **Print Format** TC Outbreak Investigation, TC Notifiable Disease Report.
13. **vi.csv**, lint, test module lần lượt, diff-cover ≥ 70 %, pre-commit, push.

## File dùng chung (chỉ thêm khối `# FEAT-069`)

hooks.py (route, permission_query_conditions, has_permission, doc_events, scheduler, ksnk_badges, ksnk_todos, hook mới
`tracecore_outbreak_nc`), core/notification EVENTS, core/error_codes UNMAPPED, permission_matrix.csv, custom_docperm.json,
tests/test_permissions.py (100), test_permissions_v112.py, ui/ksnk.py, ksnk_khoa_nav.html, translations/vi.csv,
IC Program Settings JSON (section cuối), Incident CAPA JSON (thêm option), reprocessing/incidents.py, scr_58_bao_cao_nkbv.js,
core/name_columns.py nếu test_name_columns đòi.

## Test module chạy lần lượt (`--app tracecore --module …`)

microbiology: test_notifiable, test_clusters, test_outbreaks; reprocessing test_incidents_outbreak; v1 test_outbreak_api;
tests test_ksnk_scr61, test_ksnk_scr58 (nếu có), test_ksnk_page, test_permissions, test_permissions_v112, test_name_columns,
test_no_internal_codes; ui.tests.test_ksnk_nav; occupational_safety.tests.test_ui; core test_notification, test_error_codes,
test_errors; ic_program_settings; microbiology test_isolation (đụng permissions.py).
