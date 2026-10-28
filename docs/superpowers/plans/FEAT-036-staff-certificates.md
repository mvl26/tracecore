# FEAT-036 Hồ sơ nhân viên và chứng chỉ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R02 và R10 ghi hồ sơ nhân viên (mã NV-, khu làm việc, khám sức khỏe, tiêm chủng) và chứng chỉ có hạn kèm file scan; hệ thống đánh dấu hết hạn, nhắc nhân viên và R02 ở 60/30/7 ngày, giữ lịch sử gia hạn.

**Architecture:** DocType `Certificate` (module `TraceCore`, A-44) + package `tracecore/hr/` (`certificates`, `employees`, `reminders`) + Custom Field và Property Setter cho HRMS `Employee` + RPC `tracecore.v1.staff.certificates` + Desk (form Employee, form và danh sách Certificate) + việc hằng ngày 00:00.

**Tech Stack:** Frappe v15, HRMS `Employee`, `core.notification` (FEAT-010), `core.code_registry`, nhãn `Employee Card` (FEAT-005), `IsolatedTestCase`.

**Spec:** `docs/srs.md` FR-M4-01 (.1–.5), FR-M4-02 (.1–.4), BRU-ID-006, BRU-HR-002; `docs/use-cases.md` UC-19; `docs/architecture.md` §5.3 (DT-EMP, DT-CERT); Amendment A-44.

## Global Constraints
- Employee là HRMS Employee, không tạo DocType thay thế; Certificate không xóa được, sửa có Audit Log.
- Chuỗi qua `_()`/`__()` có bản dịch; từ chung dịch theo context DocType; UI chỉ token `--tc-*`; trạng thái luôn có chữ.
- Không làm: chặn đăng nhập trạm và vô hiệu năng lực theo chứng chỉ (FEAT-037), nhập chứng chỉ từ Excel, nhân viên tự xem chứng chỉ.

## Quyết định (Amendment A-44, tạm — chờ chủ đầu tư)
| # | Quyết định | AC |
| :- | :- | :- |
| H1 | `Certificate` ở module `TraceCore`, M4 không đăng ký Module Def. | A-01 |
| H2 | Loại chứng chỉ là danh sách cố định (CCHN, KSNK, tiệt khuẩn, vận hành thiết bị áp lực, khác). | FR-M4-02 |
| H3 | Gia hạn = bản ghi mới có `renews`; bản cũ Superseded, giữ lịch sử; không xóa. | FR-M4-02.3 |
| H4 | Không hết hạn → `no_expiry`, không nhắc; file scan > 10 MB bị từ chối. | FR-M4-02.4, UC-19 E2/E3 |
| H5 | Nhắc theo mức 60/30/7 và khi hết hạn, mỗi mức một lần, qua `core.notification`; đổi ngày hạn thì nhắc lại từ đầu. | FR-M4-02.1, FR-M4-01.4 |
| H6 | Employee mới tên `NV-#####` (series mặc định), ghi Code Registry; `tc_card_id` trống thì mặc định bằng mã NV-. | FR-M4-01, BRU-ID-006 |
| H7 | In thẻ QR bằng nhãn `Employee Card` của FEAT-005 qua nút trên form. | FR-M4-01 |

## Tasks
- [x] **T1 Test** `hr/tests/test_certificates.py` (21 test), `v1/tests/test_staff_api.py` (4 test).
- [x] **T2 DocType + dịch vụ** Certificate, `hr/certificates.py`, `hr/reminders.py`, `hr/employees.py`.
- [x] **T3 Employee** Custom Field (khu, khám sức khỏe, tiêm chủng), Property Setter series NV-, hook tạo và lưu.
- [x] **T4 Việc hằng ngày** `hr.reminders.run_daily` ở cron 00:00; 3 loại sự kiện thông báo mới.
- [x] **T5 RPC + Desk** `v1.staff.certificates`, form Employee (chỉ báo, thêm/xem chứng chỉ, in thẻ QR), form và danh sách Certificate, link ở trang chủ.

## Review Focus
- Việc hằng ngày không nhắc lặp một mức và không nhắc chứng chỉ Superseded hoặc không hết hạn.
- Nhân viên cũ HR-EMP- vẫn lưu được; nhân viên mới không trùng mã NV- với mã đã cấp bằng `core.code_registry.next_code`.
- Bản dịch dùng context nên không đè bản dịch chung của Frappe/HRMS.
