"""E2E màn T6 kho vô khuẩn SCR-11 (FEAT-025, kiosk 1366x768).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy: ``pack_released`` bị tiêu thụ khi nhập kho và
``pack_stored`` khi báo rách (``devdata.ensure_t6_demo`` thay bằng gói mới ở lần chuẩn bị sau). Các test khác chỉ đọc
hoặc bị chặn, không đổi dữ liệu.
"""

import re

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"


def scan(page, raw):
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def scan_settled(page, raw):
	"""Quét rồi chờ RPC trả lời: kiosk bỏ qua mã quét khi đang chờ máy chủ (``busy``)."""
	scan(page, raw)
	expect(page.locator(".tc-t6 .tc-loading")).to_have_count(0, timeout=15000)


def open_pack(page, cycle_id):
	scan_settled(page, cycle_id)
	expect(page.locator(".tc-t6-block .tc-res-head .tc-code")).to_have_text(cycle_id, timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("KE-"))


def stock_rows(page, heading):
	"""Các dòng của bảng tồn có tiêu đề `heading` trên màn tổng quan."""
	section = page.locator(".tc-t6-block").filter(has=page.locator("h3", has_text=heading))
	return section.locator("tbody tr")


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


def test_t6_scan_box_on_top_with_stock_by_location_and_expiring(t6_page, t6_demo):
	page = t6_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("Cycle ID"))
	# ô quét nằm trên khối kết quả
	scan_box = page.locator(SCAN_INPUT).bounding_box()
	result_box = page.locator(".tc-result .tc-t6").bounding_box()
	assert scan_box["y"] < result_box["y"], (scan_box, result_box)
	by_location = stock_rows(page, "Tồn theo vị trí")
	expect(by_location.filter(has_text=t6_demo["location"])).to_have_count(1)
	expect(by_location.filter(has_text=t6_demo["location_2"])).to_have_count(1)
	expiring = stock_rows(page, "Gói hết hạn trong 7 ngày tới")
	expect(expiring.filter(has_text=t6_demo["pack_expiring"])).to_have_count(1)
	expect(expiring.filter(has_text=t6_demo["pack_stored"])).to_have_count(0)  # hạn 30 ngày


def test_t6_putaway_released_pack_without_taps(t6_page, t6_demo):
	page = t6_page
	location = t6_demo["location"]
	by_location = stock_rows(page, "Tồn theo vị trí").filter(has_text=location)
	before = int(by_location.locator("td").last.inner_text())

	open_pack(page, t6_demo["pack_released"])
	card = page.locator(".tc-t6-block").first
	expect(card.locator(".tc-badge")).to_have_text("Đã giải phóng")
	expect(card.locator(".tc-gate")).to_have_count(5)
	expect(card.locator(".tc-gate-ok")).to_have_count(5)  # đủ năm cổng Đạt, mỗi ô có chữ
	scan_settled(page, location)

	ok = page.locator(".tc-t6 .tc-alert-ok")
	expect(ok).to_contain_text(f"Đã nhập kho gói {t6_demo['pack_released']} vào {location}", timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("Cycle ID"))
	# tồn theo vị trí cập nhật sau khi nhập kho (overview tải lại); 0 chạm sau quét
	expect(by_location.locator("td").last).to_have_text(str(before + 1), timeout=15000)

	open_pack(page, t6_demo["pack_released"])
	card = page.locator(".tc-t6-block").first
	expect(card.locator(".tc-badge")).to_have_text("Trong kho vô khuẩn")
	expect(card.locator(".tc-res-grid")).to_contain_text(location)


def test_t6_pack_not_released_is_blocked_with_inline_red_alert(t6_page, t6_demo):
	page = t6_page
	open_pack(page, t6_demo["pack_not_released"])
	scan_settled(page, t6_demo["location"])
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-title")).to_contain_text("Sai thứ tự trạm")
	expect(alert.locator(".tc-alert-title")).to_contain_text(t6_demo["pack_not_released"])
	# lỗi chặn không dùng modal hay toast
	expect(page.locator(".modal.show, .msgprint, .toast, [role='dialog']:visible")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t6_unknown_shelf_keeps_pack_open(t6_page, t6_demo):
	page = t6_page
	open_pack(page, t6_demo["pack_stored"])
	scan_settled(page, "KE-9999")
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	assert_full_alert(alert)
	expect(alert.locator(".tc-alert-reason")).to_contain_text("KE-9999")
	# LOCATION_NOT_FOUND giữ thẻ gói để quét lại kệ khác
	expect(page.locator(".tc-t6-block .tc-res-head .tc-code")).to_have_text(t6_demo["pack_stored"])


def test_t6_touch_targets_and_font_sizes(t6_page, t6_demo):
	page = t6_page
	open_pack(page, t6_demo["pack_stored"])
	expect(page.locator("[data-action='damaged']")).to_be_visible()
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t6 button')).filter(visible)
				.map((el) => ({label: el.textContent.trim(), height: el.getBoundingClientRect().height}));
			const fonts = Array.from(document.querySelectorAll('.tc-station *'))
				.filter((el) => visible(el) && Array.from(el.childNodes)
					.some((node) => node.nodeType === 3 && node.textContent.trim()))
				.map((el) => ({text: el.textContent.trim().slice(0, 30), size: parseFloat(getComputedStyle(el).fontSize)}));
			return {buttons, fonts};
		}"""
	)
	assert measured["buttons"], "không có button nào trong khối T6"
	for button in measured["buttons"]:
		assert button["height"] >= 48, button
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, small[:5]


def test_t6_report_torn_requires_reason_then_voids_pack(t6_page, t6_demo):
	page = t6_page
	cycle_id = t6_demo["pack_stored"]
	open_pack(page, cycle_id)
	page.locator("[data-action='damaged']").click()
	reason = page.locator("#tc-t6-reason")
	expect(reason).to_be_focused()
	page.locator("[data-action='damaged-submit']").click()  # chưa nhập lý do
	expect(page.locator("#tc-t6-reason-err")).to_be_visible()
	expect(page.locator("#tc-t6-reason-err")).to_contain_text("Bắt buộc")
	expect(page.locator(".tc-t6-block .tc-res-head .tc-code")).to_have_text(cycle_id)  # chưa gửi gì

	page.locator("#tc-t6-reason").fill("Gói rách mép khi lấy khỏi kệ")
	page.locator("[data-action='damaged-submit']").click()
	ok = page.locator(".tc-t6 .tc-alert-ok")
	expect(ok).to_contain_text(f"Gói {cycle_id} đã hết hiệu lực", timeout=15000)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	returns = stock_rows(page, "Gói cần đưa về khu bẩn").filter(has_text=cycle_id)
	expect(returns).to_have_count(1, timeout=15000)

	open_pack(page, cycle_id)
	card = page.locator(".tc-t6-block").first
	expect(card.locator(".tc-badge")).to_have_text("Đã hủy hiệu lực")
	expect(page.locator("[data-action='damaged']")).to_have_count(0)  # chỉ gói đang trong kho mới báo rách


def test_t6_offline_shows_offline_state(t6_page, t6_demo):
	page = t6_page
	page.context.set_offline(True)
	page.evaluate("window.dispatchEvent(new Event('offline'))")
	offline = page.locator(".tc-result[data-state='offline']")
	expect(offline).to_be_visible(timeout=15000)
	expect(offline).to_contain_text("Nhập kho vô khuẩn cần có kết nối mạng")
	scan(page, t6_demo["pack_stored"])  # quét khi ngoại tuyến không gửi gì, màn vẫn báo ngoại tuyến
	expect(offline).to_be_visible()
	page.context.set_offline(False)
