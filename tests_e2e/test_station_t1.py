"""E2E màn T1 tiếp nhận SCR-05 (STN 1366x768) và SCR-34 (PDA 412x915), FEAT-019.

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy rồi chạy CẢ file này theo thứ tự: ghi sổ phiếu làm
bộ ``sets`` + ``set_new`` (luồng STN) và ``sets_pda`` (luồng PDA) chuyển sang Chờ rửa, nên test sau không dùng thứ test
trước đã tiêu thụ (``devdata.ensure_t1_demo`` thay bằng bộ mới ở lần chuẩn bị sau). Các test lỗi chỉ đọc.
"""

import re

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
# danh sách bộ của phiếu đang mở: không tính bảng dòng BOM của bộ đang kiểm và bảng phiếu hôm nay
LIST_ROWS = ".tc-t1 :not(.tc-t1-today) > .tc-t2-table:not(.tc-t1-lines) tbody tr"


def scan(page, raw):
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def scan_settled(page, raw):
	"""Quét rồi chờ RPC trả lời và ô quét lấy lại focus (kiosk xếp hàng mã quét khi đang chờ máy chủ)."""
	scan(page, raw)
	expect(page.locator(".tc-t1 .tc-loading")).to_have_count(0, timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def assert_full_alert(alert):
	"""alert-error inline đủ ba phần theo thứ tự kết quả → lý do → hành động (design.md)."""
	expect(alert).to_be_visible(timeout=15000)
	for part in (".tc-alert-title", ".tc-alert-reason", ".tc-alert-action"):
		expect(alert.locator(part)).not_to_be_empty()
	order = alert.evaluate(
		"(el) => Array.from(el.querySelectorAll('.tc-alert-title, .tc-alert-reason, .tc-alert-action'))"
		".map((node) => node.className)"
	)
	assert order == ["tc-alert-title", "tc-alert-reason", "tc-alert-action"], order


def open_receipt(page, demo):
	scan_settled(page, demo["deliverer_card"])
	expect(page.locator(".tc-t1-head")).to_contain_text(demo["deliverer_name"], timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("Set ID"))


def tick_all(page):
	"""A-94: số lượng thực tế điền sẵn theo BOM, không phải tick."""
	lines = page.locator(".tc-t1-item .tc-t1-actual")
	expect(lines.first).to_be_visible(timeout=15000)
	total = lines.count()
	assert total >= 1
	return total


def confirm_set(page):
	page.locator("[data-action='confirm-set']").click()
	expect(page.locator(".tc-t1 .tc-loading")).to_have_count(0, timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def set_status(page, set_id):
	response = page.request.get(f"/api/resource/Set%20Unit/{set_id}")
	assert response.ok, response.text()
	data = response.json()["data"]
	return data["status"], data["current_cycle_no"]


def test_t1_scan_box_on_top_and_waits_for_the_deliverer_card(t1_page):
	page = t1_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("thẻ nhân viên"))
	scan_box = page.locator(SCAN_INPUT).bounding_box()
	result_box = page.locator(".tc-result .tc-t1").bounding_box()
	assert scan_box["y"] < result_box["y"], (scan_box, result_box)
	expect(page.locator("[data-action='manual']")).to_be_visible()


def test_t1_unknown_codes_and_refused_sets_show_inline_red_alerts(t1_page, t1_demo):
	page = t1_page
	scan_settled(page, "NOT-A-CARD")  # chưa có phiếu: mã lạ không mở phiếu
	assert_full_alert(page.locator(".tc-result[data-state='error'] .tc-alert-error"))
	expect(page.locator(".tc-t1-head")).to_have_count(0)

	open_receipt(page, t1_demo)
	scan_settled(page, t1_demo["set_sterile"])  # FR-M2-02.1: bộ Vô khuẩn bị từ chối kèm lý do
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-reason")).to_contain_text(t1_demo["set_sterile"])
	expect(page.locator("[data-action='force']")).to_have_count(0)  # chỉ R02 thấy nút cưỡng bức
	for raw in (t1_demo["set_unknown"], "XYZ-123", "TB-0001"):
		scan_settled(page, raw)  # FR-M2-01.5: mã không hợp lệ
		assert_full_alert(page.locator(".tc-result[data-state='error'] .tc-alert-error"))
	# lỗi chặn không dùng modal hay toast, phiếu vẫn mở và chưa thêm bộ nào
	expect(page.locator(".modal.show, .msgprint, .toast, [role='dialog']:visible")).to_have_count(0)
	expect(page.locator(LIST_ROWS)).to_have_count(0)
	expect(page.locator(".tc-t1-head")).to_be_visible()


def test_t1_deliverer_without_card_picks_department_and_name(t1_page, t1_demo):
	page = t1_page
	page.locator("[data-action='manual']").click()
	page.locator("#tc-t1-dept").select_option(value=t1_demo["department"])
	page.locator("#tc-t1-name").fill("Nguyễn Văn Thử")
	page.locator("[data-action='manual-open']").click()
	head = page.locator(".tc-t1-head")
	expect(head).to_contain_text("Nguyễn Văn Thử", timeout=15000)
	expect(head).to_contain_text("Cần cấp thẻ")  # FR-M2-01.7: R02 cấp thẻ sau
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t1_receipt_of_several_sets_end_to_end(t1_page, t1_demo):
	page = t1_page
	first, second, third = t1_demo["sets"]
	extra = t1_demo["set_new"]
	open_receipt(page, t1_demo)

	# bộ 1: BOM có ảnh, số thực tế điền sẵn, Xác nhận bộ
	scan_settled(page, first)
	item = page.locator(".tc-t1-item")
	expect(item.locator(".tc-code")).to_have_text(first)
	expect(item.locator(".tc-t1-lines tbody tr")).to_have_count(4)
	expect(item.locator(".tc-t1-lines img.tc-photo")).to_have_count(4)  # mỗi dụng cụ có ảnh
	tick_all(page)
	confirm_set(page)
	expect(page.locator(LIST_ROWS)).to_have_count(1)
	expect(page.locator(LIST_ROWS).first).to_contain_text("Đã xác nhận")
	expect(page.locator(".tc-t1 .tc-alert-ok")).to_contain_text(first)

	# bộ 2: sửa số thực tế một dòng và ghi chú bất thường → xác nhận không bị nhắc
	scan_settled(page, second)
	page.locator(".tc-t1-item .tc-t1-actual").nth(0).fill("0")
	page.locator("#tc-t1-note").fill("Thiếu 1 kẹp, có vật lạ")
	confirm_set(page)
	expect(page.locator(LIST_ROWS)).to_have_count(2)
	expect(page.locator(LIST_ROWS).nth(1)).to_contain_text("Cần xem xét")
	expect(page.locator(".tc-t1 h3").filter(has_text="2 bộ")).to_contain_text("1 bộ cần xem xét")

	# quét trùng: cảnh báo, không thêm dòng (FR-M2-01.6)
	scan_settled(page, first)
	expect(page.locator(".tc-t1 .tc-alert-warn")).to_contain_text(first)
	expect(page.locator(LIST_ROWS)).to_have_count(2)

	# hai bộ quét liên tiếp không chờ: mã thứ hai được xếp hàng, không bị bỏ mất
	scan(page, third)
	scan(page, extra)
	expect(page.locator(LIST_ROWS)).to_have_count(4, timeout=20000)
	expect(page.locator(".tc-t1 .tc-loading")).to_have_count(0, timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator("[data-action='submit']")).to_be_disabled()  # còn bộ chờ xác nhận
	for _ in range(2):
		tick_all(page)
		confirm_set(page)
	expect(page.locator(LIST_ROWS).filter(has_text="Đã xác nhận")).to_have_count(4)
	assert set_status(page, first)[0] == "Awaiting Receipt"  # chưa ghi sổ thì chưa đổi trạng thái

	# ghi sổ: bộ sang Chờ rửa và cổng T1 Đạt
	submit = page.locator("[data-action='submit']")
	expect(submit).to_be_enabled()
	submit.click()
	done = page.locator(".tc-t1 .tc-alert-ok")
	expect(done).to_contain_text("Đã ghi sổ phiếu RC-", timeout=15000)
	expect(done).to_contain_text("4 bộ đang chờ rửa; 1 bộ cần xem xét")
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	for set_id in (first, second, third, extra):
		status, cycle_no = set_status(page, set_id)
		assert status == "Processing", (set_id, status)
		assert cycle_no >= 1, (set_id, cycle_no)
	# phiếu mới mở lại bằng thẻ người giao kế tiếp
	scan_settled(page, t1_demo["deliverer_card"])
	expect(page.locator(".tc-t1-head")).to_contain_text(t1_demo["deliverer_name"])


def test_t1_pda_viewport_reminds_before_confirming_an_unchecked_set(t1_pda_page, t1_demo):
	page = t1_pda_page
	one, two = t1_demo["sets_pda"]
	open_receipt(page, t1_demo)
	scan_settled(page, one)
	# PDA 412x915: ô quét trên cùng, không tràn ngang, nút ≥ 48 px, chữ ≥ 16 px
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	scan_box = page.locator(SCAN_INPUT).bounding_box()
	assert scan_box["y"] < page.locator(".tc-t1-item").bounding_box()["y"]
	assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t1 button')).filter(visible)
				.map((el) => ({label: el.textContent.trim(), height: el.getBoundingClientRect().height}));
			const fonts = Array.from(document.querySelectorAll('.tc-station *'))
				.filter((el) => visible(el) && Array.from(el.childNodes)
					.some((node) => node.nodeType === 3 && node.textContent.trim()))
				.map((el) => ({text: el.textContent.trim().slice(0, 30), size: parseFloat(getComputedStyle(el).fontSize)}));
			return {buttons, fonts};
		}"""
	)
	assert measured["buttons"]
	for button in measured["buttons"]:
		assert button["height"] >= 48, button
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, small[:5]

	# dòng lệch số BOM và không ghi chú: nhắc trước khi cho xác nhận (FR-M2-23.6, A-94), xác nhận vẫn được
	page.locator(".tc-t1-item .tc-t1-actual").nth(0).fill("0")
	page.locator("[data-action='confirm-set']").click()
	reminder = page.locator(".tc-t1 .tc-alert-warn")
	expect(reminder).to_be_visible()
	expect(reminder.locator(".tc-alert-items li")).to_have_count(1)
	expect(page.locator(LIST_ROWS).filter(has_text="Đã xác nhận")).to_have_count(0)
	page.locator("[data-action='confirm-anyway']").click()
	expect(page.locator(".tc-t1 .tc-loading")).to_have_count(0, timeout=15000)
	expect(page.locator(LIST_ROWS).filter(has_text="Đã xác nhận")).to_have_count(1)
	expect(page.locator(SCAN_INPUT)).to_be_focused()

	scan_settled(page, two)
	tick_all(page)
	confirm_set(page)
	page.locator("[data-action='submit']").click()
	expect(page.locator(".tc-t1 .tc-alert-ok")).to_contain_text("Đã ghi sổ phiếu RC-", timeout=15000)
	for set_id in (one, two):
		assert set_status(page, set_id)[0] == "Processing", set_id


def test_t1_offline_continues_on_device(t1_page):
	"""FEAT-009 (A-40 Q1, D3): mất mạng thì T1 tiếp nhận tiếp trên thiết bị theo snapshot, phiếu chờ đồng bộ."""
	page = t1_page
	page.wait_for_function(
		"() => frappe.tc_station.offlineData && frappe.tc_station.offlineData.function === 'RECEIVE'",
		timeout=30000,
	)
	page.context.set_offline(True)
	page.evaluate("window.dispatchEvent(new Event('offline'))")
	expect(page.locator(".tc-result")).to_contain_text("Tiếp nhận tiếp theo dữ liệu đã tải", timeout=15000)
	scan(page, "NV-00001")  # thẻ người giao chỉ kiểm khi đồng bộ
	expect(page.locator(".tc-t1-head")).to_contain_text("Phiếu ngoại tuyến")
	expect(page.locator(".tc-t1-head")).to_contain_text("NV-00001")
	page.locator("[data-action='discard']").click()
	page.locator("[data-action='discard']").click()  # bỏ phiếu offline: không gì vào hàng đợi
	expect(page.locator(".tc-sync-bar")).to_be_hidden()
	page.context.set_offline(False)
