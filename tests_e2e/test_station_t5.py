"""E2E màn T5 nạp mẻ tiệt khuẩn SCR-09 (STN 1366x768) và SCR-35 (PDA 412x915), FEAT-022.

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy (gói demo bị tiêu thụ khi nạp mẻ). Test nạp tối đa
các gói của ``TC_E2E_T5_PACKS`` theo thứ tự trong file: ``test_t5_load_happy_path_within_three_taps`` dùng cả ba gói;
test chỉ kiểm tra hiển thị dùng ``pack_plasma``/``pack_no_t4``; test nhập dữ liệu dùng mẻ ``load_running``.
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
	page.keyboard.type(raw)
	page.keyboard.press("Enter")


def scan_settled(page, raw):
	"""Quét rồi chờ RPC trả lời: kiosk bỏ qua mã quét khi đang chờ máy chủ (``busy``)."""
	scan(page, raw)
	expect(page.locator(".tc-t5 .tc-loading")).to_have_count(0, timeout=15000)


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


def test_t5_scan_box_locked_until_machine_scanned(t5_page, t5_demo):
	page = t5_page
	expect(page.locator(SCAN_INPUT)).to_be_focused()
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("QR máy tiệt khuẩn"))
	scan(page, t5_demo["packs"][0])
	alert = page.locator(".tc-t5 .tc-alert-error")
	expect(alert.locator(".tc-alert-title")).to_contain_text("Quét máy tiệt khuẩn trước", timeout=15000)
	expect(page.locator(".tc-t2-sets")).to_have_count(0)


def test_t5_locked_machine_is_rejected(t5_page, t5_demo):
	page = t5_page
	scan(page, t5_demo["machine_locked"])
	alert = page.locator(".tc-t5 .tc-alert-error")
	expect(alert).to_be_visible(timeout=15000)
	expect(alert.locator(".tc-alert-reason")).not_to_be_empty()
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()


def test_t5_incompatible_pack_shows_full_alert(t5_page, t5_demo):
	page = t5_page
	load_machine(page, t5_demo["machine"])
	scan(page, t5_demo["pack_plasma"])  # gói plasma vào máy hấp (BRU-REP-004)
	result = page.locator(".tc-result[data-state='error']")
	expect(result).to_be_visible(timeout=15000)
	alert = result.locator(".tc-alert-error")
	expect(alert.locator(".tc-alert-title")).not_to_be_empty()
	expect(alert.locator(".tc-alert-reason")).to_contain_text(t5_demo["pack_plasma"])
	expect(alert.locator(".tc-alert-action")).not_to_be_empty()
	expect(page.locator(".tc-t5-pack")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_be_focused()


def test_t5_pack_without_t4_pass_is_rejected(t5_page, t5_demo):
	page = t5_page
	load_machine(page, t5_demo["machine"])
	scan(page, t5_demo["pack_no_t4"])
	alert = page.locator(".tc-result[data-state='error'] .tc-alert-error")
	expect(alert).to_be_visible(timeout=15000)
	expect(alert.locator(".tc-alert-reason")).to_contain_text("T4")
	expect(page.locator(".tc-t5-pack")).to_have_count(0)


def test_t5_cancel_clears_machine_and_list(t5_page, t5_demo):
	page = t5_page
	load_machine(page, t5_demo["machine"])
	scan(page, t5_demo["packs"][0])
	expect(page.locator(".tc-t5-pack")).to_have_count(1, timeout=15000)
	page.locator("[data-action='t5-cancel']").click()
	expect(page.locator(".tc-t2-machine")).to_have_count(0)
	expect(page.locator(SCAN_INPUT)).to_have_attribute("placeholder", re.compile("QR máy tiệt khuẩn"))


def test_t5_duplicate_scan_shows_info_and_gate_panel(t5_page, t5_demo):
	page = t5_page
	load_machine(page, t5_demo["machine"])
	scan(page, t5_demo["packs"][0])
	expect(page.locator(".tc-t5-pack")).to_have_count(1, timeout=15000)
	scan(page, t5_demo["packs"][0])
	expect(page.locator(".tc-t5 .tc-alert-info")).to_contain_text("đã có trong danh sách", timeout=15000)
	expect(page.locator(".tc-t5-pack")).to_have_count(1)
	gates = page.locator(".tc-t5-pack").first.locator(".tc-gate")
	expect(gates).to_have_count(6)  # T1..T5 + Vô khuẩn, mỗi ô có chữ
	expect(gates.first).to_contain_text("Đạt")
	expect(gates.last).to_contain_text("Vô khuẩn")
	page.locator("[data-action='t5-cancel']").click()


def test_t5_touch_targets_and_font_sizes(t5_page, t5_demo):
	page = t5_page
	load_machine(page, t5_demo["machine"])
	scan(page, t5_demo["packs"][0])
	expect(page.locator(".tc-t5-pack")).to_have_count(1, timeout=15000)
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t5 button')).filter(visible)
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
		if button["action"] == "t5-complete":
			assert button["height"] >= 56, button
	small = [font for font in measured["fonts"] if font["size"] < 16]
	assert not small, small[:5]
	page.locator("[data-action='t5-cancel']").click()


def test_t5_load_happy_path_within_three_taps(t5_page, t5_demo):
	page = t5_page
	mock_agent(page)
	taps = Taps()
	load_machine(page, t5_demo["machine"])
	for cycle_id in t5_demo["packs"]:
		scan(page, cycle_id)
		expect(page.locator(".tc-t2-sets")).to_contain_text(cycle_id, timeout=15000)
	taps.tap(page.locator("[data-action='t5-complete']"))
	code = page.locator(".tc-t2-done .tc-cycle")
	expect(code).to_have_text(re.compile(r"^ME-\d{6}-\d{2}$"), timeout=15000)
	expect(page.locator(".tc-label .tc-label-qr")).to_be_visible()
	assert taps.count <= 3
	STATE["load"] = code.inner_text()


def test_t5_complete_by_scanning_control_code(t5_page, t5_demo):
	"""Quét ``HOAN-THANH-NAP`` cho cùng kết quả như bấm nút: dùng lại mẻ demo đã có để không tiêu thụ gói.

	Máy plasma: máy hấp ``machine`` đã có mẻ đang chạy từ test happy path (A-22: không nạp mẻ mới).
	"""
	page = t5_page
	load_machine(page, t5_demo["machine_plasma"])
	scan(page, "hoan-thanh-nap")
	alert = page.locator(".tc-t5 .tc-alert-error")
	expect(alert).to_contain_text("ít nhất 1 gói", timeout=15000)  # chưa có gói: nút bị chặn, không sinh mã
	page.locator("[data-action='t5-cancel']").click()


def test_t5_scanning_load_code_opens_lookup(t5_page, t5_demo):
	page = t5_page
	load = STATE.get("load") or t5_demo["load_running"]
	scan(page, load)
	card = page.locator(".tc-t2-lookup")
	expect(card).to_contain_text(load, timeout=15000)
	expect(card).to_contain_text("Chỉ thị hóa học loại 5")


def test_t5_manual_data_requires_confirmation_card_and_photo(t5_page, t5_demo):
	page = t5_page
	load = t5_demo["load_running"]
	page.locator("[data-action='t5-mode'][data-mode='data']").click()
	# QR mẻ trước rồi QR máy (nhận cả hai thứ tự); máy sai bị từ chối ngay
	scan_settled(page, load)
	scan_settled(page, t5_demo["machine_plasma"])
	expect(page.locator(".tc-t5 .tc-alert-error")).to_contain_text("không khớp", timeout=15000)
	expect(page.locator(".tc-t2-form")).to_have_count(0)
	scan_settled(page, load)
	scan_settled(page, t5_demo["machine_running"])
	form = page.locator(".tc-t2-form")
	expect(form).to_be_visible(timeout=15000)
	inputs = form.locator("input[data-param]")
	inputs.nth(0).fill("134")
	inputs.nth(1).fill("2,1")
	inputs.nth(2).fill("4")
	form.locator("[data-action='t5-save-data']").click()  # chưa tick, chưa quét thẻ, chưa ảnh
	alert = page.locator(".tc-t5 .tc-alert-error")
	expect(alert).to_contain_text("ô đánh dấu xác nhận", timeout=15000)
	expect(alert).to_contain_text("quét thẻ")
	form.locator("#tc-t5-file").set_input_files(
		{"name": "printout.png", "mimeType": "image/png", "buffer": PNG_1PX}
	)
	expect(page.locator("[data-region='notice']")).to_contain_text("Đã đính ảnh", timeout=15000)
	form.locator("[data-form='confirmed']").check()
	form.locator("#tc-t5-card").fill("THE-SAI-0000")
	form.locator("[data-action='t5-save-data']").click()
	expect(page.locator(".tc-t5 .tc-alert-error")).to_contain_text("Thẻ không khớp", timeout=15000)


def test_t5_manual_data_saved_flags_out_of_range_for_review(t5_page, t5_demo):
	import os

	page = t5_page
	load = t5_demo["load_running"]
	page.locator("[data-action='t5-mode'][data-mode='data']").click()
	scan_settled(page, load)
	scan_settled(page, t5_demo["machine_running"])
	form = page.locator(".tc-t2-form")
	expect(form).to_be_visible(timeout=15000)
	inputs = form.locator("input[data-param]")
	inputs.nth(0).fill("120")  # dưới dải 132-138
	expect(form.locator(".tc-t5-review").first).to_be_visible()
	expect(form.locator(".tc-t5-review").first).to_contain_text("Cần xem xét")
	inputs.nth(1).fill("2,1")
	inputs.nth(2).fill("4")
	form.locator("#tc-t5-file").set_input_files(
		{"name": "printout.png", "mimeType": "image/png", "buffer": PNG_1PX}
	)
	expect(page.locator("[data-region='notice']")).to_contain_text("Đã đính ảnh", timeout=15000)
	form.locator("[data-form='confirmed']").check()
	form.locator("#tc-t5-card").fill(os.environ["TC_E2E_T5_CARD_ID"])
	form.locator("[data-action='t5-save-data']").click()
	saved = page.locator(".tc-t5 .tc-alert-warn")
	expect(saved.first).to_contain_text("Cần xem xét", timeout=15000)
	expect(page.locator(".tc-t5")).to_contain_text("Hoàn tất chu trình")


def test_t5_offline_blocks_actions(t5_page, t5_demo):
	page = t5_page
	# máy hấp ``machine`` đã có mẻ đang chạy từ test happy path (A-22)
	load_machine(page, t5_demo["machine_plasma"])
	page.context.set_offline(True)
	page.evaluate("window.dispatchEvent(new Event('offline'))")
	expect(page.locator(".tc-t5")).to_contain_text("cần kết nối mạng", timeout=15000)
	expect(page.locator("[data-action='t5-complete']")).to_be_disabled()
	page.context.set_offline(False)


def test_t5_pda_layout_is_single_column(t5_page, t5_demo):
	"""SCR-35: màn hẹp (412x915) chuyển surface PDA: một cột, nút full-width ≥ 56 px, không cuộn ngang."""
	page = t5_page
	page.set_viewport_size({"width": 412, "height": 915})
	expect(page.locator(".tc-station")).to_have_attribute("data-surface", "PDA", timeout=15000)
	# ba gói `packs` đã nạp hết ở test happy path: dùng máy plasma với gói plasma chưa ai nạp
	load_machine(page, t5_demo["machine_plasma"])
	scan(page, t5_demo["pack_plasma"])
	expect(page.locator(".tc-t5-pack")).to_have_count(1, timeout=15000)
	measured = page.evaluate(
		"""() => {
			const visible = (el) => el.offsetParent !== null;
			const buttons = Array.from(document.querySelectorAll('.tc-t5 button')).filter(visible)
				.map((el) => {
					const parent = getComputedStyle(el.parentElement);
					const room = el.parentElement.clientWidth
						- parseFloat(parent.paddingLeft) - parseFloat(parent.paddingRight);
					return {action: el.dataset.action || '', width: el.getBoundingClientRect().width,
						height: el.getBoundingClientRect().height, room};
				});
			return {buttons, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
		}"""
	)
	assert measured["overflow"] <= 0, measured
	for button in measured["buttons"]:
		assert button["height"] >= 56, button
		# full-width = lấp đầy vùng chứa (nút trong khối có padding hẹp hơn màn), không thu về bề ngang chữ
		assert button["width"] >= button["room"] - 1, button
		# nút nằm trong khối lồng nhau (khối → mẻ đang mở) nên vùng chứa chỉ ~243 px trên màn 412 px; đã full-width ở trên
		assert button["width"] >= 200, button
	page.locator("[data-action='t5-cancel']").click()
	page.set_viewport_size({"width": 1366, "height": 768})
