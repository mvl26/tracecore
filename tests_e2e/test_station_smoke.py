import re
import time

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"


def scan(page, raw):
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def test_scan_known_giai_shows_card_within_1s(station_page, set_id):
	page = station_page
	expect(page.locator(".tc-zonebar")).to_have_class(re.compile(r"\btc-zone-clean\b"))
	expect(page.locator(".tc-zone-label")).to_have_text("Khu sạch")
	expect(page.locator(SCAN_INPUT)).to_be_focused()

	started = time.perf_counter()
	scan(page, set_id)
	expect(page.locator(".tc-result[data-state='result'] .tc-code")).to_have_text(set_id, timeout=1000)
	assert time.perf_counter() - started <= 1.0
	expect(page.locator(".tc-result .tc-badge").first).to_have_text("Mới tạo")
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_unknown_code_shows_vietnamese_error(station_page):
	page = station_page
	scan(page, "XYZ-123")
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	expect(alert).to_contain_text("Mã không hợp lệ")
	expect(alert).to_contain_text("XYZ-123")
	for action in ("retry", "offline", "call-r02"):
		button = alert.locator(f"[data-action='{action}']")
		expect(button).to_be_visible()
		assert button.bounding_box()["height"] >= 48
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_offline_state(station_page, context, set_id):
	page = station_page
	context.set_offline(True)
	scan(page, set_id)
	expect(page.locator(".tc-offline-banner")).to_be_visible()
	expect(page.locator(".tc-result")).to_have_attribute("data-state", "offline")
	context.set_offline(False)
	expect(page.locator(".tc-offline-banner")).to_be_hidden(timeout=10000)
	expect(page.locator(".tc-result")).to_have_attribute("data-state", "empty", timeout=10000)


def test_missing_station_shows_error(logged_in_page):
	page = logged_in_page
	page.goto("/app/station")
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	expect(alert).to_contain_text("Chưa cấu hình trạm")


def test_station_text_at_least_16px(station_page):
	smallest = station_page.evaluate(
		"""() => Math.min(...Array.from(document.querySelectorAll('.tc-station *'))
			.filter((el) => el.offsetParent !== null && el.textContent.trim())
			.map((el) => parseFloat(getComputedStyle(el).fontSize)))"""
	)
	assert smallest >= 16
