# FEAT-041 Vật tư tiêu hao trên ERPNext Item + nhập kho theo lô/hạn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R10/R02/R09 khai báo vật tư tiêu hao CSSD trên ERPNext `Item` (nhóm cố định, phương pháp tương thích cho nhãn, tồn tối thiểu theo kho, cờ hạn dùng, NCC, chặn trùng mã); R09/R06 nhập kho theo lô/hạn bằng `Stock Entry` Material Receipt đã ghi sổ (giá bình quân gia quyền), nhập tay trên Desk hoặc hàng loạt từ file Excel mẫu (kiểm từng dòng, báo lỗi theo dòng, không ghi gì nếu còn một dòng lỗi) — SCR-24.

**Architecture:** Không DocType mới (ADR-009, architecture §5.3 M6 "Thay"). Thêm Custom Field `tc_*` trên `Item`, `Stock Entry`, `Stock Entry Detail`; luật nghiệp vụ nằm ở package `tracecore/inventory/` (M6) và chạy qua `doc_events` của ERPNext (Desk, RPC và Excel dùng chung một hàm kiểm dòng `check_lines`, nên không có đường nào lách luật). RPC `tracecore.v1.inventory.*` chỉ phục vụ nhập Excel (tải mẫu, kiểm, ghi). Giao diện là form Desk chuẩn của Item/Stock Entry cộng Client Script (ADR-002); không import chéo M1–M10.

**Tech Stack:** Frappe/ERPNext v15 (`version-15`, ERPNext 15.123), Python 3.11, `openpyxl` (đã có trong bench), Desk Client Script, Playwright for Python.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-041 + §6 (F-1..F-20); `docs/srs.md` FR-M6-01 (.1–.3), FR-M6-02 (.1–.3), BRU-INV-001 (FEFO, chặn lô quá hạn — phần nhập kho: không nhận lô đã quá hạn), BRU-REP-011 (hai loại nhãn `VT-NHAN-HAP` / `VT-NHAN-PLASMA`), FR-M9-11 (mẫu Excel, kiểm từng dòng); `docs/use-cases.md` UC-24 (luồng chính, A1, E1, E2); `docs/ux-foundations.md` SCR-24; `docs/architecture.md` §5.3.1 M6 (Consumable Item, Stock Entry), A-02 (Custom Field Item), ADR-009; `docs/rtm.md` FR-M6-01/02. Nền: FEAT-001/018/005/014 (Custom Field `Item-tc_*`, `factories.make_item/make_batch`, `core.audit`, `core.idempotency`, `core.errors.Block`).

**FR / BRU / AC đáp ứng:** FR-M6-01, FR-M6-01.1, FR-M6-01.2, FR-M6-01.3, FR-M6-02, FR-M6-02.1, FR-M6-02.3, FR-M9-11 (phần kiểm từng dòng cho nhập kho); BRU-INV-001 (phía nhập), BRU-REP-011 (nhãn đúng phương pháp ngay từ danh mục). Chưa đạt trong FEAT-041, ghi rõ trong PR: FR-M6-02.2 (đơn giá phiên bản định giá → FEAT-044), UC-24 E3 (kiểm kê đang mở → FEAT-043), A2 (nhập trả lại từ trạm → FEAT-042), bước 4–5 (in nhãn lô, tắt cảnh báo tồn tối thiểu → FEAT-043 / chưa có FEAT in nhãn lô).

**Nhánh:** `feat/FEAT-041-supplies-receipt`, tách từ `feat/FEAT-014-instrument-master` (FEAT-014 chưa vào `main`). Làm trong `~/benches/tracecore-f041/apps/tracecore` (WSL `Ubuntu-22.04`); site test `test_f041`, site dev `tracecore-f041.local` (cổng 8300, Redis 11004/13004). PR base = `feat/FEAT-014-instrument-master` cho tới khi FEAT-014 vào nhánh gốc.

## Quyết định cần duyệt

Mã V1–V14 sẽ ghi thành Amendment **A-07** ở Task 0 (A-01..A-06 đã dùng). Phương án trong cột 4 là phương án plan code theo; chưa có phán quyết của chủ đầu tư thì ghi "tạm — chờ chủ đầu tư duyệt". Đổi phương án nào thì sửa task ghi ở cột cuối trước khi làm.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ | Task |
| :- | :- | :- | :- | :- | :- |
| V1 | [Chốt] | Danh sách nhóm cố định (FR-M6-02.1) so với Select hiện có (`Packaging`, `Chemical Indicator`, `Label`, `Lubricant`) | Select `tc_item_group_cssd` thành: `Chemical Indicator`, `Biological Indicator`, `Test`, `Packaging`, `Pouch`, `Filter Box`, `Label`, `Chemical`, `Other` (9 nhóm của FR) **và giữ `Lubricant`** vì `instrument/maintenance.py` (FEAT-014) đang lọc lô dầu theo giá trị này. Giữ nguyên chuỗi của 4 giá trị cũ để không vỡ dữ liệu và code M1/M2 | FR-M6-02.1 (không có Lubricant), A-02 (Select 4 giá trị), `maintenance.py:35` | 1 |
| V2 | [Chốt] | "Chỉ thị hóa học loại 1–6" nhưng `tc_ci_class` chỉ có 1, 2, 4, 5, 6 (A-02) | Thêm lớp `3`. T4 vẫn chỉ nhận lớp 5/6 (không đổi FEAT-018). `tc_ci_class` chỉ nhập được khi nhóm = `Chemical Indicator` | FR-M6-02.1, A-02 | 1 |
| V3 | [Chốt] | Nhóm bắt buộc có hạn dùng (FR-M6-01.1: chỉ thị hóa học, chỉ thị sinh học, hóa chất) | `Chemical Indicator`, `Biological Indicator`, `Chemical` và `Lubricant` (dầu là hóa chất). Item thuộc các nhóm này bị ép `has_batch_no = 1`, `has_expiry_date = 1`; nhóm còn lại theo cờ "có hạn dùng" của Item. Nhập thiếu hạn → chặn ghi sổ | FR-M6-01.1, FR-M6-02 "cờ có hạn dùng" | 1, 3 |
| V4 | [Chốt] | Tồn tối thiểu theo kho lưu ở đâu (architecture ghi Custom Field `tc_min_qty_by_warehouse`, nhưng "theo kho" cần nhiều dòng) | Dùng bảng con chuẩn `Item Reorder` (`Item.reorder_levels`): `warehouse` + `warehouse_reorder_level` = tồn tối thiểu; `material_request_type` mặc định `Purchase`. **Không** tạo Custom Field `tc_min_qty_by_warehouse` và không DocType mới (ADR-009 cho phép "Item Reorder hoặc `tc_min_qty`"). Một kho một dòng, mức ≥ 0. FEAT-043 (FR-M6-06) đọc bảng này | FR-M6-02, ADR-009, §5.3 M6 | 1 |
| V5 | [Chốt] | "Giá bình quân gia quyền" tính trên Item hay theo lô | Theo **Item**: Item CSSD ép `valuation_method = Moving Average` (Stock Settings mặc định của site là FIFO nên không thể dựa vào mặc định) và Batch tạo bởi nhập kho đặt `use_batchwise_valuation = 0`. Item đã có Stock Ledger Entry mà không phải Moving Average → chặn lưu (ERPNext cũng không cho đổi) | FR-M6-01 | 1, 3 |
| V6 | [Chốt] | Nhà cung cấp và số chứng từ lưu ở đâu (Stock Entry Material Receipt chuẩn không có) | Custom Field **mới** `Stock Entry-tc_supplier` (Link Supplier) và `Stock Entry-tc_document_no` (Data); trên dòng `Stock Entry Detail-tc_batch_id` (Data) và `Stock Entry Detail-tc_expiry_date` (Date) để nhập lô mới ngay trên dòng; lô tạo ra ghi `Batch.supplier`. §5.3 chỉ liệt kê `tc_source_doctype`, `tc_source_name`, `tc_reason` cho Stock Entry → cần amendment (không phải DocType mới) | FR-M6-01, architecture §5.3 M6 | 0, 1 |
| V7 | [Xác nhận] | Vật tư không theo dõi hạn mà dòng nhập vẫn điền hạn | Chặn `EXPIRY_NOT_TRACKED` với lý do "bật cờ có hạn dùng ở vật tư hoặc để trống hạn"; không âm thầm bỏ hạn | FR-M6-02 | 3 |
| V8 | [Xác nhận] | Hạn đúng bằng hôm nay | Nhận (chỉ chặn khi hạn **<** hôm nay, FR-M6-01.3); "hôm nay" theo `Asia/Ho_Chi_Minh` (System Settings) | FR-M6-01.3, UC-24 E1 | 3 |
| V9 | [Xác nhận] | Đơn giá 0 (UC-24 E2) | Cảnh báo cam, không chặn; dòng được đặt `allow_zero_valuation_rate = 1`. Đơn giá âm → chặn. Số lượng ≤ 0 → chặn | UC-24 E2 | 3 |
| V10 | [Xác nhận] | Lô đã tồn tại | Cùng Item và cùng hạn → dùng lại Batch, cộng tồn; khác hạn → chặn `BATCH_EXPIRY_MISMATCH`; mã lô thuộc Item khác → chặn `BATCH_ITEM_MISMATCH` (Batch của ERPNext có tên duy nhất toàn site). Mã lô cắt khoảng trắng đầu/cuối, tối đa 140 ký tự | ADR-009, BRU-INV-001 | 3 |
| V11 | [Chốt] | Quyền (ma trận #13 không có trong repo; R-13) | Item: TC R09, TC R10, TC R02, System Manager đọc/tạo/ghi; TC R01, R03–R08 đọc. Batch và Stock Entry nhập: TC R09, TC R06, System Manager đọc/tạo/ghi/ghi sổ; hủy sổ: TC R09, TC R02, System Manager; TC R01 đọc + report. Không ai xóa. Các DocType được Link tới (Supplier, Warehouse, Item Group, UOM, Company, Stock Entry Type) cho đọc để form Desk chọn được. Hiện thực bằng `Custom DocPerm` idempotent (`inventory.permissions.ensure_permissions`) gọi ở `after_install` và `after_migrate` | UC-24 actors, F-7, R-13 | 2 |
| V12 | [Xác nhận] | Quy tắc nhập hàng loạt (FR-M6-01.2) | Một file `.xlsx` ≤ 2 MB, ≤ 1000 dòng, đọc sheet đầu; dòng 1 là tiêu đề; **tất cả hoặc không gì**: còn một dòng lỗi thì không ghi; báo mọi lỗi (không dừng ở lỗi đầu) theo số dòng Excel. Gom dòng theo (NCC, số chứng từ, kho) thành mỗi nhóm một Stock Entry đã ghi sổ; ngày ghi sổ = hôm nay (không lùi ngày). Kiểm (dry-run) và ghi là hai RPC riêng; chỉ RPC ghi có `@idempotent` | FR-M6-01.2, FR-M9-11 | 4 |
| V13 | [Xác nhận] | Company và kho | Dùng Company mặc định của site (`erpnext.get_default_company()`); chưa có Company (dev site và test site hiện không có vì chưa chạy Setup Wizard) → RPC từ chối `COMPANY_NOT_CONFIGURED`; factory/devdata tự tạo Company thử (perpetual inventory tắt) | ADR-009 (1 company) | 3, 4, 6 |
| V14 | [Xác nhận] | Ngoài phạm vi | Import danh mục Item hàng loạt (FEAT-011 / FR-M9-11 phần "vật tư"); tiêu hao tự động, xuất kho, FEFO (FEAT-042); kiểm kê và cảnh báo tồn tối thiểu/hạn (FEAT-043); đơn giá theo phiên bản định giá (FEAT-044); in nhãn lô; NCC bắt buộc trên Item (plan để tùy chọn vì NCC đã bắt buộc ở từng phiếu nhập); `quy cách` lưu ở Custom Field `Item-tc_specification` (Data) | implementation-plan §3 | — |

## Global Constraints

- Kế thừa Global Constraints của FEAT-001/018/002/005/014/038: Frappe/ERPNext/HRMS `version-15`, Python 3.11, **không lên v16**; không import chéo giữa `instrument`, `reprocessing`, `linen`, `hr`, `equipment`, `inventory`, `costing`, `par`, `admin_reports`, `waste` (`scripts/check_architecture.py` R1; M6 chỉ nói chuyện với M2 qua Item/Batch trong DB); chỉ `core.step_gate` đổi trạng thái Set Unit.
- Không DocType mới. Chỉ Custom Field (fixtures, tên `Item-tc_*`, `Stock Entry-tc_*`, `Stock Entry Detail-tc_*`). `hooks.py` `fixtures` mở rộng filter cho hai DocType mới.
- Chứng từ Nháp → Ghi sổ → Hủy, không xóa; Audit Log mọi tạo/ghi sổ/hủy (F-6); xóa bị cấm ở permission.
- RPC đặt tên `tracecore.v1.inventory.<action>`; RPC ghi dùng `@idempotent` với `X-Idempotency-Key`, `client_ts` ISO 8601 có offset; từ chối nghiệp vụ là `core.errors.Block` + `reject_block` (mã HTTP ở `core.errors.HTTP_STATUS`: thêm `IMPORT_ROWS_INVALID`, `IMPORT_FILE_INVALID` → 422, `COMPANY_NOT_CONFIGURED` → 409).
- Mọi chuỗi hiển thị qua `_()` / `__()` và có trong `tracecore/translations/vi.csv`; thuật ngữ theo QĐ 3671/QĐ-BYT; ngày `dd/mm/yyyy`, VND không lẻ, dấu phẩy thập phân, `Asia/Ho_Chi_Minh`. Không chuỗi tiếng Việt ngoài `_()` (R3).
- Desk UI: chỉ biến `--tc-*` (không gõ hex/px, R4), Client Script nằm trong `tracecore/public/js/` và nối qua `doctype_js`/`doctype_list_js`; trạng thái luôn kèm chữ; lỗi chặn trong hộp thoại nhập Excel là khối `alert-error` inline đỏ toàn khối, thứ tự kết quả → lý do → hành động.
- Test: `FrappeTestCase`; mỗi BRU có test `@bru("BRU-…")`; test module đặt `test_ignore` cho các Link ERPNext mà site CI chưa có (chưa chạy Setup Wizard): tối thiểu `["Item", "Batch", "Stock Entry", "Warehouse", "Company", "Supplier", "Stock Entry Type", "Fiscal Year"]` — thu hẹp lại theo lần FAIL đầu tiên khi hiện thực. Site test/dev **chưa có Company, Warehouse, Fiscal Year, Stock Entry Type** (đã kiểm): `factories.ensure_stock_masters()` (Task 3) tạo đủ, idempotent.
- Coverage changed-code ≥ 70 %, lint sạch.
- Lệnh (từ Windows): `wsl -d Ubuntu-22.04 -- bash -lc "cd ~/benches/tracecore-f041 && bench --site test_f041 run-tests --app tracecore --module <module>"`; lần đầu `bench --site test_f041 set-config allow_tests true`; sau đổi fixtures: `bench --site tracecore-f041.local migrate` và `bench --site test_f041 migrate`, JS: `bench build --app tracecore`. Redis 11004/13004 không phản hồi thì chạy `redis-server config/redis_queue.conf --daemonize yes` (và `redis_cache.conf`) từ thư mục bench trong cùng lệnh wsl. Không đụng `D:\tracecore`, `~/tracecore-dev`, `~/tracecore-codex`, `~/tracecore-f015`. Không in mật khẩu.

## Review Focus

1. Hạn dùng đúng hôm nay (nhận) và hôm qua (chặn); ô Excel là ngày thật, chuỗi `dd/mm/yyyy`, chuỗi sai định dạng ("31/02/2027", "abc") → báo đúng dòng, không 500. Test ở Task 3 và 4.
2. File Excel có cả dòng đúng lẫn dòng sai (và nhiều dòng sai) → không ghi gì, báo hết các dòng sai, số dòng khớp số dòng nhìn thấy trong Excel (tiêu đề = dòng 1); file rỗng, sai đuôi, 1001 dòng, thiếu cột → lỗi `IMPORT_FILE_INVALID` rõ ràng. Test ở Task 4.
3. Bấm ghi hai lần/retry mạng với cùng `X-Idempotency-Key` → không nhân đôi tồn; gửi lại với key mới là lần nhập thứ hai theo thiết kế. Test ở Task 4.
4. Cùng lô nhập ở hai phiếu → cộng vào một Batch; cùng mã lô khác hạn hoặc thuộc vật tư khác → chặn; hai dòng cùng lô trong một file khác hạn nhau → chặn. Test ở Task 3, 4.
5. Item cũ của FEAT-005/014/018 (nhãn, chỉ thị, dầu, loại gói) vẫn lưu/sửa được sau khi đổi Select và thêm luật; toàn bộ test cũ (`test_item_fields`, `test_pack_api`, `test_codes_api`, `instrument/tests`) vẫn xanh vì luật chỉ tự bổ sung cờ chứ không chặn Item cũ. Test ở Task 1 và bước xác minh toàn app ở Task 6.

---

### Task 0: Ghi quyết định V1–V14 vào tài liệu (Amendment A-07)

**FR/BRU/AC:** điều kiện tiên quyết của mọi Task (CLAUDE.md: thay đổi ngoài architecture §5.3 phải qua amendment trước khi code).

**Files:** Modify `docs/architecture.md` (Revision History A-07; ghi chú A-07 ở §5.3.1 M6 ngay dưới ghi chú A-02: nhóm Select mới, `tc_ci_class` thêm `3`, `Item Reorder` thay `tc_min_qty_by_warehouse`, Custom Field Stock Entry/Stock Entry Detail, quyền V11, `use_batchwise_valuation = 0`), `docs/srs.md` (dòng FR-M6-01/02 trỏ A-07; không đổi ID FR/BRU), `docs/implementation-plan.md` (dòng FEAT-041: thêm Custom Field vào cột Data), `docs/rtm.md` (cột Test/ghi chú FR-M6-01/02 trỏ A-07 nếu có chỗ).

- [ ] **Step 1:** Ghi A-07: V1–V6, V11 "tạm — chờ chủ đầu tư duyệt" (dev lead chưa duyệt kế hoạch), V7–V10, V12–V14 "dev lead xác nhận" khi người dùng đã duyệt kế hoạch. Nêu rõ: không thêm DocType, không thêm/bớt FR hay BRU (49 BRU).
- [ ] **Step 2:** `pre-commit run --files <4 docs>` sạch; `bench --site test_f041 run-tests --app tracecore --module tracecore.tests.test_lint_scripts` OK.
- [ ] **Step 3:** Commit `docs: amendment A-07 quyết định FEAT-041 vật tư tiêu hao và nhập kho`.

### Task 1: Custom Field và luật Item vật tư (FR-M6-02)

**FR/BRU/AC:** FR-M6-02, FR-M6-02.1, FR-M6-02.3, FR-M6-01.1 (phía danh mục: nhóm bắt buộc hạn), BRU-REP-011, V1–V6.

**Files:**
- Modify: `tracecore/fixtures/custom_field.json`, `tracecore/hooks.py` (fixtures filter `Stock Entry-tc_%`, `Stock Entry Detail-tc_%`; `doc_events["Item"]`), `tracecore/tests/test_item_fields.py` (options mới, thứ tự trường), `tracecore/translations/vi.csv`.
- Create: `tracecore/inventory/items.py`, `tracecore/inventory/tests/__init__.py`, `tracecore/inventory/tests/test_items.py`.

**Interfaces:**
- Produces (`tracecore/inventory/items.py`):
  - `CSSD_GROUPS: tuple[str, ...]` (10 giá trị V1), `EXPIRY_REQUIRED_GROUPS = ("Chemical Indicator", "Biological Indicator", "Chemical", "Lubricant")`, `LABEL_METHOD_BY_CODE = {"VT-NHAN-HAP": "Steam", "VT-NHAN-PLASMA": "Plasma"}`.
  - `check_duplicate_code(doc, method=None) -> None` (hook `Item.before_insert`): cắt khoảng trắng `item_code`, trùng mã (không phân biệt hoa/thường) → `frappe.throw` có tiêu đề/lý do/hành động.
  - `validate_item(doc, method=None) -> None` (hook `Item.validate`): chỉ chạy khi `tc_item_group_cssd` có giá trị.
  - `is_cssd_item(item_code) -> bool`, `requires_expiry(item_code) -> bool` (dùng ở Task 3).
- Custom Field mới: `Item-tc_specification` (Data, sau `description`), `Stock Entry-tc_supplier` (Link Supplier), `Stock Entry-tc_document_no` (Data), `Stock Entry Detail-tc_batch_id` (Data, `in_list_view`), `Stock Entry Detail-tc_expiry_date` (Date, `in_list_view`). Sửa `Item-tc_item_group_cssd.options` và `Item-tc_ci_class.options` (thêm `3`) — thứ tự options cũ giữ trước.

Luật `validate_item` (V1–V5): nhóm ∈ `CSSD_GROUPS`; `tc_compatible_method` bắt buộc khi nhóm `Label`, chỉ `Steam`/`Plasma`; mã `VT-NHAN-HAP`/`VT-NHAN-PLASMA` phải đúng phương pháp ở `LABEL_METHOD_BY_CODE` và đúng nhóm `Label`; `tc_ci_class` chỉ nhập khi nhóm `Chemical Indicator`; `tc_shelf_life_days` giữ luật FEAT-018 (chỉ `Packaging`); nếu Item chưa có Stock Ledger Entry thì tự đặt `is_stock_item = 1`, `has_batch_no = 1`, `valuation_method = "Moving Average"` và `has_expiry_date = 1` cho nhóm `EXPIRY_REQUIRED_GROUPS` (không throw — không vỡ Item cũ); nếu đã có SLE mà `valuation_method` khác Moving Average → throw; `reorder_levels`: kho không trùng nhau, `warehouse_reorder_level ≥ 0`, kho không phải kho nhóm (`is_group`); nhập `reorder_levels` mới mặc định `material_request_type = "Purchase"`.

- [ ] **Step 1: Viết test (FAIL)** trong `test_items.py` (`test_ignore` như Global Constraints):
  `test_group_options_match_fr_m6_02_1` (tập options của `tc_item_group_cssd` == V1 gồm cả 4 giá trị cũ; `tc_ci_class` == `\n1\n2\n3\n4\n5\n6`); `@bru("BRU-REP-011") test_label_requires_compatible_method`; `@bru("BRU-REP-011") test_label_codes_must_match_method` (`VT-NHAN-HAP` + `Plasma` → lỗi; `VT-NHAN-PLASMA` + `Steam` → lỗi; đúng thì lưu được); `test_ci_class_only_for_chemical_indicator`; `test_invalid_group_rejected`; `@bru("BRU-INV-001") test_expiry_groups_force_batch_and_expiry_flags` (4 nhóm V3: sau insert `has_batch_no == 1`, `has_expiry_date == 1`; nhóm `Pouch` giữ `has_expiry_date` theo giá trị người dùng đặt); `test_average_valuation_forced` (`valuation_method == "Moving Average"`); `test_duplicate_code_blocked_case_and_whitespace` (`"VT-X1"` rồi `" vt-x1 "` → lỗi nêu mã trùng; FR-M6-02.3); `test_reorder_levels_unique_warehouse_and_non_negative`; `test_reorder_level_rejects_group_warehouse`; `test_specification_saved`; `test_legacy_item_without_batch_flag_still_saves` (Item tạo bằng `factories.make_item(..., has_batch_no=0)` lưu lại không lỗi và được bật `has_batch_no`); `test_item_without_cssd_group_untouched` (Item chung không có nhóm: không đổi `valuation_method`, `has_batch_no`).
- [ ] **Step 2:** `bench --site test_f041 run-tests --app tracecore --module tracecore.inventory.tests.test_items` → FAIL (module chưa có).
- [ ] **Step 3:** Hiện thực `items.py`, sửa fixtures + `hooks.py`; `bench --site test_f041 migrate` rồi `bench --site tracecore-f041.local migrate` (nhập lại fixtures).
- [ ] **Step 4:** PASS `test_items` và `tracecore.tests.test_item_fields` (sửa test cũ cho options mới, thêm `test_new_custom_fields_installed` cho 5 Custom Field mới); chạy lại `tracecore.reprocessing`, `tracecore.v1.tests.test_codes_api`, `tracecore.instrument` (Review Focus 5).
- [ ] **Step 5:** Commit `feat(inventory): vật tư tiêu hao CSSD trên Item, nhóm cố định, hạn dùng, tồn tối thiểu theo kho`.

### Task 2: Quyền và Audit (V11, F-6, F-7)

**FR/BRU/AC:** FR-M6-01/02 (người dùng đúng vai trò), F-6, F-7, NFR-SEC-03.

**Files:**
- Create: `tracecore/inventory/permissions.py`, `tracecore/inventory/audit.py`, `tracecore/inventory/tests/test_permissions.py`, `tracecore/inventory/tests/test_audit.py`.
- Modify: `tracecore/hooks.py` (`after_migrate`; `doc_events` Item/Batch/Stock Entry), `tracecore/setup/install.py` (gọi `ensure_permissions` ở `after_install`), `tracecore/tests/factories.py` (`make_user` đã có).

**Interfaces:**
- Produces: `ensure_permissions() -> None` (idempotent, dùng `frappe.permissions.add_permission` + `update_permission_property`; ma trận V11 là hằng `PERMISSION_MATRIX` trong cùng file); `on_cssd_event(doc, method) -> None` trong `inventory/audit.py` — chỉ gọi `core.audit.on_document_event` khi doc là Item có nhóm CSSD, Batch của Item CSSD, hoặc Stock Entry có ít nhất một dòng Item CSSD; không đăng ký `on_trash` (xóa bị chặn bằng permission).

- [ ] **Step 1: Viết test (FAIL):** `test_permissions.py`: `test_matrix_applied_for_each_role` (với từng cặp role × DocType trong `PERMISSION_MATRIX`, `frappe.has_permission(doctype, ptype, user=...)` đúng; gồm R09 tạo Item/Stock Entry/Batch và ghi sổ, R06 tạo + ghi sổ Stock Entry, R01 chỉ đọc), `test_nobody_can_delete_stock_entry_item_batch` (R09, R06, R10, R02 `delete` → False), `test_cancel_only_r09_r02_system_manager`, `test_link_targets_readable_for_receipt_roles` (R09/R06 đọc Supplier, Warehouse, Item Group, UOM, Company), `test_ensure_permissions_idempotent` (chạy 2 lần, số Custom DocPerm không đổi). `test_audit.py`: `test_item_create_and_update_logged`, `test_batch_create_logged`, `test_stock_entry_submit_and_cancel_logged` (sau Task 3 có factory; viết ở Task 3 nếu cần), `test_non_cssd_item_not_logged`.
- [ ] **Step 2:** Chạy → FAIL.
- [ ] **Step 3:** Hiện thực; `after_migrate = "tracecore.inventory.permissions.ensure_permissions"` trong `hooks.py` (thêm nếu chưa có hook này).
- [ ] **Step 4:** PASS; chạy `tracecore.tests.test_install` và `tracecore.core.tests` (không vỡ).
- [ ] **Step 5:** Commit `feat(inventory): quyền R09/R06/R10/R02 cho Item, Batch, Stock Entry và Audit Log vật tư`.

### Task 3: Nhập kho theo lô/hạn trên Stock Entry (FR-M6-01, .1, .3)

**FR/BRU/AC:** FR-M6-01, FR-M6-01.1, FR-M6-01.3, UC-24 bước 3–6, E1, E2; BRU-INV-001 (không nhận lô quá hạn), V5, V7–V10, V13.

**Files:**
- Create: `tracecore/inventory/receipt.py`, `tracecore/inventory/tests/test_receipt.py`.
- Modify: `tracecore/hooks.py` (`doc_events["Stock Entry"]["before_validate"]`), `tracecore/tests/factories.py` (`ensure_stock_masters`, `make_warehouse`, `make_supplier`, `make_receipt`), `tracecore/translations/vi.csv`.

**Interfaces:**
- Consumes: `inventory.items.is_cssd_item`, `requires_expiry`; `Item-tc_*`, `Stock Entry-tc_supplier/tc_document_no`, `Stock Entry Detail-tc_batch_id/tc_expiry_date` (Task 1).
- Produces (`tracecore/inventory/receipt.py`):
  - `@dataclass(frozen=True) ReceiptLine(row: int, item_code: str, batch_id: str | None, expiry: date | None, qty: float, rate: float)`; `@dataclass(frozen=True) LineIssue(row: int, code: str, field: str, reason: str)` (`reason` đã qua `_()`; `row = 0` cho lỗi đầu phiếu).
  - `check_header(supplier: str | None, document_no: str | None, warehouse: str | None) -> list[LineIssue]` (mã `SUPPLIER_REQUIRED`, `DOCUMENT_REQUIRED`, `WAREHOUSE_REQUIRED`).
  - `check_lines(lines: list[ReceiptLine], today: date) -> list[LineIssue]` — thuần, không ghi DB, trả **tất cả** lỗi: `ITEM_NOT_FOUND`, `ITEM_DISABLED`, `ITEM_NOT_CSSD`, `ITEM_NOT_BATCHED`, `QTY_INVALID`, `RATE_NEGATIVE`, `BATCH_REQUIRED`, `EXPIRY_REQUIRED` (nhóm V3 hoặc `has_expiry_date`), `EXPIRY_NOT_TRACKED` (V7), `EXPIRY_PAST` (hạn < `today`), `BATCH_EXPIRY_MISMATCH`, `BATCH_ITEM_MISMATCH`, `LOT_CONFLICT_IN_DOCUMENT` (cùng item+lô khác hạn trong cùng phiếu). Cảnh báo (không phải lỗi): `RATE_ZERO` trả riêng qua `zero_rate_rows(lines) -> list[int]`.
  - `prepare_receipt(doc, method=None) -> None` (hook `Stock Entry.before_validate`): chỉ chạy khi `doc.purpose == "Material Receipt"` và có ≥ 1 dòng Item CSSD; dựng `ReceiptLine`/header từ doc, gom lỗi và `frappe.throw` một lần liệt kê từng dòng (tiêu đề → lý do → hành động); dòng đơn giá 0 → `frappe.msgprint(indicator="orange")` + `allow_zero_valuation_rate = 1`; khi `doc._action == "submit"`: `ensure_batch(...)` cho từng dòng (tạo `Batch` với `batch_id`, `item`, `expiry_date`, `supplier`, `use_batchwise_valuation = 0`, hoặc dùng lại) rồi đặt `use_serial_batch_fields = 1`, `batch_no`.
  - `ensure_batch(item_code: str, batch_id: str, expiry: date | None, supplier: str | None) -> str` trả tên Batch.
  - `today_vn() -> date` (`frappe.utils.getdate()` theo múi giờ System Settings).
- Factories: `ensure_stock_masters() -> dict` tạo (idempotent) Company thử `TraceCore Test` (abbr `TCT`, VND, `enable_perpetual_inventory = 0`), Fiscal Year chứa hôm nay, Stock Entry Type `Material Receipt` (purpose `Material Receipt`), trả `{"company", "warehouse"}`; `make_receipt(lines, supplier, document_no, warehouse=None, submit=True) -> Document`.

- [ ] **Step 1: Viết test (FAIL)** `test_receipt.py` (`FrappeTestCase`, `test_ignore` như Global Constraints; mỗi test tạo dữ liệu bằng factories, rollback tự động):
  `@bru("BRU-INV-001") test_receipt_posts_stock_entry_and_updates_batch_stock` (Stock Entry `docstatus == 1`, `Batch.batch_qty == qty`, `Bin.actual_qty == qty`; FR-M6-01); `test_weighted_average_across_two_receipts` (10 × 100.000 rồi 10 × 200.000 cùng Item khác lô → `Bin.valuation_rate == 150000` và `Stock Ledger Entry.valuation_rate` của phiếu 2 == 150000; V5); `test_same_lot_two_receipts_adds_to_one_batch` (V10); `test_same_lot_different_expiry_blocked` (`BATCH_EXPIRY_MISMATCH`); `test_batch_of_other_item_blocked` (`BATCH_ITEM_MISMATCH`); `test_conflicting_lot_inside_one_document_blocked`; `@bru("BRU-INV-001") test_expired_lot_blocked` (hạn = hôm qua → lỗi `EXPIRY_PAST`, Stock Entry không ghi sổ; FR-M6-01.3); `test_expiry_today_accepted` (V8); `@bru("BRU-INV-001") test_indicator_biological_chemical_without_expiry_blocked` (4 nhóm V3: thiếu hạn → `EXPIRY_REQUIRED`, ghi sổ thất bại; FR-M6-01.1); `test_flagged_item_requires_expiry_even_if_group_optional` (nhóm `Pouch` + `has_expiry_date = 1`); `test_expiry_given_for_untracked_item_blocked` (V7); `test_missing_batch_blocked`; `test_qty_zero_or_negative_blocked`; `test_negative_rate_blocked`; `test_zero_rate_warns_but_posts` (UC-24 E2; `allow_zero_valuation_rate == 1`); `test_missing_supplier_or_document_no_blocked`; `test_all_errors_listed_at_once` (3 dòng lỗi khác nhau → thông báo nêu cả 3 dòng); `test_batch_created_only_on_submit` (lưu nháp không tạo Batch; submit mới tạo; lưu nháp lỗi hạn vẫn bị chặn sớm); `test_batch_supplier_and_non_batchwise_valuation` (`Batch.supplier`, `use_batchwise_valuation == 0`); `test_non_average_item_blocked_when_stock_exists` (V5, đặt `valuation_method = "FIFO"` bằng `db.set_value` sau khi có tồn → lưu Item lỗi); `test_non_cssd_stock_entry_untouched` (Material Receipt cho Item không nhóm CSSD: hook không can thiệp); `test_issue_purpose_untouched` (Material Issue không bị chặn bởi luật nhập); `test_check_lines_is_pure` (gọi `check_lines` không tạo Batch/Stock Entry); `test_cancel_receipt_reverses_stock` (hủy sổ → `Batch.batch_qty == 0`); `test_company_missing_message` (V13: xóa Company mặc định giả lập → `prepare_receipt` không 500). Bổ sung `test_audit.py::test_stock_entry_submit_and_cancel_logged`.
- [ ] **Step 2:** `bench --site test_f041 run-tests --app tracecore --module tracecore.inventory.tests.test_receipt` → FAIL.
- [ ] **Step 3:** Hiện thực `receipt.py`, đăng ký hook, factories. **Spike đầu tiên:** xác nhận trên ERPNext 15.123 hook nào chạy trước khi `Stock Entry` tạo Serial and Batch Bundle từ `batch_no` khi submit; nếu `before_validate` đến quá muộn so với bundle, chuyển việc tạo Batch sang `before_validate` của lần lưu trước submit và ghi lại trong docstring; thứ tự cuối cùng phải qua `test_batch_created_only_on_submit`.
- [ ] **Step 4:** PASS `test_receipt`, `test_items`, `test_audit`, `test_permissions`.
- [ ] **Step 5:** Commit `feat(inventory): nhập kho vật tư theo lô/hạn bằng Stock Entry Material Receipt, chặn thiếu hạn và lô quá hạn`.

### Task 4: Nhập hàng loạt từ file Excel mẫu (FR-M6-01.2, FR-M9-11)

**FR/BRU/AC:** FR-M6-01.2, FR-M9-11 (kiểm từng dòng, báo lỗi theo dòng trước khi ghi sổ), FR-M6-01.1/.3 (cùng luật qua `check_lines`), ADR-003 (idempotency), V12, V13.

**Files:**
- Create: `tracecore/inventory/receipt_import.py`, `tracecore/v1/inventory.py`, `tracecore/inventory/tests/test_receipt_import.py`, `tracecore/v1/tests/test_inventory_api.py`.
- Modify: `tracecore/core/errors.py` (`IMPORT_ROWS_INVALID`, `IMPORT_FILE_INVALID` → 422; `COMPANY_NOT_CONFIGURED` → 409), `tracecore/tests/factories.py` (`make_receipt_workbook(rows, headers=None) -> bytes`, `attach_private_file(content, file_name) -> str`), `tracecore/translations/vi.csv`.

**Interfaces:**
- Consumes: `receipt.ReceiptLine`, `receipt.LineIssue`, `receipt.check_header`, `receipt.check_lines`, `receipt.today_vn`.
- Produces (`receipt_import.py`):
  - `TEMPLATE_COLUMNS = ("item_code", "batch_id", "expiry_date", "qty", "rate", "supplier", "document_no", "warehouse")`; `MAX_ROWS = 1000`; `MAX_BYTES = 2 * 1024 * 1024`.
  - `class ImportFileError(Exception)` với `.reason` (file rỗng, sai định dạng `.xlsx`, quá cỡ, quá 1000 dòng, thiếu cột bắt buộc).
  - `build_template() -> bytes` — `.xlsx` hai sheet: `Receipt` (dòng 1 tiêu đề đã dịch `_()`, định dạng cột Hạn dùng `dd/mm/yyyy`, không dữ liệu mẫu) và `Guide` (mô tả cột, quy tắc hạn dùng bắt buộc cho nhóm V3, hạn không < hôm nay).
  - `parse_workbook(content: bytes) -> list[ImportRow]` (`ImportRow` = `row` số dòng Excel + giá trị thô); đọc `openpyxl.load_workbook(read_only=True, data_only=True)`; tiêu đề nhận cả tiếng Anh và bản dịch hiện tại; bỏ dòng trống hoàn toàn; ngày nhận ô ngày hoặc chuỗi `dd/mm/yyyy`/`yyyy-mm-dd`, còn lại → lỗi `DATE_INVALID` theo dòng; ô công thức không được tính (`data_only` trả giá trị lưu, rỗng thì coi là rỗng).
  - `check_import(rows, default_warehouse: str | None) -> tuple[list[ReceiptLine-grouped documents], list[LineIssue]]`: lỗi từng dòng gộp từ `check_header`/`check_lines` cộng `SUPPLIER_NOT_FOUND`, `WAREHOUSE_NOT_FOUND` (kho nhóm hoặc khác Company bị từ chối), `DATE_INVALID`; không ghi DB.
  - `import_receipts(content: bytes, default_warehouse: str | None, dry_run: bool) -> dict` — `dry_run=True` chỉ kiểm; ngược lại tạo + ghi sổ từng nhóm (NCC, chứng từ, kho) trong một savepoint, lỗi bất kỳ thì rollback toàn bộ.
- Produces (`v1/inventory.py`, quyền `TC R09`, `TC R06`, `System Manager` qua `require_any_role`):
  - `receipt_template()` — `GET`, trả file `.xlsx` (`frappe.response["type"] = "binary"`, `filename`, `filecontent`), không ghi.
  - `receipt_check(file_url: str, warehouse: str | None = None)` — `POST`, không `@idempotent` (chỉ đọc): `{"ok": true, "rows": N, "documents": M}` hoặc `reject_block(Block("IMPORT_ROWS_INVALID", …, items=[{"row", "code", "field", "reason"}, …]))`.
  - `receipt_import(file_url: str, warehouse: str | None = None, client_ts: str | None = None)` — `POST`, `@idempotent`: `{"ok": true, "rows": N, "stock_entries": [names]}`; lỗi như trên, kèm `IMPORT_FILE_INVALID`, `COMPANY_NOT_CONFIGURED`.
  - File đọc qua `File` doc: phải là file **private** do chính người gọi tải lên, đuôi `.xlsx`, ≤ `MAX_BYTES`; không nhận đường dẫn tuỳ ý.

- [ ] **Step 1: Viết test (FAIL).** `test_receipt_import.py`: `test_template_has_columns_and_guide_sheet`, `test_template_roundtrip_parses_to_zero_rows`, `test_parse_accepts_date_cell_and_dd_mm_yyyy_text` (cả hai ra cùng ngày), `test_parse_rejects_bad_dates_per_row` ("31/02/2027", "abc" → `DATE_INVALID` đúng số dòng), `test_row_numbers_match_excel_rows` (dòng dữ liệu đầu là dòng 2; dòng trống ở giữa vẫn giữ số dòng), `test_rejects_empty_file_wrong_extension_too_big_too_many_rows_missing_columns` (`IMPORT_FILE_INVALID`), `@bru("BRU-INV-001") test_invalid_rows_block_everything_and_report_all` (5 dòng: 2 đúng, 3 sai khác kiểu → không có Stock Entry/Batch mới nào; thông báo đủ 3 dòng; FR-M9-11), `test_groups_rows_by_supplier_document_warehouse` (3 nhóm → 3 Stock Entry đã ghi sổ), `test_same_lot_different_expiry_in_file_blocked`, `test_default_warehouse_used_when_cell_empty_and_missing_both_blocked`, `test_expired_and_missing_expiry_rows_blocked_like_desk` (cùng mã lỗi `EXPIRY_PAST`/`EXPIRY_REQUIRED` như Task 3), `test_failure_during_submit_rolls_back_all_documents` (giả lập lỗi ở nhóm thứ hai), `test_dry_run_writes_nothing`. `test_inventory_api.py`: `test_template_endpoint_returns_xlsx_for_r09_not_r04`, `test_check_requires_role` (403), `test_check_returns_row_errors_with_http_422`, `test_import_creates_documents_and_returns_names`, `@bru("BRU-INV-001") test_import_same_idempotency_key_does_not_double_stock` (gọi 2 lần cùng key → `Bin.actual_qty` chỉ một lần), `test_import_new_key_second_time_adds_stock` (theo thiết kế), `test_import_rejects_foreign_or_public_file` (file public hoặc của user khác → từ chối), `test_import_missing_idempotency_key_400`, `test_company_not_configured_409`, `test_reject_writes_audit_log`.
- [ ] **Step 2:** `bench --site test_f041 run-tests --app tracecore --module tracecore.inventory.tests.test_receipt_import` rồi `--module tracecore.v1.tests.test_inventory_api` → FAIL.
- [ ] **Step 3:** Hiện thực; mọi tiêu đề/lý do/hành động qua `_()`; `bandit` sạch (không `eval`, đọc file qua `File.get_content()`, giới hạn cỡ trước khi mở workbook).
- [ ] **Step 4:** PASS hai module trên + `tracecore.inventory`.
- [ ] **Step 5:** Commit `feat(v1): nhập kho hàng loạt từ Excel mẫu, kiểm từng dòng trước khi ghi sổ`.

### Task 5: Desk UI SCR-24

**FR/BRU/AC:** SCR-24, FR-M6-01/02 (người dùng thao tác được), FR-M6-01.2 (tải mẫu/tải file), F-12/F-13/F-14 (WEB: bàn phím, chữ + màu), design.md (token `--tc-*`).

**Files:**
- Create: `tracecore/public/js/stock_entry.js`, `tracecore/public/js/stock_entry_list.js`, `tracecore/tests/test_desk_inventory.py` (kiểm cấu hình, kiểu `test_desk_instrument.py`).
- Modify: `tracecore/public/js/item.js` (nhóm CSSD: ẩn/hiện `tc_compatible_method` chỉ khi `Label`, `tc_ci_class` chỉ khi `Chemical Indicator`, đặt mặc định `has_batch_no`, `has_expiry_date`, `valuation_method` ngay khi chọn nhóm bắt buộc hạn; không xóa nút "Cấp mã cuộn"/"In nhãn cuộn" của FEAT-005), `tracecore/hooks.py` (`doctype_js["Stock Entry"]`, `doctype_list_js["Stock Entry"]`), `tracecore/public/css/tracecore-theme.css` (khối lỗi nhập Excel dùng `--tc-*`; `scripts/build_tokens.py` nếu cần token — không sửa tay `tokens.css`), `tracecore/translations/vi.csv`.

Hành vi (kiểm bằng e2e ở Task 6):
1. **Item:** chọn nhóm → các trường phụ thuộc hiện đúng; chọn nhóm bắt buộc hạn thì `Has Expiry Date` và `Has Batch No` được tích sẵn và khóa; bảng `Reorder level` (tồn tối thiểu theo kho) và NCC hiển thị ngay; thông báo trùng mã hiện từ server.
2. **Stock Entry:** danh sách có hai nút "Nhập kho vật tư" (mở phiếu mới với `stock_entry_type = Material Receipt`, `posting_date` = hôm nay, kho đích mặc định) và "Nhập từ Excel". Form Material Receipt: hiện `NCC`, `Số chứng từ`, cột `Mã lô`, `Hạn dùng` ở lưới; ẩn trường chuyển kho/sản xuất không liên quan; hạn dùng quá hạn tô cam kèm chữ "Hết hạn"; chỉ báo trạng thái Nháp / Đã ghi sổ / Đã hủy bằng chữ.
3. **Hộp thoại "Nhập từ Excel":** nút "Tải mẫu" (gọi `receipt_template`), chọn file `.xlsx` (`frappe.ui.FileUploader`, private), nút "Kiểm tra file" (`receipt_check`): lỗi hiện bảng *dòng — cột — lý do* trong khối `alert-error` đỏ toàn khối ngay trong hộp thoại (không toast); nút "Ghi sổ" chỉ bật sau khi "Kiểm tra" sạch với **đúng file đó** (đổi file thì tắt lại); ghi sổ xong hiện danh sách phiếu (link) và số dòng; mỗi lần ghi sinh `X-Idempotency-Key` mới và giữ khóa khi bấm lại cùng một lần ghi (chống nhấp đúp).

- [ ] **Step 1: Test (FAIL)** `test_desk_inventory.py`: `test_hooks_register_stock_entry_scripts`, `test_scripts_exist_and_use_translated_strings` (không chuỗi tiếng Việt ngoài `__()`), `test_theme_css_uses_tokens_only` (R4), `test_vi_csv_has_all_new_strings` (mọi `_()`/`__()` mới của FEAT-041 có dòng dịch), `test_item_js_keeps_roll_buttons`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; `bench build --app tracecore`; `bench --site tracecore-f041.local clear-cache`.
- [ ] **Step 4:** PASS; `pre-commit run --all-files` (eslint/prettier, R3, R4); kiểm tay bằng Playwright trên `tracecore-f041.local` với user TC R09 (ảnh ở thư mục làm việc, không commit).
- [ ] **Step 5:** Commit `feat(ui): Desk SCR-24 khai báo vật tư và nhập kho theo lô/hạn, nhập từ Excel`.

### Task 6: Dữ liệu demo, E2E, xác minh, PR

**FR/BRU/AC:** F-3 (e2e), F-5, F-13, F-14; đối chiếu mọi FR của FEAT-041.

**Files:** Create `tests_e2e/test_desk_inventory.py`; Modify `tracecore/setup/devdata.py` (+ `tracecore/tests/test_devdata.py`), `scripts/e2e_prepare.sh`, `tests_e2e/conftest.py` nếu cần.

- [ ] **Step 1:** `devdata.ensure_inventory_demo() -> dict` (idempotent; chỉ dev/test site như các hàm demo khác): Company thử + kho, tài khoản `TC R09`, 1 NCC, Item mẫu cho 4 nhóm (chỉ thị hóa học lớp 5, chỉ thị sinh học, bao gói, hóa chất) có tồn tối thiểu theo kho, in JSON `TC_E2E_INV_*`. Test: idempotent (gọi hai lần không nhân bản), từ chối ngoài dev/test.
- [ ] **Step 2:** Playwright (WEB 1366×768, user R09): `test_item_form_shows_fields_by_group`, `test_receipt_form_blocks_missing_expiry_and_expired_lot` (hạn thiếu → bị chặn; hạn hôm qua → bị chặn; hạn mai → ghi sổ được, tồn lô tăng), `test_excel_dialog_reports_row_errors_then_posts_clean_file` (file 1 dòng sai → khối lỗi nêu đúng số dòng, nút Ghi sổ tắt; sửa file → ghi sổ, phiếu hiện), `test_excel_dialog_double_click_posts_once`, `test_status_text_visible_not_color_only`. Không ngủ cố định; dữ liệu test dùng mã duy nhất mỗi lần chạy (Stock Entry và Item không xóa).
- [ ] **Step 3:** Xác minh toàn nhánh bằng lệnh thật, dán output vào mô tả PR: `bench --site test_f041 run-tests --app tracecore --coverage`; `diff-cover coverage.xml --compare-branch=feat/FEAT-014-instrument-master --fail-under=70`; `pre-commit run --all-files`; `python scripts/check_architecture.py` và `python scripts/check_bru_coverage.py`; `pytest tracecore_agent`; `scripts/e2e_prepare.sh` rồi toàn bộ `pytest tests_e2e` trên dev site cổng 8300; toàn app trên một site mới chưa chạy Setup Wizard (Review Focus 5) rồi xóa site.
- [ ] **Step 4:** Bảng đối chiếu FR-M6-01 (.1–.3), FR-M6-02 (.1, .3), FR-M9-11 (phần nhập kho), BRU-INV-001, BRU-REP-011 → tên test chứng minh; ghi rõ phần chưa đạt đã nêu ở đầu plan (FR-M6-02.2, UC-24 E3/A2/bước 4–5).
- [ ] **Step 5:** Commit `test(e2e): Desk vật tư tiêu hao và nhập kho theo lô/hạn`. Không push, không mở PR: **dừng** để người dùng cho Codex review; sau đó mở PR base `feat/FEAT-014-instrument-master` (Conventional Commits, kết thúc mô tả bằng dòng attribution của Claude Code).

## Mâu thuẫn / khoảng trống cần phán quyết

Mọi mục đã có phương án tạm ở bảng "Quyết định cần duyệt"; ở đây chỉ nêu điểm tài liệu mâu thuẫn hoặc thiếu để người dùng/chủ đầu tư phán quyết (CLAUDE.md: không tự chọn).

1. **Nhóm vật tư (V1):** FR-M6-02.1 (9 nhóm, "danh sách cố định") mâu thuẫn A-02 (Select 4 giá trị, trong đó `Lubricant` không có trong FR) và code FEAT-014 đang lọc theo `Lubricant`. Cần quyết định: giữ `Lubricant` hay đổi dầu thành nhóm `Chemical` (kéo theo sửa `maintenance.py` và dữ liệu cũ).
2. **Lớp chỉ thị hóa học (V2):** FR nói loại 1–6, A-02 bỏ lớp 3. Plan thêm lớp 3; cần xác nhận lớp 3 có thật sự dùng ở bệnh viện.
3. **Tồn tối thiểu theo kho (V4):** architecture ghi Custom Field `tc_min_qty_by_warehouse` nhưng "theo kho" cần bảng con; plan dùng `Item Reorder` (ADR-009 cho phép). FEAT-043 phải đọc đúng bảng này.
4. **Giá bình quân (V5):** FR không nói bình quân theo Item hay theo lô; plan chọn theo Item (`use_batchwise_valuation = 0`). Kế toán cần xác nhận trước go-live (UC-24 Open issues đã nêu xác nhận đơn giá thực tế).
5. **Custom Field ngoài danh sách §5.3 (V6):** `tc_supplier`, `tc_document_no`, `tc_batch_id`, `tc_expiry_date`, `tc_specification`; không phải DocType mới nhưng ngoài danh sách `tc_*` của architecture.
6. **Quyền (V11):** ma trận #13 không có trong repo (R-13); R06 được tạo/ghi sổ phiếu nhập theo UC-24 "R09/R06 tạo phiếu nhập", hủy sổ chỉ R09/R02; cần chủ đầu tư duyệt.
7. **Kế toán:** nếu bệnh viện bật `perpetual inventory` trong Company, Material Receipt cần tài khoản chênh lệch/cost center; plan để ERPNext tự điền theo mặc định của Company và **không** kiểm trong test (site test tắt perpetual). Cần xác nhận cấu hình kế toán thật tại bệnh viện.
8. **Mẫu Excel (V12):** tiêu đề cột và sheet hướng dẫn do plan đề xuất; BA chưa có mẫu file. Cần BA/R09 xác nhận bố cục cột, có cần cột "Đơn vị tính" và "Ngày sản xuất" không.
9. **UC-24 bước 4 "in nhãn lô nếu cần":** không FEAT nào trong implementation-plan nhận in nhãn QR lô (A-05 R7 ghi ngoài phạm vi FEAT-005). Cần quyết định có thêm FEAT hay mở rộng FEAT-005.
10. **UC-24 A2 / E3:** nhập trả lại từ trạm (dư) và chặn khi kiểm kê đang mở không có FEAT nhận rõ ràng ngoài FEAT-042/043; plan chuyển sang hai FEAT đó, cần xác nhận.
