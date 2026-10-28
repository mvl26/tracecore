# FEAT-037 Ma trận năng lực và phân ca Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R02 gán, thu hồi năng lực theo trạm trên một ma trận nhân viên × trạm, chọn chứng chỉ bắt buộc cho từng năng lực; đăng nhập trạm chỉ qua khi năng lực còn hiệu lực và chứng chỉ bắt buộc còn hạn; xếp ca theo khu chỉ khi đủ năng lực; xuất lịch ca tuần và xem sản lượng theo người và ca.

**Architecture:** `Station Competency` (FEAT-003) thêm child `Competency Required Cert`, người đánh giá, lý do thu hồi + dịch vụ `tracecore/hr/` (`competency`, `shifts`, `permissions`) + hook `tracecore_competency_missing_certificates` cho `core.station_auth` + RPC `tracecore.v1.competency.*` + Page `competency-matrix` + HRMS `Shift Assignment` có `tc_zone` + hai Script Report (`Shift Schedule`, `Station Output`).

**Tech Stack:** Frappe v15, HRMS (Shift Type, Shift Assignment), `core.extension` hook, `core.notification` (FEAT-010), `hr.certificates` (FEAT-036), `IsolatedTestCase`.

**Spec:** `docs/srs.md` FR-M4-03 (.1–.4), FR-M4-04 (.1–.3), FR-M4-02.2, BRU-HR-001; `docs/use-cases.md` UC-20; `docs/architecture.md` §5.3 (DT-COMP, DT-SHIFT); Amendment A-45.

## Global Constraints
- Chỉ R02, R10, System Manager gán và thu hồi; R01 chỉ xem. Năng lực không xóa, thu hồi giữ bản ghi và có Audit Log.
- Đăng nhập trạm từ chối bằng một câu trả lời công khai duy nhất (ADR-006); lý do cụ thể ghi Audit Log và hiện ở ma trận.
- Chuỗi qua `_()`/`__()` có bản dịch, từ chung dịch theo context; UI chỉ token `--tc-*`; trạng thái luôn có chữ; đủ loading/empty/error/offline.
- Không làm: đổi ca có R02 duyệt (Shift Request), sản lượng T7/T8 và đồ vải, mặc định chứng chỉ theo bước trạm.

## Quyết định (Amendment A-45, tạm — chờ chủ đầu tư)
| # | Quyết định | AC |
| :- | :- | :- |
| C1 | Chứng chỉ bắt buộc chọn trên từng năng lực, không mặc định theo trạm; năng lực cũ không đổi hành vi. | FR-M4-03 |
| C2 | Đăng nhập trạm qua hook; từ chối vẫn chung, lý do cụ thể ở Audit Log và ma trận. | FR-M4-03.1/.2 |
| C3 | Chứng chỉ hết hạn → năng lực tạm dừng theo tính toán (không đổi `is_active`), báo R02 và nhân viên. | FR-M4-02.2 |
| C4 | Quyền tạm ≤ 24 giờ, có lý do, vẫn đủ chứng chỉ bắt buộc; thu hồi cần lý do. | FR-M4-03.3 |
| C5 | Ma trận một màn, bốn trạng thái ô có chữ. | FR-M4-03.4 |
| C6 | Xếp ca vào khu cần năng lực ít nhất một trạm của khu và chứng chỉ còn hạn; trùng ca do HRMS chặn. | FR-M4-04.1/.3 |
| C7 | Lịch ca tuần xuất bằng Export của báo cáo; sản lượng từ Step Gate Result và hai loại mẻ. | FR-M4-04, FR-M4-04.2 |

## Tasks
- [x] **T1 Test** `hr/tests/test_competency.py` (22), `hr/tests/test_shifts.py` (16), `v1/tests/test_competency_api.py` (5).
- [x] **T2 DocType + dịch vụ** `Competency Required Cert`, `hr/competency.py` (gán, thu hồi, ma trận, tạm dừng), hook đăng nhập trong `core.station_auth`.
- [x] **T3 Phân ca** Custom Field `Shift Assignment-tc_zone`, `hr/shifts.py`, quyền `hr/permissions.py`.
- [x] **T4 Báo cáo** `Shift Schedule`, `Station Output`.
- [x] **T5 RPC + Desk** `v1/competency.py`, Page `competency-matrix`, link ở trang chủ TraceCore, bản dịch.
- [x] **T6 Sửa test lệch** `test_station_models` mong đợi đúng tập Custom Field của Employee sau FEAT-036.

## Review Focus
- Nhân viên đủ năng lực nhưng thiếu hoặc hết hạn chứng chỉ bắt buộc không vào được trạm và không xếp được ca; gia hạn chứng chỉ khôi phục ngay.
- Người quẹt thẻ không phân biệt được "thẻ không tồn tại", "thiếu năng lực" và "thiếu chứng chỉ" qua câu trả lời.
- Quyền tạm không vượt 24 giờ và không miễn chứng chỉ bắt buộc.
