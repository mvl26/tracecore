"""E2E màn T7 cấp phát SCR-12 (kiosk 1366x768) và SCR-36 (PDA 412x915), FEAT-026.

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy CẢ FILE này: gói demo bị cấp phát theo đúng thứ tự
các test trong file (pack_1/2, pack_3/4, pack_5, pack_6 theo hạn sớm trước, nên FEFO không đòi ghi chú), và phiếu nháp cũ
của khoa demo bị xóa ở lần chuẩn bị sau.
"""

import re

import pytest
from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"


def scan(page, raw):
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def scan_settled(page, raw):
	"""Quét rồi chờ RPC trả lời; mã quét đến khi kiosk đang chờ máy chủ (``busy``) được giữ và quét sau."""
	scan(page, raw)
	expect(page.locator(".tc-t7 .tc-loading")).to_have_count(0, timeout=15000)


def pick_department(page, name):
	page.locator("[data-action='pick-dept']").filter(has_text=name).click()
	expect(page.locator(".tc-t7 .tc-res-head [data-action='change-dept']")).to_be_visible(timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("Cycle ID"))


def pack_rows(page):
	section = page.locator(".tc-t6-block").filter(has=page.locator("h3", has_text="Gói trên phiếu"))
	return section.locator("tbody tr")


def add_pack(page, cycle_id, expected_rows):
	scan_settled(page, cycle_id)
	expect(pack_rows(page)).to_have_count(expected_rows, timeout=15000)


def sign_with_card(page, card):
	page.locator("[data-action='to-sign']").click()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("thẻ"))
	scan_settled(page, card)


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


def test_t7_scan_box_on_top_and_department_buttons_are_large(t7_page, t7_demo):
	page = t7_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	scan_box = page.locator(SCAN_INPUT).bounding_box()
	result_box = page.locator(".tc-result .tc-t7").bounding_box()
	assert scan_box["y"] < result_box["y"], (scan_box, result_box)
	buttons = page.locator("[data-action='pick-dept']")
	expect(buttons.filter(has_text=t7_demo["dept_name"])).to_have_count(1)
	heights = buttons.evaluate_all("(els) => els.map((el) => el.getBoundingClientRect().height)")
	assert heights and all(height >= 56 for height in heights), heights


def test_t7_issue_two_packs_signed_by_card_moves_stock(t7_page, t7_demo):
	page = t7_page
	pick_department(page, t7_demo["dept_name"])
	add_pack(page, t7_demo["pack_1"], 1)
	add_pack(page, t7_demo["pack_2"], 2)
	sign_with_card(page, t7_demo["recipient_card"])
	expect(page.locator(".tc-t4-ok")).to_contain_text("Đã ký", timeout=15000)
	page.locator("[data-action='submit']").click()
	ok = page.locator(".tc-t7 .tc-alert-ok")
	expect(ok).to_contain_text("đã xác nhận", timeout=15000)
	expect(page.locator("[data-action='print']")).to_be_visible()

	# gói vừa cấp không còn trong kho vô khuẩn: quét lại bị chặn (FR-M2-00.1)
	page.locator("[data-action='new-issue']").click()
	pick_department(page, t7_demo["dept_name"])
	scan_settled(page, t7_demo["pack_1"])
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-reason")).to_contain_text(t7_demo["pack_1"])
	expect(page.locator(".modal.show, .msgprint, .toast, [role='dialog']:visible")).to_have_count(0)


# RPC tracecore.v1.station.verify_approver thuộc FEAT-019 (chưa có trên develop): không có nó, bước duyệt R02 trả lỗi máy
# chủ. Bỏ nguyên test (không chạy dở) vì pack_3/pack_4 không được cấp phát sẽ làm các test sau gặp cảnh báo FEFO.
# Bỏ dấu skip khi FEAT-019 merge.
@pytest.mark.skip(reason="Chờ FEAT-019: v1.station.verify_approver chưa có")
def test_t7_over_par_other_department_recipient_needs_reason_and_r02_pin(t7_page, t7_demo):
	page = t7_page
	pick_department(page, t7_demo["dept_tight_name"])
	add_pack(page, t7_demo["pack_3"], 1)
	add_pack(page, t7_demo["pack_4"], 2)
	# bảng cơ số: khoa chỉ giữ tối đa 1 gói, phiếu có 2 → vượt tối đa
	expect(page.locator(".tc-badge-r")).to_have_text("Vượt cơ số tối đa")

	sign_with_card(page, t7_demo["recipient_card"])  # nhân viên khoa khác → cảnh báo, cần lý do
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(alert)
	page.locator("#tc-t7-mismatch-reason").fill("Điều dưỡng khoa A nhận hộ")
	page.locator("[data-action='mismatch-submit']").click()
	expect(page.locator(".tc-t4-ok")).to_contain_text("Đã ký", timeout=15000)

	page.locator("[data-action='open-approval']").click()
	page.locator("#tc-t7-approver-card").fill(t7_demo["approver_card"])
	page.locator("#tc-t7-approver-pin").fill("000000")
	page.locator("[data-action='approve-submit']").click()
	wrong = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(wrong)
	expect(wrong.locator(".tc-alert-title")).to_contain_text("PIN")
	page.locator("[data-action='open-approval']").click()
	page.locator("#tc-t7-approver-card").fill(t7_demo["approver_card"])
	page.locator("#tc-t7-approver-pin").fill(t7_demo["approver_pin"])
	page.locator("[data-action='approve-submit']").click()
	expect(page.locator(".tc-t7 .tc-alert-ok")).to_contain_text("đã xác nhận", timeout=15000)


def test_t7_touch_signature_and_unconfigured_par_warning(t7_page, t7_demo):
	page = t7_page
	pick_department(page, t7_demo["dept_open_name"])
	add_pack(page, t7_demo["pack_5"], 1)
	expect(page.locator(".tc-t6-block .tc-badge-o").first).to_have_text("Chưa đặt cơ số")  # FR-M2-16.4
	page.locator("[data-action='to-sign']").click()
	page.locator("[data-action='sign-mode'][data-mode='Touch']").click()
	scan_settled(page, t7_demo["stranger_card"])  # thẻ nhân viên khoa D, khoa C: cần lý do
	page.locator("#tc-t7-pad").wait_for(timeout=15000)
	page.locator("[data-action='sign-confirm']").click()  # chưa ký gì
	expect(page.locator(".tc-alert-error")).to_contain_text("Chữ ký còn trống")
	pad = page.locator("#tc-t7-pad").bounding_box()
	page.mouse.move(pad["x"] + 20, pad["y"] + 40)
	page.mouse.down()
	page.mouse.move(pad["x"] + 120, pad["y"] + 90, steps=8)
	page.mouse.move(pad["x"] + 220, pad["y"] + 50, steps=8)
	page.mouse.up()
	page.locator("[data-action='sign-confirm']").click()
	reason = page.locator("#tc-t7-mismatch-reason")
	expect(reason).to_be_visible(timeout=15000)
	reason.fill("Nhận hộ khoa C")
	page.locator("[data-action='mismatch-submit']").click()
	expect(page.locator(".tc-t4-ok")).to_contain_text("Đã ký", timeout=15000)
	page.locator("[data-action='submit']").click()
	expect(page.locator(".tc-t7 .tc-alert-ok")).to_contain_text("đã xác nhận", timeout=15000)


def test_t7_pda_viewport_fits_without_horizontal_scroll(t7_pda_page, t7_demo):
	page = t7_pda_page
	pick_department(page, t7_demo["dept_name"])
	add_pack(page, t7_demo["pack_6"], 1)
	scan_box = page.locator(SCAN_INPUT).bounding_box()
	result_box = page.locator(".tc-result .tc-t7").bounding_box()
	assert scan_box["y"] < result_box["y"], (scan_box, result_box)
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t7 button')).filter(visible)
				.map((el) => ({label: el.textContent.trim(), height: el.getBoundingClientRect().height}));
			const fonts = Array.from(document.querySelectorAll('.tc-station *'))
				.filter((el) => visible(el) && Array.from(el.childNodes)
					.some((node) => node.nodeType === 3 && node.textContent.trim()))
				.map((el) => ({text: el.textContent.trim().slice(0, 30), size: parseFloat(getComputedStyle(el).fontSize)}));
			return {buttons, fonts, overflow: document.documentElement.scrollWidth - window.innerWidth};
		}"""
	)
	assert measured["buttons"], "không có button nào trong khối T7"
	for button in measured["buttons"]:
		assert button["height"] >= 48, button
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, small[:5]
	assert measured["overflow"] <= 0, measured["overflow"]
	sign_with_card(page, t7_demo["recipient_card"])
	page.locator("[data-action='submit']").click()
	expect(page.locator(".tc-t7 .tc-alert-ok")).to_contain_text("đã xác nhận", timeout=15000)


def test_t7_fefo_later_pack_needs_note(t7_page, t7_demo):
	page = t7_page
	pick_department(page, t7_demo["dept_open_name"])
	scan_settled(page, t7_demo["pack_fefo_far"])  # còn gói cùng loại hạn gần hơn
	warn = page.locator(".tc-alert-warn")
	expect(warn).to_be_visible(timeout=15000)
	expect(warn.locator(".tc-alert-items")).to_contain_text(t7_demo["pack_fefo_near"])
	page.locator("[data-action='fefo-submit']").click()  # chưa nhập ghi chú
	expect(page.locator(".tc-field-error")).to_contain_text("Bắt buộc")
	page.locator("#tc-t7-fefo-note").fill("Phẫu thuật viên chỉ định bộ này")
	page.locator("[data-action='fefo-submit']").click()
	expect(pack_rows(page)).to_have_count(1, timeout=15000)
	expect(pack_rows(page).first).to_contain_text("Phẫu thuật viên chỉ định")


def test_t7_pack_not_in_stock_is_blocked_with_inline_red_alert(t7_page, t7_demo):
	page = t7_page
	pick_department(page, t7_demo["dept_open_name"])
	scan_settled(page, t7_demo["pack_released"])
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-reason")).to_contain_text(t7_demo["pack_released"])
	expect(page.locator(".modal.show, .msgprint, .toast, [role='dialog']:visible")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t7_scan_before_department_is_rejected(t7_page, t7_demo):
	page = t7_page
	scan(page, t7_demo["pack_fefo_near"])
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-title")).to_contain_text("Chọn khoa trước")


def test_t7_offline_shows_offline_state(t7_page, t7_demo):
	page = t7_page
	page.context.set_offline(True)
	page.evaluate("window.dispatchEvent(new Event('offline'))")
	offline = page.locator(".tc-result[data-state='offline']")
	expect(offline).to_be_visible(timeout=15000)
	expect(offline).to_contain_text("Cấp phát gói cần có kết nối mạng")
	scan(page, t7_demo["pack_fefo_near"])  # quét khi ngoại tuyến không gửi gì, màn vẫn báo ngoại tuyến
	expect(offline).to_be_visible()
	page.context.set_offline(False)
