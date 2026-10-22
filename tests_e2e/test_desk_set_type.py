"""E2E Desk loại bộ và BOM theo phiên bản SCR-02 (FEAT-015; WEB 1366x768, user TC R02 / TC R10, trạm T4 TR-004).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên site test) ghi TC_E2E_SETTYPE_* của
``devdata.ensure_set_type_demo``. Loại bộ, dòng BOM và dụng cụ không xóa được nên dữ liệu cố định được dùng lại:
- loại bộ tạo mới (tạo loại bộ, ảnh bộ) mang mã ngẫu nhiên ``E…`` và ở lại site dev;
- ``set_type_edit`` nhận thêm phiên bản BOM hiệu lực hôm nay mỗi lần chạy; ghi đè hạn lưu được trả về 0;
- ``pack_r10`` đổi hạn lưu qua lại giữa hai giá trị;
- bộ ``set_inflight`` chỉ được mở ở T4 (không sinh Cycle ID) nên không bị tiêu thụ.
Không ngủ cố định: mọi chờ đều theo phần tử, response hoặc điều kiện JS.
"""

import re
import struct
import uuid
import zlib

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
LISTBOX = "ul[role=listbox]:not([hidden]) > *"  # gợi ý awesomplete của Link (DIV, không phải LI)
COUNT_SHEET = "tracecore.v1.set_type.count_sheet"


# --- Tiện ích ---------------------------------------------------------------------------------------------------


def new_code():
	"""Mã loại bộ mới 8 ký tự [A-Z0-9] (2-8 ký tự theo luật mã)."""
	return "E" + uuid.uuid4().hex[:7].upper()


def png_bytes(rgb, size=64):
	"""Ảnh PNG đặc một màu (chỉ dùng thư viện chuẩn; CI e2e không cài Pillow)."""
	raw = b"".join(b"\x00" + bytes(rgb) * size for _row in range(size))

	def chunk(kind, data):
		body = kind + data
		return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

	header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
	return (
		b"\x89PNG\r\n\x1a\n"
		+ chunk(b"IHDR", header)
		+ chunk(b"IDAT", zlib.compress(raw))
		+ chunk(b"IEND", b"")
	)


def modal(page, text):
	dialog = page.locator(".modal.show", has_text=text).last
	expect(dialog).to_be_visible(timeout=15000)
	return dialog


def close_modals(page):
	for _attempt in range(4):
		shown = page.locator(".modal.show")
		if not shown.count():
			return
		shown.last.locator(".btn-modal-close").first.click()
		expect(shown).to_have_count(max(shown.count() - 1, 0))


def custom_button(page, label, group=None):
	if group:
		page.locator(".inner-group-button", has_text=group).locator("button").first.click()
		page.locator(".inner-group-button .dropdown-menu a", has_text=label).first.click()
	else:
		page.locator(".page-actions .custom-actions button", has_text=label).first.click()


def call_get(page, method, **params):
	response = page.request.get(f"/api/method/{method}", params=params)
	assert response.ok, response.text()
	return response.json()["message"]


def api_doc(page, doctype, name):
	response = page.request.get(f"/api/resource/{doctype}/{name}")
	assert response.ok, response.text()
	return response.json()["data"]


def versions(page, set_type):
	return call_get(page, "tracecore.v1.set_type.form_context", set_type=set_type)["versions"]


def open_set_type(page, name):
	"""Mở form loại bộ và chờ form_context + BOM của phiên bản đang xem đã vẽ."""
	page.goto(f"/app/instrument-set-type/{name}")
	page.wait_for_function(
		"(name) => window.cur_frm && cur_frm.doc.name === name && cur_frm.tc_ctx"
		" && cur_frm.tc_ctx.set_type === name && (cur_frm.tc_view || !cur_frm.tc_ctx.versions.length)",
		arg=name,
		timeout=30000,
	)


def show_tab(page, label):
	page.locator(".form-tabs .nav-link", has_text=label).first.click()


def save_and_wait(page):
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as saved:
		page.keyboard.press("Control+s")
	return saved.value


def line_rows(dialog):
	return dialog.locator("tr.tc-st-line")


def set_line(dialog, index, code, qty=None):
	row = line_rows(dialog).nth(index)
	field = row.locator(".tc-st-instrument input")
	field.fill(code)
	blur(dialog)  # đóng gợi ý và phát change (Escape sẽ đóng cả hộp thoại); server kiểm từng dòng khi lưu
	expect(row.locator(".tc-st-code")).to_have_text(code)
	if qty is not None:
		row.locator(".tc-st-qty").fill(str(qty))


def blur(dialog):
	"""Bấm vào tiêu đề hộp thoại: rời ô đang nhập (Link/Date phát change, đóng gợi ý/lịch) mà không đóng hộp thoại."""
	dialog.locator(".modal-title").click()


def error_cell(dialog, index):
	return dialog.locator("tbody").nth(index).locator("tr.tc-st-errors")


def user_date(page, offset_days):
	"""Ngày hôm nay + `offset_days` theo định dạng người dùng (dd-mm-yyyy / dd/mm/yyyy theo System Settings)."""
	return page.evaluate(
		"(days) => frappe.datetime.str_to_user(frappe.datetime.add_days(frappe.datetime.get_today(), days))",
		offset_days,
	)


# --- Test --------------------------------------------------------------------------------------------------------


def test_create_set_type_requires_bom_and_compatible_lines(settype_page, settype_demo):
	# FR-M1-03.1 (tạo cùng BOM v1, BOM rỗng bị chặn), FR-M1-03.3 (dụng cụ chỉ Plasma lỗi tại dòng),
	# FR-M1-03.6 (dụng cụ đã Ngừng sử dụng), AC-1..AC-3; lỗi chặn là khối đỏ inline, không lưu gì
	page, demo = settype_page, settype_demo
	code = new_code()
	page.goto("/app/instrument-set-type/new")
	page.wait_for_function(
		"() => window.cur_frm && cur_frm.is_new() && cur_frm.tc_st_new_mode", timeout=30000
	)
	page.evaluate(
		"""(v) => cur_frm.set_value({type_code: v.code, set_type_name: 'E2E ' + v.code, method: 'Steam',
			department: v.department, default_pack_type: v.pack})""",
		{"code": code, "department": demo["department"], "pack": demo["pack_short"]},
	)
	page.locator(".page-actions .primary-action", has_text="Lưu và tạo BOM v1").click()
	dialog = modal(page, "Tạo loại bộ")

	dialog.locator(".modal-footer .btn-primary", has_text="Tạo loại bộ").click()
	expect(dialog.locator(".alert-danger")).to_contain_text("BOM rỗng", timeout=15000)
	assert page.request.get(f"/api/resource/Instrument Set Type/{code}").status == 404

	set_line(dialog, 0, demo["plasma"])
	dialog.locator(".tc-st-add").click()
	set_line(dialog, 1, demo["retired"])
	dialog.locator(".tc-st-add").click()
	set_line(dialog, 2, demo["steam_1"], qty=2)
	dialog.locator(".modal-footer .btn-primary", has_text="Tạo loại bộ").click()
	expect(dialog.locator(".alert-danger")).to_contain_text("2 dòng BOM có lỗi", timeout=15000)
	expect(error_cell(dialog, 0)).to_be_visible()
	expect(error_cell(dialog, 0)).to_contain_text("không tương thích")
	expect(error_cell(dialog, 0)).to_contain_text(demo["plasma"])
	expect(error_cell(dialog, 1)).to_contain_text("ngừng sử dụng")
	expect(error_cell(dialog, 2)).to_be_hidden()
	assert page.request.get(f"/api/resource/Instrument Set Type/{code}").status == 404

	# bỏ hai dòng lỗi → tạo được loại bộ cùng BOM v1
	for _index in range(2):
		line_rows(dialog).first.locator(".tc-st-remove").click()
	expect(line_rows(dialog)).to_have_count(1)
	dialog.locator(".modal-footer .btn-primary", has_text="Tạo loại bộ").click()
	page.wait_for_url(f"**/app/instrument-set-type/{code}", timeout=30000)
	bom = call_get(page, "tracecore.v1.set_type.bom", set_type=code)
	assert (bom["bom_version"], bom["status"]) == (1, "Effective"), bom
	assert [(line["instrument"], line["qty"]) for line in bom["lines"]] == [(demo["steam_1"], 2)]


def test_pack_type_without_shelf_life_not_offered_and_override_shorter_only(settype_page, settype_demo):
	# FR-M1-03.5 + BRU-REP-009: chỉ loại gói có hạn lưu được gợi ý (kèm số ngày); FR-M1-03.4: ghi đè chỉ ngắn hơn
	page, demo = settype_page, settype_demo
	page.goto("/app/instrument-set-type/new")
	page.wait_for_function("() => window.cur_frm && cur_frm.is_new()", timeout=30000)
	pack = page.locator("[data-fieldname='default_pack_type'] input")
	pack.click()
	pack.fill("DEMO-F15-GOI")
	options = page.locator(LISTBOX)
	expect(options.filter(has_text=demo["pack_short"])).to_have_count(1, timeout=15000)
	texts = options.all_inner_texts()
	assert any(demo["pack_short"] in text and "30 ngày" in text for text in texts), texts
	assert any(demo["pack_long"] in text and "180 ngày" in text for text in texts), texts
	assert not any(demo["pack_none"] in text for text in texts), texts
	pack.press("Escape")

	edit = demo["set_type_edit"]
	open_set_type(page, edit)
	show_tab(page, "Thông tin")
	shelf = page.locator("[data-fieldname='shelf_life_html']")
	expect(shelf).to_contain_text("Áp dụng: 180 ngày")
	override = page.locator("[data-fieldname='shelf_life_days'] input")
	try:
		override.fill("200")
		override.press("Tab")
		saved = save_and_wait(page)
		assert saved.status == 417, saved.status
		expect(modal(page, "ngắn hơn 180 ngày")).to_be_visible()
		close_modals(page)
		assert api_doc(page, "Instrument Set Type", edit)["shelf_life_days"] == 0

		override.fill("20")
		override.press("Tab")
		assert save_and_wait(page).ok
		expect(shelf).to_contain_text("Áp dụng: 20 ngày", timeout=15000)
		assert api_doc(page, "Instrument Set Type", edit)["shelf_life_days"] == 20
	finally:
		# trả về không ghi đè cho lần chạy sau
		open_set_type(page, edit)
		if page.evaluate("() => cur_frm.doc.shelf_life_days"):
			show_tab(page, "Thông tin")
			page.locator("[data-fieldname='shelf_life_days'] input").fill("0")
			page.locator("[data-fieldname='shelf_life_days'] input").press("Tab")
			assert save_and_wait(page).ok
	expect(page.locator("[data-fieldname='shelf_life_html']")).to_contain_text(
		"Áp dụng: 180 ngày", timeout=15000
	)


def _edit_dialog(page, set_type):
	open_set_type(page, set_type)
	show_tab(page, "Chi tiết")
	custom_button(page, "Sửa BOM", group="BOM")
	return modal(page, f"Sửa BOM của {set_type}")


def _bump_first_qty(dialog, by=1):
	qty = line_rows(dialog).first.locator(".tc-st-qty")
	value = int(qty.input_value()) % 900 + by
	qty.fill(str(value))
	return value


def test_edit_bom_creates_version_with_effective_date_and_compare(settype_page, settype_demo):
	# FR-M1-04 (phiên bản mới, không sửa đè), FR-M1-04.4 (ngày quá khứ không chọn được / bị chặn),
	# FR-M1-04.3 + UC-02 A1 (lưu xong mở so sánh, nhãn chữ), OTH-RET-002 (phiên bản cũ còn nguyên)
	page, demo = settype_page, settype_demo
	set_type = demo["set_type_edit"]
	before = versions(page, set_type)
	latest = before[0]["bom_version"]
	dialog = _edit_dialog(page, set_type)
	expect(dialog).to_contain_text(f"Lưu sẽ tạo BOM phiên bản {latest + 1}")

	date_input = dialog.locator("[data-fieldname='effective_from'] input")
	min_date = date_input.evaluate(
		"el => { const p = $(el).data('datepicker'); return p && p.opts.minDate"
		" ? frappe.datetime.obj_to_str(p.opts.minDate) : null; }"
	)
	assert min_date == page.evaluate("() => frappe.datetime.get_today()"), min_date
	new_qty = _bump_first_qty(dialog)
	date_input.fill(user_date(page, -1))
	blur(dialog)
	dialog.locator("[data-fieldname='reason'] textarea").fill("E2E: đổi số lượng kéo")
	dialog.locator(".modal-footer .btn-primary", has_text="Lưu phiên bản mới").click()
	expect(dialog.locator(".alert-danger")).to_contain_text("đã qua", timeout=15000)
	assert versions(page, set_type)[0]["bom_version"] == latest

	date_input.fill(user_date(page, 0))
	blur(dialog)
	dialog.locator(".modal-footer .btn-primary", has_text="Lưu phiên bản mới").click()
	compare = modal(page, "Đổi số lượng")
	expect(compare).to_contain_text(f"phiên bản {latest}")
	expect(compare).to_contain_text(f"phiên bản {latest + 1}")
	row = compare.locator("tbody tr", has_text=demo["steam_1"])
	expect(row.locator("td").first).to_have_text("Đổi số lượng")
	expect(row).to_contain_text(f"→ {new_qty}")
	close_modals(page)

	after = versions(page, set_type)
	assert after[0]["bom_version"] == latest + 1
	assert after[0]["status"] == "Effective"
	assert after[0]["reason"] == "E2E: đổi số lượng kéo"
	assert [row["bom_version"] for row in after[1:]] == [row["bom_version"] for row in before]
	old = call_get(page, "tracecore.v1.set_type.bom", set_type=set_type, version=latest)
	assert old["status"] == "Superseded", old["status"]
	# danh sách phiên bản trên form có trạng thái bằng chữ
	open_set_type(page, set_type)
	show_tab(page, "Chi tiết")
	expect(page.locator("[data-fieldname='bom_html']")).to_contain_text("Đang hiệu lực")
	expect(page.locator("[data-fieldname='bom_html']")).to_contain_text("Đã thay thế")


def test_concurrent_edit_shows_conflict(settype_page, settype_demo, other_user_page):
	# S4 + Review Focus 3: hai trang cùng sửa từ một phiên bản → người sau BOM_VERSION_CONFLICT, tải lại được
	page, demo = settype_page, settype_demo
	set_type = demo["set_type_edit"]
	other = other_user_page("TC_E2E_SETTYPE_USER", "TC_E2E_SETTYPE_PASSWORD")
	latest = versions(page, set_type)[0]["bom_version"]
	first = _edit_dialog(page, set_type)
	second = _edit_dialog(other, set_type)

	_bump_first_qty(second, by=2)
	second.locator("[data-fieldname='reason'] textarea").fill("E2E: người sửa thứ hai lưu trước")
	second.locator(".modal-footer .btn-primary", has_text="Lưu phiên bản mới").click()
	expect(modal(other, "Đổi số lượng")).to_be_visible()  # lưu xong mở so sánh

	_bump_first_qty(first, by=1)
	first.locator("[data-fieldname='reason'] textarea").fill("E2E: người sửa thứ nhất lưu sau")
	first.locator(".modal-footer .btn-primary", has_text="Lưu phiên bản mới").click()
	block = first.locator(".alert-danger")
	expect(block).to_contain_text(f"Có phiên bản mới hơn (v{latest + 1})", timeout=15000)
	assert [row["bom_version"] for row in versions(page, set_type)][:1] == [latest + 1]

	first.locator(".tc-st-reload", has_text="Tải lại BOM").click()
	expect(first).to_be_hidden()
	page.wait_for_function(
		"(v) => cur_frm.tc_ctx && cur_frm.tc_ctx.versions[0].bom_version === v", arg=latest + 1, timeout=15000
	)
	history = versions(page, set_type)
	assert history[0]["reason"] == "E2E: người sửa thứ hai lưu trước"
	assert "E2E: người sửa thứ nhất lưu sau" not in [row["reason"] for row in history]


def test_count_sheet_pdf_downloads(settype_page, settype_demo):
	# FR-M1-03 + EI-HW-007 (phiếu kiểm đếm PDF theo phiên bản, S9): tên file <TYPE_CODE>-BOM-V<n>.pdf, mở được
	page, demo = settype_page, settype_demo
	set_type, version = demo["set_type"], int(demo["effective_version"])
	open_set_type(page, set_type)
	custom_button(page, "In phiếu kiểm đếm", group="BOM")
	dialog = modal(page, "In phiếu kiểm đếm")
	expect(dialog.locator("select[data-fieldname='version']")).to_have_value(str(version))
	with page.context.expect_event("request", lambda request: COUNT_SHEET in request.url) as opened:
		dialog.locator(".modal-footer .btn-primary", has_text="Mở PDF").click()
	url = opened.value.url
	assert f"set_type={set_type}" in url and f"version={version}" in url, url

	response = page.request.get(url)
	assert response.ok, response.status
	assert response.headers["content-type"].startswith("application/pdf"), response.headers
	disposition = response.headers.get("content-disposition", "")
	assert f"{set_type}-BOM-V{version}.pdf" in disposition, disposition
	body = response.body()
	assert body.startswith(b"%PDF-"), body[:16]
	assert b"%%EOF" in body[-1024:]
	assert len(re.findall(rb"/Type\s*/Page[^s]", body)) >= 1
	for extra in page.context.pages[1:]:
		extra.close()


def _create_set_type_via_desk(page, demo, code):
	"""Tạo loại bộ cùng BOM v1 qua đúng RPC của form (khóa idempotency + client_ts do tc_codes.js đặt)."""
	page.goto("/app/instrument-set-type")
	page.wait_for_function("() => window.tracecore && tracecore.codes", timeout=30000)
	result = page.evaluate(
		"""async (v) => tracecore.codes.send('tracecore.v1.set_type_admin.create', tracecore.codes.new_request({
			header: {type_code: v.code, set_type_name: 'E2E photos ' + v.code, method: 'Steam',
				department: v.department, default_pack_type: v.pack},
			lines: [{instrument: v.instrument, qty: 1, position: 1}],
		}))""",
		{
			"code": code,
			"department": demo["department"],
			"pack": demo["pack_short"],
			"instrument": demo["steam_1"],
		},
	)
	assert result["ok"], result


def _upload_photo(page, field, name, content):
	page.locator(f"[data-fieldname='{field}'] button.btn-attach").first.click()
	uploader = page.locator(".modal.show .file-uploader")
	expect(uploader).to_be_visible(timeout=10000)
	uploader.locator("input[type=file]").first.set_input_files(
		{"name": name, "mimeType": "image/png", "buffer": content}
	)
	with page.expect_response(lambda response: "upload_file" in response.url) as upload:
		page.locator(".modal.show .btn-primary").last.click()
	assert upload.value.ok, upload.value.text()
	page.wait_for_function("(f) => Boolean(cur_frm.doc[f])", arg=field)


def test_set_type_photos_upload_and_reorder(settype_page, settype_demo):
	# FR-M1-03 + FR-M1-03.2 (1-3 ảnh bộ đã xếp, S6): tải lên qua luật file + thumbnail, đổi thứ tự có kiểm trùng vị trí
	page, demo = settype_page, settype_demo
	code = new_code()
	_create_set_type_via_desk(page, demo, code)
	open_set_type(page, code)
	show_tab(page, "Thông tin")
	tray = page.locator("[data-fieldname='tray_html']")
	expect(tray).to_contain_text("Chưa có ảnh")
	colors = ((200, 40, 40), (40, 160, 60), (40, 60, 200))
	for index, (field, rgb) in enumerate(
		zip(("tray_image", "tray_image_2", "tray_image_3"), colors, strict=True)
	):
		_upload_photo(page, field, f"{code.lower()}-khay-{index + 1}.png", png_bytes(rgb))
	assert save_and_wait(page).ok
	open_set_type(page, code)
	show_tab(page, "Thông tin")
	expect(tray.locator("img")).to_have_count(3, timeout=15000)
	before = api_doc(page, "Instrument Set Type", code)
	for field in ("tray_image", "tray_image_2", "tray_image_3"):
		assert before[field].startswith("/private/files/"), before[field]
		assert before[field.replace("image", "thumbnail")], field

	tray.locator(".tc-st-reorder").click()
	dialog = modal(page, "Lưu thứ tự")
	dialog.locator("select[data-fieldname='position_1']").select_option("2")
	dialog.locator(".modal-footer .btn-primary", has_text="Lưu thứ tự").click()
	expect(dialog.locator(".alert-danger")).to_contain_text("Hai ảnh trùng vị trí")

	dialog.locator("select[data-fieldname='position_1']").select_option("3")
	dialog.locator("select[data-fieldname='position_3']").select_option("1")
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as saved:
		dialog.locator(".modal-footer .btn-primary", has_text="Lưu thứ tự").click()
	assert saved.value.ok
	after = api_doc(page, "Instrument Set Type", code)
	assert (after["tray_image"], after["tray_image_2"], after["tray_image_3"]) == (
		before["tray_image_3"],
		before["tray_image_2"],
		before["tray_image"],
	)


def test_item_pack_shelf_life_set_by_r10(codes_page, settype_demo):
	# FR-M2-07.8 + BRU-REP-009 (S7): R10 sửa hạn lưu loại gói trên form Item, lý do bắt buộc, áp cho gói đóng sau
	page, pack = codes_page, settype_demo["pack_r10"]
	current = api_doc(page, "Item", pack)["tc_shelf_life_days"]
	new_days = 60 if current != 60 else 120
	page.goto(f"/app/item/{pack}")
	page.wait_for_function("(p) => window.cur_frm && cur_frm.doc.name === p", arg=pack, timeout=30000)
	custom_button(page, "Đặt hạn lưu")
	dialog = modal(page, f"Đặt hạn lưu cho {pack}")
	dialog.locator("[data-fieldname='days'] input").fill(str(new_days))
	dialog.locator(".modal-footer .btn-primary", has_text="Lưu hạn lưu").click()
	expect(dialog.locator(".alert-danger")).to_be_visible(timeout=15000)  # thiếu lý do: REASON_REQUIRED
	assert api_doc(page, "Item", pack)["tc_shelf_life_days"] == current

	dialog.locator("[data-fieldname='reason'] textarea").fill("E2E: nhà cung cấp đổi vật liệu gói")
	dialog.locator(".modal-footer .btn-primary", has_text="Lưu hạn lưu").click()
	saved = modal(page, "Đã lưu hạn lưu")
	expect(saved).to_contain_text(f"{current} → {new_days} ngày")
	close_modals(page)
	assert api_doc(page, "Item", pack)["tc_shelf_life_days"] == new_days


def test_in_flight_set_keeps_old_bom_at_t4(settype_page, settype_demo, other_user_page):
	# FR-M1-04.1 + AC-9 (S3): bộ đang giữa chu trình ghim phiên bản cũ; SCR-08 (T4) hiện BOM đã ghim dù phiên bản
	# mới hơn đang hiệu lực
	page, demo = settype_page, settype_demo
	set_type, set_id = demo["set_type_inflight"], demo["set_inflight"]
	pinned, effective = int(demo["inflight_version"]), int(demo["inflight_effective"])
	assert pinned < effective, "chạy lại scripts/e2e_prepare.sh"
	assert call_get(page, "tracecore.v1.set_type.bom", set_type=set_type)["bom_version"] == effective

	def names(version):
		bom = call_get(page, "tracecore.v1.set_type.bom", set_type=set_type, version=version)
		return sorted(line["instrument_name"] for line in bom["lines"])

	assert names(pinned) != names(effective)
	t4 = other_user_page("TC_E2E_T4_USER", "TC_E2E_T4_PASSWORD")
	t4.goto("/app/station?station=TR-004")
	t4.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	t4.keyboard.type(set_id)
	t4.keyboard.press("Enter")
	expect(t4.locator(".tc-t4[data-view='ctx'] .tc-code").first).to_have_text(set_id, timeout=15000)
	expect(t4.locator("h3", has_text="Thành phần bộ")).to_contain_text(f"BOM v{pinned})")
	shown = sorted(t4.locator(".tc-ins .tc-ins-name").all_inner_texts())
	assert shown == names(pinned), shown
	expect(t4.locator(SCAN_INPUT)).to_be_focused()
