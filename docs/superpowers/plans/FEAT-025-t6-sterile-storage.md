# FEAT-025 T6 Kho vô khuẩn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (hoặc subagent-driven-development). Steps dùng checkbox `- [ ]`.

**Goal:** KTV kho vô khuẩn (R06) tại trạm T6 quét Cycle ID rồi quét mã kệ `KE-` → Pack sang *Trong kho vô khuẩn* kèm vị trí; tồn theo vị trí và theo loại bộ; gói sắp hết hạn 7 ngày; FEFO gợi ý; gói quá hạn (00:00 ngày sau hạn) hoặc quét báo rách/ướt kèm lý do → Pack *Hết hiệu lực* (Void) và Set Unit *Chờ tiếp nhận* để đưa về khu bẩn.

**Architecture:** Dịch vụ nghiệp vụ M2 ở `tracecore/reprocessing/storage.py`; đổi trạng thái Set Unit chỉ qua `core.step_gate` (hàm mới `check_stored`, `return_to_receipt`); RPC mỏng `tracecore/v1/putaway.py` + `pack.mark_damaged`; scheduler `0 0 * * *`; UI là phần T6 của Page `station` (`public/js/station_t6.js`, nạp bằng `page_js`). Không import chéo M1–M10.

**Spec:** implementation-plan §3 (FEAT-025); srs FR-M2-13(.1–.5), FR-M2-14(.1–.2); use-cases UC-11; architecture §5.3 (Sterile Location, Sterile Putaway), ADR-005; ux-foundations SCR-11.

FR/BRU đáp ứng: FR-M2-13, FR-M2-13.1–.5, FR-M2-14, FR-M2-14.1, FR-M2-14.2; BRU-REP-008, BRU-ID-003, BRU-FLOW-002/003/004.

**Nhánh:** `feat/FEAT-025-t6-sterile-storage` (tách từ `develop`), làm trong `~/tracecore-dev/apps/tracecore`.

## Quyết định

| # | Loại | Nội dung | Căn cứ |
| :- | :- | :- | :- |
| D1 | [Chốt 22/10/2026] | Thêm trạng thái `Awaiting Receipt` (Chờ tiếp nhận) vào `Set Unit.status`; giải quyết mâu thuẫn srs Appendix mục 4. FEAT-027 dùng chung | FR-M2-14, FR-M2-17 |
| D2 | [Chốt 22/10/2026] | Test T6 lấy gói Released + 5 cổng Pass bằng factory qua `step_gate`; FEAT-023 thay bằng luồng thật | implementation-plan §3 (FEAT-025 chỉ phụ thuộc 005) |
| D3 | [Xác nhận] | "T6 kiểm" = `step_gate.check_stored(set_unit)` (chỉ đọc): bộ phải Sterile (đủ T1..T5 Pass), nếu không trả `GATE_PREV_NOT_PASSED` kèm `items` = các bước còn thiếu. Không thêm hàng `Step Gate Result` T6 (enum bước giữ T1..T5) | UC-11 E1, BRU-FLOW-004 |
| D4 | [Xác nhận] | Sterile Location (Reprocessing, tên `KE-####` qua `code_registry.next_code("KE")`, Link Zone Station, cờ `is_active`); Sterile Putaway (submittable, mỗi lần nhập kho/chuyển vị trí một chứng từ, tên `SP-.YYMMDD.-.####`); `Pack.location` (Link, allow_on_submit) chỉ đổi qua dịch vụ T6 | architecture §5.3 |
| D5 | [Xác nhận] | Quá hạn = `expiry < hôm nay` (chạy 00:00 ngày sau hạn), áp cho Pack `In Sterile Stock` và `Released`. Hủy bằng `status = Void`, `void_reason = Expired` (quá hạn) hoặc `Torn` (rách/ướt/mở); Code Registry vô hiệu | FR-M2-14, BRU-ID-003 |
| D6 | [Xác nhận] | FEFO: `fefo_suggest(set_type)` trả gói `In Sterile Stock` hạn sớm nhất; `fefo_check(pack)` trả cảnh báo khi còn gói cùng loại bộ hạn gần hơn (FR-M2-13.4 chấp nhận khi chọn theo Set ID kèm ghi chú: để FEAT-026 gọi) | FR-M2-13.3/.4 |
| D7 | [Xác nhận] | Ngoài phạm vi: gia hạn hạn lưu (FR-M2-14.3, R02), kiểm kê E3, in PDF danh sách đưa về khu bẩn (RPC trả dữ liệu, in qua FEAT-007), chặn quét ở T7 (FEAT-026 đọc `status != In Sterile Stock`) | implementation-plan §3 |

## Tasks

Mọi task: test trước (thấy FAIL), code, PASS, commit `feat(...)`. Bản dịch `vi.csv` cập nhật cùng task.

- [ ] **T0 Amendment** `architecture.md` Revision History A-08 (D1, D3–D7) + `srs.md` Appendix mục 4 ghi đã chốt.
- [ ] **T1 Set Unit `Awaiting Receipt` + `step_gate.check_stored` + `step_gate.return_to_receipt`** (FR-M2-14, BRU-FLOW-004). Test: `core/tests/test_step_gate.py`.
- [ ] **T2 DocType Sterile Location** (+ test, quyền R10 ghi, R06/R02/R01 đọc, `next_code("KE")`, audit hook). Test: `reprocessing/doctype/sterile_location/test_sterile_location.py`.
- [ ] **T3 DocType Sterile Putaway + `Pack.location`** (guard trường, quyền, audit). Test: `reprocessing/doctype/sterile_putaway/test_sterile_putaway.py`, `pack/test_pack.py`.
- [ ] **T4 `reprocessing/storage.py`**: `putaway`, `mark_damaged`, `expire_due`, `overview`, `fefo_suggest`, `fefo_check`, `return_list` (FR-M2-13.x, 14.x). Test: `reprocessing/tests/test_storage.py`.
- [ ] **T5 RPC** `v1.putaway.scan/overview/fefo/return_list`, `v1.pack.mark_damaged`; mã lỗi HTTP; role `TC R06`. Test: `v1/tests/test_putaway_api.py`.
- [ ] **T6 Scheduler** `0 0 * * *` → `storage.expire_due` (+ Audit Log). Test trong T4.
- [ ] **T7 UI SCR-11** `station_t6.js` (ô quét trên cùng, 4 trạng thái, alert-error inline, tồn theo loại bộ/vị trí, gói sắp hết hạn, nút báo rách ≥ 48 px) + test `test_station_page.py`.
- [ ] **T8 Kết thúc**: `pre-commit run --all-files`, `run-tests --coverage`, `diff-cover --fail-under=70`, cập nhật `rtm.md`, PR vào `main`.
