"""E2E Desk cấu hình cơ số SCR-30 (FEAT-031; WEB 1366x768, user TC R02).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên site test) ghi TC_E2E_INSTR_* của
``devdata.ensure_instrument_demo``; FEAT-031 không thêm dữ liệu demo riêng (plan Task 4). Par Level không xóa được và
unique theo (loại, đối tượng, khoa) nên test dùng lại một Par Level tái xử lý của loại bộ demo ``set_type_steam``:
lần đầu tạo, các lần sau mở lại và đổi cơ số qua lại giữa hai giá trị. Dùng loại bộ (không dùng dụng cụ) để không
đồng bộ sang ``Instrument.max_cycles`` của dụng cụ demo mà ``test_desk_instrument.py`` dựa vào; Par Level của loại bộ
không ghi Set Unit (A-11 S1). Không ngủ cố định: mọi chờ đều theo phần tử hoặc response.
"""

import json

from playwright.sync_api import expect

CAPS = (480, 490)
REASON = "E2E: cập nhật cơ số theo IFU mới"


def find_par(page, set_type):
	filters = json.dumps(
		[
			["par_kind", "=", "Reprocessing"],
			["target_doctype", "=", "Instrument Set Type"],
			["target", "=", set_type],
		]
	)
	response = page.request.get("/api/resource/Par Level", params={"filters": filters})
	assert response.ok, response.text()
	rows = response.json()["data"]
	return rows[0]["name"] if rows else None


def api_par(page, name):
	response = page.request.get(f"/api/resource/Par Level/{name}")
	assert response.ok, response.text()
	return response.json()["data"]


def field(page, name):
	return page.locator(f".frappe-control[data-fieldname='{name}']")


def save_and_wait(page):
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as saved:
		page.keyboard.press("Control+s")
	return saved.value


def wait_form(page, name=None):
	if name:
		page.wait_for_function("(n) => window.cur_frm && cur_frm.doc.name === n", arg=name, timeout=30000)
	else:
		page.wait_for_function("() => window.cur_frm && cur_frm.doctype === 'Par Level'", timeout=30000)


def create_par(page, set_type, cap):
	page.goto("/app/par-level/new")
	wait_form(page)
	field(page, "par_kind").locator("select").select_option("Reprocessing")
	field(page, "target_doctype").locator("select").select_option("Instrument Set Type")
	target = field(page, "target").locator("input")
	target.fill(set_type)
	target.press("Escape")
	field(page, "max_cycles").locator("input").fill(str(cap))
	field(page, "source").locator("select").select_option("IFU")
	# không tự lấy cơ số từ IFU: gợi ý hiện ngay dưới trường
	expect(field(page, "max_cycles")).to_contain_text("IFU")
	response = save_and_wait(page)
	assert response.ok, response.text()
	page.wait_for_url("**/app/par-level/PAR-*", timeout=30000)
	return find_par(page, set_type)


def test_par_level_change_with_reason_and_history(instr_page, instr_demo):
	# FR-M8-01 (nhập tay, nguồn IFU), FR-M8-01.3 (lịch sử người, thời điểm, cũ/mới; lý do bắt buộc), AC-1, AC-4, AC-6
	page, set_type = instr_page, instr_demo["set_type_steam"]
	name = find_par(page, set_type) or create_par(page, set_type, CAPS[0])
	current = int(api_par(page, name)["max_cycles"] or 0)
	new_cap = CAPS[1] if current == CAPS[0] else CAPS[0]

	page.goto(f"/app/par-level/{name}")
	wait_form(page, name)
	expect(field(page, "used_html")).to_contain_text("Đã xác định" if current > 0 else "Chưa xác định")
	field(page, "max_cycles").locator("input").fill(str(new_cap))
	field(page, "max_cycles").locator("input").press("Tab")
	# đổi cơ số trên bản đã lưu → lý do bắt buộc ngay trên form (server vẫn kiểm)
	page.keyboard.press("Control+s")
	expect(page.locator(".modal.show", has_text="Lý do thay đổi")).to_be_visible(timeout=15000)
	page.locator(".modal.show .btn-modal-close").last.click()
	assert int(api_par(page, name)["max_cycles"] or 0) == current

	field(page, "reason").locator("textarea").fill(REASON)
	response = save_and_wait(page)
	assert response.ok, response.text()
	doc = api_par(page, name)
	assert doc["max_cycles"] == new_cap
	rows = [row for row in doc["history"] if row["field_name"] == "max_cycles"]
	assert (rows[-1]["old_value"], rows[-1]["new_value"], rows[-1]["reason"]) == (
		str(current),
		str(new_cap),
		REASON,
	)
	# bảng lịch sử chỉ đọc hiện dòng mới; lý do đã xóa trắng sau khi ghi lịch sử
	wait_form(page, name)
	history = field(page, "history")
	expect(history.locator(".grid-body .grid-row").last).to_contain_text(str(new_cap), timeout=15000)
	expect(history.locator(".grid-add-row")).to_be_hidden()
	assert not doc.get("reason")
