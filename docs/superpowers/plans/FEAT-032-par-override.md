# FEAT-032 Kiểm soát vượt cơ số và ghi đè có phê duyệt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps dùng checkbox (`- [ ]`).

**Goal:** Bộ (hoặc một dụng cụ trong BOM của bộ) đã dùng hết cơ số tái xử lý thì T4 không sinh Cycle ID, hiển thị dụng cụ vượt, chuyển Set Unit sang **Hết vòng đời – chờ thanh lý** và chặn quét ở mọi trạm. R04 bấm **Đề nghị ghi đè** (lý do) ngay trên SCR-08; R01 (hoặc R02 được ủy quyền) mở đề nghị trên Desk (SCR-31), nhập số chu trình thêm, thời hạn, lý do và **PIN** → bộ được đóng gói lại trong phạm vi số chu trình và thời hạn đó; ghi đè tự hết hiệu lực. Cảnh báo cam khi còn ít chu trình (API cho T3/dashboard). Báo cáo ghi đè theo tháng cho QLCL.

**Architecture:** Module Frappe `Par` (M8), package `tracecore/par/`. DocType mới **`Par Override`** đúng architecture §5.3 (DT-OVERRIDE). Quy tắc cơ số ở `par/check.py` (thay stub FEAT-018 sau cùng interface hook `tracecore_pack_context` / `tracecore_pack_prechecks`, P-5); vòng đời ghi đè ở `par/override.py`; RPC mỏng `tracecore/v1/par/__init__.py` (`check`) và `tracecore/v1/par/override.py` (`request`, `approve`, `reject`). Trạng thái Set Unit chỉ đổi qua hai hàm mới của `core.step_gate` (`end_of_life`, `reopen_after_override`). M2 (đóng gói) không import `par`: T4 gọi qua hook như FEAT-018; M8 không import M1/M2 (đọc `Set Unit`, `Instrument`, `Set BOM Item`, `Pack` theo tên DocType).

**Tech Stack:** Frappe v15 (DocType submittable, Script Report, Notification Log, scheduler), `core.step_gate`, `core.station_auth.verify_pin`, `core.audit`, `@idempotent`, Page `station` (station_t4.js), Desk Client Script.

**Spec:** `implementation-plan.md` §3 dòng FEAT-032, §5.3 AC-11 (FEAT-018); `srs.md` FR-M8-03 (.1–.3), FR-M8-04 (.1–.4), FR-M1-06.3, FR-M2-07.5, FR-M2-18.1, FR-M2-05.3, KPI dòng 139; `use-cases.md` UC-31 (main, A1, A2, E1–E3), UC-08 E1; `architecture.md` §5.3.1 M8 (DT-OVERRIDE), §6.7 (sequence UC-31), A-11 (FEAT-031); `ux-foundations.md` SCR-31, SCR-08, luồng "Duyệt ghi đè cơ số"; `design.md` §6 (giọng, "Sắp …", lỗi chặn); `fixtures/permission_matrix.csv` DT-OVERRIDE.

**FR/BRU → AC:**

| AC | EARS | FR / BRU |
| :- | :- | :- |
| AC-1 | Khi số chu trình còn lại của bộ hoặc của một dụng cụ trong BOM ≤ ngưỡng cảnh báo sớm (Q1), `par.check.evaluate` trả `state = "warn"` kèm số còn lại và danh sách dụng cụ sắp hết; T4 hiển thị cảnh báo cam có chữ; `v1.par.check` trả danh sách bộ cảnh báo cho dashboard | FR-M8-03.1, FR-M2-05.3 (API); BRU-PAR-003 |
| AC-2 | Nếu `cycles_used ≥ max_cycles` của bộ hoặc ≥ cơ số của bất kỳ dụng cụ nào trong BOM (Q2) và không có ghi đè hiệu lực, thì T4 không sinh Cycle ID, trả `PAR_EXCEEDED` (409) kèm danh sách dụng cụ vượt | FR-M8-03.2, FR-M2-07.5; BRU-PAR-002 |
| AC-3 | Khi AC-2 xảy ra, Set Unit chuyển **End of Life** qua `step_gate.end_of_life` (Audit Log); quét bộ đó ở bất kỳ trạm nào trả `SET_END_OF_LIFE` (409) | FR-M8-03.2, FR-M1-06.3, FR-M2-18.1; UC-31 E2; BRU-PAR-002 |
| AC-4 | Khi R04 bấm "Đề nghị ghi đè" trên SCR-08 với lý do, hệ thống tạo `Par Override` trạng thái **Requested** (Nháp), ghi Audit Log và gửi thông báo cho R01 (+ R02 ủy quyền); thiếu lý do → `REASON_REQUIRED`; bộ chưa vượt → `PAR_NOT_EXCEEDED`; đã có đề nghị chờ hoặc ghi đè hiệu lực → `OVERRIDE_PENDING` | FR-M8-04; BRU-PAR-004 |
| AC-5 | Chỉ R01 hoặc R02 được ủy quyền (Q6) duyệt/từ chối; người khác → `APPROVER_NOT_ALLOWED` (403) | FR-M8-04.1; BRU-PAR-004 |
| AC-6 | Khi duyệt với số chu trình thêm ≥ 1, thời hạn ≥ hôm nay, lý do và PIN đúng, Override → **Approved** (ghi sổ), Set Unit End of Life → Processing (Q4), Audit Log (người duyệt, lý do, PIN đã xác thực); sai PIN → `PIN_INVALID`, 3 lần → `PIN_LOCKED` | FR-M8-04, FR-M8-04.2; BRU-PAR-004 |
| AC-7 | Nếu duyệt hoặc từ chối không có lý do, hệ thống chặn (`REASON_REQUIRED`) | FR-M8-04.4; UC-31 E1 |
| AC-8 | Khi bộ có ghi đè hiệu lực, T4 sinh Cycle ID trong phạm vi số chu trình thêm và thời hạn; mỗi chu trình (khác `cycle_no`) trừ 1; void + đóng gói lại cùng chu trình không trừ thêm | FR-M8-03.3; BRU-PAR-004 |
| AC-9 | Khi ghi đè dùng hết số chu trình thêm, hoặc qua hết ngày thời hạn (cron 00:00), Override → **Expired**; T4 chặn lại như AC-2 | FR-M8-04.2; UC-31 A2; FR-M2-18.1 |
| AC-10 | Khi từ chối (lý do + PIN), Override → **Rejected** (ghi sổ), Set Unit giữ End of Life | UC-31; ux-foundations luồng duyệt |
| AC-11 | Báo cáo "Par Override Report" (SCR-31) theo tháng: mọi ghi đè trong tháng (bộ, người đề nghị/duyệt, lý do, số chu trình thêm/đã dùng, thời hạn, trạng thái) + KPI số ghi đè ÷ số bộ đạt cơ số (mục tiêu ≤ 10 %); ngày 1 hằng tháng gửi Notification Log cho R01 trỏ tới báo cáo tháng trước | FR-M8-04.3; srs KPI dòng 139 |
| AC-12 | Cơ số bộ/dụng cụ Chưa xác định (0/trống) → không chặn, `state = "undefined"` | UC-31 E3; FR-M8-01.1 |
| AC-13 | Không ai xóa được Par Override (kể cả System Manager); quyền theo `permission_matrix.csv` DT-OVERRIDE | ADR-008; OTH-RET-002 |
| AC-14 | SCR-08: nút "Đề nghị ghi đè" bật (thay nút disabled "Có từ FEAT-032" của FEAT-018 AC-11) cho `PAR_EXCEEDED` và `SET_END_OF_LIFE`, mở hộp lý do, gửi `v1.par.override.request` idempotent; thanh cơ số hiện trạng thái ghi đè | FR-M8-04; SCR-08 |

**Nhánh:** `feat/FEAT-032-par-override` từ `develop` trong bench `~/tracecore-f032` (site `test_f032`, dev `tracecore-f032.local`, cổng 8032, Redis 13032/11032).

## Quyết định

`[Cần duyệt]` = tài liệu thiếu/mâu thuẫn, chọn phương án tạm và **chờ người dùng/chủ đầu tư duyệt**; `[Xác nhận]` = dev lead xác nhận. Ghi thành **Amendment A-18** (bảng đã chốt: A-13 FEAT-016, A-14 FEAT-011, A-15 FEAT-019, A-16 FEAT-022, A-17 FEAT-026).

| # | Loại | Quyết định | Phương án khác | Căn cứ |
| :- | :- | :- | :- | :- |
| Q1 | [Cần duyệt] | **Ngưỡng cảnh báo sớm** "10 % hoặc 5 lần" = cảnh báo khi còn lại ≤ max(⌈`warn_percent` % × cơ số⌉, `warn_count`) (thỏa một trong hai). `warn_percent`/`warn_count` lấy từ Par Level Reprocessing đang dùng của loại bộ (cấp bộ) hoặc của dụng cụ (cấp dụng cụ), mặc định 10/5. Trùng quy tắc tạm của FEAT-020 Q10 | "và" (thỏa cả hai) | srs review #7, A-11 S5, FEAT-020 Q10, design.md §6 "cơ số ≥ 90 %" |
| Q2 | [Cần duyệt] | **Cơ số cấp dụng cụ:** chưa có bộ đếm riêng của dụng cụ (A-11 G4) nên chu trình đã dùng của dụng cụ = `cycles_used` của bộ chứa nó; cơ số = `Instrument.max_cycles` (đồng bộ từ Par Level, A-11 S1). Dụng cụ lấy từ BOM phiên bản ghim của chu trình (`cycle_bom_version`), 0 thì phiên bản hiện hành. Thay dụng cụ từ kho dự phòng (UC-31 A1) chưa có mô hình dữ liệu → gap G1 | Chỉ kiểm cấp bộ tới khi có bộ đếm dụng cụ | FR-M8-03.2, A-11 G4 |
| Q3 | [Cần duyệt] | **Thời điểm chuyển Hết vòng đời:** khi T4 phát hiện vượt (hook `check_pack`) và không có ghi đè hiệu lực: `step_gate.end_of_life(set_unit, reason)`. Đường quét (`get_context`) ghi và commit; trong `generate` lỗi chặn hoàn tác về savepoint nhưng màn T4 luôn quét trước khi sinh mã. Không chuyển lúc giải phóng mẻ (gói cuối cùng trong cơ số vẫn hợp lệ). `step_gate.check` trả `SET_END_OF_LIFE` cho bộ End of Life ở **mọi bước** (chặn quét sử dụng) | Chuyển khi bộ đếm đạt cơ số lúc giải phóng (FEAT-023) | FR-M8-03.2, FR-M1-06.3, FR-M2-18.1, UC-31 bước 3 |
| Q4 | [Cần duyệt] | **Mở lại sau duyệt:** Set Unit End of Life → **Processing** (architecture §6.7 "Đang tái xử lý"); cổng của chu trình hiện hành giữ nguyên nên bộ quay lại T4 đóng gói ngay | → Reprocess | architecture §6.7 |
| Q5 | [Xác nhận] | **Từ chối:** Override Rejected (ghi sổ), Set Unit giữ End of Life; R04/R02 được đề nghị lại (đề nghị mới) | — | ux-foundations luồng duyệt |
| Q6 | [Cần duyệt] | **R02 được ủy quyền:** trường mới `TraceCore Settings.par_override_delegate` (Link User, một người, R01/R10 đặt); người đó phải có role TC R02 | Mọi R02 đều duyệt được | FR-M8-04.1 không nêu cách ủy quyền |
| Q7 | [Xác nhận] | **PIN trên Desk:** người duyệt nhập PIN 6 số của Employee gắn với user (`station_auth.verify_pin`: sai 3 lần khóa 5 phút, Audit Log). User không có Employee/PIN → `PIN_INVALID` | Proof của FEAT-020 (`create_approver_proof`, chưa merge) | implementation-plan FEAT-032 "R01 duyệt PIN"; A-08 |
| Q8 | [Xác nhận] | **WF-08 trên chứng từ:** `is_submittable`; Requested = Nháp (docstatus 0) → Approved / Rejected = Ghi sổ → Expired (sau ghi sổ, `allow_on_submit`); Hủy (docstatus 2) = R01 thu hồi ghi đè đã duyệt → Cancelled. Chỉ `par.override` được submit (cờ `flags.tc_par_override`), không submit tay trên form | Workflow Frappe | CLAUDE.md "Nháp → Ghi sổ → Hủy"; WF-08 |
| Q9 | [Xác nhận] | **Tiêu thụ:** hook `tracecore_after_cycle_id` → `override.consume(pack, ctx)`: chỉ khi bộ đang vượt cơ số; `cycle_no` khác `last_cycle_no` thì `cycles_consumed + 1`; đủ `extra_cycles` → Expired. Hiệu lực = Approved, `valid_until ≥ hôm nay`, và (`cycles_consumed < extra_cycles` hoặc `last_cycle_no = current_cycle_no`) | Đếm theo Pack | FR-M8-03.3, FR-M8-04.2 |
| Q10 | [Cần duyệt] | Naming `GD-.YYYY.-.#####` (Ghi Đè; nhóm "Chứng từ khác" §5.3.3) | — | architecture §5.3.3 |
| Q11 | [Cần duyệt] | **Thông báo:** `Notification Log` (chuông Desk) cho user R01 đang hoạt động + R02 ủy quyền khi có đề nghị; ngày 1 hằng tháng (scheduler `monthly`) cho R01 trỏ tới báo cáo tháng trước. Email/SMS, thông báo cho trạm T4 khi đã duyệt, SCR-42 → FEAT-010 (G3) | Chờ FEAT-010 | FR-M8-04, FR-M8-04.3, UC-38 A1 |
| Q12 | [Xác nhận] | **KPI tháng:** "số bộ đạt cơ số" = số Set Unit khác nhau có Audit Log chuyển End of Life trong tháng (step_gate ghi); tỷ lệ = số ghi đè Approved trong tháng ÷ số đó | Đếm Reject `PAR_EXCEEDED` | srs dòng 139 |
| Q13 | [Xác nhận] | **T3 / dashboard:** FEAT-032 chỉ cung cấp `par.check.evaluate(set_unit)` và RPC `tracecore.v1.par.check` (một bộ, hoặc danh sách bộ `warn`/`blocked`/`override` cho dashboard). Hiển thị trên SCR-07 do FEAT-020 (`assembly_context` gọi `evaluate`); widget SCR-32 → FEAT-006, báo cáo dự báo thay thế → FEAT-007 (G4) | — | FEAT-020 Q10; implementation-plan FEAT-006/007 |
| Q14 | [Xác nhận] | **RPC:** `tracecore.v1.par.check(set_id=None)` (Desk/trạm, chỉ đọc); `tracecore.v1.par.override.request(set_id, station, reason, client_ts, token)` (`station_session(R04, R02, System Manager)` + `@idempotent`); `tracecore.v1.par.override.request_desk(set_unit, reason)`, `approve(override, extra_cycles, valid_until, reason, pin)`, `reject(override, reason, pin)` (Desk, kiểm role, không idempotent — Desk không gửi khóa). Mã lỗi mới: `SET_END_OF_LIFE`, `PAR_NOT_EXCEEDED`, `OVERRIDE_PENDING`, `OVERRIDE_NOT_PENDING` (409), `APPROVER_NOT_ALLOWED` (403), `EXTRA_CYCLES_INVALID`, `VALID_UNTIL_INVALID` (422) | — | implementation-plan FEAT-032; D3 |
| Q15 | [Xác nhận] | Ngoài phạm vi: bộ đếm chu trình (FEAT-023, test đặt `cycles_used` bằng fixture), thanh lý `Disposed` (G5 FEAT-016), offline (FEAT-009), quét sử dụng T8 (dùng lại `SET_END_OF_LIFE` của `step_gate.check`) | — | — |

## Global Constraints

- Không import chéo M1–M10 (`scripts/check_architecture.py`): `par` đọc `Set Unit`, `Instrument`, `Set BOM Item`, `Instrument Set Type`, `Pack` theo tên DocType; `reprocessing.packing` không đổi import.
- Chỉ `core.step_gate` đổi `Set Unit.status` (hai hàm mới, cờ `tc_step_gate`); Override chỉ submit/đổi trạng thái trong `par.override` (cờ `flags.tc_par_override`).
- Mọi chuỗi qua `_()`/`__()` + `translations/vi.csv`; ngày `dd/mm/yyyy`; token `--tc-*`; trạng thái luôn có chữ; lỗi chặn trên SCR-08 là `alert-error` inline, hộp thoại chỉ nhập lý do.
- TDD + `@bru`; coverage changed-code ≥ 70 %; `test_ignore = ["Item", "Batch", "Department", "User", "Employee"]`.
- Lệnh: `wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-f032 && bench --site test_f032 run-tests --module …"`.

## Interface cho FEAT-020 (T3) và dashboard

`tracecore.par.check.evaluate(set_unit: str | dict) -> dict`:

```
{"set_unit", "cycles_used", "max_cycles", "remaining", "percent", "warn_at",
 "state": "ok" | "warn" | "blocked" | "override" | "undefined",
 "instruments": [{"instrument", "instrument_name", "max_cycles", "remaining", "state": "warn" | "blocked"}],
 "override": {"name", "extra_cycles", "cycles_consumed", "valid_until"} | None}
```

`pack_context` trả `{"par": evaluate(...)}` (giữ khóa FEAT-018 `cycles_used/max_cycles/percent/state`). FEAT-020 `assembly_context` nên trả `{"par": check.evaluate(ctx["set_unit"])}`.

---

### Task 0: Amendment A-18 + plan

**Files:** Modify `docs/architecture.md` (Revision History A-18; §5.3.1 M8 ghi chú Par Override; §5.3.3 dòng `GD-`), `docs/rtm.md` (FR-M8-03/04 cột Test). Create plan này.

- [ ] Ghi Q1–Q15 (Q1–Q4, Q6, Q10, Q11 "tạm — chờ duyệt"), gap G1–G5. `pre-commit run --files <docs>`. Commit `docs: amendment A-18 quyết định FEAT-032`.

### Task 1: `step_gate.end_of_life` / `reopen_after_override` + `SET_END_OF_LIFE`

**FR/BRU/AC:** FR-M8-03.2, FR-M1-06.3, FR-M2-18.1; AC-3; BRU-PAR-002.
**Files:** Modify `tracecore/core/step_gate.py`, `tracecore/core/errors.py`, `tracecore/core/tests/test_step_gate.py`.

- [ ] Test: `test_end_of_life_sets_status_and_keeps_cycle` (Audit Log Update có old/new status), `test_end_of_life_idempotent`, `@bru("BRU-PAR-002") test_check_blocks_end_of_life_at_every_step` (T1..T5 → `SET_END_OF_LIFE` 409), `test_reopen_after_override_only_from_end_of_life` (→ Processing; trạng thái khác → lỗi). FAIL → code → PASS → commit `feat(core): step gate chuyển bộ Hết vòng đời và mở lại sau ghi đè`.

### Task 2: DocType `Par Override` + quyền + settings

**FR/BRU/AC:** FR-M8-04, .1, .2; AC-4, AC-5, AC-13; BRU-PAR-004.
**Files:** Create `tracecore/par/doctype/par_override/{__init__,par_override.json,par_override.py,par_override.js,test_par_override.py}`; Modify `tracecore/tracecore/doctype/tracecore_settings/tracecore_settings.json` (`par_override_delegate`), `tracecore/fixtures/permission_matrix.csv` (notes), `tracecore/fixtures/custom_docperm.json` (`write_fixture`), `tracecore/hooks.py` (`doc_events["Par Override"]`), `tracecore/translations/vi.csv`.

**Trường:** `set_unit` (Link, reqd, set_only_once), `set_type`, `department` (fetch), `status` (Select Requested/Approved/Rejected/Expired/Cancelled, read_only, allow_on_submit), `cycles_used`, `max_cycles` (snapshot), `exceeded_instruments` (Small Text), `reason` (Small Text, reqd), `requested_by` (Link User), `requested_at`, `station` (Link Zone Station); quyết định: `extra_cycles` (Int), `valid_until` (Date), `decision_reason`, `decided_by` (Link User), `decided_by_employee` (Link Employee), `decided_at`, `pin_verified` (Check); tiêu thụ: `cycles_consumed`, `last_cycle_no` (Int, allow_on_submit), `expired_at`, `expiry_cause` (Select Cycles Used/Date Passed). Naming `GD-.YYYY.-.#####`.

- [ ] Test: tạo đề nghị hợp lệ; không submit tay (`flags`); không xóa (cả System Manager); quyền theo ma trận (R01 RWSA, R02 RWS, R04 đọc); `before_save` chặn đổi set_unit/reason sau khi tạo. FAIL → code → `bench migrate` → PASS → commit `feat(par): DocType Par Override (WF-08)`.

### Task 3: `par/check.py` — quy tắc đầy đủ (thay stub)

**FR/BRU/AC:** FR-M8-03.1/.2/.3, FR-M2-07.5; AC-1, AC-2, AC-3, AC-8, AC-12; BRU-PAR-002, BRU-PAR-003, BRU-PAR-004.
**Files:** Modify `tracecore/par/check.py`, `tracecore/par/tests/test_check.py`.

- [ ] Test (đổi các test stub cũ sang quy tắc Q1): ngưỡng Q1 (300 → cảnh báo khi còn ≤ 30; 20 → còn ≤ 5; Par Level loại bộ 20 %/2), cấp dụng cụ Q2 (dụng cụ cơ số 100 trong bộ 300, đã dùng 100 → `blocked`, item nêu dụng cụ), Chưa xác định (E3), ghi đè hiệu lực → `override` (không chặn), hết hạn/hết số → chặn, `check_pack` chuyển End of Life + `PAR_EXCEEDED` có `items`. FAIL → code → PASS → commit `feat(par): kiểm cơ số cấp bộ và dụng cụ, cảnh báo sớm, chặn và Hết vòng đời`.

### Task 4: `par/override.py` — đề nghị, duyệt, từ chối, tiêu thụ, hết hiệu lực, thông báo

**FR/BRU/AC:** FR-M8-04, .1, .2, .4, FR-M8-03.3; AC-4..AC-10; BRU-PAR-004.
**Files:** Create `tracecore/par/override.py`, `tracecore/par/tests/test_override.py`; Modify `tracecore/hooks.py` (`tracecore_after_cycle_id += par.override.consume`; cron 00:00 `par.override.expire_overdue`; `monthly` `par.override.notify_monthly_report`).

- [ ] Test: request (lý do, chưa vượt, trùng, thông báo R01 + ủy quyền), approve (vai trò, lý do, extra ≥ 1, ngày, PIN đúng/sai/khóa, bộ → Processing, Audit), reject, consume theo chu trình (void + đóng lại không trừ), hết số → Expired, cron hết hạn, thu hồi (cancel). FAIL → code → PASS → commit `feat(par): đề nghị và duyệt ghi đè cơ số có PIN`.

### Task 5: RPC `tracecore.v1.par.*`

**FR/AC:** AC-1, AC-4..AC-7, AC-10.
**Files:** Create `tracecore/v1/par/__init__.py`, `tracecore/v1/par/override.py`, `tracecore/v1/tests/test_par_api.py`.

- [ ] Test: phiên trạm T4 + idempotent replay, mã HTTP, Audit Log Reject, Desk approve/reject 403/422/409, `check` một bộ và danh sách. Luồng đầy đủ: bộ vượt → quét T4 chặn + EOL → request → approve PIN → quét T4 ok → sinh Cycle ID → override trừ 1. FAIL → code → PASS → commit `feat(v1): RPC par.check và par.override`.

### Task 6: UI — SCR-08 nút Đề nghị ghi đè, SCR-31 Desk

**FR/AC:** AC-14, AC-6, AC-10, UC-31.
**Files:** Modify `tracecore/public/js/station_t4.js`, `tracecore/public/css/station.css` (nếu cần), `par_override.js`; Create `tracecore/par/tests/test_par_override_desk_assets.py`.

- [ ] SCR-08: nút bật cho `PAR_EXCEEDED`/`SET_END_OF_LIFE`, hộp lý do, toast/notice "Đã gửi đề nghị ghi đè GD-…"; thanh cơ số `override` ("Đang ghi đè … còn n chu trình đến dd/mm/yyyy"), `warn` liệt kê dụng cụ. SCR-31: nút Duyệt/Từ chối trên form Requested (dialog: số chu trình, thời hạn, lý do, PIN), lỗi hiện headline đỏ; indicator list theo trạng thái. Test tài sản: chuỗi `__()` có bản dịch, không hex/px. Commit `feat(ui): đề nghị ghi đè trên T4 và duyệt trên Desk`.

### Task 7: Báo cáo ghi đè tháng (SCR-31)

**FR/AC:** FR-M8-04.3; AC-11.
**Files:** Create `tracecore/par/report/par_override_report/{__init__,par_override_report.json,.py,.js,test_par_override_report.py}`.

- [ ] Test: lọc theo tháng, cột, KPI, quyền R01/R02. Commit `feat(par): báo cáo ghi đè cơ số theo tháng`.

### Task 8: Kiểm toàn bộ

- [ ] Chạy module `par`, `core`, `reprocessing`, `v1` liên quan; coverage `diff-cover --compare-branch=github/develop --fail-under=70`; `pre-commit run --files <file đổi>`; `scripts/check_architecture.py`. PR vào `main` kèm bảng AC → test.

## Gap / ngoài phạm vi

- G1: thay dụng cụ từ kho dự phòng (UC-31 A1) và bộ đếm chu trình riêng từng dụng cụ — chưa có mô hình; cấp dụng cụ dùng proxy Q2.
- G2: bộ đếm chu trình tăng khi giải phóng (FR-M8-03 gốc, BRU-PAR-001) → FEAT-023.
- G3: email/SMS, thông báo realtime cho T4 khi duyệt, SCR-42 → FEAT-010.
- G4: widget dashboard SCR-32 → FEAT-006; báo cáo dự báo thay thế → FEAT-007 (dùng `v1.par.check`).
- G5: thanh lý bộ End of Life → Disposed (FEAT-016 G5).

## Phối hợp với các nhánh FEAT khác (người dùng đã duyệt)

- Thứ tự merge: FEAT-016/011/019/020, rồi 022, 026, **032 cuối**; rebase lên `develop` mới nhất và chạy lại test theo `--module` trước khi mở PR. Conflict ở `step_gate.py`, `test_step_gate.py`, `hooks.py`, `errors.py`, `architecture.md`, `rtm.md`, `par/`: giữ phần của cả hai bên (FEAT-026 thêm `par/stock.py`, hook `tracecore_issue_par_check`).
- **Duyệt tại T4 (WF-08):** dùng approver proof của FEAT-019 (`create_approver_proof(token, card_id, pin, role="TC R01")`, `consume_approver_proof(session, proof, role="TC R01")`), KHÔNG dùng `verify_card_pin` của FEAT-026. Làm sau khi 019 lên `develop`: thêm `TC R01` vào `APPROVER_ROLES`, `APPROVER_NOT_ALLOWED` cho role khác R02 (giữ `R02_CONFIRM_REQUIRED` cho R02). Hiện tại duyệt chỉ trên Desk (SCR-31) bằng PIN Employee của user đăng nhập (Q7).
- `end_of_life`/`reopen_after_override` đi qua `_save_lifecycle` (hook `tracecore_after_set_status` của 019 tự phát). Khi rebase: chặn Hết vòng đời cả `step_gate.receive` (T1) và thêm test.
