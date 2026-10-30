"""E2E Desk danh mục dụng cụ SCR-01 (FEAT-014; WEB 1366x768, user TC R02 / TC R10, trạm T4 TR-004).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên test_site) ngay trước mỗi lần chạy: ghi TC_E2E_INSTR_*
của ``devdata.ensure_instrument_demo``. Instrument không xóa được, Ngừng sử dụng và cấp mã GIAI là một chiều nên:
dụng cụ đủ dữ liệu (``full``) được dùng lại (đổi phương pháp rồi trả lại, khởi tạo bộ đếm lại cùng giá trị, đổi hãng
theo lần chạy); dụng cụ ``retire`` và ``giai`` bị dùng hết và được script thay bằng dụng cụ mới ở lần chuẩn bị sau.
Form mới (``/app/instrument/new``) không bao giờ được lưu. File IFU quá cỡ tạo tạm trong ``tmp_path`` của pytest.
"""

import json
import os
import re
import uuid

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
THUMB_SRC = re.compile(r"^/private/files/.*-thumb.*\.jpg$")
GIAI_CODE = re.compile(r"\d{4,12}I-\d{8}")
PDF_OVER_LIMIT = 20 * 1024 * 1024 + 1  # FR-M1-01.5: IFU tối đa 20 MiB


def open_form(page, name):
	page.goto(f"/app/instrument/{name}")
	panel = page.locator(".tc-instr-panel[data-panel='maintenance']")
	expect(panel).to_be_visible(timeout=30000)
	# panel hiện "Đang tải..." cho tới khi form_context trả về
	page.wait_for_function(
		"() => { const p = document.querySelector(\".tc-instr-panel[data-panel='maintenance']\");"
		" return p && !p.textContent.includes('...'); }"
	)
	return panel


def panel(page, name):
	return page.locator(f".tc-instr-panel[data-panel='{name}']")


def indicator(page):
	return page.locator(".page-head .indicator-pill").first


def custom_button(page, label, group=None):
	if group:
		page.locator(".inner-group-button", has_text=group).locator("button").first.click()
		page.locator(".inner-group-button .dropdown-menu a", has_text=label).first.click()
	else:
		page.locator(".page-actions .custom-actions button", has_text=label).first.click()


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


def api_doc(page, doctype, name):
	response = page.request.get(f"/api/resource/{doctype}/{name}")
	assert response.ok, response.text()
	return response.json()["data"]


def save(page):
	page.keyboard.press("Control+s")


def save_and_wait(page):
	"""Ctrl+S và chờ server lưu xong (savedocs trả 200)."""
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as saved:
		save(page)
	assert saved.value.ok, saved.value.text()


def scan_t4(page, set_id):
	page.goto("/app/station?station=TR-004")
	# FEAT-003: kiosk chỉ nhận quét sau khi nhân viên quét thẻ (phiên trạm)
	page.locator("#tc-card-input").fill(os.environ["TC_E2E_T4_CARD_ID"])
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	page.keyboard.type(set_id)
	page.keyboard.press("Enter")
	expect(page.locator(".tc-t4[data-view='ctx'] .tc-code").first).to_have_text(set_id, timeout=15000)


def test_create_instrument_missing_fields_then_duplicate_suggestion(instr_page, instr_demo):
	# FR-M1-01.1 (thiếu trường báo một lần, đủ tên trường) và FR-M1-01.4 (trùng mã → gợi ý mã kế tiếp còn trống)
	page = instr_page
	page.goto("/app/instrument/new")
	code = page.locator("[data-fieldname='instrument_code'] input")
	expect(code).to_be_visible(timeout=30000)

	save(page)
	missing = modal(page, "Tên dụng cụ")
	for label in ("Mã dụng cụ", "Tên dụng cụ", "Phân loại Spaulding", "Phương pháp"):
		expect(missing).to_contain_text(label)
	close_modals(page)

	# mã đã có, gõ chữ thường kèm khoảng trắng: chuẩn hóa rồi báo trùng và gợi ý
	code.fill(f"  {instr_demo['full'].lower()} ")
	check = page.locator(".tc-instr-code-check")
	expect(check).to_contain_text("đã tồn tại", timeout=10000)
	expect(check).to_contain_text("Gợi ý:")
	check.get_by_role("button", name="Dùng mã gợi ý").click()
	expect(code).to_have_value(re.compile(rf"^{re.escape(instr_demo['full'])}-\d{{2,}}$"))
	expect(check).to_contain_text("chưa được dùng", timeout=10000)
	suggested = code.input_value()

	save(page)
	missing = modal(page, "Tên dụng cụ")
	expect(missing).not_to_contain_text("Mã dụng cụ")
	close_modals(page)
	# chưa lưu gì: vẫn ở form mới, mã gợi ý chưa thành bản ghi
	assert page.url.endswith("/app/instrument/new") or "new-instrument" in page.url, page.url
	assert page.request.get(f"/api/resource/Instrument/{suggested}").status == 404


def test_ifu_over_limit_rejected_record_saved(instr_page, instr_demo, tmp_path):
	# FR-M1-01.5 + UC-01 E2: IFU 20 MiB + 1 byte bị từ chối có lý do; dụng cụ vẫn lưu được không kèm IFU
	page = instr_page
	big = tmp_path / "ifu-qua-co.pdf"
	header, tail = b"%PDF-1.4\n", b"\n%%EOF\n"
	big.write_bytes(header + b"%" * (PDF_OVER_LIMIT - len(header) - len(tail)) + tail)
	assert big.stat().st_size == PDF_OVER_LIMIT
	before = api_doc(page, "Instrument", instr_demo["full"])

	open_form(page, instr_demo["full"])
	page.locator("[data-fieldname='ifu'] button.btn-attach").first.click()
	uploader = page.locator(".modal.show .file-uploader")
	expect(uploader).to_be_visible(timeout=10000)
	uploader.locator("input[type=file]").first.set_input_files(str(big))
	with page.expect_response(lambda response: "upload_file" in response.url) as upload:
		page.locator(".modal.show .btn-primary").last.click()
	assert upload.value.status == 417, upload.value.status
	expect(modal(page, "20 MB")).to_contain_text("lưu dụng cụ không kèm IFU")
	close_modals(page)
	big.unlink()

	manufacturer = f"E2E Maker {uuid.uuid4().hex[:6].upper()}"
	page.locator("[data-fieldname='manufacturer'] input").fill(manufacturer)
	page.keyboard.press("Tab")
	page.wait_for_function("(value) => cur_frm.doc.manufacturer === value", arg=manufacturer)
	save_and_wait(page)
	saved = api_doc(page, "Instrument", instr_demo["full"])
	assert saved["manufacturer"] == manufacturer
	assert saved.get("ifu") == before.get("ifu")
	assert not saved.get("ifu"), saved.get("ifu")


def test_photo_thumbnail_visible_on_form_and_t4(instr_page, instr_demo, other_user_page):
	# FR-M1-01.5/.6: ảnh thực tế hiện trên form dụng cụ và trên lưới BOM SCR-08 (T4) bằng thumbnail riêng tư
	page = instr_page
	open_form(page, instr_demo["full"])
	image = panel(page, "media").locator("img")
	expect(image).to_have_count(1)
	expect(image).to_have_js_property("complete", True)
	src = image.get_attribute("src")
	assert THUMB_SRC.match(src), src
	width = image.evaluate("img => Math.max(img.naturalWidth, img.naturalHeight)")
	assert 0 < width <= 320, width
	assert src == api_doc(page, "Instrument", instr_demo["full"])["image_thumbnail"]

	t4 = other_user_page("TC_E2E_T4_USER", "TC_E2E_T4_PASSWORD")
	scan_t4(t4, instr_demo["set_plasma"])
	line = t4.locator(".tc-ins", has_text=instr_demo["full"])
	expect(line).to_have_count(1)
	photo = line.locator("img")
	expect(photo).to_have_attribute("src", src)
	expect(photo).to_have_js_property("complete", True)
	assert photo.evaluate("img => img.naturalWidth") > 0


def test_get_rejection_audit_log_survives_request(instr_page):
	# Final fix I-1: RPC GET từ chối (404) ghi Audit Log `Reject`; Frappe v15 rollback request GET trừ khi
	# flags.commit → dòng phải còn sau khi request kết thúc (đọc lại ở request khác)
	page = instr_page
	code = f"E2E-NOPE-{uuid.uuid4().hex[:8].upper()}"
	for method in ("get_image", "form_context"):
		response = page.request.get(
			f"/api/method/tracecore.v1.instrument.{method}", params={"instrument": f"{code}-{method}"}
		)
		assert response.status == 404, response.text()
		assert response.json()["message"]["error"]["code"] == "INSTRUMENT_NOT_FOUND"
	rows = page.request.get(
		"/api/resource/Audit Log",
		params={
			"filters": json.dumps([["action", "=", "Reject"], ["ref_name", "like", f"{code}-%"]]),
			"fields": json.dumps(["ref_name", "reason"]),
			"limit_page_length": 10,
		},
	)
	assert rows.ok, rows.text()
	found = sorted((row["ref_name"], row["reason"]) for row in rows.json()["data"])
	assert found == [
		(f"{code}-form_context", "INSTRUMENT_NOT_FOUND"),
		(f"{code}-get_image", "INSTRUMENT_NOT_FOUND"),
	], found


def test_form_keeps_other_buttons_and_renders_only_site_files(instr_page, instr_demo):
	# Final fix Minor 6/9: URL ảnh/thumbnail/IFU chỉ vào href/src khi là file của site (/private/files/, /files/);
	# tải lại form_context không xóa nút do Client Script khác thêm
	page = instr_page
	context_url = "**/api/method/tracecore.v1.instrument.form_context*"

	def poison(route):
		response = route.fetch()
		body = response.json()
		body["message"]["image"].update(
			image_url="javascript:alert(1)", thumbnail_url="https://evil.example/x.jpg", has_image=True
		)
		route.fulfill(response=response, json=body)

	page.route(context_url, poison)
	open_form(page, instr_demo["full"])
	media = panel(page, "media")
	expect(media).to_contain_text("Chưa có ảnh.")
	expect(media.locator("img")).to_have_count(0)
	page.unroute(context_url)

	# Client Script khác thêm nút ở refresh; IFU trỏ ra ngoài (chỉ trên trình duyệt, không lưu) → chỉ hiện chữ
	page.evaluate(
		"""() => frappe.ui.form.on("Instrument", {
			refresh(frm) { frm.add_custom_button("E2E other script", () => {}); },
		})"""
	)
	with page.expect_response(lambda response: "tracecore.v1.instrument.form_context" in response.url):
		page.evaluate("() => { cur_frm.doc.ifu = 'javascript:alert(1)'; cur_frm.refresh(); }")
	buttons = page.locator(".page-actions .custom-actions button")
	expect(buttons.filter(has_text="Lịch sử phiên bản")).to_have_count(1)
	expect(buttons.filter(has_text="E2E other script")).to_have_count(1)
	expect(media).to_contain_text("Chưa đính kèm IFU.")
	expect(media.locator("a[href^='javascript'], a[href^='http'], img[src^='http']")).to_have_count(0)
	expect(media.locator("img")).to_have_count(1)  # thumbnail thật (form_context không còn bị sửa)


def _drop_eo(page):
	"""Trả phương pháp về như dữ liệu demo (bỏ EO) nếu lần chạy trước để lại; lưu → thêm một phiên bản."""
	if page.evaluate("() => cur_frm.doc.compatible_methods.some((row) => row.method === 'EO')"):
		page.evaluate(
			"""async () => {
				cur_frm.doc.compatible_methods = cur_frm.doc.compatible_methods.filter((r) => r.method !== 'EO');
				cur_frm.refresh_field('compatible_methods');
				cur_frm.dirty();
				await cur_frm.save();
			}"""
		)
		close_modals(page)


def test_method_change_creates_version_and_bom_warning(instr_page, instr_demo):
	# FR-M1-01.3 + A-06 I1/I3: đổi tập phương pháp → phiên bản +1, cảnh báo liệt kê mọi loại bộ có BOM hiện hành
	page = instr_page
	open_form(page, instr_demo["full"])
	_drop_eo(page)
	open_form(page, instr_demo["full"])
	version = page.evaluate("() => cur_frm.doc.version_no")

	grid = page.locator("[data-fieldname='compatible_methods']")
	grid.locator(".grid-add-row").click()
	row = grid.locator(".grid-body .grid-row").last
	row.locator("[data-fieldname='method']").first.click()
	row.locator("select[data-fieldname='method']").select_option(label="EO")
	save(page)
	warning = modal(page, "phiên bản")
	for key in ("set_type_steam", "set_type_plasma"):
		expect(warning.locator(f"a[href='/app/instrument-set-type/{instr_demo[key]}']")).to_have_count(1)
	close_modals(page)
	page.wait_for_function(f"() => cur_frm.doc.version_no === {version + 1}")

	# trả lại như cũ: lại một phiên bản mới (lịch sử giữ đủ)
	_drop_eo(page)
	page.wait_for_function(f"() => cur_frm.doc.version_no === {version + 2}")
	open_form(page, instr_demo["full"])
	custom_button(page, "Lịch sử phiên bản")
	history = modal(page, "Lịch sử phiên bản").locator("table")
	rows = history.locator("tbody tr")
	expect(rows.filter(has_text="EO")).not_to_have_count(0)
	cells = rows.locator("td:first-child").all_inner_texts()
	assert [str(version + 1), str(version + 2)] == [c.strip() for c in cells][-2:], cells
	close_modals(page)


def test_init_counters_and_t4_reminder(instr_page, instr_demo, other_user_page):
	# A-06 I6 + FR-M1-09.1: khởi tạo bộ đếm bằng ngưỡng hiệu lực (ngưỡng nhóm) → T4 hiện nhắc Đến hạn (BRU-REP-014)
	page = instr_page
	interval = api_doc(page, "Instrument Group", instr_demo["group"])["maint_interval_cycles"]
	assert interval > 0
	maintenance = open_form(page, instr_demo["full"])
	expect(maintenance).to_contain_text("Nhóm dụng cụ")

	custom_button(page, "Khởi tạo bộ đếm", group="Bảo dưỡng")
	dialog = modal(page, "Khởi tạo bộ đếm")
	row = dialog.locator(".grid-body .grid-row", has_text=instr_demo["set_steam"])
	expect(row).to_have_count(1)
	row.locator("[data-fieldname='cycles_since']").first.click()
	row.locator("input[data-fieldname='cycles_since']").fill(str(interval))
	dialog.locator("[data-fieldname='reason'] textarea").fill("E2E: số chu trình theo sổ bảo dưỡng giấy")
	dialog.locator(".btn-primary", has_text="Khởi tạo bộ đếm").click()
	expect(dialog).to_be_hidden(timeout=15000)
	counter = panel(page, "maintenance").locator("tr", has_text=instr_demo["set_steam"])
	expect(counter).to_contain_text("Đến hạn", timeout=15000)
	expect(counter).to_contain_text(str(interval))

	t4 = other_user_page("TC_E2E_T4_USER", "TC_E2E_T4_PASSWORD")
	scan_t4(t4, instr_demo["set_steam"])
	reminder = t4.locator("[data-region='maint'] .tc-maint", has_text=instr_demo["full"])
	expect(reminder).to_have_count(1)
	expect(reminder).to_contain_text("Đến hạn")
	expect(reminder).to_contain_text(f"{interval}/{interval}")
	expect(t4.locator(SCAN_INPUT)).to_be_focused()


def test_retire_instrument_in_bom_requires_confirmation(instr_page, instr_demo):
	# UC-01 E3 + A-06 I13: dụng cụ trong BOM hiện hành → liệt kê BOM, phải xác nhận; chưa xác nhận thì chưa ghi gì
	page = instr_page
	code = instr_demo["retire"]
	assert api_doc(page, "Instrument", code)["status"] == "Active", "chạy lại scripts/e2e_prepare.sh"
	open_form(page, code)
	expect(indicator(page)).to_have_text("Đang dùng", timeout=15000)

	custom_button(page, "Ngừng sử dụng")
	reason = modal(page, "Lý do ngừng sử dụng")
	reason.locator("textarea").fill("E2E: gãy mũi kẹp")
	reason.locator(".btn-primary").click()
	confirm = modal(page, "BOM hiện hành")
	expect(
		confirm.locator(f"a[href='/app/instrument-set-type/{instr_demo['set_type_retire']}']")
	).to_have_count(1)
	assert api_doc(page, "Instrument", code)["status"] == "Active"

	confirm.locator(".btn-primary", has_text="Vẫn ngừng sử dụng").click()
	expect(indicator(page)).to_have_text("Ngừng sử dụng", timeout=15000)
	expect(page.locator(".page-actions .custom-actions button", has_text="Ngừng sử dụng")).to_have_count(0)
	assert api_doc(page, "Instrument", code)["status"] == "Retired"


def _set_giai_flag(page, on):
	page.goto("/app/tracecore-settings")
	box = page.locator("input[data-fieldname='enable_instrument_giai']")
	expect(box).to_be_visible(timeout=30000)
	if box.is_checked() == on:
		return
	box.set_checked(on)
	save_and_wait(page)
	assert api_doc(page, "TraceCore Settings", "TraceCore Settings")["enable_instrument_giai"] == int(on)


def test_giai_section_follows_feature_flag(r10_page, instr_demo):
	# FR-M1-02/.1/.3 + A-06 I7/I8: R10 bật cờ → cấp mã (server sinh, duy nhất) → xem trước; tắt cờ → chỉ đọc
	page = r10_page
	code = instr_demo["giai"]
	assert not api_doc(page, "Instrument", code).get("giai_code"), "chạy lại scripts/e2e_prepare.sh"
	_set_giai_flag(page, True)
	try:
		open_form(page, code)
		giai = panel(page, "giai")
		expect(giai).to_contain_text("Chưa có mã GIAI")
		custom_button(page, "Cấp mã GIAI", group="GIAI")
		page.locator(".modal.show .btn-primary").last.click()
		expect(giai.locator("span").first).to_have_text(GIAI_CODE, timeout=15000)
		assigned = giai.locator("span").first.inner_text()
		font = giai.locator("span").first.evaluate("el => getComputedStyle(el).fontFamily")
		assert "Courier New" in font, font
		assert api_doc(page, "Instrument", code).get("giai_code") == assigned

		custom_button(page, "Xem trước DataMatrix", group="GIAI")
		preview = modal(page, "DataMatrix")
		expect(preview.locator("img")).to_be_visible(timeout=15000)
		expect(preview).to_contain_text(assigned)
		close_modals(page)
	finally:
		_set_giai_flag(page, False)

	open_form(page, code)
	giai = panel(page, "giai")
	expect(giai).to_contain_text("Tính năng đang tắt")
	expect(giai).to_contain_text(assigned)
	for label in ("Cấp mã GIAI", "Ghi nhận khắc"):
		expect(page.locator(".inner-group-button .dropdown-menu a", has_text=label)).to_have_count(0)
	# quyết định Minor 5: cờ tắt vẫn xem trước được mã đã cấp (R10/SM) để đối chiếu
	custom_button(page, "Xem trước DataMatrix", group="GIAI")
	preview = modal(page, "DataMatrix")
	expect(preview.locator("img")).to_be_visible(timeout=15000)
	expect(preview).to_contain_text(assigned)
	close_modals(page)
