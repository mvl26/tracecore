# FEAT-004 — Audit Trail, xóa danh mục, chuyển trạng thái thủ công, Thanh lý bộ

**Đầu vào:** implementation-plan §3 FEAT-004 (FR-M9-16, FR-M2-00.3, NFR-SEC-03; UC-33; SCR-33), Amendment **A-37**
(architecture Revision History, 2026-10-26) — quyết định chủ đầu tư về Thanh lý (FR-M1-05.2, FR-M1-06).

**Nhánh:** `feat/FEAT-004-audit-disposal` (từ develop local). Không PR; merge vào develop local, không push.

## Task 1 — Thanh lý bộ (A-37 a; FR-M1-05.2, FR-M1-06; BRU-ID-001)

- `core.step_gate.dispose(set_unit, reason)`: Hết vòng đời / Xử lý lại → Đã thanh lý, bỏ Cycle ID; không quay lại.
- `instrument.disposal.request / approve / reject`:
  - R02 đề nghị kèm lý do; bộ phải Hết vòng đời, hoặc Xử lý lại do Assembly Record chu trình hiện hành `branch=Disposal`.
  - R01 duyệt/từ chối bằng PIN Employee (Desk), kèm ghi chú.
  - Duyệt → `step_gate.dispose` + `code_registry.disable` (Set ID vô hiệu, không cấp lại).
  - Thông báo Notification Log: R01 khi có đề nghị, người đề nghị khi có quyết định.
  - Mã lỗi: `DISPOSAL_NOT_ALLOWED`, `REASON_REQUIRED`, `DISPOSAL_NOT_ELIGIBLE`, `DISPOSAL_PENDING`,
    `DISPOSAL_NOT_PENDING`, `PIN_INVALID`.
- Set Unit: trường `disposal_*` chỉ đọc, chỉ ghi qua dịch vụ (cờ `flags.tc_disposal`) → Audit Log Update.
- RPC `tracecore.v1.set_unit.disposal_request / disposal_approve / disposal_reject`; nút Desk trên form Set Unit.
- Test: `instrument/tests/test_disposal.py`, `v1/tests/test_disposal_admin_api.py`.

## Task 2 — Chuyển trạng thái thủ công (A-37 b; FR-M2-00.3; BRU-FLOW-002 ngoại lệ)

- `core.step_gate.force_status`: đích Processing / Reprocess / Sterile / At Department / Awaiting Receipt / End of Life,
  khác hiện tại, không từ Đã thanh lý.
- `reprocessing.storage.force_status`: gói Released / In Sterile Stock / Issued / Used → In Sterile Stock / Issued /
  Used / Void; Void đi đường hết hiệu lực (vô hiệu Cycle ID, bộ Vô khuẩn về Chờ tiếp nhận).
- `reprocessing.manual_transition.force_set_status / force_pack_status`: chỉ R02, bắt buộc lý do + ticket
  (Void cần `void_reason`); Audit Log `Override`; tự tạo Incident CAPA loại Other.
- RPC `tracecore.v1.admin.force_transition`; nút Desk trên form Set Unit và Pack (`pack.js`).
- Test: `reprocessing/tests/test_manual_transition.py`.

## Task 3 — Audit Trail (A-37 c; NFR-SEC-03)

- Script Report `Audit Trail` (module TraceCore, R01/R02/R10/System Manager), lọc theo đối tượng, người, trạm, thao tác,
  khoảng ngày; đọc qua `frappe.get_list` (theo quyền Audit Log).
- Test: `tests/test_master_delete_and_audit_trail.py::TestAuditTrail`.

## Task 4 — Xóa danh mục (A-37 d; FR-M9-16)

- `core.audit.block_delete`: danh mục trong `MASTER_DOCTYPES` được xóa khi user là R10 thật (không phải Administrator)
  và không có giao dịch liên kết (`check_if_doc_is_linked` / dynamic); ghi Audit `Delete`, vô hiệu mã trong Code Registry.
  Người khác vẫn bị chặn (chỉ ngừng dùng).
- `ignore_links_on_delete = ["Audit Log", "Code Registry"]` (lịch sử / sổ mã không phải giao dịch).
- Permission: R10 (ký hiệu W) nhận cờ `delete` trên danh mục (`setup.permissions`), fixture sinh lại.
- Test: `tests/test_master_delete_and_audit_trail.py::TestMasterDelete`, `tests/test_permissions.py`.

## Xong khi

Test các module trên pass, full suite không thêm lỗi so với develop, pre-commit sạch, vi.csv có bản dịch (ngữ cảnh cho
từ chung), migrate cả hai site.
