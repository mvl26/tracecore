"""E2E màn T4 đóng gói SCR-08 (FEAT-018, kiosk 1366x768).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy (bộ demo bị tiêu thụ khi đóng gói).
Thứ tự test trong file có chủ ý: ``test_t4_touch_targets_and_font_sizes`` dùng bộ plasma ở bước ngữ cảnh,
chạy trước ``test_t4_plasma_waits_for_plasma_roll`` là test sinh Cycle ID cho bộ đó.
"""

import json
import re

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
AGENT_PRINT_URL = "http://127.0.0.1:8765/print"


def scan(page, raw):
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def mock_agent(page):
	"""Agent giả trả 202 cho POST /print; trả về danh sách payload đã nhận (kể cả CORS preflight)."""
	received = []
	cors = {
		"access-control-allow-origin": "*",
		"access-control-allow-headers": "Content-Type",
		"access-control-allow-methods": "POST, OPTIONS",
	}

	def handle(route):
		request = route.request
		if request.method == "OPTIONS":
			return route.fulfill(status=204, headers=cors)
		received.append(json.loads(request.post_data or "{}"))
		route.fulfill(
			status=202, headers=cors, content_type="application/json", body=json.dumps({"ok": True})
		)

	page.route(AGENT_PRINT_URL, handle)
	return received


class Taps:
	"""Đếm chạm của người dùng vào nút trên màn T4; quét bằng bàn phím không tính."""

	def __init__(self):
		self.count = 0

	def tap(self, locator):
		expect(locator).to_be_enabled()
		locator.click()
		self.count += 1
		# ô quét lấy lại focus sau 150 ms (station.js); máy quét thật không gõ trong khoảng đó ngay sau chạm
		expect(locator.page.locator(SCAN_INPUT)).to_be_focused()


def scan_set_and_wait_context(page, set_id):
	scan(page, set_id)
	expect(page.locator(".tc-t4[data-view='ctx'] .tc-code").first).to_have_text(set_id, timeout=15000)


def assert_touch_and_font(page):
	"""Mọi button trong khối T4 cao >= 48 px, nút chính >= 56 px, mọi chữ >= 16 px (getComputedStyle)."""
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t4 button')).filter(visible)
				.map((el) => ({
					label: el.textContent.trim(),
					action: el.dataset.action || '',
					height: el.getBoundingClientRect().height,
				}));
			const fonts = Array.from(document.querySelectorAll('.tc-station *'))
				.filter((el) => visible(el) && Array.from(el.childNodes)
					.some((node) => node.nodeType === 3 && node.textContent.trim()))
				.map((el) => ({
					node: el.className || el.tagName,
					text: el.textContent.trim().slice(0, 30),
					size: parseFloat(getComputedStyle(el).fontSize),
				}));
			return {buttons, fonts};
		}"""
	)
	assert measured["buttons"], "không có button nào trong khối T4"
	for button in measured["buttons"]:
		assert button["height"] >= 48, f"nút '{button['label']}' cao {button['height']} px < 48"
		if button["action"] == "confirm-pack":
			assert button["height"] >= 56, f"nút chính cao {button['height']} px < 56"
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, f"chữ nhỏ hơn 16 px: {small[:5]}"


def test_t4_happy_path_within_three_taps(t4_page, t4_demo):
	page = t4_page
	sent = mock_agent(page)  # không bao giờ chạm agent thật ở 127.0.0.1:8765
	taps = Taps()
	expect(page.locator(SCAN_INPUT)).to_be_focused()

	scan_set_and_wait_context(page, t4_demo["set_steam"])
	expect(page.locator("[data-region='maint'] [data-action='maint-done']")).to_have_count(
		0
	)  # bộ sạch, không nhắc
	confirm_all = page.locator("[data-action='confirm-all']")
	expect(confirm_all).to_be_enabled(timeout=20000)  # D1: bật khi lưới BOM đã hiển thị đủ và ảnh đã tải

	taps.tap(confirm_all)
	scan(page, t4_demo["ci_steam"])
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text(t4_demo["ci_steam"])
	expect(page.locator(".tc-missing")).to_have_count(0)
	taps.tap(page.locator("[data-action='confirm-pack']"))

	expect(page.locator(".tc-cycle")).to_have_text(re.compile(r"^CY-\d{6}-\d{4}$"), timeout=15000)
	label = page.locator(".tc-label")
	expect(label).to_contain_text("HẠN SỬ DỤNG")
	expect(label).to_contain_text("TEST")
	expect(label.locator(".tc-label-dm")).to_be_visible()
	# Agent giả nhận đúng 1 job (không phụ thuộc agent trên CI)
	expect(page.locator("[data-region='print'] .tc-alert-ok")).to_be_visible(timeout=15000)
	assert len(sent) == 1
	assert page.locator("[data-region='print'] .tc-alert-error").count() == 0

	# AC-15: đường chính sau quét <= 3 chạm; thực tế 2 (xác nhận tất cả + xác nhận hoàn thành)
	assert taps.count == 2, f"đường chính cần 2 chạm, thực tế {taps.count}"
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t4_maintenance_reminder_flow(t4_page, t4_demo):
	"""AC-12 (luồng thay thế, không tính vào 3 chạm của AC-15): nhắc tra dầu phải được xử lý trước khi sinh."""
	page = t4_page
	mock_agent(page)
	taps = Taps()

	scan_set_and_wait_context(page, t4_demo["set_maint"])
	reminder = page.locator("[data-region='maint'] .tc-maint")
	expect(reminder).to_have_count(1)
	expect(reminder).to_contain_text("Đến hạn")
	done_button = reminder.locator("[data-action='maint-done']")
	expect(done_button).to_have_count(1)
	taps.tap(page.locator("[data-action='confirm-all']"))
	scan(page, t4_demo["ci_steam"])
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text(t4_demo["ci_steam"])
	# chưa xử lý nhắc: nút chính khóa và nêu lý do
	expect(page.locator("[data-action='confirm-pack']")).to_be_disabled()
	expect(page.locator(".tc-missing")).to_contain_text("bảo dưỡng")

	done_button.click()
	dialog = page.locator(".tc-modal [role='dialog']")
	expect(dialog).to_be_visible()
	oil_lot = dialog.locator("#tc-dlg-oil_batch")
	expect(oil_lot).to_be_visible()
	dialog.locator("button[type='submit']").click()  # để trống: bắt buộc nhập lô dầu
	expect(dialog.locator("#tc-dlg-oil_batch-err")).to_be_visible()
	oil_lot.fill("DEMO-T4-DAU-01")
	dialog.locator("button[type='submit']").click()
	expect(page.locator(".tc-modal")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator("[data-region='maint']")).to_contain_text("DEMO-T4-DAU-01")

	taps.tap(page.locator("[data-action='confirm-pack']"))
	expect(page.locator(".tc-cycle")).to_have_text(re.compile(r"^CY-\d{6}-\d{4}$"), timeout=15000)
	expect(page.locator(".tc-alert-error")).to_have_count(0)


def test_t4_gate_not_passed_shows_full_alert(t4_page, t4_demo):
	page = t4_page
	scan(page, t4_demo["set_gate_fail"])
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	expect(alert).to_be_visible()
	# kết quả -> lý do -> hành động: đủ cả ba khối và có chữ (không chỉ màu)
	expect(alert.locator(".tc-alert-title")).to_contain_text("chưa đạt")
	expect(alert.locator(".tc-alert-reason")).not_to_be_empty()
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()
	assert result.locator("[data-action='confirm-pack']").count() == 0
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t4_touch_targets_and_font_sizes(t4_page, t4_demo):
	page = t4_page
	scan_set_and_wait_context(page, t4_demo["set_plasma"])
	expect(page.locator("[data-action='confirm-all']")).to_be_enabled(timeout=20000)
	expect(page.locator("[data-action='confirm-pack']")).to_be_visible()
	assert_touch_and_font(page)


def test_t4_plasma_waits_for_plasma_roll(t4_page, t4_demo):
	page = t4_page
	sent = mock_agent(page)
	taps = Taps()

	scan_set_and_wait_context(page, t4_demo["set_plasma"])
	taps.tap(page.locator("[data-action='confirm-all']"))
	scan(page, t4_demo["ci_plasma"])
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text(t4_demo["ci_plasma"])
	taps.tap(page.locator("[data-action='confirm-pack']"))

	# Cycle ID vẫn giữ nhưng máy in đang lắp nhãn hấp: nhãn chờ, alert-error có lý do và hành động (AC-8)
	expect(page.locator(".tc-cycle")).to_have_text(re.compile(r"^CY-\d{6}-\d{4}$"), timeout=15000)
	waiting = page.locator("[data-region='print'] .tc-alert-error")
	expect(waiting).to_be_visible(timeout=15000)
	expect(waiting.locator(".tc-alert-reason")).not_to_be_empty()
	expect(waiting).to_contain_text("VT-NHAN-PLASMA")
	expect(waiting).to_contain_text("CN-")
	assert sent == [], "không được in tạm nhãn plasma trên cuộn nhãn hấp"
	assert_touch_and_font(page)

	# Đổi cuộn: quét mã cuộn plasma -> alert-info, đúng 1 job chờ được giải phóng và gửi tới agent (AC-9)
	scan(page, t4_demo["roll_plasma"])
	expect(page.locator(".tc-alert-info")).to_contain_text(t4_demo["roll_plasma"], timeout=15000)
	expect(page.locator("[data-region='print'] .tc-alert-ok")).to_be_visible(timeout=15000)
	assert len(sent) == 1, f"phải giải phóng đúng 1 job, thực tế {len(sent)}"
	assert sent[0].get("print_job") and sent[0].get("zpl")
	expect(page.locator(SCAN_INPUT)).to_be_focused()
