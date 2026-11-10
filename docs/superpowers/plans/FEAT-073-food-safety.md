# FEAT-073 — An toàn thực phẩm và truyền thông người bệnh (M17) — kế hoạch

> Nhánh `feat/FEAT-073-food-safety` (bench `~/tracecore-f032`, site test `test_f032`), cắt từ develop 3cc2247.
> Amendment **A-151**. Đầu vào: implementation-plan §3 E-18 dòng FEAT-073; srs §3.1.17 FR-M17-01..06, BRU-FS-001..002;
> use-cases UC-56; ux-foundations SCR-65 (WEB), SCR-52 (PDA + DEPT); architecture §5.3.1 M17, §5.3.3; ảnh `SCR-65_ATTP.png`.

## Quyết định của người dùng (10/11/2026, chọn cả 4 phương án đề xuất)

| # | Câu hỏi | Chọn |
| --- | --- | --- |
| Q1 | Liên kết ổ dịch khi `Outbreak Investigation` (FEAT-069) chưa có trên develop | `Foodborne Event.outbreak_status` (Đề nghị / Đã mở / Không mở có lý do) + `outbreak_investigation` kiểu Data chỉ đọc. Nút "Mở điều tra ổ dịch" chỉ hiện khi DocType đã có, mở form mới điền sẵn `source_doctype`/`source_name`; M17 bắt `doc_events["Outbreak Investigation"]` để ghi ngược tên. Sau khi merge FEAT-069, session cha đổi Data → Link |
| Q2 | Ngưỡng số người bị ảnh hưởng (FR-M17-04.1) | `IC Program Settings.foodborne_outbreak_threshold` (Int); trống = chưa đặt → chỉ đề nghị NC và nhắc R01 (UC-56 E2) |
| Q3 | Tài liệu truyền thông Nháp / thu hồi, QR cho người không đăng nhập | `IC Procedure Document.status` thêm Draft, Withdrawn (+ `withdrawn_reason`); QR = URL cố định `/tai-lieu/<doc_code>`; trang www cho Guest trả file của bản hiện hành, chỉ với loại Tài liệu truyền thông; Nháp chưa ban hành / đã thu hồi → thông báo. File vẫn private |
| Q4 | Vòng đời | `Food Handler Health Check` mỗi lần khám 1 phiếu submittable, trạng thái người chế biến = phiếu ghi sổ mới nhất theo `employee` hoặc (`supplier` + họ tên); `Foodborne Event` submittable, ghi sổ → báo ngay R01/R11 + đề nghị NC như mẫu môi trường M15; `IC Education Session` bản ghi thường, không xóa |

## Thiết kế (A-151)

DocType mới, module `Food Safety` (`tracecore/food_safety/`):

| DocType | Tên | Trường |
| --- | --- | --- |
| Food Handler Health Check | `SKTP-.YYYY.-.#####`, submittable | `employee` hoặc `supplier` (đúng một), `full_name`*, `department` (khoa của nhân viên nội bộ), `checked_on`*, `next_due`*, `fit_for_work`* (Fit / Unfit), `evidence`, `handler_key` (ẩn). **Không có trường chẩn đoán/kết quả** (BRU-FS-001) |
| Foodborne Event | `NDTP-.YYYY.-.###`, submittable | `event_date`*, `location`*, `department`* (khoa/đơn vị phụ trách, NC gắn khoa), `affected_count`*, `suspected_food`, `supplier`, `description`, `reported_ref`; NC: `nc_status`, `incident_capa`, `nc_reason`; ổ dịch: `threshold_applied`, `outbreak_status`, `outbreak_investigation` (Data), `outbreak_reason` |
| IC Education Session | `GDS-.YYYY.-.#####` | `session_date`*, `department`*, `audience`* (Patients / Patient Families / Staff / Food Handlers / Students), `topic`* (nhóm biện pháp, cùng danh sách `measure_group`), `title`*, `attendee_count`*, `materials` (IC Procedure Document loại Tài liệu truyền thông), `facilitator`, `notes` |

Chạm module khác (khối `# FEAT-073`, không import chéo):
- M11 `IC Procedure Document`: status + Draft, Withdrawn, `withdrawn_reason`; `procedure_documents.py` giữ Nháp, chỉ thay
  bản cũ khi ban hành, `publish`/`withdraw`, `current_material(doc_code)`; chỉ số văn bản bỏ Nháp/thu hồi.
- M11 `IC Program Settings`: `foodborne_outbreak_threshold`.
- M2 `Incident CAPA`: `incident_type` + "Food Safety Nonconformity", `incident_category` + "Food Safety"; hook mới
  `tracecore_food_safety_nc` → `reprocessing.incidents.on_food_safety_nc`.
- M12 PDA: `pda.context` thêm `caterers` (Supplier `tc_ic_service_type` = Catering); `station_audit.js` chọn đơn vị suất
  ăn hoặc "Bếp ăn bệnh viện" khi mẫu loại An toàn thực phẩm, gửi `supplier`.
- M15: không đổi code; mẫu thực phẩm = `Environmental Sample` `sample_type` Food (test chứng minh FR-M17-03).
- Seed: dùng lại mẫu Nháp `ATTP` của FEAT-070, không seed trùng; không có seed mới nên không cần patch.

## Task (TDD: test `FrappeTestCase` trước, thấy đỏ, rồi code)

1. **Docs A-151** — Revision History architecture + srs; §5.3.1 M17, IC Procedure Document, IC Program Settings,
   Incident CAPA; ux SCR-65; rtm FR-M17-01..06; dòng FEAT-073.
2. **Food Handler Health Check** (FR-M17-02, .1; BRU-FS-001; UC-56 bước 2, E1, E3, A3) — test: không có trường chẩn
   đoán (`@bru("BRU-FS-001")`); đúng một trong employee/supplier; `next_due` ≥ `checked_on`; trạng thái mới nhất theo
   người; Không đủ hiện nhãn, không chặn; scheduler nhắc R11 còn 30 ngày và quá hạn, mỗi mốc một lần; danh sách quá hạn
   theo đơn vị.
3. **Foodborne Event** (FR-M17-04, .1; BRU-FS-002; UC-56 bước 4, E2, A2) — test: ghi sổ → thông báo R01/R11,
   `nc_status` Suggested; `affected_count` ≥ ngưỡng → `outbreak_status` Suggested (`@bru("BRU-FS-002")`); ngưỡng trống
   → không đề nghị ổ dịch, nhắc R01; `open_nc` tạo Incident Food Safety (idempotent), `dismiss_nc`/`dismiss_outbreak`
   cần lý do; Outbreak Investigation có nguồn là sự cố → ghi ngược tên, Đã mở.
4. **Phiếu ATTP M12** (FR-M17-01, .1) — test: mẫu ATTP Nháp có sẵn từ seed M15, không seed trùng; PDA context có
   `caterers`; phiếu ATTP gắn supplier; tổng hợp kết quả theo đơn vị.
5. **Mẫu thực phẩm** (FR-M17-03) — test: mẫu `sample_type` Food ở vùng bếp so ngưỡng Food, Không đạt → cờ, NC Suggested.
6. **IC Education Session + báo cáo quý** (FR-M17-05, .1) — test: R12 chỉ ghi/thấy khoa mình; tổng hợp quý theo đối
   tượng–chủ đề; Script Report "Food Safety and Communication by Quarter".
7. **Tài liệu truyền thông QR** (FR-M17-06, .1; UC-56 bước 6, E4) — test: Nháp không thay bản cũ, ban hành mới thay;
   `current_material` trả bản mới nhất; QR cố định theo `doc_code`; trang `/tai-lieu/<code>` cho Guest: bản hiện hành
   → file, Nháp/thu hồi → thông báo, loại khác → không phục vụ.
8. **SCR-65** — Page `tc-ksnk` slug `attp` (nhóm environment; R01, R11, R13 tổng hợp, System Manager); RPC
   `tracecore.v1.food_safety.*`; badge người quá hạn + sự cố chờ quyết định.
9. **Chỉ số, quyền, thông báo** — `tracecore_ic_indicators` (`food_handler_health_valid`); 3 dòng ma trận (95 → 98),
   `custom_docperm` sinh lại; EVENTS FOODBORNE_EVENT_REPORTED, FOODBORNE_THRESHOLD_MISSING, FOOD_HANDLER_CHECK_DUE,
   FOOD_HANDLER_CHECK_OVERDUE; name_columns; vi.csv.
10. **Kiểm** — test module (`--module`, khóa `/tmp/tc-moduletest.lock`), test_permissions, test_permissions_v112,
    test_name_columns, test gọi `ksnk.nav`; diff-cover ≥ 70 %; pre-commit.

## Ngoài phạm vi / follow-up

- Đổi `Foodborne Event.outbreak_investigation` Data → Link và nối `source_doctype`/`source_name` khi merge FEAT-069.
- Chọn đơn vị thuê ngoài cho phiếu "Đơn vị thuê ngoài" trên PDA (FEAT-066 chưa có) — chỉ làm cho ATTP.
- Danh mục `IC Indicator` cho chỉ số M17 do R01/R10 tạo (như các FEAT trước).
