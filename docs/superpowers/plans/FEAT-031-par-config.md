# FEAT-031 Cấu hình cơ số tái xử lý và cơ số tồn khoa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps dùng checkbox (`- [ ]`).

**Goal:** R01/R02 (SCR-30, WEB) nhập tay **cơ số tái xử lý tối đa** cho dụng cụ / loại bộ kèm nguồn (IFU / Ước tính) và ngưỡng cảnh báo sớm (% hoặc số lần), và **cơ số tồn khoa** (khoa × loại bộ: tối thiểu, tối đa, % cho phép vượt, cờ khoa cấp cứu). Mọi thay đổi ghi lịch sử người – thời điểm – giá trị cũ/mới. Hệ thống không tự lấy cơ số từ IFU.

**Architecture:** Module Frappe `Par` (M8), package `tracecore/par/` (đã có `check.py` stub FEAT-018). Hai DocType đúng architecture §5.3 / DT-PARLEVEL: `Par Level` (master, Dynamic Link `target_doctype` + `target`) và child `Par Level History`. Không DocType mới ngoài §5.3. Logic ở `par/config.py` (luật, đồng bộ, lịch sử), controller mỏng. Giao diện Desk form + Client Script (ADR-002). Không import chéo M1–M10: `par` đọc `Instrument`, `Instrument Set Type`, `Set Unit`, `Department` theo tên DocType qua `frappe.db`, không `import tracecore.instrument`.

**Tech Stack:** Frappe v15 (DocType, child table, `track_changes`), `core.audit` (doc_events), Python 3.11, Desk Client Script.

**Spec:** `implementation-plan.md` §3 FEAT-031; `srs.md` FR-M8-01 (.1–.4), FR-M8-02 (.1, .3; .2 xem S6), OTH-RET-002, OQ-07; `use-cases.md` UC-30; `ux-foundations.md` SCR-30; `architecture.md` §5.3.1 M8 (DT-PARLEVEL), ERD dòng 576–578, ghi chú I4 dòng 358.

**FR/BRU/AC:** FR-M8-01 → AC-1; .1 → AC-2; .2 → AC-3; .3 → AC-4; .4 → AC-5; FR-M8-02 → AC-6; .1 → AC-7; .3 → AC-8. BRU: BRU-PAR-001..005 (cấu hình, chưa kiểm tại T4 — FEAT-032); BRU-PAR-005 (cơ số khoa, ngoại lệ cấp cứu ≤ 20 %).

**Nhánh:** `feat/FEAT-031-par-config` từ `develop` trong bench `~/tracecore-f031` (site `test_f031`, dev `tracecore-f031.local`, cổng 8031, Redis 13031/11031).

## Quyết định

| # | Loại | Quyết định | Căn cứ |
| :- | :- | :- | :- |
| S1 | [Đã duyệt 22/10/2026] | **`Par Level` là nguồn sự thật cơ số tái xử lý.** Lưu `Par Level` (loại *Reprocessing*, `target_doctype = Instrument`) đồng bộ **một chiều** sang `Instrument.max_cycles` (+ `max_cycles_status`) bằng `flags`, để `catalog`, `check.py`, báo cáo FEAT-014 giữ nguyên. Sửa tay `Instrument.max_cycles` vẫn được (nhập liệu FEAT-014/011); khi đó tạo/ cập nhật `Par Level` tương ứng không thuộc FEAT-031 — ghi gap G1. Loại bộ: **không** ghi vào `Set Unit.max_cycles` (snapshot lúc cấp Set ID, FEAT-016/032); FEAT-031 chỉ cung cấp `par.config.effective_set_type_cap()` | architecture dòng 358 (chờ chốt) → user chọn phương án này |
| S2 | [Chốt] | Hai loại Par Level (`par_kind`): **Reprocessing** (dụng cụ / loại bộ / vật tư tái sử dụng: `max_cycles`, `source` IFU/Ước tính, `warn_percent`, `warn_count`) và **Department Stock** (`department` + `target` = loại bộ: `min_qty`, `max_qty`, `over_percent`, `is_emergency_dept`). Một bản ghi duy nhất cho mỗi (`par_kind`, `target_doctype`, `target`, `department`) — unique | DT-PARLEVEL; FR-M8-01/02 |
| S3 | [Chốt] | Đối tượng hiện có: `Instrument`, `Instrument Set Type` (Reprocessing); `Instrument Set Type` (Department Stock). **Vật tư tái sử dụng** chưa có định nghĩa trong tài liệu (không có trường/nhóm Item) và **`Linen Type`** chưa tồn tại (FEAT-033, S3) nên chưa nằm trong `target_doctype`; thêm tùy chọn khi có | Out of scope G2 |
| S4 | [Chốt] | Cơ số trống/0 → "Chưa xác định": lưu được, không chặn (FR-M8-01.1). Loại bộ không có Par Level riêng → cơ số bộ = min `max_cycles` > 0 của BOM hiệu lực (FR-M8-01.2) qua `par.config.effective_set_type_cap(set_type)`, đọc BOM bằng `frappe.db` (không import `instrument`) | FR-M8-01.1, .2 |
| S5 | [Chốt] | Cảnh báo sớm: `warn_percent` (mặc định 10) và `warn_count` (mặc định 5), "10 % hoặc 5 lần" theo SRS review #7: ngưỡng cảnh báo khi còn lại ≤ max(10 % cơ số, 5 lần)? Cách kết hợp **chưa chốt**: lưu hai trường, FEAT-032 quyết cách dùng; FEAT-031 không đổi `check.WARN_PERCENT` | SRS bảng review #7 |
| S6 | [Xác nhận] | FR-M8-02.2 (xuất báo cáo tồn khoa so cơ số) cần tồn khoa từ FEAT-026 (S2) → **không làm ở FEAT-031**, ghi gap G3 | implementation-plan: FEAT-026 cộng tồn khoa |
| S7 | [Xác nhận] | Cơ số ≤ chu trình đã dùng (FR-M8-01.4): chặn lưu lần đầu với thông báo, cho lưu khi người dùng tick `confirm_below_used` (trường Check không lưu). "Đã dùng" = `Instrument` không có bộ đếm → max `cycles_used` của Set Unit chứa dụng cụ; với loại bộ = max `Set Unit.cycles_used` của loại bộ. Dụng cụ không có bộ đếm riêng ở FEAT-014 ⇒ chỉ kiểm cho loại bộ; dụng cụ kiểm bằng `Instrument Maintenance` nếu có bộ đếm, ngược lại bỏ qua (G4) | FR-M8-01.4; UC-30 E1 |
| S8 | [Chốt] | Khoa cấp cứu: `is_emergency_dept = 1` mới được đặt `over_percent` 1–20; khoa thường `over_percent` = 0 (mặc định); > 20 → chặn. `min_qty` ≤ `max_qty` (E2, FR-M8-02.3) | FR-M8-02.1, .3; BRU-PAR-005 |
| S9 | [Chốt] | Lịch sử: child `Par Level History` (append-only: `changed_by`, `changed_on`, `field`, `old_value`, `new_value`, `reason`). Mọi `Par Level` insert/update tạo dòng; lý do bắt buộc khi sửa cơ số tối đa / tối thiểu. Không sửa/xóa dòng lịch sử (kể cả System Manager). Song song `track_changes` + Audit Log | FR-M8-01.3; OTH-RET-002; ADR-008 |
| S10 | [Chốt] | Quyền theo permission_matrix: R01 đọc/ghi/tạo (duyệt = ghi), R02 đọc/ghi/tạo, R04/R06/R07/R09 đọc, System Manager toàn quyền trừ xóa; không ai xóa (đặt `is_active` thay vì xóa) | permission_matrix DT-PARLEVEL; UC-30 actors |
| S11 | [Chốt] | Naming `PAR-.#####` (nhật ký: cần thêm một dòng vào architecture §5.3.3) | §5.3.3 |

## Global Constraints

- Kế thừa constraints FEAT-001/014/015: không import chéo M1–M10, mọi chuỗi qua `_()`/`__()` + `translations/vi.csv`, Audit Log, không xóa, TDD + `@bru`, coverage changed-code ≥ 70 %, `test_ignore = ["Item", "Batch", "Department", "User", "Employee"]` cho test link tới `Department`/`Item`.
- Chỉ `core.step_gate` ghi trường vòng đời Set Unit — FEAT-031 **không** ghi `Set Unit`.
- Ghi `Instrument.max_cycles` chỉ trong `par.config.sync_instrument()` (cờ `flags.tc_par`); `Instrument.validate` hiện không cấm nên không cần đổi.
- UI: chữ trạng thái luôn kèm chữ (Đã xác định / Chưa xác định), mã Courier New, token `--tc-*`, không hex.
- Lệnh: `wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-f031 && bench --site test_f031 run-tests ..."`.

## Review Focus

1. Đồng bộ `Instrument.max_cycles`: lưu/đổi/xóa cơ số (đặt về 0) → `max_cycles_status` đúng; không ghi khi `Par Level` không phải Reprocessing/Instrument; không vòng lặp (Instrument.on_update không gọi lại).
2. Lịch sử bất biến và đủ: đổi 3 trường cùng lúc → 3 dòng, cùng `reason`; không sửa/xóa kể cả System Manager.
3. Biên: min = max OK, min > max chặn; over_percent 20 vs 21; khoa thường có over_percent > 0; cơ số = đã dùng và < đã dùng.
4. Unique (kind, target, department): hai người tạo trùng.

---

### Task 0: Amendment — ghi quyết định S1–S11

**FR/AC:** chuẩn bị. **Files:** Modify `docs/architecture.md` (Revision History; ghi chú I4 dòng 358 thay "chờ chủ đầu tư chốt" bằng quyết định S1; §5.3.1 M8 trường `Par Level`; §5.3.3 dòng `PAR-.#####`), `docs/rtm.md` (FR-M8-01/02 cột Test).

- [ ] **Step 1:** Ghi Amendment (số kế tiếp trong Revision History) với S1 "đã duyệt bởi người dùng 22/10/2026", S2–S11 "tạm — chờ chủ đầu tư duyệt"; ghi gap G1–G4 (cuối plan). **Step 2:** `pre-commit run --files <docs>`. **Step 3:** Commit `docs: amendment quyết định FEAT-031`.

### Task 1: DocType `Par Level` + child `Par Level History`, quyền, audit

**FR/BRU/AC:** FR-M8-01, FR-M8-02, FR-M8-02.3, FR-M8-01.3; AC-1, AC-4, AC-6; BRU-PAR-005.

**Files:** Create `tracecore/par/doctype/par_level/{__init__,par_level.json,par_level.py,test_par_level.py,par_level.js}`, `tracecore/par/doctype/par_level_history/{__init__,par_level_history.json,par_level_history.py}`; Modify `tracecore/hooks.py` (`doc_events["Par Level"] = dict(_AUDIT_EVENTS)`), `tracecore/translations/vi.csv`, `tracecore/tests/factories.py` (`make_par_level`).

**Interfaces — `Par Level`:** `par_kind` (Select `Reprocessing`/`Department Stock`, reqd), `target_doctype` (Select `Instrument`/`Instrument Set Type`/`Item`, reqd), `target` (Dynamic Link, reqd), `department` (Link Department, reqd khi Department Stock), `max_cycles` (Int ≥ 0, Reprocessing), `source` (Select `IFU`/`Estimate`, mặc định `Estimate`), `warn_percent` (Percent, 10), `warn_count` (Int, 5), `min_qty`, `max_qty` (Int ≥ 0), `over_percent` (Percent 0–20), `is_emergency_dept` (Check), `is_active` (Check, 1), `confirm_below_used` (Check, không lưu), `reason` (Small Text, không lưu, dùng khi sửa), `history` (Table `Par Level History`, read_only).

- [ ] **Step 1 — test trước** (`test_ignore` đủ): `test_create_reprocessing_par_for_instrument` (AC-1: lưu, nguồn IFU, `warn_percent` mặc định 10), `test_blank_cap_is_undefined_not_blocked` (AC-2), `test_unique_kind_target_department`, `test_min_greater_than_max_blocked` (AC-8/E2), `test_min_equal_max_ok`, `@bru("BRU-PAR-005") test_over_percent_only_for_emergency_dept_max_20` (AC-7: 20 OK, 21 chặn, khoa thường > 0 chặn), `test_department_required_for_stock_par`, `test_target_must_exist`, `test_history_rows_one_per_changed_field` (AC-4), `test_history_immutable_even_for_system_manager`, `test_no_delete_for_anyone`, `test_permissions` (R01/R02 ghi, R04 đọc, R03 không thấy), `test_par_audited`.
- [ ] **Step 2:** chạy → FAIL. **Step 3:** Hiện thực JSON + controller (`validate` gọi `config.validate(doc)`, `before_save`/`on_update` ghi history); `bench --site test_f031 migrate`. **Step 4:** PASS. **Step 5:** Commit `feat(par): DocType Par Level và Par Level History`.

### Task 2: `par/config.py` — đồng bộ, cơ số bộ suy ra, cảnh báo dưới chu trình đã dùng

**FR/BRU/AC:** FR-M8-01.1, .2, .4; AC-2, AC-3, AC-5; BRU-PAR-001..004 (cấu hình).

**Files:** Create `tracecore/par/config.py`, `tracecore/par/tests/test_config.py`; Modify `par_level.py`.

**Interfaces:** `config.sync_instrument(doc)` (Reprocessing + Instrument + `is_active`: `frappe.db.set_value("Instrument", target, {max_cycles, max_cycles_status})` với `flags.tc_par`; đổi về 0 hoặc `is_active = 0` giữ giá trị cuối? → đặt `max_cycles = 0`/Undefined, test), `config.effective_set_type_cap(set_type) -> dict` (`{value, source: "Par Level" | "Derived" | "Undefined", undefined: [mã]}`), `config.used_cycles(doc) -> int | None` (S7), `config.validate(doc)`.

- [ ] **Step 1 — test:** `test_save_syncs_instrument_max_cycles` (Review Focus 1), `test_zero_cap_marks_instrument_undefined`, `test_inactive_par_does_not_touch_instrument` (Par ngừng dùng không đổi `Instrument.max_cycles`), `test_effective_set_type_cap_own_par_wins`, `test_effective_set_type_cap_derived_min_of_bom` (FR-M8-01.2: 500/300 → 300; có dụng cụ trống → liệt kê), `test_cap_not_above_used_blocks_unless_confirmed` (AC-5; bằng và nhỏ hơn chặn, cao hơn OK; tick `confirm_below_used` cho lưu), `test_no_sync_for_set_type_par` (Set Unit không đổi), `test_check_py_unchanged` (`tracecore/par/tests/test_check.py` xanh không sửa).
- [ ] **Step 2–5:** FAIL → hiện thực → PASS toàn `tracecore.par` + `tracecore.instrument` → commit `feat(par): đồng bộ cơ số sang Instrument, cơ số bộ suy ra, cảnh báo dưới chu trình đã dùng`.

### Task 3: Desk form SCR-30

**FR/AC:** UC-30; AC-1, AC-5, AC-6.

**Files:** Modify `par_level.js`, `translations/vi.csv`; Create `tracecore/tests/test_desk_par.py` (e2e Desk mỏng, Playwright, dev site; **không** chạy trên site test).

- [ ] **Step 1:** Form: hiện/ẩn nhóm trường theo `par_kind`; badge "Đã xác định / Chưa xác định"; hiện "Đã dùng N / Cơ số M" khi sửa; hộp xác nhận (FR-M8-01.4) + trường lý do; bảng lịch sử read-only; tooltip "không tự lấy từ IFU". **Step 2:** `bench build --app tracecore`; Playwright: tạo Par Level cho một dụng cụ, đổi cơ số kèm lý do, mở lịch sử. **Step 3:** Commit `feat(par): form Desk cấu hình cơ số`.

### Task 4: Dọn và kiểm (dữ liệu demo `setup/devdata.py` không làm: ngoài AC của FEAT-031)

- [ ] Patch không cần (chưa có dữ liệu cũ). `pre-commit run --files <file đổi>`, `python3 scripts/check_architecture.py`, coverage: `diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70`. Commit `feat(par): dữ liệu demo cơ số`.

## Gap / ngoài phạm vi

- G0: quyền Par Level theo `permission_matrix.csv` DT-PARLEVEL (R01 RWSA, R02 RWS, R04/R06/R07/R09/R10 R); `custom_docperm.json` sinh lại bằng `write_fixture`.
- G1: sửa tay `Instrument.max_cycles` không tạo Par Level (hai nơi cùng ghi; chủ đầu tư nên chốt khóa trường về read-only sau FEAT-011).
- G2: `Linen Type` → FEAT-033; vật tư tái sử dụng (FR-M8-01 nêu) chưa có mô hình dữ liệu nào trong tài liệu, cần quyết định riêng. G3: báo cáo tồn khoa vs cơ số (FR-M8-02.2) → sau FEAT-026. G4: cơ số dụng cụ ≤ đã dùng chưa kiểm được khi dụng cụ chưa có bộ đếm.
- Import Excel cơ số (UC-30 A2) → FEAT-011. Chặn/ghi đè cơ số tại T4 → FEAT-032. Cách kết hợp "10 % hoặc 5 lần" → FEAT-032.
