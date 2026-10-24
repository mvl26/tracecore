"""E2E màn T2 lô rửa SCR-06 (FEAT-021, kiosk 1366x768).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy (bộ demo bị tiêu thụ khi nạp lô). Mỗi test nạp
tối đa các bộ của ``TC_E2E_T2_SETS`` theo thứ tự trong file: ``test_t2_load_happy_path_within_three_taps`` dùng cả ba
bộ rồi dỡ lô đó ở các test sau; test chỉ kiểm tra hiển thị dùng ``set_no_t1``/``set_redo``.
"""

import re

from playwright.sync_api import expect

SCAN_INPUT = "#tc-scan-input"
AGENT_PRINT_URL = "http://127.0.0.1:8765/print"
PNG_1PX = bytes.fromhex(
	"89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
	"0000000d4944415478da63f8cfc0f01f0005fe02fea7d2b7a20000000049454e44ae426082"
)
STATE = {}


def scan(page, raw):
	# đổi chế độ vẽ lại màn; ô quét lấy lại focus sau 150 ms (station.js blur): gõ sớm hơn sẽ mất các ký tự đầu
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def scan_settled(page, raw):
	"""Quét rồi chờ RPC trả lời: kiosk bỏ qua mã quét khi đang chờ máy chủ (``busy``), nên hai mã dỡ lô liên tiếp
	phải đợi nhau (màn đã hiện khối "Đang dỡ lô" trước khi RPC đầu trả lời)."""
	scan(page, raw)
	expect(page.locator(".tc-t2 .tc-loading")).to_have_count(0, timeout=15000)


def mock_agent(page):
	received = []

	def handle(route):
		if route.request.method == "OPTIONS":
			return route.fulfill(status=204, headers={"access-control-allow-origin": "*"})
		received.append(route.request.post_data)
		route.fulfill(status=202, headers={"access-control-allow-origin": "*"}, body="{}")

	page.route(AGENT_PRINT_URL, handle)
	return received


class Taps:
	def __init__(self):
		self.count = 0

	def tap(self, locator):
		expect(locator).to_be_enabled()
		locator.click()
		self.count += 1


def load_machine(page, machine):
	scan(page, machine)
	expect(page.locator(".tc-t2-machine")).to_contain_text(machine, timeout=15000)


def test_t2_scan_box_locked_until_machine_scanned(t2_page, t2_demo):
	page = t2_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("QR máy rửa"))
	scan(page, t2_demo["sets"][0])
	alert = page.locator(".tc-t2 .tc-alert-error")
	expect(alert.locator(".tc-alert-title")).to_contain_text("quét QR máy rửa trước")
	expect(page.locator(".tc-t2-sets")).to_have_count(0)


def test_t2_locked_machine_is_rejected(t2_page, t2_demo):
	page = t2_page
	scan(page, t2_demo["machine_locked"])
	alert = page.locator(".tc-t2 .tc-alert-error")
	expect(alert).to_be_visible(timeout=15000)
	expect(alert.locator(".tc-alert-reason")).not_to_be_empty()
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()


def test_t2_set_without_t1_shows_full_alert(t2_page, t2_demo):
	page = t2_page
	load_machine(page, t2_demo["machine"])
	scan(page, t2_demo["set_no_t1"])
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	expect(alert.locator(".tc-alert-title")).not_to_be_empty()
	expect(alert.locator(".tc-alert-reason")).not_to_be_empty()
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t2_redo_queue_panel_lists_failed_set(t2_page, t2_demo):
	panel = t2_page.locator(".tc-t2-redo")
	expect(panel).to_contain_text(t2_demo["set_redo"], timeout=15000)
	expect(panel).to_contain_text("rửa lại lần 1")


def test_t2_cancel_clears_machine_and_list(t2_page, t2_demo):
	page = t2_page
	load_machine(page, t2_demo["machine"])
	scan(page, t2_demo["sets"][0])
	expect(page.locator(".tc-t2-sets tbody tr")).to_have_count(1, timeout=15000)
	page.locator("[data-action='t2-cancel']").click()
	expect(page.locator(".tc-t2-machine")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("QR máy rửa"))


def test_t2_duplicate_scan_shows_info_and_gate_panel(t2_page, t2_demo):
	page = t2_page
	load_machine(page, t2_demo["machine"])
	scan(page, t2_demo["sets"][0])
	expect(page.locator(".tc-t2-sets tbody tr")).to_have_count(1, timeout=15000)
	scan(page, t2_demo["sets"][0].lower())
	expect(page.locator(".tc-t2 .tc-alert-info")).to_contain_text("đã có trong danh sách", timeout=15000)
	expect(page.locator(".tc-t2-sets tbody tr")).to_have_count(1)
	gates = page.locator(".tc-t2-sets tbody tr").first.locator(".tc-gate")
	expect(gates).to_have_count(6)  # T1..T5 + Vô khuẩn, mỗi ô có chữ
	expect(gates.first).to_contain_text("Đạt")
	expect(gates.last).to_contain_text("Vô khuẩn")
	page.locator("[data-action='t2-cancel']").click()


def test_t2_touch_targets_and_font_sizes(t2_page, t2_demo):
	page = t2_page
	load_machine(page, t2_demo["machine"])
	scan(page, t2_demo["sets"][0])
	expect(page.locator(".tc-t2-sets tbody tr")).to_have_count(1, timeout=15000)
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t2 button')).filter(visible)
				.map((el) => ({label: el.textContent.trim(), action: el.dataset.action || '',
					height: el.getBoundingClientRect().height}));
			const fonts = Array.from(document.querySelectorAll('.tc-station *'))
				.filter((el) => visible(el) && Array.from(el.childNodes)
					.some((node) => node.nodeType === 3 && node.textContent.trim()))
				.map((el) => ({text: el.textContent.trim().slice(0, 30), size: parseFloat(getComputedStyle(el).fontSize)}));
			return {buttons, fonts};
		}"""
	)
	for button in measured["buttons"]:
		assert button["height"] >= 48, button
		if button["action"] == "t2-complete":
			assert button["height"] >= 56, button
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, small[:5]
	page.locator("[data-action='t2-cancel']").click()


def test_t2_load_happy_path_within_three_taps(t2_page, t2_demo):
	page = t2_page
	mock_agent(page)
	taps = Taps()
	load_machine(page, t2_demo["machine"])
	for set_id in t2_demo["sets"]:
		scan(page, set_id)
		expect(page.locator(".tc-t2-sets")).to_contain_text(set_id, timeout=15000)
	taps.tap(page.locator("[data-action='t2-complete']"))
	code = page.locator(".tc-t2-done .tc-cycle")
	expect(code).to_have_text(re.compile(r"^LR-\d{6}-\d{2}$"), timeout=15000)
	expect(page.locator(".tc-label .tc-label-qr")).to_be_visible()
	assert taps.count <= 3
	STATE["batch"] = code.inner_text()


def test_t2_unload_requires_matching_machine(t2_page, t2_demo):
	page = t2_page
	batch = STATE.get("batch")
	assert batch, "chạy test_t2_load_happy_path_within_three_taps trước"
	page.locator("[data-action='t2-mode'][data-mode='unload']").click()
	scan_settled(page, batch)
	expect(page.locator(".tc-t2-unload")).to_contain_text(batch, timeout=15000)
	scan_settled(page, t2_demo["machine_two_door"])
	alert = page.locator(".tc-t2 .tc-alert-error")
	expect(alert).to_contain_text("không khớp", timeout=15000)
	expect(page.locator(".tc-t2-form")).to_have_count(0)


def test_t2_pass_blocked_until_manual_data_confirmed(t2_page, t2_demo):
	page = t2_page
	batch = STATE["batch"]
	page.locator("[data-action='t2-mode'][data-mode='unload']").click()
	# QR lô trước rồi QR máy (Q15 nhận cả hai thứ tự): máy demo có thể còn lô đang chạy của lần chạy dở trước,
	# khi đó quét máy trước bị chặn "máy có nhiều lô đang chạy"
	scan_settled(page, batch)
	scan_settled(page, t2_demo["machine"])
	form = page.locator(".tc-t2-form")
	expect(form).to_be_visible(timeout=15000)
	expect(page.locator(".tc-t2-verdict")).to_have_count(0)  # chưa có dữ liệu: chưa kết luận được
	inputs = form.locator("input[data-param]")
	inputs.nth(0).fill("93")
	inputs.nth(1).fill("6")
	form.locator("[data-action='t2-save-data']").click()  # chưa tick, chưa ảnh
	expect(page.locator(".tc-t2 .tc-alert-error")).to_contain_text("tick xác nhận", timeout=15000)
	form.locator("#tc-t2-file").set_input_files(
		{"name": "printout.png", "mimeType": "image/png", "buffer": PNG_1PX}
	)
	expect(form).to_contain_text("Đã đính ảnh", timeout=15000)
	form.locator("[data-form='confirmed']").check()
	form.locator("[data-action='t2-save-data']").click()
	expect(page.locator(".tc-t2-verdict")).to_be_visible(timeout=15000)


def test_t2_close_requires_clean_test_and_confirm_tick_then_fail_returns_all_sets(t2_page, t2_demo):
	page = t2_page
	batch = STATE["batch"]
	page.locator("[data-action='t2-mode'][data-mode='unload']").click()
	scan_settled(page, batch)
	scan_settled(page, t2_demo["machine"])
	verdict = page.locator(".tc-t2-verdict")
	expect(verdict).to_be_visible(timeout=15000)
	verdict.locator("[data-field='result'][data-value='Fail']").click()
	verdict.locator("[data-field='clean'][data-value='Fail']").click()
	verdict.locator("[data-action='t2-record']").click()
	expect(page.locator(".tc-t2 .tc-alert-error")).to_contain_text("tick xác nhận")
	verdict.locator("[data-verdict='confirmed']").check()
	verdict.locator("[data-action='t2-record']").click()
	summary = page.locator(".tc-t2-result[data-result='Fail']")
	expect(summary).to_be_visible(timeout=15000)
	expect(summary).to_contain_text("FEAT-030")
	expect(summary.locator("tbody tr")).to_have_count(len(t2_demo["sets"]))
	expect(summary).to_contain_text("Xử lý lại")


def test_t2_offline_blocks_actions(t2_page, t2_demo):
	page = t2_page
	load_machine(page, t2_demo["machine"])
	page.context.set_offline(True)
	page.evaluate("window.dispatchEvent(new Event('offline'))")
	expect(page.locator(".tc-t2")).to_contain_text("FEAT-009", timeout=15000)
	expect(page.locator("[data-action='t2-complete']")).to_be_disabled()
	page.context.set_offline(False)
