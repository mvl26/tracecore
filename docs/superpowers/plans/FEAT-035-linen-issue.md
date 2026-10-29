# FEAT-035 Đồ vải: cấp phát theo khoa, tồn khoa, đối chiếu thu − trả − hủy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R07 ghi cấp phát (trả) đồ vải sạch cho khoa với người nhận ký điện tử, thấy ngay lượng thu gom chưa trả; cảnh báo vượt định mức tối đa; ghi hủy đồ vải hỏng (lý do + ảnh); bảng đối chiếu thu − trả − hủy theo khoa/loại/kỳ (Script Report, xuất Excel); cuối ngày cảnh báo R02 khi lệch tháng > 5 %.

**Architecture:** Mở rộng module `Linen` (M3): DocType `Linen Issue` (+ child `Linen Issue Line`), dịch vụ `tracecore/linen/issue.py` (ghi cấp phát, tồn khoa, định mức) và `tracecore/linen/reconcile.py` (đối chiếu, cảnh báo); RPC mỏng `tracecore.v1.linen.*` theo khuôn FEAT-033; màn SCR-18 trong Page `station` (class `LinenIssue`, bước `LIN` dùng chung với thu gom); Script Report `Linen Reconciliation`; scheduler dùng `core.notification.emit`.

**Spec:** `docs/implementation-plan.md` §3 FEAT-035; `docs/srs.md` FR-M3-05 (.1, .2), FR-M3-06 (.1–.4); `docs/use-cases.md` UC-18; `docs/ux-foundations.md` SCR-18; `docs/architecture.md` §5.3 M3 (DT-LINENISS).

FR/BRU đáp ứng: FR-M3-05, FR-M3-05.1, FR-M3-05.2, FR-M3-06, FR-M3-06.1–.4; BRU-LIN-001, BRU-LIN-004 (xem G1).

**Nhánh:** `feat/FEAT-035-linen-issue` cắt từ `develop` (bbf2f31 trở đi).

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt. **[Xác nhận]** = lựa chọn trong phạm vi tài liệu.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| G1 | [Chốt] | BRU-LIN-004 chỉ được tham chiếu, không có định nghĩa ở srs/architecture | Hiểu BRU-LIN-004 = quy tắc đối chiếu của FR-M3-06.1: chênh lệch tháng `(thu − trả − hủy) / thu` > 5 % số chiếc thì cảnh báo R02. Test gắn `@bru("BRU-LIN-004")` theo cách hiểu này; ghi amendment để chủ đầu tư xác nhận. | srs FR-M3-06.1 |
| G2 | [Chốt] | "Ghi hủy" (FR-M3-06.2) và "Cấp mới" / "Trả dư" (UC-18 A1, A2) chưa có DocType riêng trong §5.3 | Không thêm DocType: `Linen Issue.kind` = `Return` (trả sau giặt) / `New` (cấp mới từ kho, A1) / `Dispose` (hủy). `Dispose` bắt buộc `reason` + ảnh đính kèm, không có người nhận/chữ ký. **Trả dư (A2) để ngoài phạm vi** vì nó sửa luồng thu gom của FEAT-033; ghi vào mục chưa làm. | UC-18 A1, A2; FR-M3-06.2 |
| G3 | [Chốt] | Định nghĩa "tồn khoa" và "chênh lệch" | Chênh lệch theo FR-M3-06: `thu − trả − hủy` (chiếc và kg, `Return` và `Dispose` trừ vào thu; `New` không tính). **Tồn khoa** = `Σ(Return + New) − Σ thu` cộng dồn theo khoa/loại (đồ sạch đang nằm ở khoa so với đồ bẩn đã lấy đi). Hiển thị cả hai ở SCR-18. | FR-M3-05, FR-M3-06 |
| G4 | [Xác nhận] | Chữ ký nhận điện tử | Giống `Issue Note` (FEAT-026): `sign_method` Card/Touch, `signature` (Signature), `signed_at`; người nhận là Employee quét thẻ hoặc ký trên màn cảm ứng. Chỉ `Return`/`New` cần ký. | FR-M3-05.1; FEAT-026 |
| G5 | [Xác nhận] | Cảnh báo định mức | Khi cấp: nếu `tồn khoa + số cấp > max_qty` của khoa/loại → trả cảnh báo (không chặn), cho phép giữ kèm ghi chú. Khoa chưa có định mức → cho phép, hiện "Chưa cấu hình định mức" (UC-18 E1). `min_qty`: chỉ cảnh báo trong báo cáo/đối chiếu. | FR-M3-05.2, FR-M3-06, UC-18 E1 |
| G6 | [Xác nhận] | Cảnh báo cuối ngày | Job `0 0 * * *` (00:00, tính cho ngày trước và tháng đang chạy): chênh lệch tháng > 5 % hoặc tồn dưới `min_qty` → `core.notification.emit("LINEN_VARIANCE", …)` tới R02; quy tắc thông báo mặc định thêm ở `ensure_default_rules`. | FR-M3-06, FR-M3-06.1 |
| G7 | [Xác nhận] | Báo cáo | Script Report `Linen Reconciliation` (bộ lọc khoa, loại, từ ngày, đến ngày; cột thu, trả, hủy, chênh lệch, %, tồn khoa, min, max). Kỳ không có dữ liệu → 0 chứ không lỗi. Xuất Excel dùng nút có sẵn của Frappe. Quyền: R01, R02, R07, R09. | FR-M3-06.3, .4 |
| G8 | [Xác nhận] | Sửa phiếu đã ký | Hủy + Sửa đổi (`amended_from`), không sửa đè (UC-18 E3). Hủy cần R02. | UC-18 E3 |
| G9 | [Xác nhận] | Biên nhận | Print Format `TC Linen Issue Receipt` (A5) có chữ ký; nút In trên màn trạm và Desk. | FR-M3-05.1 |
| G10 | [Xác nhận] | RPC | `tracecore.v1.linen.balance` (POST, không `@idempotent`: khoa → chưa trả, tồn khoa, quota theo loại) và `tracecore.v1.linen.issue` (POST, `@idempotent`, tạo + ghi sổ). Ghi hủy làm trên Desk (cần đính ảnh), không có RPC kiosk. Mã lỗi mới `LINEN_ISSUE_*` (422). Lệch plan gốc (chỉ ghi `v1.linen.issue`). | implementation-plan §3 |
| G11 | [Xác nhận] | Quyền | `Linen Issue`: R07 RWS; R02 RWSA; R01, R09 R. R08 chưa có (xem G12). Thêm hàng `DT-LINENISS` vào `permission_matrix.csv`, sinh lại `custom_docperm.json`. | architecture §5.3 |
| G12 | [Chốt] | View DEPT "Đồ vải đã nhận" cho R08 (SCR-18 view, #17) | Ngoài phạm vi FEAT-035: cần Portal và lọc theo khoa của R08. Ghi vào mục chưa làm. | ux-foundations SCR-18 |
| G13 | [Xác nhận] | Ngoài phạm vi | Dashboard kg/khoa (FEAT-006), lô giặt và chi phí/kg (FEAT-034), dùng `unit_value` (FEAT-034/046). | implementation-plan |

## File structure

- Tạo: `tracecore/linen/doctype/{linen_issue,linen_issue_line}/`, `tracecore/linen/issue.py`, `tracecore/linen/reconcile.py`, `tracecore/linen/report/linen_reconciliation/`, `tracecore/linen/print_format/tc_linen_issue_receipt/`
- Tạo: `tracecore/linen/tests/{test_linen_issue,test_reconcile,test_linen_issue_report,test_linen_issue_print,test_linen_issue_station_assets}.py`, `tracecore/v1/tests/test_linen_issue_api.py`
- Sửa: `tracecore/v1/linen.py`, `tracecore/core/errors.py`, `tracecore/hooks.py` (audit events, scheduler, asset), `tracecore/core/notification/__init__.py` (rule `LINEN_VARIANCE`), `tracecore/public/js/station_linen.js` (hoặc `station_linen_issue.js`), `station.js`, `station.css`, `fixtures/permission_matrix.csv`, `translations/vi.csv`, `docs/architecture.md` (A-51), `docs/rtm.md`

## Tasks

- [ ] **Task 0 — Docs:** amendment A-51 ở `architecture.md` (G1–G13), cập nhật §5.3 `Linen Issue`, series `LNI-.YYYY.-.#####`.
- [ ] **Task 1 — Test trước + DocType (FR-M3-05, FR-M3-05.1; BRU-LIN-001):** `Linen Issue`/`Linen Issue Line`, kiểm tra khoa, dòng, quy đổi số ↔ kg dùng lại `collection.convert`, `Dispose` bắt buộc lý do + ảnh, ký bắt buộc khi `Return`/`New`.
- [ ] **Task 2 — Tồn khoa và đối chiếu (FR-M3-05, FR-M3-06, .4; BRU-LIN-004):** `reconcile.balance(department)`, `reconcile.rows(filters)`, giá trị 0 khi kỳ rỗng.
- [ ] **Task 3 — Cảnh báo (FR-M3-05.2, FR-M3-06.1):** vượt max khi cấp; job cuối ngày; rule `LINEN_VARIANCE`.
- [ ] **Task 4 — RPC + quyền + lỗi:** `balance`, `issue`; `LINEN_ISSUE_*`; ma trận quyền.
- [ ] **Task 5 — Màn SCR-18 trên Page `station`:** chọn khoa, hiện chưa trả/tồn khoa, dòng loại–số–kg (dùng lại `TcWeighLine`), cảnh báo định mức, ký, in; đủ 4 trạng thái.
- [ ] **Task 6 — Report + Print Format (FR-M3-06.3, FR-M3-05.1).**
- [ ] **Task 7 — Dịch, full test, coverage ≥ 70 %, lint, ghi chú, commit, push.**

## Acceptance criteria (EARS, từ FR)

| AC | Điều kiện | Kiểm bằng |
| :- | :- | :- |
| AC-1 | Cấp phát tạo Linen Issue, cập nhật tồn khoa và hiện đối chiếu so với thu gom của khoa (FR-M3-05) | test service + RPC |
| AC-2 | Thiếu khoa/loại/số/kg → không ghi sổ (BRU-LIN-001) | test |
| AC-3 | Xác nhận phải có chữ ký người nhận; in được biên nhận (FR-M3-05.1) | test + Print Format |
| AC-4 | Vượt `max_qty` → cảnh báo, vẫn ghi được; khoa chưa có định mức → cho phép (FR-M3-05.2, UC-18 E1) | test |
| AC-5 | Chênh lệch = thu − trả − hủy theo khoa/loại/kỳ; kỳ rỗng → 0 (FR-M3-06, .4) | test report |
| AC-6 | Chênh lệch tháng > 5 % → thông báo R02 (đúng 5 % thì không) (FR-M3-06.1, BRU-LIN-004) | test scheduler |
| AC-7 | Hủy bắt buộc lý do và ảnh (FR-M3-06.2) | test |
| AC-8 | Xuất Excel bảng chênh lệch theo khoa (FR-M3-06.3) | test report |
| AC-9 | Sửa phiếu đã ký = hủy + sửa đổi (UC-18 E3) | test |

## Ghi chú hiện thực

_(điền khi làm xong)_
