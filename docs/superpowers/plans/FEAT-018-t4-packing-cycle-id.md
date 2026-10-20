# FEAT-018 T4 Đóng gói → Cycle ID GS1 + in nhãn theo phương pháp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KTV khu sạch (R04) quét Set ID tại T4, xác nhận BOM có ảnh, xử lý nhắc bảo dưỡng, quét lô chỉ thị, chọn loại gói, bấm Xác nhận → hệ thống sinh **một** Cycle ID `CY-YYMMDD-NNNN` mang payload GS1 DataMatrix (01)(11)(17)(21), ghi cổng T4 Đạt cùng transaction, chọn Label Template + Printer theo phương pháp (hấp/plasma) và gửi nhãn qua Station Agent; không có máy in đúng loại thì giữ Cycle ID, Print Job Chờ.

**Architecture:** Lát cắt dọc đầu tiên (implementation-plan §5). Dịch vụ xuyên suốt ở `tracecore/core/` (`step_gate` mới, `gs1`, `print`, `code_registry`, `errors`, `extension`); nghiệp vụ đóng gói ở M2 `tracecore/reprocessing/packing.py`; M1 (BOM, bảo dưỡng) và M8 (cơ số, stub) góp dữ liệu và kiểm tra qua **hook tùy biến trong `hooks.py`** (ADR-001 "Link/hook", không import chéo); RPC mỏng `tracecore/v1/pack.py`; giao diện là phần T4 của Page `station` (file riêng nạp bằng `page_js`). T1–T3, cơ số cấp dụng cụ, lô chỉ thị, đăng nhập thẻ, sinh mã offline là **stub** theo §5.3.

**Tech Stack:** Frappe/ERPNext/HRMS v15 (đã pin ở `deploy/pins.env`), Python 3.11, MariaDB 10.6, `pylibdmtx`, Pillow, Station Agent Python stdlib, Playwright for Python.

**Spec:** `docs/implementation-plan.md` §3 (dòng FEAT-018), §5.1–§5.5 (luồng, AC-1..AC-16, stub, handoff); `docs/srs.md` FR-M2-07(.1–.12), FR-M2-08(.1–.8), FR-M2-25(.1–.2), FR-M2-00.1/.2, FR-M8-03.2, FR-M1-09(.1–.6), §3.1.11; `docs/use-cases.md` UC-08; `docs/architecture.md` §5.3.1, §5.3.3, §6.3, ADR-001/003/004/005/006; `docs/ux-foundations.md` A2 (SCR-08); `docs/design.md` §4.1–4.19, §5, §6; BA #08 DT-PACK, #16 WF-02 (9 trạng thái gói). Nền: `docs/superpowers/plans/FEAT-001-walking-skeleton.md`.

FR/BRU/AC đáp ứng: FR-M2-07, FR-M2-08, FR-M2-25 (partial: check T3, record T4), FR-M2-00.1/.2, FR-M8-03.2 (partial, cấp bộ), FR-M1-09.3–.6; BRU-ID-002, BRU-ID-004, BRU-ID-005, BRU-REP-009, BRU-REP-011, BRU-REP-013, BRU-REP-014, BRU-FLOW-002, BRU-FLOW-004, BRU-PAR-002, BRU-INV-001; AC-1..AC-15 (AC-16 ghi pending-environment nếu chưa có vật liệu nhãn D-03).

**Nhánh:** `feat/FEAT-018-t4-packing-cycle-id`, tách từ `feat/FEAT-001-walking-skeleton` (FEAT-001 chưa vào `main`). Làm trong `~/tracecore-dev/apps/tracecore` (WSL). PR mở vào `main` sau khi FEAT-001 merge; trước đó base = nhánh FEAT-001.

## Quyết định cần duyệt (chặn bắt đầu Task 1)

Plan viết theo cột "Đề xuất". Mục **[Chốt]** là chỗ tài liệu mâu thuẫn hoặc thiếu, cần chủ đầu tư/BA trả lời; mục **[Xác nhận]** là lựa chọn thiết kế trong phạm vi tài liệu, chỉ cần dev lead đồng ý. Đổi đề xuất nào thì sửa task ghi ở cột cuối trước khi làm.

| # | Loại | Câu hỏi | Đề xuất trong plan | Căn cứ | Task bị ảnh hưởng |
| :- | :- | :- | :- | :- | :- |
| D1 | [Chốt] | T4 có nút "Xác nhận tất cả thành phần" không? | **Có**: một chạm tick mọi dòng BOM (vẫn lưu từng dòng `Pack Instrument Confirmed`), nút tick từng dòng vẫn còn. Không có nút này thì đường chính = số dòng BOM + 1 chạm, trượt AC-15 (≤ 3 chạm) | FR-M2-07 "tick từng loại" ↔ design.md §4.11 có nút; ảnh #17 số 12 | 11, 12 |
| D2 | [Chốt] | Mã cuộn nhãn `CN-` do ai cấp, gắn với loại nhãn ở đâu? | Mã `CN-#####` nằm trong `Code Registry` (prefix `CN`, `ref_doctype = Item`, `ref_name` = Item nhãn `VT-NHAN-HAP/PLASMA`). FEAT-018 chỉ **đọc**; cấp và in mã cuộn là việc của FEAT-005. Devdata/test đăng ký trực tiếp | FR-M9-07 (cuộn nhãn có mã CN-), ADR-006, AC-9; không DocType nào giữ cuộn | 5, 9, 11 |
| D3 | [Chốt] | Từ chối nghiệp vụ trả HTTP nào? | **409** + body `{"ok": false, "error": {code, title, reason, action, items?, redo_step?}}` cho mọi RPC trạm, kể cả `set_unit.get` của FEAT-001 (sửa helper `rejection`). Trả lời lặp lại theo cùng key cũng 409 | implementation-plan §5.5 (409), ADR-003 (outbox phân biệt 4xx); BA #11 §5 ghi 422 | 9 |
| D4 | [Chốt] | Hạn dùng khi loại bộ có hạn lưu riêng | `expiry = ngày đóng gói + min(hạn lưu loại gói, hạn lưu loại bộ nếu > 0)`; loại gói chưa có hạn lưu → không chọn được | srs §3.1.11 mục 5 còn mở; FR-M1-03 cho loại bộ ghi đè **ngắn hơn**; FR-M2-07.7 | 6 |
| D5 | [Chốt] | Ngưỡng chặn bảo dưỡng | Đến hạn khi `cycles_since ≥ interval`; chặn khi `cycles_since > 1,2 × interval` mà không chọn Đã bảo dưỡng, **hoặc** đã hoãn 3 lần mà còn đến hạn (lần hoãn thứ 4 bị từ chối). Mỗi nhắc đến hạn phải được xử lý (Đã bảo dưỡng/Hoãn) trước khi sinh. Người đóng gói tự hoãn kèm lý do; PIN R02 thêm khi có FEAT-003 | srs §3.1.11 mục 1 (gộp OR, chờ BA); FR-M1-09.3–.6; BRU-REP-014 "R02 hoãn tối đa 3" | 7 |
| D6 | [Chốt] | GTIN-14 của loại bộ cho AI (01) | Sinh khi tạo loại bộ, không sửa: `"0" + tiền tố GS1 + số thứ tự loại bộ (đệm 0 tới 12 − độ dài tiền tố) + check digit mod-10`, ghi `Code Registry` prefix `GTIN`. Dev/staging dùng tiền tố TEST `9520000` (OQ-05) | ADR-004 "GTIN-14 nội bộ"; mã loại bộ có chữ nên không đưa thẳng vào GTIN | 2, 3 |
| D7 | [Chốt] | Kích thước và ngôn ngữ nhãn mẫu | Mẫu 60 × 40 mm, 300 dpi, **ZPL** (TSPL để sau khi có máy in TSPL trong D-03); chữ tiếng Việt in **bỏ dấu** qua hàm `fold()` vì font ZPL `0` không có glyph tiếng Việt; có dòng tiếng Anh phụ. R10 sửa mẫu không cần code | ux-foundations §B gap 5 (kích thước chưa chốt); design.md §4.12; NFR-USAB-02 | 5 |
| D8 | [Xác nhận] | Người đóng gói khi chưa có đăng nhập thẻ (FEAT-003) | `Pack.packed_by_user` (Link User, user trạm đang đăng nhập) bắt buộc; `Pack.packed_by` (Link Employee) để trống, FEAT-003 điền | BA DT-PACK.packed_by → DT-EMP; stub §5.3 | 6, 8 |
| D9 | [Xác nhận] | Vị trí module và cách gọi chéo | `Step Gate Result`, `Printer`, `Label Template` ở module `TraceCore` (do `core.*` sở hữu, đúng tinh thần A-01); `Pack` (+ 2 child), `Assembly Record` (stub) ở `Reprocessing`; `Instrument`, `Set BOM Item`, `Instrument Maintenance` ở `Instrument`. M1/M8 góp vào M2 qua hook `tracecore_pack_context`, `tracecore_pack_prechecks`, `tracecore_pack_checks`, `tracecore_after_cycle_id` | ADR-001, architecture §5.2 A-01 | 3–8 |
| D10 | [Xác nhận] | Ô quét trên kiosk T4 | Một ô quét duy nhất ở đầu màn (luôn focus). Server phân loại bằng `core.gs1.parse_scan` qua RPC `pack.scan`: Set ID → mở bộ; Cycle ID → tra cứu (AC-14); `CN-` → đổi cuộn (AC-9); mã khác khi đang mở bộ → lô chỉ thị. Khối "Lô chỉ thị" chỉ hiển thị kết quả, không phải ô nhập thứ hai | CLAUDE.md "ô quét luôn trên cùng và có focus"; ADR-004 chỉ `core.gs1` phân tích mã; ux A2 "scan-box thứ hai" | 9, 11 |
| D11 | [Xác nhận] | Đường in an toàn | Kiosk gửi `{print_job, zpl, printer}` (tên Printer) tới agent `127.0.0.1:8765/print`; agent chỉ in tới máy in có trong cấu hình trạm kéo từ RPC mới `tracecore.v1.station.config` (FEAT-018 trả danh sách máy in; FEAT-002 bổ sung thiết bị ngoại vi khác) | ADR-006; implementation-plan §5.5 `POST /print {job, zpl, printer_ip}` | 5, 9, 10 |
| D12 | [Xác nhận] | Trạng thái gói và hủy Cycle ID tại T4 | `Pack.status` có đủ 9 trạng thái WF-02 (Packed, In Load, Quarantine, Released, In Sterile Stock, Issued, Used, Recalled, Void); FEAT-018 chỉ dùng Packed và Void. Pack là chứng từ submittable (`docstatus 1` ngay khi sinh), hủy bằng `status = Void` (không cancel, không xóa). Hủy tại T4 ghi cổng T4 Không đạt (`redo_count++`, Set Unit → Reprocess), vô hiệu mã trong Code Registry | BA #16 WF-02; FR-M2-25.2; FR-M2-08.6 | 4, 6, 8 |
| D13 | [Xác nhận] | Thời điểm đóng gói | `packed_at = client_ts` đổi sang giờ hệ thống (ADR-003 "thời điểm nghiệp vụ = client_ts"); ngày trong Cycle ID, (11) và hạn dùng lấy từ `packed_at`. Cửa sổ in lại 10 phút đo bằng giờ server | ADR-003 | 8 |
| D14 | [Xác nhận] | Ngoài phạm vi FEAT-018 | Sinh Cycle ID offline (FEAT-009); nhắc dán chỉ thị trong/ngoài cho gói đôi cấy ghép (UC-08 A2); trừ tiêu hao nhãn/bao gói/chỉ thị (FR-M2-07.3, FR-M2-08.3 → FEAT-042 nghe hook `tracecore_after_cycle_id`); chuyển Set Unit sang Hết vòng đời khi vượt cơ số (FEAT-032); đếm chu trình (FEAT-023) | implementation-plan §5.3 stub | — |

Câu hỏi D1–D7 cần trả lời trước Task 1; nếu chủ đầu tư chưa trả lời kịp, dev lead có thể cho chạy theo đề xuất và ghi "tạm" trong Revision History (Task 0).

## Global Constraints

- Kế thừa toàn bộ Global Constraints của FEAT-001 (phiên bản v15, không import chéo M1–M10, chỉ `core.step_gate` đổi trạng thái Set Unit, Audit Log append-only, RPC `tracecore.v1.<domain>.<action>`, `@idempotent` + `X-Idempotency-Key` + `client_ts` có offset, mã GS1 sinh ở server, chuỗi qua `_()`/`__()`, token `--tc-*`, lỗi chặn `alert-error` inline, TDD + `@bru`, coverage changed-code ≥ 70 %).
- Trường vòng đời Set Unit (`status`, `cycles_used`, `current_station`, `active_cycle_id`, **`current_cycle_no` mới**) chỉ đổi qua `tracecore.core.step_gate` (cờ `flags.tc_step_gate`).
- Module nghiệp vụ gọi nhau qua hook (D9): M2 gọi `tracecore.core.extension.run("<hook>", ctx)`; M1/M8 khai báo hàm trong `hooks.py`. Không `from tracecore.instrument …` trong `tracecore/reprocessing/…` và ngược lại (lint R1).
- Mã: Cycle ID `CY-YYMMDD-NNNN` (series key `CY-YYMMDD-`, đếm theo ngày `packed_at`), ghi `Code Registry` prefix `CY` ref `Pack`; GTIN prefix `GTIN` ref `Instrument Set Type`; cuộn `CN-#####` prefix `CN` ref `Item` (D2); Assembly Record `AS-.YYYY.-.#####`.
- Payload Cycle ID: `GS + "01" + gtin14 + "11" + YYMMDD + "17" + YYMMDD + "21" + cycle_id` (GS = `\x1d`, không GS sau (21) vì là AI cuối); chuỗi người đọc `(01)…(11)…(17)…(21)…`.
- Mã từ chối (`error.code`): `STATION_WRONG_STEP`, `SCAN_INVALID`, `SET_NOT_FOUND`, `STATUS_INVALID_FOR_STATION`, `ACTIVE_CYCLE_EXISTS`, `GATE_PREV_NOT_PASSED`, `PAR_EXCEEDED`, `MAINT_ACTION_REQUIRED`, `MAINT_OVERDUE`, `MAINT_OIL_LOT_REQUIRED`, `BOM_INCOMPLETE`, `CI_LOT_INVALID`, `CI_LOT_EXPIRED`, `PACK_TYPE_INVALID`, `REASON_REQUIRED`, `REPRINT_WINDOW_EXPIRED`, `PACK_NOT_FOUND`, `PACK_NOT_VOIDABLE`, `ROLL_UNKNOWN`, `ROLL_PRINTER_AMBIGUOUS`. `NO_PRINTER_FOR_METHOD` là **cảnh báo** đi kèm kết quả thành công (Cycle ID vẫn giữ).
- Thứ tự kiểm khi sinh (trả lỗi đầu tiên gặp): trạm đúng T4 → mã quét → trạng thái Set Unit → Cycle ID hiệu lực → cổng T3 → cơ số (precheck) → bảo dưỡng → BOM → lô chỉ thị → loại gói.
- Item ERPNext mở rộng bằng Custom Field (fixtures, tên `Item-tc_*`): `tc_item_group_cssd` (Select `Packaging/Chemical Indicator/Label/Lubricant`), `tc_compatible_method` (Select `Steam/Plasma`), `tc_ci_class` (Select `1/2/4/5/6`), `tc_shelf_life_days` (Int). Lô = ERPNext `Batch`.
- Test module có Link tới DocType ERPNext/HRMS khai báo `test_ignore` (`Item`, `Batch`, `Department`, `User`, `Employee` tùy module) để site CI chưa chạy Setup Wizard không lỗi (xem commit `20eff59`); factory tự tạo `Item Group` "All Item Groups" và UOM "Nos" nếu thiếu.
- Mỗi task thêm bản dịch `translations/vi.csv` cho mọi chuỗi, nhãn trường, option Select mới; `test_vi_translations_cover_source_strings` xanh sau mỗi task.
- Nhãn in: ZPL bắt đầu `^XA`, kết thúc `^XZ`, `^CI28`; DataMatrix bằng `gs1.zpl_datamatrix`; giá trị chữ đưa vào mẫu đã bỏ `^` và `~`.
- Hiệu năng: `pack.generate_cycle_id` ≤ 1 s P95 trên bench dev với 50 bộ seed (AC-15).
- Lệnh bench gọi từ Windows: `wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && …"`. Test: `bench --site test_site run-tests --module <module>`; sau đổi DocType/fixture: `bench --site test_site migrate` (và `tracecore-dev.local` khi cần thử tay).

## Review Focus

1. Hai lần sinh cho cùng Set ID với **hai key khác nhau** (hai kiosk, hoặc tải lại trang rồi bấm lại) → lần sau trả `ACTIVE_CYCLE_EXISTS` nêu Cycle ID đầu, chỉ có 1 Pack (khóa `FOR UPDATE` trên Set Unit). Test ở Task 8.
2. Lô chỉ thị quét có tiền tố AIM (`]C1`), chữ thường, `\r\n`/Tab cuối → vẫn ra đúng Batch. Test ở Task 6.
3. Đóng gói lúc 00:30 giờ Việt Nam (ngày UTC còn là hôm trước) → Cycle ID, (11) và hạn dùng theo ngày giờ hệ thống, không theo UTC. Test ở Task 8.
4. Tên bộ/khoa có dấu tiếng Việt hoặc ký tự điều khiển ZPL (`^`, `~`) → nhãn không bị chèn lệnh ZPL, chữ được bỏ dấu, DataMatrix không đổi. Test ở Task 5.
5. In lại đúng biên 10 phút (600 s được, 601 s bị từ chối) và in lại không có lý do → từ chối. Test ở Task 8.

---

### Task 0: Ghi quyết định đã duyệt vào tài liệu

**Files:**
- Modify: `docs/architecture.md` (Revision History + ghi chú A-02 ở §5.3.1 nhóm M2/M6/M9), `docs/srs.md` (§3.1.11 mục 1 và 5: cột "Cách xử lý"), `docs/implementation-plan.md` (§5.5: tên RPC `pack.scan` thay `get_context`/`lookup`, `station.config`)

- [ ] **Step 1:** Ghi Amendment A-02 (ngày duyệt, người duyệt) tóm tắt D1–D13 đã chốt: Custom Field Item `tc_ci_class`, `tc_shelf_life_days`; `Pack.packed_by_user`; `Set Unit.current_cycle_no`; module của Step Gate Result/Printer/Label Template; 4 hook tùy biến; mã HTTP 409; công thức hạn dùng; ngưỡng bảo dưỡng; GTIN-14; nhãn mẫu 60×40 ZPL. Mục nào duyệt "tạm" ghi rõ "tạm".
- [ ] **Step 2:** `pre-commit run --files docs/architecture.md docs/srs.md docs/implementation-plan.md` sạch.
- [ ] **Step 3:** Commit `docs: amendment A-02 quyết định FEAT-018`.

### Task 1: Custom Field cho Item, factory Item/Batch

**Files:**
- Create: `tracecore/fixtures/custom_field.json`, `tracecore/tests/test_item_fields.py`
- Modify: `tracecore/hooks.py` (fixtures thêm `{"dt": "Custom Field", "filters": [["name", "like", "Item-tc_%"]]}`), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Produces: `factories.ensure_item_masters() -> None`; `factories.make_item(item_code: str, group: str, method: str | None = None, ci_class: str | None = None, shelf_life_days: int | None = None, has_batch_no: int = 0) -> Document`; `factories.make_batch(item_code: str, batch_id: str, expiry_date=None) -> Document` (bật `has_batch_no` của Item nếu chưa).

- [ ] **Step 1:** Test (`test_ignore = ["Item", "Batch"]`): `test_item_custom_fields_installed` (4 trường có trong `frappe.get_meta("Item")`; options `tc_item_group_cssd` == `"\nPackaging\nChemical Indicator\nLabel\nLubricant"`; `tc_compatible_method` == `"\nSteam\nPlasma"`; `tc_ci_class` == `"\n1\n2\n4\n5\n6"`; `tc_shelf_life_days` fieldtype `Int`, `depends_on` = `eval:doc.tc_item_group_cssd=='Packaging'`), `test_factories_create_items_and_batches` (`make_item("VT-NHAN-HAP", "Label", method="Steam").tc_compatible_method == "Steam"`; `make_batch("CI5-STEAM", "LOT-A", expiry_date=add_days(today(), 30)).item == "CI5-STEAM"`).
- [ ] **Step 2:** `bench --site test_site run-tests --module tracecore.tests.test_item_fields` → FAIL.
- [ ] **Step 3:** Viết fixture 4 Custom Field (insert_after nhóm "item_group"), factory, bản dịch nhãn/option; `bench --site test_site migrate`.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat(inventory): custom field Item cho nhóm CSSD, chỉ thị, nhãn, hạn lưu loại gói`.

### Task 2: `core.gs1` — GTIN-14, payload Cycle ID, `parse_scan` cho gói

**Files:**
- Modify: `tracecore/core/gs1.py`, `tracecore/core/tests/test_gs1.py`

**Interfaces:**
- Produces: `gtin_check_digit(body13: str) -> str`; `make_gtin14(prefix: str, item_ref: int) -> str`; `make_cycle_payload(gtin: str, packed: date, expiry: date, cycle_id: str) -> str`; `cycle_hri(gtin: str, packed: date, expiry: date, cycle_id: str) -> str`; `clean_scan(raw: str) -> str` (đổi tên công khai của `_clean`); `parse_scan` trả thêm cho gói dạng GS1: `{"type": "pack", "id": cycle_id, "raw", "gtin", "packed": date, "expiry": date}`; Cycle ID trần `CY-…` → `{"type": "pack", "id", "raw"}`.

- [ ] **Step 1:** Test: `test_gtin_check_digit` (`gtin_check_digit("0001234560001") == "2"`), `test_make_gtin14` (`make_gtin14("9520000", 1) == "09520000000011"`; `make_gtin14("9520000", 100000)` → `GS1Error` code `GS1_ITEM_REF`; prefix `"95A"` → `GS1_PREFIX`), `test_make_cycle_payload` (`make_cycle_payload("09520000000011", date(2026, 10, 20), date(2026, 11, 19), "CY-261020-0001") == "\x1d0109520000000011112610201726111921CY-261020-0001"`; `cycle_hri(...) == "(01)09520000000011(11)261020(17)261119(21)CY-261020-0001"`), `test_cycle_payload_rejects` (GTIN sai check digit → `GS1_GTIN`; cycle_id có khoảng trắng hoặc dài > 20 → `GS1_SERIAL`; expiry < packed → `GS1_DATES`), `test_parse_scan_pack_variants` (`"]d2\x1d0109520000000011112610201726111921CY-261020-0001\r\n"`, chuỗi HRI, `"0109520000000011112610201726111921CY-261020-0001"` → `type == "pack"`, `id == "CY-261020-0001"`, `gtin == "09520000000011"`, `packed == date(2026, 10, 20)`, `expiry == date(2026, 11, 19)`; `"CY-261020-0001"` và `"CY-261020-T04-0001"` → pack), `test_parse_scan_pack_bad_check_digit` (`"(01)09520000000012(11)…"` → unknown), `test_zpl_datamatrix_cycle` (`zpl_datamatrix(payload, 0, 0)` chứa `^FD_10109520000000011112610201726111921CY-261020-0001^FS`). Các test GIAI cũ vẫn xanh.
- [ ] **Step 2:** `--module tracecore.core.tests.test_gs1` → FAIL.
- [ ] **Step 3:** Hiện thực. Check digit GTIN-14: trọng số 3,1,3,… từ trái qua 13 chữ số, `(10 − tổng mod 10) mod 10`. `parse_scan` thử dạng GS1 gói (regex cho dạng ngoặc và dạng liền, kiểm check digit + ngày hợp lệ) **trước** nhánh GIAI.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat(core): GTIN-14 loại bộ, payload Cycle ID (01)(11)(17)(21), parse_scan gói`.

### Task 3: DocType M1 cho đóng gói — Set Type mở rộng, Instrument, Set BOM Item, Instrument Maintenance

**Files:**
- Create: `tracecore/instrument/doctype/{instrument,set_bom_item,instrument_maintenance}/` (json, py, test), `tracecore/instrument/bom.py`, `tracecore/patches/v0_1/__init__.py`, `tracecore/patches/v0_1/backfill_set_type_gtin.py`
- Modify: `tracecore/instrument/doctype/instrument_set_type/{instrument_set_type.json,.py,test_instrument_set_type.py}`, `tracecore/instrument/doctype/set_unit/{set_unit.json,set_unit.py}`, `tracecore/core/code_registry.py`, `tracecore/patches.txt`, `tracecore/hooks.py` (doc_events audit cho 3 DocType mới), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: `gs1.make_gtin14` (Task 2), `factories.make_item` (Task 1).
- Produces:
  - Instrument Set Type thêm: `gtin` (Data, read-only, unique), `department` (Link Department), `default_pack_type` (Link Item), `shelf_life_days` (Int, ≥ 0, 0 = không ghi đè), `tray_image` (Attach Image), `current_bom_version` (Int, mặc định 1).
  - Instrument (`autoname: field:instrument_code`, mã viết hoa, chỉ `[A-Z0-9-]`): `instrument_name`, `image` (Attach Image), `maint_interval_cycles` (Int ≥ 0, trống/0 = không nhắc), `maint_type` (Select `Lubrication/Blade Check/Screw Tightening/Battery Replacement`), `max_cycles` (Int).
  - Set BOM Item (`autoname: hash`, index `set_type`+`bom_version`): `set_type`, `bom_version`, `instrument`, `qty` (≥ 1), `position`, `effective_from` (Date).
  - Instrument Maintenance (`autoname: format:{set_unit}-{instrument}`): `set_unit`, `instrument`, `cycles_since_maint`, `deferred_count`, `last_maint_on`, `last_maint_by` (Link User), `last_oil_batch` (Link Batch), `last_defer_on`, `last_defer_reason`.
  - Set Unit thêm `current_cycle_no` (Int, read-only, thêm vào `LIFECYCLE_DEFAULTS` = 0).
  - `code_registry.next_set_type_gtin() -> str` (series `GTIN-<prefix>`, độ rộng `12 − len(prefix)`, ghi sổ prefix `GTIN`).
  - `tracecore.instrument.bom.lines(set_type: str, version: int) -> list[dict]` (`instrument, instrument_name, image, qty, position`, sắp theo `position`).
  - Factory: `make_instrument(code, name=None, interval=None, maint_type=None, image=None)`, `make_bom(set_type, lines: list[tuple[str, int]], version=1)`, `make_maintenance(set_unit, instrument, cycles_since=0, deferred_count=0)`; `make_set_type(..., default_pack_type=None, shelf_life_days=0, tray_image=None)`.

- [ ] **Step 1:** Test (`test_ignore = ["Department", "Item", "Batch", "User"]` ở module cần): `test_gtin_issued_on_insert` (14 chữ số, bắt đầu `"0" + company_prefix()`, `gtin_check_digit(gtin[:13]) == gtin[13]`, `Code Registry` có `gtin` với `ref_doctype == "Instrument Set Type"`), `test_gtin_unique_per_type`, `test_gtin_immutable` (sửa `gtin` → `ValidationError`), `test_shelf_life_override_not_negative`, `test_instrument_code_normalized` (`"kc-01"` → name `"KC-01"`; `"KC 01"` → lỗi), `test_bom_lines_for_version` (2 phiên bản, `lines(st, 2)` chỉ trả dòng v2 theo `position`), `test_one_maintenance_row_per_set_unit_instrument` (trùng → `DuplicateEntryError`), `test_current_cycle_no_guarded` (sửa tay → `ValidationError`), `test_backfill_set_type_gtin` (đặt `gtin` NULL bằng `frappe.db.set_value` rồi `execute()` → có GTIN hợp lệ).
- [ ] **Step 2:** Chạy các module test → FAIL.
- [ ] **Step 3:** Tạo/sửa DocType JSON + controller; `before_insert` của Set Type gọi `next_set_type_gtin()`; patch ở `[post_model_sync]`; `bench --site test_site migrate`.
- [ ] **Step 4:** PASS (cả test Set Unit/Set Type của FEAT-001). **Step 5:** Commit `feat(instrument): GTIN loại bộ, Instrument, Set BOM Item, Instrument Maintenance, current_cycle_no`.

### Task 4: `core.step_gate`, `Step Gate Result`, `Assembly Record` (stub T3)

**Files:**
- Create: `tracecore/core/errors.py`, `tracecore/core/step_gate.py`, `tracecore/core/tests/test_step_gate.py`, `tracecore/tracecore/doctype/step_gate_result/`, `tracecore/reprocessing/doctype/assembly_record/` (json, py, test)
- Modify: `tracecore/hooks.py` (doc_events audit cho Step Gate Result, Assembly Record), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Produces:
  - `core.errors.Block` (dataclass: `code, title, reason, action, items: list | None = None, redo_step: str | None = None`; `as_dict() -> dict`), `core.errors.BlockedError(frappe.ValidationError)` (`http_status_code = 409`, thuộc tính `block`).
  - `step_gate.STEPS = ("T1", "T2", "T3", "T4", "T5")`; `STATION_STATUSES = {"T4": ("Processing", "Reprocess")}` (bước khác thêm ở FEAT của bước đó).
  - `start_cycle(set_unit: str) -> int` (stub cho T1: `current_cycle_no + 1`, status `Processing`).
  - `check(set_unit: str, step: str) -> Block | None` (`STATUS_INVALID_FOR_STATION` hoặc `GATE_PREV_NOT_PASSED` với `redo_step` = bước trước).
  - `record(set_unit: str, step: str, result: str, ref_doctype=None, ref_name=None, station=None) -> str` (upsert theo name `{set_unit}-C{cycle_no}-{step}`; `Fail` → `redo_count++`, bước sau về `Pending`, status `Reprocess`; `Pass` khi đang `Reprocess` → `Processing`; đủ 5 bước Pass → `Sterile`).
  - `gates(set_unit: str) -> list[dict]` (`[{"step", "result", "redo_count"}]` đủ T1..T5, thiếu = `Pending`).
  - `bind_cycle(set_unit: str, cycle_id: str, station: str | None) -> None`; `release_cycle(set_unit: str) -> None`.
  - Step Gate Result (module TraceCore): `set_unit, cycle_no, step` (Select T1..T5), `result` (Select `Pending/Pass/Fail`), `redo_count`, `ref_doctype` (Link DocType), `ref_name` (Dynamic Link), `station`, `recorded_by` (Link User), `recorded_at`. Không ai có quyền write/delete ngoài System Manager đọc.
  - Assembly Record (Reprocessing, submittable, `AS-.YYYY.-.#####`): `set_unit`, `cycle_no` (read-only, lấy từ Set Unit), `result` (Select `Pass/Fail`), `notes`; `on_submit` → `step_gate.record(set_unit, "T3", result, "Assembly Record", name)`.
  - Factory: `make_cycle(set_unit, passed=("T1", "T2", "T3")) -> int` (start_cycle + record từng bước Pass; T3 qua Assembly Record submit).

- [ ] **Step 1:** Test: `@bru("BRU-FLOW-004") test_check_requires_previous_step_pass` (sau `start_cycle`, `check(su, "T4").code == "GATE_PREV_NOT_PASSED"`, `.redo_step == "T3"`; record T3 Pass → `None`), `@bru("BRU-FLOW-002") test_check_rejects_status_invalid_for_station` (Set Unit `New` → `STATUS_INVALID_FOR_STATION`), `test_record_upserts_one_row` (2 lần Pass T4 → 1 bản ghi name `f"{su}-C1-T4"`), `@bru("BRU-FLOW-004") test_fail_counts_redo_and_resets_later_steps` (T3 Pass, T4 Pass, T5 Pass rồi T4 Fail → T4 `redo_count == 1`, T5 `Pending`, Set Unit `Reprocess`; T4 Pass lại → `Processing`), `test_all_five_pass_sets_sterile`, `test_bind_and_release_cycle`, `test_start_cycle_increments`, `test_assembly_submit_records_t3` (submit Pass → `gates(su)[2] == {"step": "T3", "result": "Pass", …}`; name bắt đầu `AS-`), `test_block_as_dict` (`Block("X", "t", "r", "a").as_dict() == {"code": "X", "title": "t", "reason": "r", "action": "a"}` — bỏ khóa None).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; Set Unit đổi bằng `doc.flags.tc_step_gate = True; doc.save(ignore_permissions=True)` trong `step_gate` (audit Update tự ghi); `bench --site test_site migrate`.
- [ ] **Step 4:** PASS; `python3 scripts/check_architecture.py` sạch. **Step 5:** Commit `feat(core): step_gate engine, Step Gate Result, Assembly Record stub cho T3`.

### Task 5: `core.print` — Printer, Label Template, chọn máy in theo phương pháp, render, đổi cuộn

**Files:**
- Create: `tracecore/tracecore/doctype/{printer,label_template}/` (json, py, test), `tracecore/setup/label_templates.py`, `tracecore/setup/label_templates/pack_steam.zpl.jinja`, `tracecore/setup/label_templates/pack_plasma.zpl.jinja`, `tracecore/patches/v0_1/create_sample_label_templates.py`
- Modify: `tracecore/core/print.py`, `tracecore/core/tests/test_print.py`, `tracecore/core/code_registry.py`, `tracecore/tracecore/doctype/print_job/print_job.json`, `tracecore/setup/install.py` (`after_install` gọi `ensure_sample_templates`), `tracecore/patches.txt`, `tracecore/hooks.py` (doc_events audit cho Printer, Label Template), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: `gs1.zpl_datamatrix`, `Block/BlockedError` (Task 4), `make_item` (Task 1).
- Produces:
  - Printer (TraceCore, `autoname: PRN-.###`, title `printer_name`): `printer_name`, `station` (Link Zone Station, phải là trạm), `host` (trống = agent ghi file), `port` (9100), `language` (Select `ZPL`), `dpi` (300), `label_type_loaded` (Link Item nhóm `Label` có `tc_compatible_method`), `roll_code` (read-only), `roll_loaded_on`, `roll_loaded_by`, `is_active`.
  - Label Template (TraceCore, `autoname: field:template_name`): `label_object` (Select `Pack`), `method` (Select `Steam/Plasma`), `language` (`ZPL`), `width_mm`, `height_mm`, `dpi`, `body` (Code, Jinja), `is_active`; chỉ một mẫu active cho mỗi (`label_object`, `method`).
  - Print Job: `printer` đổi sang Link Printer; `status` thêm `Waiting`; thêm `ref_doctype`/`ref_name` (Dynamic Link).
  - `tracecore.setup.label_templates.ensure_sample_templates() -> list[str]`: tạo **nếu chưa có** 2 mẫu `Pack label - Steam`, `Pack label - Plasma` (60×40 mm, 300 dpi) từ file `.zpl.jinja`; không ghi đè mẫu R10 đã sửa (không dùng fixtures vì `migrate` sẽ ghi đè). Gọi từ `after_install` và patch (site đã cài). Mẫu nhận ngữ cảnh `doc` với khóa: `set_id, cycle_id, set_name, dept, packer, packed_at` (dd/mm/yyyy HH:mm), `expiry` (dd/mm/yyyy), `method_label, pack_type, ci_lot, bom_version, is_loaner, warning, payload, hri`; dòng cuối "Nhan hap hoi nuoc 134C / Steam label" hoặc "Nhan plasma H2O2 / Plasma label"; dòng hạn "HAN SU DUNG / EXP: {expiry}".
  - `print.fold(text) -> str` (NFKD bỏ dấu, `đ/Đ` → `d/D`, bỏ ký tự ngoài ASCII in được).
  - `print.render(template: str, doc: dict) -> str` (`frappe.render_template` với ngữ cảnh `doc` đã bỏ `^`/`~` ở mọi chuỗi, hàm `datamatrix(payload, x, y, module=6)`, `fold`, `dpi`, `width_dots`, `height_dots`; kết quả phải `^XA…^XZ`, sai → `frappe.ValidationError`).
  - `print.pack_template(method: str) -> str | None`.
  - `print.select_printer(station: str, method: str) -> dict | None` (`{"name", "host", "port", "label_type"}`; máy in active của trạm có `label_type_loaded` cùng `tc_compatible_method`; nhiều máy → theo `name`).
  - `print.create_job(station, zpl, data=None, template="test-label", printer=None, status="Queued", ref_doctype=None, ref_name=None, reprint_reason=None) -> str` (giữ tương thích lời gọi cũ).
  - `print.set_roll(printer: str, roll_code: str) -> dict` (`{"printer", "label_type", "method", "released_jobs": [{"print_job", "zpl", "printer"}]}`; mã không có trong sổ hoặc không phải Item nhãn → `BlockedError(ROLL_UNKNOWN)`; Print Job `Waiting` của cùng trạm có `data.method` khớp → `Queued` + gán máy in).
  - `print.station_printers(station: str) -> list[dict]` (`name, host, port, label_type, method`, chỉ máy active).
  - `code_registry.roll_label_item(roll_code: str) -> str | None`.
  - Factory: `make_label_items()` (tạo `VT-NHAN-HAP`/Steam, `VT-NHAN-PLASMA`/Plasma), `make_printer(station, label_item, host="", name="Test printer") -> str`, `make_roll(label_item) -> str` (đăng ký `CN-#####` qua `getseries("CN-", 5)` + `register`).

- [ ] **Step 1:** Test (`test_ignore = ["Item"]`): `test_printer_requires_station_not_zone` (`station="ZONE-CLEAN"` → lỗi), `test_label_type_must_be_label_item` (Item nhóm `Packaging` → lỗi), `test_one_active_template_per_object_method`, `test_sample_templates_installed`, `@bru("BRU-REP-011") test_select_printer_by_method` (TR-004 có P1 nhãn hấp, P2 nhãn plasma → `select_printer("TR-004", "Plasma")["name"] == P2`; P2 inactive → `None`), `test_render_pack_label` (bắt đầu `^XA`, kết thúc `^XZ`, chứa `^BXN`, `_10109520000000011`, dòng người đọc `(01)09520000000011(11)261020(17)261119(21)CY-261020-0001`, `HAN SU DUNG / EXP: 19/11/2026`), `test_sample_templates_survive_reinstall` (sửa `body` mẫu Steam rồi gọi lại `ensure_sample_templates()` → `body` giữ bản đã sửa), `test_render_sanitizes_zpl_and_folds_vietnamese` (`set_name = "Bộ mổ ^FO tim ~JA"` → chứa `Bo mo FO tim JA`; số lần xuất hiện `^FO` bằng khi `set_name = "Bo mo tim"`), `test_fold` (`fold("Đường hấp 134°C") == "Duong hap 134C"`), `@bru("BRU-REP-011") test_set_roll_updates_label_type_and_releases_waiting_jobs` (job `Waiting` trạm TR-004 `data={"method": "Plasma"}`; `set_roll(P1, roll_plasma)` → `label_type_loaded == "VT-NHAN-PLASMA"`, `roll_code == roll_plasma`, job trong `released_jobs`, job `Queued` + `printer == P1`, Audit Log `Update` của Printer có old/new `label_type_loaded`), `test_set_roll_unknown_code` (`"CN-99999"` và mã CN của Item không phải nhãn → `ROLL_UNKNOWN`), `test_station_printers_for_agent`, `test_create_job_backward_compatible` (lời gọi kiểu FEAT-001 vẫn tạo job `Queued`).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực + 2 file mẫu nhãn + patch; `bench --site test_site migrate`. **Step 4:** PASS (kể cả test print/agent của FEAT-001). **Step 5:** Commit `feat(core): Printer, Label Template, chọn máy in theo loại nhãn, render ZPL, đổi cuộn`.

### Task 6: Pack DocType và quy tắc đóng gói (hạn dùng, lô chỉ thị, BOM)

**Files:**
- Create: `tracecore/reprocessing/doctype/{pack,pack_instrument_confirmed,pack_maintenance_done}/`, `tracecore/core/extension.py`, `tracecore/core/tests/test_extension.py`, `tracecore/reprocessing/packing.py` (phần quy tắc), `tracecore/reprocessing/tests/__init__.py`, `tracecore/reprocessing/tests/test_packing_rules.py`
- Modify: `tracecore/hooks.py` (doc_events audit cho Pack), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: `make_item/make_batch` (Task 1), `bom.lines`, Set Type mở rộng (Task 3), `Block/BlockedError` (Task 4), `gs1.clean_scan` (Task 2).
- Produces:
  - Pack (Reprocessing, submittable, name = Cycle ID gán khi sinh): `set_unit`, `set_type`, `set_name`, `department`, `cycle_no`, `assembly` (Link Assembly Record), `method` (Select `Steam/Plasma`), `pack_type` (Link Item), `bom_version`, `packed_by_user` (Link User, reqd), `packed_by` (Link Employee), `packed_at`, `client_ts`, `expiry` (Date), `ci_batch` (Link Batch), `station`, `barcode_payload`, `label_type` (Link Item), `status` (Select 9 trạng thái D12, allow_on_submit), `void_reason` (Select `Used/Expired/Torn/Load Failed/Returned Unused/Label Damaged`, allow_on_submit), `void_note`, `label_print_count` (allow_on_submit), `instruments_confirmed` (Table Pack Instrument Confirmed: `instrument`, `qty`), `maint_done` (Table Pack Maintenance Done: `instrument`, `action` Select `Done/Deferred`, `oil_batch`, `reason`, `cycles_at_action`). Quyền: System Manager R/W/C/S, TC R04 R/C/S, TC R01/R02/R05 R; không ai delete.
  - `extension.run(hook: str, *args, **kwargs) -> list` (gọi lần lượt mọi đường dẫn trong `frappe.get_hooks(hook)`, bỏ kết quả `None`).
  - `packing.compute_expiry(packed_on: date, pack_type: str, set_type: str) -> date` (D4; loại gói không phải `Packaging` hoặc hạn lưu ≤ 0 → `BlockedError(PACK_TYPE_INVALID)`).
  - `packing.pack_types(set_type: str) -> list[dict]` (`item, item_name, shelf_life_days`; mặc định của loại bộ đứng đầu; chỉ Item `Packaging` có hạn lưu > 0).
  - `packing.resolve_ci_batch(raw: str, method: str, on_date: date) -> dict` (`{"batch", "item", "expiry_date", "ci_class"}`; Batch không có/không phải chỉ thị/lớp ∉ {5, 6}/khác phương pháp → `CI_LOT_INVALID`; hết hạn trước `on_date` → `CI_LOT_EXPIRED`).
  - `packing.missing_lines(bom: list[dict], confirmed: list[str]) -> list[dict]`.
  - Factory: `make_ci_batch(method="Steam", ci_class="5", expiry_days=30) -> str`, `make_pack_type(name="Giay crepe", shelf_life_days=30) -> str`.

- [ ] **Step 1:** Test (`test_ignore = ["Item", "Batch", "Department", "User", "Employee"]`): `test_pack_status_options_wf02` (đúng 9 option theo thứ tự D12), `test_pack_cannot_be_deleted`, `test_run_collects_results_in_hook_order` (patch `frappe.get_hooks` trả 2 hàm test; kết quả theo thứ tự, bỏ None), `@bru("BRU-REP-009") test_compute_expiry_uses_pack_type_days` (30 ngày, 20/10/2026 → 19/11/2026), `@bru("BRU-REP-009") test_compute_expiry_set_type_override_shorter` (loại bộ 14 → 03/11/2026; loại bộ 60 → 19/11/2026), `@bru("BRU-REP-009") test_pack_type_without_shelf_life_rejected`, `test_pack_types_lists_only_packaging_with_shelf_life`, `@bru("BRU-REP-013") test_resolve_ci_batch_cleans_scanner_noise` (`" ]C1lot-a\r\n"` → `batch == "LOT-A"`), `@bru("BRU-REP-013") test_resolve_ci_batch_rejects_wrong_method_class_or_item` (CI plasma cho bộ hấp, lớp 4, Batch của Item bao gói, lô không tồn tại → `CI_LOT_INVALID`), `@bru("BRU-INV-001") test_resolve_ci_batch_rejects_expired` (hết hạn hôm qua → `CI_LOT_EXPIRED`), `@bru("BRU-REP-013") test_missing_lines` (BOM `[KC-01×2, KC-02×1]`, confirmed `["KC-01"]` → chỉ KC-02).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; `bench --site test_site migrate`. **Step 4:** PASS. **Step 5:** Commit `feat(reprocessing): Pack, quy tắc hạn dùng, lô chỉ thị, BOM; core.extension`.

### Task 7: Hook M1 (BOM, bảo dưỡng) và M8 (cơ số stub)

**Files:**
- Create: `tracecore/instrument/maintenance.py`, `tracecore/instrument/tests/__init__.py`, `tracecore/instrument/tests/test_maintenance.py`, `tracecore/par/check.py`, `tracecore/par/tests/__init__.py`, `tracecore/par/tests/test_check.py`
- Modify: `tracecore/instrument/bom.py`, `tracecore/hooks.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: ngữ cảnh `ctx` do M2 dựng (Task 8): `{"set_unit": {name, set_type, status, cycles_used, max_cycles, active_cycle_id, current_cycle_no, is_loaner}, "set_type": {name, set_type_name, method, gtin, department, default_pack_type, shelf_life_days, tray_image, current_bom_version}, "station": str, "maint_actions": [{"instrument", "action": "Done" | "Deferred", "oil_batch"?, "reason"?}]}`.
- Produces (khai báo trong `hooks.py`):
  - `tracecore_pack_context = ["tracecore.instrument.bom.pack_context", "tracecore.instrument.maintenance.pack_context", "tracecore.par.check.pack_context"]` — mỗi hàm `(ctx) -> dict` được gộp vào ngữ cảnh: `{"bom", "bom_version", "tray_image"}`; `{"maintenance": [{"instrument", "instrument_name", "image", "maint_type", "interval", "cycles_since", "deferred_count", "state": "due" | "overdue", "can_defer"}]}`; `{"par": {"cycles_used", "max_cycles", "percent", "state": "ok" | "warn" | "blocked"}}` (warn ≥ 90 %).
  - `tracecore_pack_prechecks = ["tracecore.par.check.check_pack"]` — `(ctx) -> Block | None` (`PAR_EXCEEDED` khi `cycles_used ≥ max_cycles`; action nêu "Đề nghị ghi đè có từ FEAT-032").
  - `tracecore_pack_checks = ["tracecore.instrument.maintenance.check_pack"]` — `(ctx) -> Block | None` (`MAINT_ACTION_REQUIRED`, `MAINT_OVERDUE`, `REASON_REQUIRED`, `MAINT_OIL_LOT_REQUIRED` theo D5; `oil_batch` phải là Batch của Item `Lubricant`).
  - `tracecore_after_cycle_id = ["tracecore.instrument.maintenance.apply_pack"]` — `(pack_doc, ctx) -> None` (Done: `cycles_since_maint = 0`, `deferred_count = 0`, `last_maint_*`; Deferred: `deferred_count + 1`, `last_defer_*`; tạo dòng Instrument Maintenance nếu chưa có).

- [ ] **Step 1:** Test: `@bru("BRU-REP-014") test_context_lists_due_instruments_only` (interval 10: cycles 9 → không có; 10 → `due`; 13 → `overdue`; interval trống → không bao giờ, FR-M1-09.1), `@bru("BRU-REP-014") test_due_requires_action` (đến hạn, không action → `MAINT_ACTION_REQUIRED`), `@bru("BRU-REP-014") test_overdue_blocks_unless_done` (13/10 + Deferred → `MAINT_OVERDUE`; + Done có lô dầu → None), `@bru("BRU-REP-014") test_fourth_deferral_blocked` (deferred_count 3 → `MAINT_OVERDUE`, `can_defer` False; deferred_count 2 → None), `test_deferral_needs_reason_and_lubrication_needs_oil_lot`, `test_apply_done_resets_counter`, `test_apply_deferred_increments`, `@bru("BRU-PAR-002") test_par_blocks_at_max` (300/300 → `PAR_EXCEEDED`; 299/300 → None), `test_par_context_state` (270/300 warn, 100/300 ok, 300/300 blocked, `percent == 90` cho 270/300), `test_hooks_registered` (3 khóa hook chứa đúng đường dẫn).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS; `check_architecture.py` sạch (không import chéo). **Step 5:** Commit `feat(instrument,par): hook ngữ cảnh/kiểm tra đóng gói cho bảo dưỡng và cơ số`.

### Task 8: Sinh Cycle ID, in lại, hủy, tra cứu (`reprocessing.packing`)

**Files:**
- Modify: `tracecore/reprocessing/packing.py`, `tracecore/core/code_registry.py`, `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`
- Create: `tracecore/reprocessing/tests/test_packing.py`

**Interfaces:**
- Consumes: mọi Interfaces ở Task 2–7.
- Produces:
  - `code_registry.next_cycle_id(packed_at: datetime) -> str` (`getseries(f"CY-{packed_at:%y%m%d}-", 4)` → `CY-YYMMDD-NNNN`; ghi sổ prefix `CY` ref `Pack`).
  - `packing.get_context(set_id: str, station: str) -> dict` (raise `BlockedError` cho: trạm không phải T4, mã lạ/không phải bộ, không tìm thấy, `step_gate.check`, Cycle ID hiệu lực, prechecks). Trả `{"set": {set_id, set_type, set_name, method, is_loaner, status, cycles_used, max_cycles, department}, "gates", "bom", "bom_version", "tray_image", "maintenance", "par", "pack_types", "ci": {"method", "classes": ["5", "6"]}, "label_type", "printer"}`.
  - `packing.generate(set_id: str, station: str, confirmed: list[str], ci_batch: str, pack_type: str, maint_actions: list[dict], client_ts: datetime) -> dict` (`client_ts` là kết quả `parse_client_ts`: UTC, không múi giờ) — trong savepoint: khóa Set Unit `for_update`, chạy kiểm theo thứ tự Global Constraints, `packed_at` theo D13, `next_cycle_id`, insert + submit Pack, `step_gate.record(set_unit, "T4", "Pass", "Pack", cycle_id, station)`, `step_gate.bind_cycle`, `extension.run("tracecore_after_cycle_id", pack, ctx)`, render nhãn + Print Job (`Queued` nếu có máy in, ngược lại `Waiting` + cảnh báo `NO_PRINTER_FOR_METHOD`). Lỗi → rollback savepoint rồi raise lại. Trả `{"pack": {cycle_id, set_id, set_name, method, pack_type, pack_type_name, expiry, packed_at, packer, ci_batch, bom_version, label_type, is_loaner}, "hri", "datamatrix_png_b64", "print": {"print_job", "status", "printer", "zpl", "warning"}}`.
  - `packing.reprint(cycle_id: str, reason: str, station: str) -> dict` (≤ 600 s từ `packed_at` theo giờ server; lý do rỗng → `REASON_REQUIRED`; quá hạn → `REPRINT_WINDOW_EXPIRED` với action "Hủy Cycle ID và đóng gói lại"; `label_print_count + 1`; Print Job mới có `reprint_reason`; cùng dạng `print` như generate).
  - `packing.void(cycle_id: str, reason: str, station: str, note: str | None = None) -> dict` (chỉ `status == "Packed"`, ngược lại `PACK_NOT_VOIDABLE`; `status = Void`, `void_reason`; Code Registry của Cycle ID `Disabled`; `step_gate.record(set_unit, "T4", "Fail", "Pack", cycle_id, station)`; `release_cycle`).
  - `packing.lookup(raw: str) -> dict` (AC-14: `{cycle_id, set_id, set_name, packed_at, packer, expiry, method, pack_type, ci_batch, status, label_print_count}`; không phải mã gói → `SCAN_INVALID`; không có → `PACK_NOT_FOUND`).
  - Factory: `make_t4_ready_set(method="Steam", bom=(("KC-01", 2), ("KC-02", 1)), with_printer=True, **set_kwargs) -> frappe._dict` (`set_id, set_type, pack_type, ci_batch, printer, instruments`; Set Unit đã qua T1..T3 Pass trong chu trình 1).

- [ ] **Step 1:** Test (`test_ignore` như Task 6): `test_get_context_returns_bom_gates_par_pack_types` (T3 `Pass`, T4 `Pending`, `pack_types[0]["item"] == default_pack_type`, `printer` khớp), `@bru("BRU-FLOW-004") test_get_context_rejects_when_t3_not_passed`, `@bru("BRU-ID-002") test_generate_creates_pack_with_all_fields` (`cycle_id` khớp `^CY-\d{6}-\d{4}$`; Pack `docstatus == 1`, `status == "Packed"`, `bom_version == 1`, `packed_by_user == frappe.session.user`, `label_print_count == 1`, `expiry` đúng D4, `barcode_payload == make_cycle_payload(gtin, packed_at.date(), expiry, cycle_id)`; 2 dòng `instruments_confirmed`; Code Registry có `cycle_id`), `@bru("BRU-FLOW-004") test_generate_records_t4_pass_and_binds_cycle` (Step Gate Result T4 `Pass` `ref_name == cycle_id`; Set Unit `active_cycle_id == cycle_id`, `current_station == "TR-004"`), `@bru("BRU-ID-004") test_second_generate_rejected_with_existing_cycle` (key khác → `ACTIVE_CYCLE_EXISTS`, `reason` chứa Cycle ID đầu; số Pack của bộ == 1), `@bru("BRU-REP-013") test_incomplete_bom_rejected_and_rolled_back` (`BOM_INCOMPLETE`, `items[0]["instrument"] == "KC-02"`; không có Pack, Code Registry `CY` không tăng, không có Step Gate T4), `@bru("BRU-PAR-002") test_par_exceeded_blocks_generate`, `@bru("BRU-REP-014") test_generate_applies_maintenance_actions`, `@bru("BRU-REP-011") test_no_printer_for_method_keeps_cycle_id` (bộ plasma, trạm chỉ có máy nhãn hấp → `print.status == "Waiting"`, `print.warning.code == "NO_PRINTER_FOR_METHOD"`, `printer is None`, `zpl is None`; Pack tồn tại), `test_generate_queues_label_on_matching_printer` (`status == "Queued"`, `zpl` chứa `_101` + GTIN; Print Job `ref_name == cycle_id`), `test_generate_uses_local_date_from_client_ts` (client_ts `2026-10-21T00:30:00+07:00` → `cycle_id` bắt đầu `CY-261021-`, payload chứa `11261021`), `@bru("BRU-REP-009") test_shelf_life_change_applies_to_new_packs_only` (sinh gói A với hạn lưu 30, đổi `tc_shelf_life_days` của loại gói thành 20, void A rồi sinh gói B → `A.expiry` không đổi, `B.expiry` = ngày đóng gói + 20), `@bru("BRU-ID-005") test_reprint_window_boundary` (`packed_at` lùi 600 s → OK, `label_print_count == 2`, Print Job có `reprint_reason`; lùi 601 s → `REPRINT_WINDOW_EXPIRED`; lý do `"  "` → `REASON_REQUIRED`), `@bru("BRU-ID-005") test_void_then_regenerate` (void `Label Damaged` → Pack `Void`, Code Registry `Disabled`, T4 `Fail` `redo_count == 1`, Set Unit `Reprocess`, `active_cycle_id` rỗng; generate lại → Cycle ID mới, T4 `Pass`, Set Unit `Processing`), `test_void_only_packed`, `test_lookup_returns_pack_details` (tra bằng chuỗi HRI và bằng Cycle ID trần), `test_lookup_unknown`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS. **Step 5:** Commit `feat(reprocessing): sinh Cycle ID T4 một transaction, in lại 10 phút, hủy, tra cứu gói`.

### Task 9: RPC `tracecore.v1.pack.*`, `printer.set_roll`, `station.config`, từ chối 409

**Files:**
- Create: `tracecore/v1/pack.py`, `tracecore/v1/printer.py`, `tracecore/v1/station.py`, `tracecore/v1/tests/test_pack_api.py`, `tracecore/v1/tests/test_station_api.py`
- Modify: `tracecore/v1/_common.py`, `tracecore/core/idempotency.py` (trả lời lặp lại `ok: false` → 409), `tracecore/ui/page/station/station.js` (`rpc()` đọc body khi 409), `tracecore/tests/factories.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: `packing.*` (Task 8), `print.set_roll/station_printers` (Task 5), `require_agent_for` (FEAT-001).
- Produces (mọi RPC ghi: `@frappe.whitelist(methods=["POST"])` + `@idempotent`):
  - `_common.rejection(code, title, reason, action, **extra) -> dict` đặt `frappe.local.response["http_status_code"] = 409` khi đang có request; `_common.reject_block(block, ref_doctype=None, ref_name=None, raw=None) -> dict` (ghi Audit Log `Reject` rồi trả `rejection`); `_common.require_step(station, step) -> Block | None` (`STATION_WRONG_STEP`).
  - `v1.pack.scan(raw, station, open_set=None, client_ts=None) -> dict`: `{"ok": true, "kind": "context", "context": …}` | `{"kind": "pack", "pack": …}` | `{"kind": "roll", "roll": …}` (một máy in → đổi cuộn; > 1 máy → `ROLL_PRINTER_AMBIGUOUS`) | `{"kind": "ci", "ci": …}` (chỉ khi có `open_set`; không có → `SCAN_INVALID`).
  - `v1.pack.generate_cycle_id(set_id, station, confirmed_lines, ci_batch, pack_type, maint_actions=None, client_ts=None)` (kiểm `frappe.has_permission("Pack", "create", throw=True)` trước mọi ghi; danh sách nhận cả list và chuỗi JSON).
  - `v1.pack.reprint_label(cycle_id, reason, station, client_ts=None)`, `v1.pack.void(cycle_id, reason, station, note=None, client_ts=None)`.
  - `v1.printer.set_roll(roll_code, station, printer=None, client_ts=None)`.
  - `v1.station.config(station, client_ts=None) -> {"station", "printers": print.station_printers(station)}` (role `TC Agent`, `require_agent_for`; không `@idempotent`, giống `agent.heartbeat`).

- [ ] **Step 1:** Test (dùng `request_headers({"X-Idempotency-Key": uuid, "X-TC-Station": "TR-004"})`): `test_scan_set_returns_context`, `@bru("BRU-FLOW-004") test_scan_rejection_writes_audit_and_409` (`ok is False`, code `GATE_PREV_NOT_PASSED`, Audit Log `Reject` `ref_doctype == "Set Unit"`, `frappe.local.response.http_status_code == 409`), `test_scan_wrong_station_step` (TR-003 → `STATION_WRONG_STEP`), `test_scan_routes_pack_roll_and_ci`, `test_generate_replay_same_key_returns_same_cycle` (AC-13: cùng key 2 lần → cùng `cycle_id`, 1 Pack), `test_rejection_replay_keeps_409`, `test_generate_requires_create_permission` (user không có `TC R04` → `PermissionError`, không có Audit/Pack), `test_generate_p95_under_1s_with_50_sets` (AC-15: 50 bộ seed, đo 20 lần sinh, `sorted(t)[18] < 1.0`), `test_station_config_for_agent` (agent TR-004 thấy máy in của TR-004; agent trạm khác → `PermissionError`), `test_set_unit_get_unknown_now_409` (FEAT-001 vẫn `ok is False` + 409).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; sửa `rpc()` trong `station.js`: `response.status === 409` → trả `data.message`.
- [ ] **Step 4:** PASS toàn app (`run-tests --app tracecore`); e2e smoke FEAT-001 (`pytest tests_e2e/test_station_smoke.py`) vẫn xanh. **Step 5:** Commit `feat(v1): RPC pack.scan/generate/reprint/void, printer.set_roll, station.config; từ chối 409`.

### Task 10: Station Agent in theo máy in có tên

**Files:**
- Create: `tracecore_agent/printers.py`, `tracecore_agent/tests/test_printers.py`
- Modify: `tracecore_agent/client.py`, `tracecore_agent/jobqueue.py`, `tracecore_agent/server.py`, `tracecore_agent/service.py`, `tracecore_agent/cli.py`, `tracecore_agent/tests/{test_queue,test_server,test_client}.py`

**Interfaces:**
- Consumes: RPC `tracecore.v1.station.config` (Task 9).
- Produces: `ServerClient.station_config() -> dict`; `printers.PrinterDirectory(cfg, client)` với `refresh() -> None`, `resolve(name: str | None) -> tuple[str, int] | None` (None tên → `(cfg.printer_host, cfg.printer_port)` như cũ; tên lạ → refresh một lần rồi `None`; `host` rỗng → chế độ file); bảng `jobs` thêm cột `printer` (tự `alter table` khi mở DB cũ); `PrintQueue.enqueue(zpl, preview_png=None, print_job=None, printer=None)`; `POST /print` nhận `printer` (chuỗi ≤ 140); `process_one(cfg, queue, client=None, directory=None)`; lệnh mới `python3 -m tracecore_agent config` in cấu hình trạm; `serve` refresh khi khởi động và mỗi 10 nhịp heartbeat.

- [ ] **Step 1:** Test (`python -m pytest tracecore_agent`): `test_queue_adds_printer_column_to_old_db` (DB tạo bằng schema cũ → mở lại có cột `printer`, job cũ giữ nguyên), `test_print_endpoint_accepts_printer` (202, job có `printer == "PRN-001"`; `printer` dài 200 → 400), `test_process_routes_to_named_printer` (directory trả `("127.0.0.1", port)` của socket server test → nhận đúng ZPL), `test_unknown_printer_fails_after_refresh` (refresh gọi đúng 1 lần; sau 3 lần → `failed`, ack `Failed` có lỗi "Unknown printer PRN-404"), `test_client_station_config` (stub HTTP: gọi `tracecore.v1.station.config` với `station`), `test_hello_still_uses_ini_printer` (không đổi hành vi FEAT-001).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS. **Step 5:** Commit `feat(agent): định tuyến lệnh in theo Printer của trạm từ station.config`.

### Task 11: Giao diện T4 SCR-08 trên Page `station` + dữ liệu demo

**Files:**
- Create: `tracecore/public/js/station_t4.js`
- Modify: `tracecore/hooks.py` (`page_js = {"station": "public/js/station_t4.js"}`), `tracecore/ui/page/station/{station.js,station.html,station.css}`, `tracecore/setup/devdata.py`, `tracecore/tests/test_devdata.py`, `tracecore/tests/test_station_page.py`, `tracecore/translations/vi.csv`

**Interfaces:**
- Consumes: RPC Task 9; agent `POST http://127.0.0.1:8765/print {zpl, print_job, printer}` (Task 10); token `--tc-*`; component design.md §4.1, 4.2, 4.4, 4.7, 4.8, 4.11, 4.12, 4.13, 4.16, 4.18, 4.19.
- Produces: `class T4Packing` (trong `station_t4.js`) được `TraceCoreStation` dùng khi `stationInfo.step === "T4"`: mọi lần quét đi qua `tracecore.v1.pack.scan` (kèm `open_set`); `devdata.ensure_t4_demo() -> dict` (idempotent; in JSON `{"set_steam", "set_plasma", "set_gate_fail", "ci_steam", "ci_plasma", "roll_steam", "roll_plasma", "printer"}`; máy in TR-004 nạp nhãn hấp, `host` rỗng; ảnh dụng cụ là PNG sinh bằng Pillow ghi chữ "DEMO").

Hành vi màn T4 (mỗi dòng là một yêu cầu kiểm được trên e2e/tay):
1. Trống: "Quét Set ID của bộ cần đóng gói". Ô quét luôn ở đầu và có focus (kể cả sau khi đóng modal).
2. Quét Set ID → khối thông tin bộ (Set ID mono, tên bộ, badge phương pháp có chữ, badge LOANER nếu có), gate panel T1–T5 có chữ Đạt/Chưa/Không đạt (§4.4), thanh cơ số kèm chữ "n/max chu trình (x%)" (§4.11), khối nhắc bảo dưỡng (nếu có), lưới BOM có ảnh + checkbox ≥ 32 px từng dòng + nút "Xác nhận tất cả thành phần" (D1), khối lô chỉ thị ("Quét lô chỉ thị loại 5/6 – Hấp"; sau khi quét hiện lô, hạn), chọn loại gói (mặc định của loại bộ, hiện hạn dùng dự kiến dd/mm/yyyy), dòng loại nhãn + máy in sẽ dùng.
3. Nút chính "Xác nhận hoàn thành đóng gói" 56 px: khi còn thiếu thì disabled và liệt kê mục thiếu bằng chữ ("Còn thiếu: 1 dụng cụ, lô chỉ thị, xử lý bảo dưỡng KC-02").
4. Nhắc bảo dưỡng: "Đã bảo dưỡng" mở dialog (§4.13) có ô nhận lô dầu (khi `maint_type = Lubrication`); "Hoãn" mở dialog bắt buộc lý do; `can_defer = false` thì nút Hoãn disabled kèm chú thích.
5. Từ chối (`ok: false`) → `alert-error` toàn khối: tiêu đề kết quả → lý do → hành động; `PAR_EXCEEDED` có nút "Đề nghị ghi đè" disabled + chú thích "có từ FEAT-032"; `items` hiện thành danh sách.
6. Sinh thành công → Cycle ID mono cỡ lớn, label preview §4.12 (DataMatrix PNG thật, biến thể hấp viền liền / plasma viền đứt, dòng "HẠN SỬ DỤNG"), trạng thái in. `print.status = Queued` → POST agent; agent không phản hồi → `alert-warn` "Chưa gửi được tới máy in, Cycle ID vẫn giữ — kiểm tra Station Agent rồi In lại". `Waiting` (`NO_PRINTER_FOR_METHOD`) → `alert-error` nêu loại nhãn cần nạp và "Quét mã cuộn CN- sau khi đổi cuộn".
7. Nút phụ "In lại (lý do)" và nút nguy hiểm "Hủy Cycle ID" (dialog lý do + chọn `void_reason`); quét mã cuộn → `alert-info` "Đã nạp cuộn … vào máy in …", gửi các job được giải phóng tới agent; quét Cycle ID → thẻ tra cứu (AC-14).
8. Offline: thông báo "Đóng gói cần kết nối mạng; sinh Cycle ID offline có từ FEAT-009", không cho bấm Xác nhận. Đủ 4 trạng thái loading/empty/error/offline.
9. Chữ ≥ 16 px, nút ≥ 48 px, khoảng cách ≥ 12 px, không hover-only/swipe/long-press, trạng thái luôn có chữ hoặc ký hiệu, ngày dd/mm/yyyy.

- [ ] **Step 1:** Test Python: `test_station_page_includes_t4_script` (`frappe.get_hooks("page_js")["station"]` chứa `"public/js/station_t4.js"`), `test_ensure_t4_demo_idempotent` (gọi 2 lần trả cùng dict; `set_gate_fail` chưa có T3 Pass; `set_steam` có T3 Pass; máy in TR-004 nạp `VT-NHAN-HAP`), coverage bản dịch (test có sẵn).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực JS/HTML/CSS (chỉ biến `--tc-*`, không hex/px), devdata, bản dịch; `bench build --app tracecore`.
- [ ] **Step 4:** PASS; `pre-commit run --all-files` sạch (eslint/prettier, R3/R4); mở `/app/station?station=TR-004` trên dev site, đi hết 9 hành vi trên ở viewport 1366×768, chụp ảnh màn hình đính PR. **Step 5:** Commit `feat(ui): màn T4 đóng gói SCR-08 trên Page station, devdata T4`.

### Task 12: E2E T4, xác minh AC và PR

**Files:**
- Create: `tests_e2e/test_station_t4.py`
- Modify: `scripts/e2e_prepare.sh` (gọi `ensure_t4_demo`, ghi `TC_E2E_T4_*` vào file env), `.github/workflows/*.yml` nếu cần biến mới

- [ ] **Step 1:** Test Playwright (kiosk 1366×768): `test_t4_happy_path_within_three_taps` (quét `set_steam` → chạm "Xác nhận tất cả thành phần" → quét `ci_steam` → chạm "Xác nhận hoàn thành đóng gói": đếm 2 chạm; thấy Cycle ID khớp `CY-\d{6}-\d{4}`, label preview có "HẠN SỬ DỤNG"; cảnh báo agent không phản hồi chấp nhận được trên CI), `test_t4_gate_not_passed_shows_full_alert` (`set_gate_fail` → `.tc-alert-error` có tiêu đề + lý do + hành động), `test_t4_plasma_waits_for_plasma_roll` (bộ plasma → Cycle ID hiện + alert loại nhãn; quét `roll_plasma` → `alert-info`, 1 job được giải phóng), `test_t4_touch_targets_and_font_sizes` (mọi `button` trong khối T4 cao ≥ 48 px, nút chính ≥ 56 px, `font-size` chữ ≥ 16 px qua `getComputedStyle`).
- [ ] **Step 2:** `scripts/e2e_prepare.sh tracecore-dev.local` rồi `pytest tests_e2e` (bench start chạy nền) → PASS.
- [ ] **Step 3:** Xác minh toàn nhánh, dán kết quả thật vào mô tả PR: `bench --site test_site run-tests --app tracecore --coverage`; `diff-cover coverage.xml --compare-branch=origin/feat/FEAT-001-walking-skeleton --fail-under=70` (đổi sang `origin/main` khi FEAT-001 đã merge); `pre-commit run --all-files`; `python -m pytest tracecore_agent`; `pytest tests_e2e`; `python3 -m tracecore_agent hello` + một lần in nhãn gói thật ở chế độ file (`.zpl`, ảnh) để kiểm bằng mắt.
- [ ] **Step 4:** Bảng AC-1..AC-16 trong mô tả PR: mỗi AC ghi test chứng minh; AC-16 ghi "pending-environment" nếu chưa có nhãn chịu hấp/plasma (R-01).
- [ ] **Step 5:** Push nhánh; hỏi người dùng trước khi mở PR (base theo trạng thái FEAT-001). Commit cuối `test(e2e): luồng T4 đóng gói trên kiosk`.
