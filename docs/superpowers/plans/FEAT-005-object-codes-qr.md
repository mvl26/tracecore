# FEAT-005 Sinh mã đối tượng tự động & in QR nội bộ (NV-/TB-/KE-/TR-/CN-) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mọi đối tượng cần quét (thiết bị `TB-`, trạm `TR-`, cuộn nhãn `CN-`; nhân viên `NV-` và vị trí kệ `KE-` khi DocType của chúng có) có mã do hệ thống sinh, ghi sổ đăng ký, không nhập tay/sửa/cấp lại; R10 in nhãn QR ngay từ bản ghi trên Desk (SCR-33) ra máy in nhãn.

**Architecture:** Dịch vụ xuyên suốt ở `tracecore/core/` (`code_registry.next_code`, `qr` mới, mở rộng `print` với nhãn đối tượng và đường in từ server theo ADR-006 "dự phòng server worker → máy in qua VLAN"); RPC mỏng ở `tracecore/v1/`; giao diện là Client Script trên Desk. Equipment (M5) và Zone Station (M9) chỉ gọi `core`, không import chéo.

**Tech Stack:** Frappe v15, `PyQRCode` (đã có trong môi trường vì Frappe dùng cho 2FA; khai báo thêm trong `pyproject.toml`), Pillow, ZPL `^BQN` (máy in tự mã hóa QR), `socket` stdlib cho đường in từ server, Playwright for Python.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-005; `docs/srs.md` FR-M9-07 (.1–.4), BRU-ID-006; `docs/use-cases.md` UC-33 bước 4; `docs/architecture.md` §5.3.3 (mẫu mã), ADR-004 (mã QR nội bộ), ADR-006 (đường in), A-02..A-04. Nền: FEAT-001/018/002/038 (`Code Registry`, `parse_scan`, Printer, Label Template, Print Job, `set_roll`, Equipment, Zone Station).

FR/BRU đáp ứng: FR-M9-07 (sinh mã tự động, in QR từ bản ghi, ghi sổ), FR-M9-07.1 (không sửa/không cấp lại — đã có ở FEAT-001, mở rộng cho CN-), FR-M9-07.2 (vô hiệu mã khi đối tượng ngừng hoạt động), FR-M9-07.3 (mã lạ bị từ chối + log — đã có ở FEAT-001, thêm mã đã vô hiệu), FR-M9-07.4 (đăng ký thẻ có sẵn: chỉ hàm lõi, DocType Employee ở FEAT-003/036); FR-M5-01 phần "in QR thiết bị"; BRU-ID-006.

**Nhánh:** `feat/FEAT-005-object-codes-qr`, tách từ `feat/FEAT-038-equipment-programs` (PR #4). PR base = nhánh FEAT-038 cho tới khi các PR trước vào nhánh gốc.

## Quyết định cần duyệt

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ | Task |
| :- | :- | :- | :- | :- | :- |
| R1 | [Chốt] | In nhãn đối tượng từ Desk ra máy in bằng đường nào (Station Agent chỉ nhận lệnh từ kiosk cùng máy, không kéo lệnh từ server) | Đường **server worker** (ADR-006 dự phòng): lệnh in nằm hàng đợi Print Job, một background job gửi ZPL tới `Printer.host:Printer.port` (TCP, timeout, tối đa 3 lần, ack Printed/Failed). Chỉ máy in có `host` trong Printer đang hoạt động; host/port **chỉ lấy từ Printer**, không nhận từ client. Máy in chỉ qua agent (host rỗng) → không in được từ Desk, báo rõ lý do | ADR-006 "in thẻ từ Desk"; FEAT-018 final review (Desk không đẩy được tới agent) | 3, 4 |
| R2 | [Chốt] | Kích thước và nội dung nhãn QR đối tượng | 50 × 30 mm, 300 dpi, ZPL (như nhãn thử): QR trái (payload = mã trần, vd `TB-0001`), phải 3 dòng: mã (đậm), tên đối tượng, loại/khu; dòng "TEST" không dùng. Mẫu cấu hình trong Label Template (R10 sửa không cần code, FR-M2-08.4): thêm giá trị `label_object` = `Equipment`, `Station`, `Roll`, `Employee Card`, `Location`; cùng cơ chế sandbox/kiểm render của FEAT-018 | ux-foundations gap 5 (kích thước nhãn chưa chốt); NFR-MAINT-01 | 2 |
| R3 | [Chốt] | Cấp mã cuộn nhãn `CN-` (D2 giao cho FEAT-005) | R10/System Manager cấp hàng loạt trên form **Item** (nhóm Nhãn): nút "Cấp mã cuộn" nhập số lượng 1–200 → sinh `CN-#####` liên tiếp, ghi `Code Registry` (prefix `CN`, ref Item), trả danh sách để in cả loạt. Không có DocType "cuộn" riêng (đúng D2/FEAT-018) | srs FR-M9-07 "cuộn nhãn"; plan FEAT-018 D2 | 4, 5 |
| R4 | [Xác nhận] | Khi nào vô hiệu mã (FR-M9-07.2) | Thiết bị chuyển `Retired` → mã `TB-` thành `Disabled` (lý do = lý do ngừng sử dụng); trạm chỉ bị tắt (`is_active = 0`, đảo ngược được) **không** vô hiệu mã. Quét mã `Disabled`: `equipment.get` vẫn tra được (lịch sử) kèm cảnh báo; **không in được nhãn** cho mã `Disabled` | FR-M9-07.2 "giữ nguyên lịch sử tra cứu"; FEAT-038 Q5 | 4 |
| R5 | [Xác nhận] | Thư viện QR | `PyQRCode~=1.2.1` thêm vào `pyproject.toml` (đã cài sẵn qua Frappe); `core.qr` bọc: PNG xem trước (Pillow), và `zpl_qr` dùng lệnh `^BQN,2,<magnification>` + `^FDQA,<mã>` (máy in tự mã hóa, ECC mức M) — cùng payload | ADR-004 "QR nội bộ" | 1 |
| R6 | [Xác nhận] | NV- và KE- | `core.code_registry.next_code("NV"/"KE")` và `register_card(...)` (thẻ có sẵn của bệnh viện, FR-M9-07.4: duy nhất, không trùng tiền tố hệ thống, quét được qua `parse_scan`) có hàm + test, **chưa có UI/DocType**: Employee (FEAT-003/036) và Sterile Location (FEAT-025) tự gọi. Nút in dùng chung (`tracecore.codes.print_dialog`) để các FEAT đó chỉ cần gắn nút | implementation-plan §3 (R: Employee, Sterile Location chưa có) | 1, 5 |
| R7 | [Xác nhận] | Ngoài phạm vi | Thẻ Set ID/nhãn khay DataMatrix GIAI (FEAT-016), mã `CT-` chất thải (FEAT-047), in từ kiosk/PDA, Print Designer, in thử trên máy thật (R-01 vật liệu) | implementation-plan §3 | — |
| R8 | [Xác nhận] | Quyền | In nhãn đối tượng và cấp mã cuộn: TC R10 và System Manager; TC R02 xem trước (không in) — không cần ngoài R10 trong v1 | BA #13 (R10 quản trị mã) | 4 |

## Global Constraints

- Kế thừa Global Constraints của FEAT-001/018/002/038 (v15, không import chéo M1–M10, chuỗi qua `_()`/`__()` + `vi.csv`, Audit Log, không xóa, TDD + `@bru`, coverage changed-code ≥ 70 %, `test_ignore` cho Link ERPNext/HRMS/User vì CI không có Setup Wizard; **không chạy e2e/devdata trên `test_site`**).
- Mã theo §5.3.3: `NV-.#####`, `TB-.####`, `KE-.####`, `TR-.###`, `CN-.#####`; mã sinh chỉ bởi `core.code_registry`, ghi `Code Registry` trong cùng transaction; không cấp lại mã (kể cả đã `Disabled`).
- Payload QR = mã trần (không tiền tố AI); `gs1.parse_scan` phải nhận lại đúng `{type, id}` cho mọi mã đã sinh, kể cả có tiền tố AIM `]Q1`, khoảng trắng, `\r\n`.
- Mọi chuỗi đưa vào ZPL đã bỏ ký tự điều khiển (`^`, `~`), bỏ dấu khi máy in `supports_unicode = 0` (cơ chế của `core.print.render`); `Printer.host/port` chỉ từ DocType Printer đang hoạt động.
- RPC ghi: `@frappe.whitelist(methods=["POST"])` + `@idempotent`, kiểm role trước mọi ghi, lỗi nghiệp vụ qua `core.errors.Block` + Audit `Reject`; mã lỗi mới ghi vào `core.errors.HTTP_STATUS`.
- Desk UI: chỉ Client Script; chuỗi `__()` + vi.csv; trạng thái luôn có chữ.
- Lệnh: như FEAT-038 (`wsl.exe -d Ubuntu-22.04 --exec bash -lc 'cd ~/tracecore-dev && …'`; bật lại Redis nếu WSL khởi động lại).

## Review Focus

1. Hai lần cấp mã đồng thời (hai request, hai worker) không bao giờ ra trùng mã; cấp 200 mã cuộn một lần vẫn liên tiếp, không thủng số ngoài ý muốn khi lỗi giữa chừng (rollback cả loạt). Test ở Task 1, 4.
2. Mã trong QR do máy quét HID đọc ra có tiền tố AIM (`]Q1`), `\r\n` hoặc Tab → `parse_scan` vẫn nhận ra. Test ở Task 1.
3. Máy in không phản hồi/từ chối kết nối khi gửi từ server → Print Job `Failed` sau 3 lần kèm lý do, yêu cầu của R10 không treo; không gửi tới host nào ngoài Printer đang hoạt động. Test ở Task 3.
4. In nhãn cho mã đã `Disabled` hoặc đối tượng đã `Retired` bị chặn có lý do; tra cứu lịch sử vẫn được. Test ở Task 4.
5. Tên đối tượng có dấu tiếng Việt hoặc ký tự `^`/`~` → ZPL không bị chèn lệnh, nhãn không dấu khi máy in không hỗ trợ Unicode, QR không đổi. Test ở Task 2.

---

### Task 0: Ghi quyết định R1–R8 vào tài liệu (Amendment A-05)

**Files:** Modify `docs/architecture.md` (Revision History A-05; §5.3.1 M9 note; ADR-006 bullet đường in từ server), `docs/srs.md` (ghi chú FR-M9-07 trỏ A-05), `docs/implementation-plan.md` (dòng FEAT-005: phạm vi đúng với R6/R7).

- [ ] **Step 1:** Ghi A-05: R1–R3 "tạm — chờ chủ đầu tư duyệt", R4–R8 dev lead xác nhận. Không thêm/bớt FR/BRU (49 BRU).
- [ ] **Step 2:** `pre-commit run --files <3 docs>`; `bench --site test_site run-tests --module tracecore.tests.test_lint_scripts` OK.
- [ ] **Step 3:** Commit `docs: amendment A-05 quyết định FEAT-005 (tạm, chờ chủ đầu tư duyệt)`.

### Task 1: `core.qr`, `next_code`, `register_card`, `parse_scan` với tiền tố AIM

**Files:** Create `tracecore/core/qr.py`, `tracecore/core/tests/test_qr.py`; Modify `tracecore/core/code_registry.py`, `tracecore/core/gs1.py` (chỉ nếu `]Q1` chưa được nhận), `tracecore/core/tests/test_gs1.py`, `tracecore/pyproject.toml` hoặc `pyproject.toml` (thêm `PyQRCode~=1.2.1`), `tracecore/translations/vi.csv`; test `tracecore/core/tests/test_code_registry.py`.

**Interfaces:**
- Produces: `qr.qr_png(payload: str, module_px: int = 8, margin_px: int = 16) -> bytes`; `qr.zpl_qr(payload: str, x: int, y: int, magnification: int = 6) -> str` (`^FO{x},{y}^BQN,2,{magnification}^FDQA,{payload}^FS`; payload chứa `^`/`~` → `QRError`); `qr.decode_png(png: bytes) -> str` (chỉ cho test/kiểm nhãn; dùng `pylibdmtx` không giải được QR → viết cách kiểm bằng `PyQRCode` mã hóa lại và so ma trận, hoặc `pyzbar` nếu có sẵn — chọn cách không thêm phụ thuộc mới: so sánh ma trận mã hóa). `code_registry.CODE_FORMATS: dict[str, tuple[str, int]]` = `{"NV": ("NV-", 5), "TB": ("TB-", 4), "KE": ("KE-", 4), "TR": ("TR-", 3), "CN": ("CN-", 5)}`; `code_registry.next_code(prefix: str, ref_doctype: str | None = None, ref_name: str | None = None, station: str | None = None) -> str` (atomic qua `getseries`, bỏ qua số đã dùng, ghi `register`); `code_registry.register_card(code: str, ref_doctype: str, ref_name: str) -> str` (FR-M9-07.4: mã sạch bằng `gs1.clean_scan`, 4–40 ký tự CSET82, không bắt đầu bằng tiền tố hệ thống `NV-/TB-/KE-/TR-/CN-/CT-/CY-/LR-/ME-` hay là chuỗi GIAI, duy nhất trong sổ, prefix `CARD`); `code_registry.disable(code, reason)` đã có — dùng lại.

- [ ] **Step 1:** Test: `test_qr_png_encodes_payload` (PNG hợp lệ, ma trận khớp `PyQRCode`), `test_zpl_qr_format` (`zpl_qr("TB-0001", 30, 40)` chứa `^BQN,2,6^FDQA,TB-0001^FS`), `test_zpl_qr_rejects_control_chars`, `@bru("BRU-ID-006") test_next_code_formats_and_registers` (mỗi prefix ra đúng độ rộng `NV-00001`, `TB-0001`, `KE-0001`, `TR-001`, `CN-00001`; có dòng Code Registry với ref đã truyền; `parse_scan(code)["type"]` đúng loại), `@bru("BRU-ID-006") test_next_code_skips_already_registered_numbers` (đăng ký tay số kế tiếp rồi gọi → ra số sau đó), `test_next_code_unknown_prefix_rejected`, `test_next_code_is_unique_under_repeated_calls` (200 lần, tập mã không trùng, liên tiếp), `@bru("BRU-ID-006") test_register_card_rules` (FR-M9-07.4: mã hợp lệ → prefix `CARD`; trùng → `CodeAlreadyIssuedError`; bắt đầu bằng `NV-` hoặc là GIAI → lỗi; chứa khoảng trắng/ký tự ngoài CSET82 → lỗi), `test_parse_scan_internal_codes_with_aim_prefix_and_noise` (Review Focus 2: `" ]Q1TB-0001\r\n"`, `"]d1NV-00012\t"`, `"\x1dKE-0001"` → nhận ra đúng; chuỗi lạ → `unknown`).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS toàn app; `check_architecture.py` sạch. **Step 5:** Commit `feat(core): QR nội bộ, cấp mã NV-/TB-/KE-/TR-/CN- tập trung, đăng ký thẻ có sẵn`.

### Task 2: Nhãn đối tượng — Label Template theo loại đối tượng và `core.print.render_object`

**Files:** Modify `tracecore/tracecore/doctype/label_template/label_template.json` (+ `.py`: kiểm render bằng ngữ cảnh mẫu theo `label_object`), `tracecore/core/print.py`, `tracecore/core/tests/test_print.py`, `tracecore/setup/label_templates.py`, `tracecore/translations/vi.csv`; Create `tracecore/setup/label_templates/object_qr.zpl.jinja`, `tracecore/patches/v0_1/create_object_label_templates.py` (+ `patches.txt`), test `tracecore/tracecore/doctype/label_template/test_object_templates.py`.

**Interfaces:**
- Consumes: `qr.zpl_qr`, `print.render`, `ensure_sample_templates` pattern (không ghi đè mẫu R10 đã sửa).
- Produces: `Label Template.label_object` có thêm `Equipment`, `Station`, `Roll`, `Employee Card`, `Location` (mẫu `Pack` giữ nguyên; trường `method` chỉ bắt buộc với `Pack`; chỉ một mẫu active cho mỗi (`label_object`, `method`, `language`) — với đối tượng khác `method` rỗng); mẫu mặc định `Object label - Equipment/Station/Roll/Employee Card/Location` 50×30 mm 300 dpi từ file `object_qr.zpl.jinja`; `setup.label_templates.sample_object_context(label_object) -> dict` (`code, title, subtitle, payload, is_test`); `print.object_context(label_object, code, title, subtitle="") -> dict`; `print.render_object(label_object: str, code: str, title: str, subtitle: str = "", printer: dict | None = None) -> str` (chọn mẫu active theo `label_object` + ngôn ngữ máy in, `unicode = printer.supports_unicode`, QR bằng `zpl_qr` của mẫu qua hàm trong ngữ cảnh; thiếu mẫu → `frappe.ValidationError` đã dịch). `ensure_object_templates() -> list[str]` (idempotent, không ghi đè).

- [ ] **Step 1:** Test: `test_object_templates_installed_by_patch_and_install` (5 mẫu, kích thước 50×30, 300 dpi, active), `test_object_templates_survive_reinstall` (sửa body rồi chạy lại → giữ bản đã sửa), `test_one_active_template_per_object` (mẫu thứ hai active cùng loại → lỗi), `test_method_required_only_for_pack`, `test_render_object_contains_qr_and_code` (bắt đầu `^XA`, kết thúc `^XZ`, chứa `^BQN`, `^FDQA,TB-0001`, mã người đọc), `test_render_object_sanitizes_and_folds` (Review Focus 5: tên `Máy ^FO hấp ~JA` → ZPL không có lệnh chèn, `unicode=False` bỏ dấu, `unicode=True` giữ dấu; số lệnh `^FO` bằng nhãn tên sạch), `test_render_object_missing_template_is_translated_error`, `test_broken_object_template_rejected_on_save` (kiểm render khi lưu như mẫu Pack).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; `bench --site test_site migrate`. **Step 4:** PASS (giữ nguyên test Pack/Printer của FEAT-018). **Step 5:** Commit `feat(print): mẫu nhãn QR theo loại đối tượng, render_object`.

### Task 3: Đường in từ server (hàng đợi Print Job → TCP 9100)

**Files:** Modify `tracecore/core/print.py` (hoặc tạo `tracecore/core/print_server.py` nếu `print.py` quá lớn — quyết định theo kích thước, ≤ 650 dòng), `tracecore/tracecore/doctype/print_job/print_job.json` (+ trạng thái `Sending`? — **không**: dùng `Queued` + `attempts`), `tracecore/hooks.py` (scheduler `all` hoặc `cron` quét job mồi), `tracecore/core/tests/test_print_server.py`, `tracecore/translations/vi.csv`.

**Interfaces:**
- Produces: `print.dispatch_job(job: str) -> dict` (`{"status": "Printed" | "Failed" | "Queued", "attempts": int}`; chỉ job `Queued` có `printer` có `host` và Printer `is_active`; mở socket tới `(host, port)` của **Printer** với timeout 5 s, gửi `payload.encode("utf-8")`, thành công → `ack(..., "Printed", "Printer", output_ref="host:port")`; lỗi `OSError` → `attempts += 1`, còn < 3 → giữ `Queued` + ghi `error`, đủ 3 → `ack(..., "Failed", "Printer", error=...)`); `print.enqueue_server_dispatch(job: str) -> None` (`frappe.enqueue(..., queue="short", enqueue_after_commit=True)`); `print.dispatch_pending(limit: int = 20) -> int` (quét job `Queued` quá 1 phút chưa có lần thử, gọi `dispatch_job`; scheduler mỗi phút, bỏ qua job của máy in chỉ-qua-agent). Port phải trong `1..65535`; `host` không rỗng; không cho host nằm ngoài Printer (không có tham số host/port ở bất kỳ hàm công khai nào).

- [ ] **Step 1:** Test (socket server giả cục bộ, không cần máy in thật): `test_dispatch_sends_payload_to_printer_host` (job Queued → server giả nhận đúng ZPL, job `Printed`, `output_ref` đúng), `test_dispatch_unreachable_printer_retries_then_fails` (Review Focus 3: cổng đóng → lần 1, 2 giữ `Queued` có `error`; lần 3 `Failed`; mỗi lần không treo quá timeout), `test_dispatch_ignores_agent_only_printer` (host rỗng → không gửi, job giữ nguyên), `test_dispatch_inactive_printer_does_nothing`, `test_dispatch_only_uses_printer_host_not_job_data` (job có `data` chứa host khác → không dùng), `test_dispatch_pending_picks_old_queued_jobs`, `test_dispatch_job_is_idempotent_for_printed_job` (job đã Printed → không gửi lại).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS; kiểm bằng `bandit` (SSRF: ghi chú `# nosec B310/B104` chỉ khi cần, có lý do). **Step 5:** Commit `feat(print): đường in từ server tới máy in nhãn qua TCP 9100 (ADR-006 dự phòng)`.

### Task 4: Hook vô hiệu mã khi ngừng sử dụng, RPC cấp mã cuộn, in nhãn đối tượng

**Files:** Create `tracecore/v1/codes.py`, `tracecore/v1/tests/test_codes_api.py`; Modify `tracecore/equipment/status.py` (+ test) — `Retired` gọi `code_registry.disable(name, reason)`; `tracecore/v1/print.py` (thêm `object_label`, `object_preview`) hoặc đặt trong `v1/codes.py` (giữ `v1.print.object_label` đúng tên ở plan); `tracecore/core/errors.py` (+ test); `tracecore/translations/vi.csv`.

**Interfaces:**
- Produces: `tracecore.v1.codes.issue_rolls(item, count, client_ts=None)` (`@idempotent`, roles TC R10/System Manager kiểm trước mọi ghi; `item` phải là Item nhóm Nhãn có `tc_compatible_method`; `count` 1–200; trả `{"ok": true, "codes": ["CN-00001", …], "item": item}`; cả loạt trong một transaction, lỗi giữa chừng rollback hết; sai Item → `ROLL_NOT_LABEL` 422 đã có; vượt giới hạn → `COUNT_OUT_OF_RANGE` 422). `tracecore.v1.print.object_label(label_object, code, printer=None, client_ts=None)` (`@idempotent`, R10/SM): tra đối tượng từ mã (Equipment `TB-`, Zone Station `TR-`, Item nhãn của cuộn `CN-`), kiểm mã `Active` (`Disabled` → `CODE_DISABLED` 409, đối tượng `Retired` → `EQUIPMENT_RETIRED` 409), `render_object`, tạo Print Job (`ref_doctype`/`ref_name` = đối tượng, `template`, `printer`) `Queued` rồi `enqueue_server_dispatch` khi máy in có `host`; máy in chỉ-agent → job `Waiting` + cảnh báo `PRINTER_AGENT_ONLY` (không phải lỗi HTTP); trả `{"ok": true, "print_job", "status", "warning"|null}`. `tracecore.v1.print.object_preview(label_object, code)` (đọc; R10/SM/R02): `{"ok": true, "png_b64", "zpl", "hri": code}` (PNG xem trước từ `qr.qr_png` ghép chữ như `_preview_png` của FEAT-001). Thêm mã lỗi: `CODE_DISABLED: 409`, `COUNT_OUT_OF_RANGE: 422` vào `HTTP_STATUS`.
- `equipment.status.set_status(..., "Retired", reason)` gọi `code_registry.disable(equipment, reason)` (core), Audit Log ghi đã có; không ảnh hưởng `Zone Station.is_active`.

- [ ] **Step 1:** Test: `@bru("BRU-ID-006") test_issue_rolls_sequential_registered_and_atomic` (Review Focus 1: 5 mã liên tiếp; Code Registry ref Item; lỗi giữa chừng — patch hàm ghi sổ ném lỗi ở mã thứ 3 → không còn mã nào của loạt), `test_issue_rolls_requires_r10_or_sm_before_any_write` (R04 → `PermissionError`, không có Idempotency Key/Audit), `test_issue_rolls_rejects_non_label_item_and_bad_count` (0, 201, Item bao gói), `test_issue_rolls_replay_same_key_same_codes`, `@bru("BRU-ID-006") test_retire_equipment_disables_tb_code` (FR-M9-07.2: Code Registry `Disabled` + lý do; `equipment.get` vẫn trả thiết bị + cảnh báo `EQUIPMENT_RETIRED`; không cấp lại mã), `test_zone_station_deactivation_keeps_code_active` (R4), `test_object_label_creates_job_and_dispatches_for_host_printer` (job `Queued`, enqueue gọi), `test_object_label_agent_only_printer_waits_with_warning`, `test_object_label_blocked_for_disabled_code_and_retired_equipment` (Review Focus 4: 409, Audit Reject), `test_object_label_unknown_code_rejected` (`SCAN_INVALID`/`*_NOT_FOUND` 404, Audit Reject), `test_object_label_requires_roles`, `test_object_preview_returns_png_zpl_and_hri`, `test_http_status_codes_new` (`CODE_DISABLED` 409, `COUNT_OUT_OF_RANGE` 422).
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS toàn app; e2e smoke FEAT-001/T4 không đổi (không chạy trên `test_site`). **Step 5:** Commit `feat(v1): cấp mã cuộn nhãn, in nhãn QR đối tượng, vô hiệu mã khi thiết bị ngừng sử dụng`.

### Task 5: Desk UI SCR-33

**Files:** Create `tracecore/public/js/tc_codes.js` (hàm dùng chung `tracecore.codes.print_dialog(frm, label_object, code, title, subtitle)`), `tracecore/equipment/doctype/equipment/equipment.js` (nút "In nhãn QR"), `tracecore/admin_reports/doctype/zone_station/zone_station.js` (nút "In nhãn QR" cho trạm), `tracecore/public/js/item.js` + hook `doctype_js = {"Item": "public/js/item.js"}` (nút "Cấp mã cuộn" cho Item nhóm Nhãn, R10/SM), `tracecore/hooks.py` (`app_include_js` cho `tc_codes.js`); list view bulk action "In nhãn QR" cho Equipment/Zone Station (`equipment_list.js`, `zone_station_list.js`); `tracecore/translations/vi.csv`.

Hành vi (kiểm được bằng tay/e2e):
1. Equipment/Zone Station form (bản ghi đã lưu, mã `Active`): nút "In nhãn QR" mở hộp thoại: xem trước PNG (từ `object_preview`), chọn máy in (Link Printer, gợi ý máy in có `host`), nút In → `object_label`; kết quả hiện trạng thái bằng chữ (Đã xếp hàng / Đang chờ agent kèm giải thích); mã `Disabled`/thiết bị `Retired` → nút bị ẩn và dòng chữ giải thích.
2. List view: chọn nhiều bản ghi → "In nhãn QR" (tối đa 50) → hộp thoại chọn máy in một lần, gửi tuần tự, tổng kết thành công/thất bại từng mã.
3. Item (nhóm Nhãn, R10/SM): nút "Cấp mã cuộn" → hộp thoại số lượng 1–200 → danh sách mã vừa cấp + nút "In tất cả" dùng cùng hộp thoại in; lỗi hiện `frappe.msgprint` (tiêu đề/lý do/hành động).
- Dùng `fetch` + `X-Idempotency-Key` mới mỗi lần + `client_ts` ISO có offset (mẫu `printer.js` FEAT-002); không chép bảng hằng số nghiệp vụ trong JS.

- [ ] **Step 1:** Test Python: `test_hooks_register_item_script_and_include_js` (`doctype_js["Item"]`, `app_include_js`). 
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; `bench build --app tracecore`. **Step 4:** PASS; `pre-commit run --all-files` (R3: không chuỗi tiếng Việt trong JS); kiểm tay 3 hành vi trên **dev site** `tracecore-dev.local` bằng Playwright (user R10 tạm, mật khẩu ngẫu nhiên file 600, xóa sau khi xong; máy in thử: Printer có `host` trỏ tới một socket giả cục bộ), ảnh vào workspace. **Step 5:** Commit `feat(ui): in nhãn QR đối tượng và cấp mã cuộn trên Desk`.

### Task 6: E2E, xác minh toàn nhánh, dừng chờ Codex

**Files:** Create `tests_e2e/test_desk_codes.py`; Modify `scripts/e2e_prepare.sh` (máy in thử có `host` + socket giả do test dựng; `TC_E2E_CODES_*`), `tracecore/setup/devdata.py` (+ `test_devdata.py`): `ensure_codes_demo()`, `tests_e2e/conftest.py`.

- [ ] **Step 1:** `devdata.ensure_codes_demo() -> dict` (idempotent; dev/test site; máy in demo `host=127.0.0.1` cổng do biến môi trường; thiết bị demo từ `ensure_equipment_demo`). Test Playwright (WEB 1366×768, user R10; socket TCP giả trong fixture nhận ZPL): `test_print_equipment_qr_label_reaches_printer` (hộp thoại xem trước, in, socket nhận ZPL chứa `^BQN` và `TB-`), `test_print_blocked_for_retired_equipment`, `test_issue_rolls_then_print_all` (cấp 3 mã cuộn, in cả loạt → 3 lệnh in), `test_bulk_print_from_list`. Không ngủ cố định; dọn dữ liệu bằng bản ghi tái sử dụng.
- [ ] **Step 2:** Xác minh (output thật vào PR): `run-tests --app tracecore --coverage`; `diff-cover coverage.xml --compare-branch=ade1a21 --fail-under=70`; `pre-commit run --all-files`; `check_architecture.py`; `pytest tracecore_agent`; `e2e_prepare.sh tracecore-dev.local` (**không** `test_site`) + toàn bộ `pytest tests_e2e` (dev site cổng 8100); toàn app trên site mới không Setup Wizard rồi xóa site; xác nhận `test_site` không có dữ liệu rò rỉ.
- [ ] **Step 3:** Bảng đối chiếu FR-M9-07 (.1–.4), FR-M5-01 "in QR", BRU-ID-006 → test; ghi rõ NV-/KE- chưa có UI (R6).
- [ ] **Step 4:** Review toàn nhánh bằng model mạnh, sửa lượt cuối nếu cần; **push, mở PR base nhánh FEAT-038 rồi DỪNG chờ Codex review** (không bắt đầu FEAT kế tiếp).
