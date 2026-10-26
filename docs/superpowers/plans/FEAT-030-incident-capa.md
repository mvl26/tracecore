# FEAT-030 — Sự cố / NC / CAPA (UC-15, SCR-15, WF-06)

**Đầu vào:** implementation-plan §3 FEAT-030; SRS FR-M2-21 (.1–.4), FR-M2-22 (.1–.2), FR-M2-04.4, FR-M2-06.2,
FR-M2-12.2 (phần NC), FR-M1-02.4; UC-15; architecture §5.3 (DT-INCIDENT, child `CAPA Action`, WF-06, tên `NC-`),
A-35 (T6: hook `tracecore_assembly_nc`). FR-M2-21/22 không gắn BRU nên không có marker `@bru` mới.

**Phạm vi:** DocType `Incident CAPA` + child `CAPA Action` (module Reprocessing, M2), dịch vụ
`tracecore.reprocessing.incidents`, RPC `tracecore.v1.incident.*`, form Desk SCR-15 có nút chuyển trạng thái, tự tạo NC
từ lô rửa Không đạt / mẻ Không đạt / T3 thiếu hoặc dụng cụ lạ, nhắc CAPA quá hạn. Ngoài phạm vi: đồng bộ
`Non Conformance`/`Quality Action` (tùy chọn theo FEAT-030, để sau), email/SMS (FEAT-010; tạm dùng Notification Log như
FEAT-032), loại Chất thải (M10).

## Quyết định thiết kế

| Mã | Quyết định | FR / UC |
| --- | --- | --- |
| D1 | `Incident CAPA` submittable, tên `NC-.YYYY.-.#####`. Nháp chứa các trạng thái mở New → Analysis → CAPA → Verification; Đóng (Closed) và Hủy (Cancelled) đều là ghi sổ do dịch vụ thực hiện. Không xóa (`block_delete`), không hủy kiểu Frappe (docstatus 2) vì "hủy" của nghiệp vụ là trạng thái Cancelled có lý do. | FR-M2-21.4, FR-M2-22 |
| D2 | Loại: Missing Instrument, Foreign Instrument, Wash Failed, Load Failed, Damaged Pack, Equipment Fault, Other. Mức: Low, Medium, High. | FR-M2-21, FR-M1-02.4 |
| D3 | Liên kết đối tượng: `set_unit`, `pack`, `wash_batch`, `sterilization_load`, `equipment`, `employee`, `assembly_record` (+ `department`, `station` phụ). Lưu khi không có liên kết nào → `INCIDENT_LINK_REQUIRED`. | FR-M2-21.2, UC-15 E1 |
| D4 | Tạo mới: thông báo chuông Desk cho mọi R02; mức High thêm R01. | FR-M2-21, .3 |
| D5 | Chuyển trạng thái chỉ qua dịch vụ (cờ `flags.tc_incident`, như FEAT-032); trường trạng thái/nguồn/người đóng bị khóa với sửa tay. R01/R02 chuyển; Analysis → CAPA cần `root_cause` và ≥ 1 hành động đủ mô tả, người phụ trách, hạn; CAPA → Verification cần mọi hành động Done; Verification → Closed cần `verification_result`, chỉ R01/R02. Hủy cần lý do, chỉ R01/R02. | FR-M2-22, .2, UC-15 E3 |
| D6 | Tự tạo NC (idempotent theo `source_doctype` + `source_name` + loại): hook `tracecore_after_wash_failed` → Wash Failed (Medium, liên kết lô + máy); `tracecore_after_load_failed` → Load Failed (High, mẻ + máy); `tracecore_assembly_nc` → Missing / Foreign Instrument (Medium, phiếu lắp ráp + bộ). | FR-M2-21.1, FR-M2-04.4, FR-M2-06.2, FR-M2-12.2, FR-M1-02.4 |
| D7 | Nhắc quá hạn: job hằng ngày, hành động chưa Done có `due_date` < hôm nay → thông báo người phụ trách + R02, mỗi hành động tối đa một lần/ngày (`last_reminded_on`). | FR-M2-22.1, UC-15 E2 |
| D8 | Quyền theo `permission_matrix.csv` dòng DT-INCIDENT (đổi tên DocType từ "Incident" thành "Incident CAPA"); sinh lại `custom_docperm.json`. | NFR-SEC |

## Task (TDD: test trước, thấy fail, rồi code)

1. DocType `CAPA Action` (istable) và `Incident CAPA` + fixture quyền + doc_events Audit/không xóa. Test: tạo thiếu liên kết bị chặn (D3); xóa bị chặn; tên `NC-`.
2. Dịch vụ `incidents.create` + thông báo (D4). Test: R02 nhận Notification Log; mức High thêm R01.
3. Chuyển trạng thái `start_analysis`, `plan_capa`, `submit_verification`, `close`, `cancel` + chặn sửa tay (D1, D5). Test từng điều kiện và vai trò.
4. Tự tạo NC từ 3 hook (D6). Test idempotent và liên kết đúng; test tích hợp lô rửa Không đạt thật tạo NC.
5. Nhắc quá hạn (D7). Test chỉ nhắc một lần/ngày.
6. RPC `v1.incident.create/advance/close/cancel` + form Desk (nút theo trạng thái/vai trò) + bản dịch vi.csv.
7. Chạy test module liên quan + `test_permissions` + pre-commit; merge `develop` local.
