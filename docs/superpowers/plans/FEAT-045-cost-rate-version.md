# FEAT-045 Bảng định giá có phiên bản — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R09 lập phiên bản bảng giá (đơn giá vật tư, nhân công/giờ, điện/kWh, nước/lít, hơi/kg) và định mức theo loại gói, R01 duyệt; hệ thống trả đúng phiên bản có hiệu lực tại một ngày cho FEAT-046.

**Architecture:** DocType submittable `Cost Rate Version` (module Costing) với hai child `Cost Rate Line` và `Cost Norm Line`. Logic ở `tracecore/costing/rates.py` (kiểm dữ liệu, hiệu lực, tự đóng, tra cứu theo ngày, A1 giá bình quân); controller chỉ chuyển sang đó như `cost_entry.py`. RPC chỉ đọc `tracecore.v1.costing.rate_at`.

**Tech Stack:** Frappe v15, ERPNext v15 (Item, Bin), `FrappeTestCase` qua `tracecore.tests.utils.IsolatedTestCase`.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-045; `docs/srs.md` FR-M7-03, FR-M7-03.1–.3, FR-M7-04, FR-M7-04.1–.3; `docs/use-cases.md` UC-28; `docs/architecture.md` §5.3 DT-COSTRATE và amendment A-48 (Task 1).

## Quyết định người dùng chốt ngày 28/10/2026 (ghi thành A-48)

- **D1 Định mức một nguồn:** định mức theo chương trình giữ ở `Process Program.consumables` (FEAT-038, đang dùng cho trừ kho FEAT-042), không lặp lại. `Cost Norm Line` chỉ chứa định mức theo **loại gói** (`pack_type` = Item vật liệu gói như `Pack.pack_type`), số lượng/gói. FR-M7-04.1 (mẻ đã Hoàn tất không đổi) đạt vì FEAT-046 chụp định mức vào Cost Sheet lúc giải phóng; FEAT-045 không sửa Program Consumable.
- **D2 Hiệu lực:** chỉ nhập `effective_from`. R09 lập Nháp, **R01 Ghi sổ = duyệt**; sau duyệt không sửa (trừ `effective_to` do hệ thống đặt), Hủy để rút. Duyệt bản mới → bản đã duyệt đang mở có `effective_from` nhỏ nhất liền trước được đặt `effective_to = effective_from mới − 1`. Có bản đã duyệt với `effective_from ≥` ngày của bản mới → chặn (E1, FR-M7-03.3). Chỉ hủy được bản đã duyệt mới nhất; hủy thì bản liền trước mở lại (`effective_to` rỗng).
- **D3 Luồng phụ:** làm A1 (nút "Lấy giá bình quân tồn kho" trên bản Nháp), hoãn A2 (Excel) — ghi gap.

## Global Constraints

- Frappe/ERPNext `version-15`; không thêm DocType ngoài DT-COSTRATE (+2 child đã nêu ở §5.3).
- Không import chéo M1–M10: `costing` chỉ đọc `Process Program`, `Item`, `Bin` bằng `frappe.get_all`/`frappe.db`, không import `tracecore.equipment` hay `tracecore.inventory`.
- Chứng từ Nháp → Ghi sổ → Hủy, không xóa: `is_submittable=1`, `on_trash` gọi `audit.block_delete`; `track_changes=1`.
- Naming `DG-.YYYY.-.#####` (A-48, thêm vào dòng "Chứng từ khác" §5.3.3).
- Quyền (A-48, sửa dòng DT-COSTRATE của `permission_matrix.csv`): R01 `RWSA` (Frappe cần W để Ghi sổ), R02 `R`, R09 `RW`, R10 `R`; sinh lại `custom_docperm.json`.
- Mọi chuỗi qua `_()`, bản dịch ở `tracecore/translations/vi.csv` (3 cột); tiền VND không lẻ (`Currency`, precision 0).
- Ngày "hôm nay" theo VN: `tracecore.inventory.receipt.today_vn` KHÔNG được import (M6) → dùng `frappe.utils.nowdate()` (System Settings = Asia/Ho_Chi_Minh).
- Mỗi BRU-CST-002 test gắn `@bru("BRU-CST-002")`.

## Review Focus

1. **Duyệt bản lùi ngày** (effective_from trước bản đang mở): phải chặn với lỗi nêu bản bị chồng — test `test_approving_an_older_date_is_blocked` (Task 3).
2. **Hai bản Nháp cùng ngày** chỉ bị chặn lúc duyệt bản thứ hai, Nháp thì lưu được — test `test_two_drafts_same_date_only_second_approval_blocked` (Task 3).
3. **Ngày đúng bằng `effective_to`** của bản cũ vẫn lấy bản cũ, ngày kế tiếp lấy bản mới — test `test_version_at_boundaries` (Task 4).
4. **Bản Nháp/Đã hủy không bao giờ được trả** bởi `version_at`/`rate_at` (E3) — test `test_draft_and_cancelled_versions_are_ignored` (Task 4).
5. **A1 với vật tư không có tồn** giữ nguyên đơn giá và báo tên vật tư, không ghi 0 — test `test_fill_keeps_rate_when_no_stock` (Task 5).

---

## File Structure

| File | Trách nhiệm |
| --- | --- |
| `tracecore/costing/doctype/cost_rate_version/cost_rate_version.{json,py,js}` | DocType gốc; controller mỏng; JS nút A1 |
| `tracecore/costing/doctype/cost_rate_line/cost_rate_line.{json,py}` | child đơn giá |
| `tracecore/costing/doctype/cost_norm_line/cost_norm_line.{json,py}` | child định mức theo loại gói |
| `tracecore/costing/rates.py` | kiểm dữ liệu, duyệt/hủy, tra cứu theo ngày, A1 |
| `tracecore/v1/costing.py` | RPC `rate_at` |
| `tracecore/costing/tests/test_cost_rate_version.py`, `test_rates.py`, `test_rate_at_rpc.py` | test |
| `tracecore/tests/factories.py` | `make_cost_rate_version`, `rate_line`, `norm_line` |
| `tracecore/fixtures/permission_matrix.csv`, `custom_docperm.json` | quyền |
| `tracecore/translations/vi.csv` | bản dịch |
| `docs/architecture.md`, `docs/rtm.md` | A-48, Revision History, RTM FEAT-045 |

---

### Task 1: Amendment A-48 + DocType và quyền

**Files:**
- Modify: `docs/architecture.md` (Revision History dòng A-48; ghi chú A-48 sau A-47; bảng §5.3 dòng Cost Rate Version; §5.3.3 thêm `DG- Cost Rate Version (A-48)`)
- Create: ba DocType ở bảng trên
- Modify: `tracecore/fixtures/permission_matrix.csv` dòng 38 → `DT-COSTRATE,Cost Rate Version,RWSA,R,,,,,,,RW,R,FEAT-045 A-48 D2: R01 duyệt (Ghi sổ/Hủy), R09 lập Nháp`
- Regenerate: `tracecore/fixtures/custom_docperm.json`
- Test: `tracecore/costing/tests/test_cost_rate_version.py`

**Interfaces — Produces:**
- `Cost Rate Version`: `version_label` (Data, bắt buộc), `effective_from` (Date, bắt buộc), `effective_to` (Date, read_only, allow_on_submit), `note` (Small Text), `approved_by` (Link User, read_only), `approved_on` (Datetime, read_only), `rates` (Table Cost Rate Line), `pack_norms` (Table Cost Norm Line), `amended_from`.
- `Cost Rate Line`: `rate_type` (Select `Item\nLabor\nElectricity\nTap Water\nRO Water\nSteam`, bắt buộc), `item` (Link Item, `depends_on`/`mandatory_depends_on: eval:doc.rate_type=='Item'`), `uom` (Data, read_only, fetch Item.stock_uom; với loại khác đặt `hour`/`kWh`/`L`/`L`/`kg`), `rate` (Currency, precision 0, bắt buộc).
- `Cost Norm Line`: `pack_type` (Link Item, bắt buộc), `item` (Link Item, bắt buộc), `qty_per_pack` (Float, bắt buộc).
- Factory `make_cost_rate_version(effective_from=None, rates=None, pack_norms=None, submit=False, **kw)`; `rate_line(rate, rate_type="Item", item=None)`; `norm_line(pack_type, item, qty)`.

- [ ] **Step 1: Ghi A-48** vào architecture (nội dung = D1–D3 + naming + quyền + gap ở cuối plan), Revision History ngày 2026-10-28.
- [ ] **Step 2: Test thất bại** `TestCostRateVersionDoc`:
  - `test_named_dg`: `assertRegex(name, r"^DG-\d{4}-\d{5}$")`
  - `test_is_submittable_and_not_deletable`: `frappe.get_meta(...).is_submittable == 1`; `frappe.delete_doc` bản Nháp → raise `frappe.ValidationError` (hoặc lỗi của `audit.block_delete`).
  - `test_permissions_follow_a48`: Custom DocPerm của `TC R01` có `submit=1, cancel=1, write=0`; `TC R09` có `write=1, create=1, submit=0`; `TC R02`, `TC R10` chỉ `read`.
- [ ] **Step 3: Chạy** `bench --site test_f041 run-tests --module tracecore.costing.tests.test_cost_rate_version` → FAIL (DocType chưa có).
- [ ] **Step 4: Tạo** ba DocType (module Costing, `track_changes=1`, `autoname: DG-.YYYY.-.#####`), controller `CostRateVersion` với `validate → rates.validate(self)`, `before_submit → rates.before_submit(self)`, `on_submit → rates.on_submit(self)`, `before_cancel → rates.before_cancel(self)`, `on_cancel → rates.on_cancel(self)`, `on_trash → audit.block_delete(self, "on_trash")`; `rates.py` tạm có các hàm rỗng. Sửa matrix, sinh lại fixture (cách FEAT-044 làm), `bench --site test_f041 migrate`.
- [ ] **Step 5: Chạy lại** module test + `tracecore.tests.test_permissions` → PASS.
- [ ] **Step 6: Commit** `feat(costing): DocType Cost Rate Version, DG-, quyền R01 duyệt (FEAT-045, FR-M7-03, A-48)`.

### Task 2: Kiểm dữ liệu dòng giá và định mức gói

**Files:** Modify `tracecore/costing/rates.py`; Test `tracecore/costing/tests/test_rates.py`.

**Interfaces — Produces:** `rates.validate(doc) -> None`.

- [ ] **Step 1: Test thất bại** `TestRateLines` (`@bru("BRU-CST-002")` ở class):
  - `test_negative_rate_blocked`: `rate_line(-1)` → `frappe.ValidationError`.
  - `test_item_rate_requires_item` và `test_non_item_rate_must_not_have_item`.
  - `test_duplicate_rate_blocked`: hai dòng `Item` cùng item → chặn; hai dòng `Electricity` → chặn.
  - `test_uom_set_from_type`: dòng Item lấy `stock_uom` của Item; `Electricity` → `"kWh"`, `Labor` → `"hour"`, `Steam` → `"kg"`, nước → `"L"`.
  - `test_zero_rate_or_norm_warns_but_saves` (FR-M7-04.3, UC-28 E2): rate 0 hoặc `qty_per_pack` 0 → lưu được, `frappe.get_message_log()` có cảnh báo chứa tên dòng.
  - `test_negative_norm_blocked`; `test_duplicate_pack_norm_blocked` (cùng `pack_type` + `item`).
  - `test_programs_without_norm_are_listed` (FR-M7-04.2): có Process Program `is_active=1`, `norm_status="Missing"` → lưu phiên bản có cảnh báo nêu `program_code`.
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Hiện thực `validate(doc)`**: chặn bằng `frappe.throw(_("Row {0}: ..."))`; cảnh báo bằng `frappe.msgprint(..., indicator="orange", alert=False)`. Không chặn khi bảng rỗng (Nháp đang soạn); chặn rỗng ở `before_submit` (Task 3).
- [ ] **Step 4: Chạy** → PASS. **Step 5: Commit** `feat(costing): kiểm dòng đơn giá và định mức gói, cảnh báo định mức 0 (FEAT-045, FR-M7-04.2/.3)`.

### Task 3: Duyệt, tự đóng phiên bản cũ, hủy

**Files:** Modify `tracecore/costing/rates.py`; Test `test_rates.py`.

**Interfaces — Produces:** `rates.before_submit(doc)`, `rates.on_submit(doc)`, `rates.before_cancel(doc)`, `rates.on_cancel(doc)`.

- [ ] **Step 1: Test thất bại** `TestApproval` (`@bru("BRU-CST-002")`):
  - `test_approval_records_user_and_time`: submit bởi user `TC R01` → `approved_by == user`, `approved_on` có giá trị.
  - `test_empty_version_cannot_be_approved`: không có dòng giá → chặn.
  - `test_approving_closes_previous_open_version`: V1 từ 01/01 đã duyệt; duyệt V2 từ 01/04 → `V1.effective_to == 31/03`, `V2.effective_to` rỗng.
  - `test_approving_an_older_date_is_blocked` (E1, FR-M7-03.3): V1 từ 01/04 đã duyệt; duyệt V0 từ 01/03 → `frappe.ValidationError` nêu tên V1.
  - `test_two_drafts_same_date_only_second_approval_blocked`.
  - `test_approved_version_cannot_be_edited`: sửa `rates[0].rate` sau duyệt → `frappe.UpdateAfterSubmitError`.
  - `test_only_latest_approved_can_be_cancelled`: hủy V1 khi V2 đã duyệt → chặn; hủy V2 → được và `V1.effective_to` rỗng lại.
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Hiện thực**: `before_submit` kiểm có dòng giá và không có bản `docstatus=1` với `effective_from >= doc.effective_from` (khóa `for_update` các bản đã duyệt để hai lần duyệt đồng thời không cùng qua), đặt `approved_by = frappe.session.user`, `approved_on = now_datetime()`. `on_submit` tìm bản đã duyệt có `effective_to` rỗng và `effective_from < doc.effective_from` → `db_set("effective_to", add_days(doc.effective_from, -1))`. `before_cancel` chặn nếu có bản đã duyệt `effective_from > doc.effective_from`. `on_cancel` bản liền trước có `effective_to == add_days(doc.effective_from, -1)` → `db_set("effective_to", None)`.
- [ ] **Step 4: Chạy** → PASS. **Step 5: Commit** `feat(costing): duyệt phiên bản giá, tự đóng bản cũ, chặn chồng lấn (FEAT-045, FR-M7-03, FR-M7-03.3, UC-28 E1)`.

### Task 4: Tra cứu theo ngày + RPC `rate_at`

**Files:** Modify `tracecore/costing/rates.py`; Create `tracecore/v1/costing.py`; Test `test_rates.py`, `tracecore/costing/tests/test_rate_at_rpc.py`.

**Interfaces — Produces (FEAT-046 dùng):**
- `rates.version_at(date) -> str | None` — bản `docstatus=1`, `effective_from <= date` và (`effective_to` rỗng hoặc `>= date`).
- `rates.rate_for(date, rate_type, item=None) -> float | None` — None khi không có bản hoặc không có dòng (FEAT-046 đánh dấu Chưa định giá, FR-M7-05.2).
- `rates.pack_norms(date, pack_type) -> list[dict]` — `[{"item", "qty_per_pack"}]` theo `idx`.
- RPC `tracecore.v1.costing.rate_at(date)` (GET, chỉ đọc, role `TC R01/R02/R09/R10`, System Manager): `{"ok": True, "version": name|None, "effective_from", "effective_to", "rates": [{"rate_type","item","uom","rate"}], "pack_norms": [{"pack_type","item","qty_per_pack"}]}`; `date` sai định dạng → `BadRequestError`.

- [ ] **Step 1: Test thất bại**:
  - `test_version_at_boundaries`: V1 01/01 (đóng 31/03), V2 01/04 → `version_at(31/03)==V1`, `version_at(01/04)==V2`, `version_at(31/12/năm trước) is None`.
  - `test_draft_and_cancelled_versions_are_ignored` (E3).
  - `test_rate_for_returns_none_when_missing`; `test_rate_for_item_and_utility`.
  - `test_past_lookup_unchanged_after_new_version` (FR-M7-03.1, BRU-CST-002): `rate_for(15/02, "Electricity")` trước và sau khi duyệt V2 bằng nhau.
  - `test_pack_norms_for_pack_type`.
  - RPC: `test_rate_at_returns_version_payload`, `test_rate_at_rejects_bad_date`, `test_rate_at_requires_role` (user không có role → `frappe.PermissionError`).
- [ ] **Step 2: Chạy** → FAIL. **Step 3: Hiện thực** theo Interfaces; RPC dùng `require_any_role` của `tracecore.v1._common`, `getdate` bọc lỗi thành `BadRequestError`.
- [ ] **Step 4: Chạy** → PASS. **Step 5: Commit** `feat(costing): tra phiên bản giá theo ngày và RPC v1.costing.rate_at (FEAT-045, FR-M7-03.1, BRU-CST-002)`.

### Task 5: A1 — lấy giá bình quân tồn kho + form Desk

**Files:** Modify `tracecore/costing/rates.py`, `cost_rate_version.py`, `cost_rate_version.js`; Test `test_rates.py`, `tracecore/costing/tests/test_cost_rate_version_desk_assets.py`.

**Interfaces — Produces:** `rates.fill_from_stock(doc) -> {"updated": [item], "skipped": [item]}`; phương thức whitelisted `CostRateVersion.fill_from_stock()` (chỉ Nháp, chỉ user có quyền write).

- [ ] **Step 1: Test thất bại**:
  - `test_fill_uses_weighted_average_of_bins`: hai Bin của item (10 × 1.000 đ và 10 × 3.000 đ) → rate 2.000 (`round(sum(stock_value)/sum(actual_qty))`).
  - `test_fill_keeps_rate_when_no_stock` → rate cũ giữ, item nằm trong `skipped`.
  - `test_fill_only_on_draft`: bản đã duyệt → `frappe.ValidationError`.
  - Desk assets (kiểu `test_cost_entry_desk_assets.py`): JS có nút gọi `fill_from_stock` chỉ khi `docstatus === 0`, chuỗi qua `__()`; JSON field order đúng Task 1.
- [ ] **Step 2: Chạy** → FAIL. **Step 3: Hiện thực** (`frappe.get_all("Bin", filters={"item_code": ...}, fields=["actual_qty","stock_value"])`, bỏ Bin `actual_qty <= 0`); JS hiện `frappe.msgprint` liệt kê `skipped`.
- [ ] **Step 4: Chạy** → PASS. **Step 5: Commit** `feat(costing): lấy giá bình quân tồn kho vào bảng giá Nháp (FEAT-045, UC-28 A1)`.

### Task 6: Bản dịch, RTM, kiểm tra cuối

- [ ] **Step 1:** Thêm mọi chuỗi mới vào `vi.csv` (thuật ngữ: Cost Rate Version = "Phiên bản bảng giá", Effective From = "Hiệu lực từ", Pack Norms = "Định mức theo loại gói"); kiểm không trùng khóa, đủ 3 cột (script đã dùng khi merge FEAT-044).
- [ ] **Step 2:** `docs/rtm.md` dòng FR-M7-03, FR-M7-04: thay `_TBD_` cột thiết kế/test bằng A-48 và các file test.
- [ ] **Step 3:** Chạy `tracecore.costing` (mọi file test), `tracecore.equipment.tests.test_norms`, `tracecore.tests.test_permissions`, `scripts/check_architecture.py`, `scripts/check_bru_coverage.py`, `pre-commit run --all-files` trong bench → dán kết quả.
- [ ] **Step 4:** Ghi chú hiện thực (kết quả test, điểm lệch, gap) vào cuối plan; commit `docs(plan): ghi chú hiện thực FEAT-045`.
- [ ] **Step 5:** Merge `--no-ff` vào `develop` (Conventional Commits), không push, không tạo PR.

## Gap ghi nhận / ngoài phạm vi (ghi vào A-48)

- UC-28 A2 nhập bảng giá từ Excel: hoãn (có thể thêm kind `cost_rate` vào importer FEAT-011).
- FR-M7-03.2 tính lại giá thành quá khứ có ghi chú phiên bản: thuộc FEAT-046 (cần Cost Sheet).
- FR-M7-04 định mức theo chương trình: dùng `Process Program.consumables` có sẵn; FR-M7-04.3 ở đó hiện **chặn** dòng 0/0 (chặt hơn "cảnh báo"), giữ nguyên.
- Định mức theo loại gói chưa nối vào trừ kho tự động (FEAT-042 gap "nhãn/bao gói theo Cycle ID"): để FEAT-046 hoặc FEAT sau.
