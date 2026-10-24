"""E2E màn T3 kiểm đếm lắp ráp SCR-07 (FEAT-020, kiosk 1366x768), luồng nhiều bước theo e2e-lighter-policy.

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy (bộ demo bị tiêu thụ khi ghi sổ). Thứ tự test trong
file có chủ ý và test sau không dùng thứ test trước đã tiêu thụ: ``set_full`` → đếm đủ rồi ghi sổ; ``set_short`` → đếm
thiếu, R02 đổi thẻ nhập PIN xác nhận rồi ghi sổ; ``set_branch`` → rẽ nhánh Thanh lý; ``set_no_wash`` chỉ để kiểm chặn.
"""

import re

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
CARD_INPUT = "#tc-card-input"


def scan(page, raw):
	# ô quét lấy lại focus sau mỗi thao tác (station.focus(true)); gõ khi chưa focus sẽ mất các ký tự đầu
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def open_set(page, set_id):
	scan(page, set_id)
	expect(page.locator(".tc-t3 .tc-ins").first).to_be_visible(timeout=15000)
	expect(page.locator(".tc-t3 .tc-loading")).to_have_count(0, timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def line(page, instrument):
	return page.locator(f".tc-t3 .tc-ins[data-instrument='{instrument}']")


class Taps:
	def __init__(self):
		self.count = 0

	def tap(self, locator):
		expect(locator).to_be_enabled()
		locator.click()
		self.count += 1


def recorded(page):
	return page.locator(".tc-t3 .tc-badge", has_text=re.compile("Đã ghi nhận lắp ráp"))


def test_t3_empty_state_has_scan_box_focused(t3_page):
	page = t3_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("Set ID"))
	expect(page.locator(".tc-t3 .tc-empty")).to_contain_text("Quét Set ID")


def test_t3_set_without_passed_wash_is_blocked_inline(t3_page, t3_demo):
	page = t3_page
	scan(page, t3_demo["set_no_wash"])
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	expect(alert.locator(".tc-alert-title")).not_to_be_empty()
	expect(alert.locator(".tc-alert-reason")).to_contain_text("T2")
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()
	expect(page.locator(".tc-t3 .tc-ins")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t3_full_count_is_recorded_within_three_taps(t3_page, t3_demo):
	page = t3_page
	open_set(page, t3_demo["set_full"])
	# BOM kèm ảnh từng dụng cụ và ảnh bộ đã xếp; Đóng gói đang khóa vì chưa ghi nhận
	expect(page.locator(".tc-t3 .tc-ins img.tc-photo").first).to_be_visible()
	expect(page.locator(".tc-t3 .tc-tray img").first).to_be_visible()
	expect(page.locator(".tc-t3-lock")).to_contain_text("Đóng gói: khóa")
	submit = page.locator("[data-action='t3-submit']")
	expect(submit).to_be_disabled()
	measure_touch_and_font(page)

	taps = Taps()
	taps.tap(page.locator("[data-action='t3-all']"))
	expect(page.locator(".tc-t3 .tc-ins.is-done")).to_have_count(
		page.locator(".tc-t3 .tc-ins").count(), timeout=15000
	)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	taps.tap(submit)
	expect(recorded(page)).to_be_visible(timeout=15000)
	expect(page.locator(".tc-alert-ok")).to_contain_text("Đóng gói: sẵn sàng")
	expect(page.locator(".tc-gates .tc-gate-ok").nth(2)).to_contain_text("Đạt")
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	assert taps.count <= 3, taps.count


def measure_touch_and_font(page):
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t3 button')).filter(visible)
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


def test_t3_shortage_locks_packing_until_r02_confirms_with_pin(t3_page, t3_demo, t3_r02):
	page = t3_page
	open_set(page, t3_demo["set_short"])
	page.locator("[data-action='t3-all']").click()
	short = line(page, t3_demo["short_instrument"])
	expect(short.locator(".tc-t3-count")).to_have_text("2", timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	short.locator("[data-action='t3-dec']").click()
	# thiếu 1: chữ + ký hiệu (không chỉ màu), Đóng gói khóa, nút ghi nhận khóa, R04 không tự xác nhận được
	expect(short.locator(".tc-ins-state").first).to_contain_text("Thiếu (-1)", timeout=15000)
	expect(page.locator(".tc-t3 .tc-alert-error")).to_contain_text("Dụng cụ thiếu")
	expect(page.locator(".tc-t3-lock")).to_contain_text("Đóng gói: khóa")
	expect(page.locator("[data-action='t3-submit']")).to_be_disabled()
	expect(page.locator("[data-action='t3-confirm']")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()

	# R02 quét thẻ của mình tại trạm, quét lại Set ID: bản nháp còn nguyên số đã đếm
	page.locator("[data-action='rescan-card']").click()
	page.locator(CARD_INPUT).fill(t3_r02["card"])
	page.locator(CARD_INPUT).press("Enter")
	page.locator(".tc-result[data-state='empty'] .tc-t3").wait_for(timeout=30000)
	open_set(page, t3_demo["set_short"])
	expect(line(page, t3_demo["short_instrument"]).locator(".tc-t3-count")).to_have_text("1")
	page.locator("[data-action='t3-confirm']").click()
	page.locator("#tc-t3-confirm-reason").fill("Ca mổ gấp, bổ sung dụng cụ sau")
	# PIN sai bị chặn inline, chưa mở khóa
	page.locator("#tc-t3-pin").fill("000000")
	page.locator("[data-action='t3-confirm-save']").click()
	expect(page.locator(".tc-t3 .tc-alert-error")).to_be_visible(timeout=15000)
	expect(page.locator("[data-action='t3-submit']")).to_be_disabled()
	# PIN đúng: R02 xác nhận, ghi nhận kiểm đếm, Đóng gói mở
	if not page.locator("#tc-t3-pin").count():
		page.locator("[data-action='t3-confirm']").click()
	page.locator("#tc-t3-confirm-reason").fill("Ca mổ gấp, bổ sung dụng cụ sau")
	page.locator("#tc-t3-pin").fill(t3_r02["pin"])
	page.locator("[data-action='t3-confirm-save']").click()
	expect(page.locator(".tc-t3 [data-region='notice'] .tc-alert-ok")).to_contain_text(
		"R02 đã xác nhận thiếu", timeout=15000
	)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	submit = page.locator("[data-action='t3-submit']")
	expect(submit).to_be_enabled()
	submit.click()
	expect(recorded(page)).to_be_visible(timeout=15000)
	expect(page.locator(".tc-alert-ok")).to_contain_text("Đóng gói: sẵn sàng")
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t3_damaged_set_is_branched_to_disposal(t3_page, t3_demo):
	page = t3_page
	open_set(page, t3_demo["set_branch"])
	page.locator("[data-action='t3-branch']").click()
	page.locator("[data-action='t3-branch-pick'][data-value='Disposal']").click()
	page.locator("#tc-t3-branch-reason").fill("Gãy mũi kẹp, không sửa được")
	page.locator("[data-action='t3-branch-save']").click()
	badge = page.locator(".tc-t3 .tc-badge-r")
	expect(badge).to_contain_text("Lắp ráp không đạt", timeout=15000)
	expect(page.locator(".tc-t3-lock")).to_contain_text("Đóng gói: khóa")
	expect(page.locator(".tc-gates .tc-gate-bad")).to_contain_text("Không đạt")
	expect(page.locator(SCAN_INPUT)).to_be_focused()
