# FEAT-033 Đồ vải: danh mục loại và thu gom theo khoa (có cân) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R07 khai báo loại đồ vải (khối lượng chuẩn/chiếc, định mức theo khoa, giá trị/chiếc) và ghi lượt thu gom theo khoa: nhiều dòng loại, số chiếc, kg (lấy từ cân qua station agent hoặc nhập tay có xác nhận), cờ nhiễm; hệ thống quy đổi số ↔ kg, cảnh báo lệch > 15 %, ghi sổ `Linen Collection` và cho in biên nhận.

**Architecture:** Module `Linen` (M3) thêm `Linen Type` (+ child `Linen Dept Quota`), `Linen Collection` (+ child `Linen Collection Line`) và dịch vụ `tracecore/linen/collection.py`; RPC mỏng `tracecore.v1.linen.*` theo khuôn `v1.receive` (`station_session` + `@idempotent`). Màn trạm đồ vải là một screen mới trong Page `station` (`public/js/station_linen.js`) dùng component dùng chung `TcWeighLine` (`public/js/tc_weigh_line.js`) để FEAT-047 tái dùng.

**Tech Stack:** Frappe v15, Python 3.11, JS thuần trong Page `station`, Playwright (không chạy E2E trừ khi được bảo).

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-033; `docs/srs.md` FR-M3-01 (.1–.5), FR-M3-02 (.1–.3), EI-HW-004, NFR-AVAIL-04; `docs/use-cases.md` UC-16; `docs/ux-foundations.md` SCR-16; `docs/architecture.md` §5.3 M3, ADR-006/007, dòng "Agent mất kết nối / cân không phản hồi".

FR/BRU đáp ứng: FR-M3-01, FR-M3-01.1–.5, FR-M3-02, FR-M3-02.1–.3; BRU-LIN-001, BRU-LIN-002; EI-HW-004; NFR-AVAIL-04.

**Nhánh:** `feat/FEAT-033-linen-collect` cắt từ `develop` (60136aa).

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt gật đầu. **[Xác nhận]** = lựa chọn thiết kế trong phạm vi tài liệu. Phương án đang ghi là phương án sẽ làm nếu được duyệt. Số amendment dự kiến: **A-49** (A-47, A-48 đã dùng cho FEAT-044, FEAT-045).

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| L1 | [Chốt] | Trạm đồ vải trên Page `station` | Trạm đồ vải là "khu riêng", không có cổng 5 bước. Thêm giá trị bước **`LIN`** vào trường bước của `Zone Station` (hiện chỉ T1–T8); `navigation` gán `LIN` cho `TC R07`; không đi qua `step_gate` và không đổi trạng thái Set Unit. Page `station` định tuyến `LIN` sang màn `LinenCollect`. | ux-foundations (linen là khu riêng); architecture §5.3, ADR-002 |
| L2 | [Xác nhận] | DocType và mã | `Linen Type` (autoname `field:type_name`, `std_weight_kg`, `unit_value` VND, `is_active`, child `Linen Dept Quota` {khoa, `min_qty`, `max_qty`}); `Linen Collection` submittable, naming `LNC-.YYYY.-.#####` (thêm vào §5.3.3, kiểm trùng tiền tố khi hiện thực); child `Linen Collection Line`. Không có mã từng chiếc. | architecture §5.3; FR-M3-01.1 |
| L3 | [Xác nhận] | Cờ nhiễm theo dòng hay theo phiếu | Theo **dòng** (`contaminated`, mặc định Nhiễm). FR-M3-01 ghi "từng dòng ... cờ nhiễm". Chặn trộn nhiễm/không nhiễm trong một lô giặt thuộc FEAT-034 (BRU-LIN-003), không phải ở đây. | FR-M3-01 |
| L4 | [Chốt] | Quy đổi số ↔ kg và lệch > 15 % | Chỉ nhập một trong số chiếc/kg → tự tính theo `std_weight_kg`, `weight_source = Quy đổi` (kg làm tròn 3 lẻ, số chiếc làm tròn nguyên). Nhập cả hai và lệch > 15 % so với quy đổi → cảnh báo; server **chặn ghi sổ nếu thiếu ghi chú lệch** (`variance_note`), có ghi chú thì giữ giá trị nhập. | FR-M3-01.3, FR-M3-01.4; BRU-LIN-002 |
| L5 | [Xác nhận] | UC-16 A1: chỉ có cân tổng của xe | RPC nhận `total_kg` kèm số chiếc từng loại; server chia kg theo tỷ lệ `qty × std_weight_kg`, phần dư vào dòng cuối, `weight_source = Quy đổi`. | UC-16 A1 |
| L6 | [Xác nhận] | Sửa lượt đã ký (UC-16 E3) | Chứng từ đi Nháp → Ghi sổ → Hủy; "sửa" = Hủy rồi Sửa đổi (`amended_from`), không sửa đè. Hủy cần R02. | UC-16 E3; CLAUDE.md |
| L7 | [Xác nhận] | Biên nhận | Print Format `Linen Collection Receipt` (A5), nút In biên nhận trên màn trạm và trên Desk. Chữ ký tay trên bản in; chữ ký điện tử chỉ có ở cấp phát (FR-M3-05.1, FEAT-035). | FR-M3-01.5; FR-M3-05.1 |
| L8 | [Chốt] | Offline | Không đưa vào offline outbox (FEAT-009 chỉ phủ T1/T4/T8). Mất mạng → màn hiện trạng thái offline và không ghi. Cân lỗi hoặc agent không phản hồi (timeout 2 s) → nhập tay kg kèm tick xác nhận, `weight_source = Nhập tay`. | FEAT-009 phạm vi; NFR-AVAIL-04; architecture dòng 1261 |
| L9 | [Xác nhận] | Người giao, người nhận, khoa | Người nhận = Employee của phiên thẻ (không nhận từ tham số). Người giao nhập tên (bắt buộc). Khoa chọn từ danh sách khoa đang dùng cho chứng từ (cùng cách các FEAT trước chọn khoa; kiểm khi hiện thực). Ngày giờ lấy giờ máy chủ. | FR-M3-01; UC-16 bước 1 |
| L10 | [Xác nhận] | Quyền | `Linen Type`: R02, R10 RW; R01, R07, R09 R. `Linen Collection`: R07 RWS; R02 RA (hủy/sửa đổi); R01, R09, R10 R. Thêm hàng vào `permission_matrix.csv` nếu chưa có và sinh lại `custom_docperm.json`. Quyền xem theo khoa của R08 thuộc FEAT-035. | CLAUDE.md; architecture §Department permission |
| L11 | [Chốt] | Ngoài phạm vi FEAT-033 | Dashboard kg/khoa trong ngày (UC-16 bước 6) → FEAT-006; đối chiếu và cảnh báo vượt `min/max` quota → FEAT-035 (033 chỉ lưu quota); dùng `unit_value` → FEAT-034/046 (033 chỉ lưu). Danh mục loại đồ vải nhập trên Desk (SCR-16 chỉ là màn thu gom). | implementation-plan; UC-16 |
| L12 | [Xác nhận] | RPC | `tracecore.v1.linen.catalog` (GET: loại đang dùng kèm quota của khoa) và `tracecore.v1.linen.collect` (POST, `@idempotent`, tạo + ghi sổ). Lệch so với bảng plan (chỉ ghi `v1.linen.collect`): thêm `catalog` để màn trạm đọc danh mục. | implementation-plan; CLAUDE.md |

## File structure

- Tạo: `tracecore/linen/doctype/{linen_type,linen_dept_quota,linen_collection,linen_collection_line}/`
- Tạo: `tracecore/linen/collection.py`, `tracecore/linen/tests/`
- Tạo: `tracecore/v1/linen.py`, `tracecore/v1/tests/test_linen_api.py`
- Tạo: `tracecore/public/js/tc_weigh_line.js`, `tracecore/public/js/station_linen.js`
- Tạo: print format `Linen Collection Receipt`
- Sửa: Zone Station (giá trị `LIN`), `tracecore/v1/navigation.py`, `tracecore/ui/page/station/station.js`, `tracecore/hooks.py`, `permission_matrix.csv` + `custom_docperm.json`, `translations/vi.csv`, `tests/factories.py`, `docs/architecture.md` (A-49, §5.3.3), `docs/rtm.md`.

## Tasks

- [ ] **Task 0 — Amendment A-49 và tài liệu** (L1, L2): thêm hàng Revision History, ghi chú A-49, §5.3.3 `LNC-`, hàng `Zone Station` có `LIN`.
- [ ] **Task 1 — Linen Type + Linen Dept Quota** (FR-M3-02, .1–.3; BRU-LIN-001/002): test trước. `std_weight_kg > 0`; trùng tên bị chặn; ngừng dùng = `is_active = 0`, giữ lịch sử, ẩn khỏi danh sách chọn; quota `min ≤ max`, không trùng khoa.
- [ ] **Task 2 — Dịch vụ quy đổi** (FR-M3-01.3, .4; L4, L5): `convert`, `variance`, `allocate_total`; hàm thuần, test biên 15 %, phần dư, làm tròn.
- [ ] **Task 3 — Linen Collection + Line** (FR-M3-01, .1; L2, L3, L6): validate thiếu khoa/loại/số chiếc/kg thì chặn; loại ngừng dùng bị chặn (UC-16 E2); lệch > 15 % cần ghi chú; submittable, không xóa (`audit.block_delete`); Hủy/Sửa đổi.
- [ ] **Task 4 — RPC `v1.linen.*`** (L8, L9, L12): `catalog`, `collect` với `station_session`, `@idempotent`, bước `LIN`; bảng mã lỗi HTTP trong `core/errors.py` và test bảng mã.
- [ ] **Task 5 — Quyền và Zone Station `LIN`** (L1, L10): ma trận quyền, `custom_docperm.json`, `navigation`, Zone Station; cập nhật `test_permissions`.
- [ ] **Task 6 — UI trạm** (FR-M3-01.2, EI-HW-004; L7, L8): `TcWeighLine`, màn `LinenCollect` (ô quét/chọn đầu trang, 4 trạng thái loading/empty/error/offline, alert-error inline, nút ≥ 48 px), nút Lấy cân gọi `GET http://localhost:8765/scale` timeout 2 s, nhập tay có xác nhận; Print Format biên nhận; form Desk cho `Linen Type`.
- [ ] **Task 7 — Dịch, kiểm tra, ghi chú**: `vi.csv` (theo quy tắc ngữ cảnh DocType), lint, coverage changed-code ≥ 70 %, cập nhật `rtm.md`, ghi chú hiện thực cuối file này.

## Acceptance criteria (EARS) và test

| AC | Nội dung | Test |
| :- | :- | :- |
| AC-1 | Khi R07 ghi lượt thu gom đủ khoa, loại, số chiếc, kg, hệ thống ghi sổ `Linen Collection` (FR-M3-01) | `@bru("BRU-LIN-001")` |
| AC-2 | Nếu thiếu khoa, loại, số chiếc hoặc kg thì chặn ghi sổ (FR-M3-01.1) | `@bru("BRU-LIN-001")` |
| AC-3 | Khi chỉ nhập số chiếc hoặc kg, hệ thống tự tính giá trị còn lại (FR-M3-01.3) | `@bru("BRU-LIN-002")` |
| AC-4 | Nếu lệch > 15 % thì cảnh báo và chỉ ghi sổ khi có ghi chú (FR-M3-01.4) | `@bru("BRU-LIN-002")` |
| AC-5 | Nếu `std_weight_kg ≤ 0` hoặc trùng tên thì chặn lưu loại (FR-M3-02.1, .3) | `@bru("BRU-LIN-001")` |
| AC-6 | Loại ngừng dùng bị ẩn khỏi danh sách chọn, lịch sử giữ nguyên (FR-M3-02.2) | `@bru("BRU-LIN-001")` |
| AC-7 | Cân không phản hồi thì nhập tay có xác nhận, nguồn Nhập tay (NFR-AVAIL-04) | test JS tài sản + RPC |
| AC-8 | Sau ghi sổ có biên nhận in được (FR-M3-01.5) | test Print Format |

## Ghi chú hiện thực

**Kết quả (2026-10-29):** full suite 2744 test, 18 đỏ (6 fail, 12 error), không có test nào do FEAT-033 gây ra:
- 10 lỗi `test_linen_type` do user của test trước bị rò sang (chỉ đỏ khi chạy full); đã thêm `setUp` đặt Administrator, chạy lại 10/10 pass.
- Đỏ có sẵn trên develop, không thuộc FEAT này: `test_set_templates` (3), `test_set_tags` (2), `test_set_tag_printing` (1), `test_shifts.test_week_schedule...` (1), `test_station_page.test_vi_translations_do_not_override_other_apps` ('Audit Trail').
- Coverage dòng đổi phía Frappe: 97,1 % (231/238). `tracecore_agent` (scale.py, server.py) không nằm trong coverage của bench; 68 test agent chạy riêng, pass. `diff-cover` chưa cài trong env nên tính trực tiếp từ coverage.xml.
- `pre-commit run --all-files` sạch.

**Khác với plan:**
- `catalog` là POST (cùng kiểu `sync.snapshot`), không phải GET.
- Print Format tên "TC Linen Receipt".
- R08 chưa có quyền đọc Linen Collection cho đến FEAT-035.
- Thêm `GET /scale` ở agent, nhóm launcher "Linen", 5 mã lỗi `LINEN_*`.
- Sửa một dòng dịch FEAT-045 còn thiếu ("Price list {0} is already approved ...").

**Chưa làm / lưu ý:**
- Chưa thử tay màn kiosk trên trình duyệt; chưa migrate site dev `tracecore-dev.local`.
- Trạm đồ vải không seed: R10 tạo Zone (loại Linen) và trạm bước LIN trên Desk.
- PC trạm cân cần `pip install pyserial` cho agent.
