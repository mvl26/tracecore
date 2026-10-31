"""E2E Desk in nhãn QR đối tượng và cấp mã cuộn (SCR-33, FEAT-005; WEB 1366x768, user TC R10 + Stock User).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên test_site) ghi TC_E2E_CODES_* của
``devdata.ensure_codes_demo``: máy in mạng demo host 127.0.0.1, cổng TC_E2E_CODES_PRINTER_PORT. Fixture ``fake_printer``
dựng socket TCP giả ở cổng đó; worker của bench (đường server, A-05 R1) gửi ZPL tới và test chờ đúng nhãn của mã mình
(lọc theo ``^FDMA,<mã>``) nên lệnh in còn sót của lần chạy trước không làm sai kết quả. Equipment không xóa được, mã
cuộn không cấp lại: test dùng lại máy demo và mỗi lần cấp mã cuộn mới (dữ liệu cũ trên site dev được chấp nhận).
"""

import re

from playwright.sync_api import expect

LABEL_OBJECT_DIALOG = ".modal.show"


def open_form(page, doctype_slug, name):
	page.goto(f"/app/{doctype_slug}/{name}")
	expect(page.locator(".page-head .indicator-pill")).to_be_visible(timeout=30000)


def open_print_dialog(page, click):
	"""Mở hộp thoại in bằng `click()` và chờ lượt gợi ý máy in mặc định xong (để không ghi đè lựa chọn của test).

	Site e2e luôn có máy in mạng demo đang hoạt động nên hộp thoại luôn gợi ý một máy in (máy mạng đầu tiên theo tên).
	"""
	click()
	dialog = page.locator(LABEL_OBJECT_DIALOG, has=page.locator("input[data-fieldname='printer']"))
	expect(dialog).to_be_visible()
	expect(dialog.locator("input[data-fieldname='printer']")).not_to_have_value("", timeout=15000)
	return dialog


def choose_printer(dialog, printer):
	"""Chọn máy in demo trong ô Link (mặc định là máy in mạng đầu tiên theo tên, có thể không phải máy demo)."""
	field = dialog.locator("input[data-fieldname='printer']")
	field.click()  # hộp thoại giữ focus ở modal: fill không focus thì awesomplete không mở danh sách
	field.fill(printer)
	dialog.page.locator("ul[role='listbox'] [role='option']", has_text=printer).first.click()
	expect(field).to_have_value(printer)
	expect(dialog).to_contain_text("Máy in mạng: máy chủ gửi nhãn thẳng tới máy in.", timeout=15000)


def result_row(dialog, code):
	return dialog.locator("tbody tr", has=dialog.page.locator("td", has_text=re.compile(rf"^{code}$")))


def test_print_equipment_qr_label_reaches_printer(codes_page, codes_demo, fake_printer):
	code = codes_demo["equipment"]
	open_form(codes_page, "equipment", code)
	dialog = open_print_dialog(codes_page, codes_page.get_by_role("button", name="In nhãn QR").click)
	# xem trước: ảnh PNG do server dựng (QR + mã), chưa gửi gì tới máy in
	expect(dialog.locator(f"img[alt*='{code}']")).to_be_visible(timeout=30000)
	assert fake_printer.labels_for(code) == []

	choose_printer(dialog, codes_demo["printer"])
	dialog.get_by_role("button", name="In", exact=True).click()
	row = result_row(dialog, code)
	expect(dialog.get_by_role("button", name="Đóng", exact=True)).to_be_visible(timeout=30000)
	# hộp thoại hỏi job_status tới khi worker ghi kết quả: "Đã in", không dừng ở "Đã xếp hàng"
	expect(row).to_contain_text("Đã in", timeout=30000)

	zpl = fake_printer.wait_for([code])[code][0]
	assert "^BQN" in zpl, zpl
	assert f"^FDMA,{code}^FS" in zpl, zpl
	assert zpl.startswith("^XA") and zpl.rstrip().endswith("^XZ"), zpl


def test_print_blocked_for_retired_equipment(codes_page, codes_demo, fake_printer):
	code = codes_demo["retired"]
	open_form(codes_page, "equipment", code)
	expect(codes_page.locator(".form-message")).to_contain_text(
		f"Không in được nhãn QR: thiết bị {code} đã ngừng sử dụng; vẫn tra cứu được lịch sử.", timeout=15000
	)
	expect(codes_page.get_by_role("button", name="In nhãn QR")).to_have_count(0)

	# gọi thẳng RPC (như bấm từ một tab cũ): server vẫn chặn có lý do, không tạo lệnh in
	result = codes_page.evaluate(
		"""async ([code, printer]) => tracecore.codes.post("tracecore.v1.print.object_label",
			{label_object: "Equipment", code, printer})""",
		[code, codes_demo["printer"]],
	)
	assert result["ok"] is False, result
	assert result["error"]["code"] in ("EQUIPMENT_RETIRED", "CODE_DISABLED"), result
	assert result["error"]["title"] and result["error"]["reason"] and result["error"]["action"], result
	assert fake_printer.labels_for(code) == []


def test_issue_rolls_then_print_all(codes_page, codes_demo, fake_printer):
	open_form(codes_page, "item", codes_demo["label_item"])
	codes_page.get_by_role("button", name="Cấp mã cuộn").click()
	issue = codes_page.locator(LABEL_OBJECT_DIALOG, has=codes_page.locator("input[data-fieldname='count']"))
	expect(issue).to_be_visible()
	issue.locator("input[data-fieldname='count']").fill("3")
	issue.get_by_role("button", name="Cấp mã", exact=True).click()

	issued = codes_page.locator(LABEL_OBJECT_DIALOG, has_text="Đã cấp 3 mã cuộn cho")
	expect(issued).to_be_visible(timeout=30000)
	codes = re.findall(r"CN-\d{5}", issued.inner_text())
	assert len(codes) == 3, codes
	numbers = [int(code[3:]) for code in codes]
	assert numbers == list(range(numbers[0], numbers[0] + 3)), codes  # liên tiếp, không thủng số

	dialog = open_print_dialog(codes_page, issued.get_by_role("button", name="In tất cả").click)
	choose_printer(dialog, codes_demo["printer"])
	dialog.get_by_role("button", name="In 3 nhãn", exact=True).click()
	expect(dialog).to_contain_text(
		"Đã in 3/3 nhãn; 0 nhãn chờ phần mềm trạm; 0 nhãn không in được.", timeout=60000
	)
	for code in codes:
		expect(result_row(dialog, code)).to_contain_text("Đã in")

	received = fake_printer.wait_for(codes)
	# mã mới cấp: mỗi mã đúng một lệnh in
	assert {code: len(labels) for code, labels in received.items()} == dict.fromkeys(codes, 1), received
	assert all("^BQN" in labels[0] for labels in received.values()), received


def test_bulk_print_from_list(codes_page, codes_demo, fake_printer):
	ready = [codes_demo["equipment"], codes_demo["equipment_2"]]
	retired = codes_demo["retired"]
	codes_page.goto("/app/equipment?manufacturer=E2E%20Maker")
	for code in [*ready, retired]:
		row = codes_page.locator(".list-row-container", has_text=code).first
		expect(row).to_be_visible(timeout=30000)
		row.locator("input.list-row-checkbox").check()

	codes_page.get_by_role("button", name="Các thao tác").click()
	dialog = open_print_dialog(
		codes_page, codes_page.locator(".dropdown-menu.show .dropdown-item", has_text="In nhãn QR").click
	)
	choose_printer(dialog, codes_demo["printer"])
	dialog.get_by_role("button", name="In 3 nhãn", exact=True).click()

	expect(dialog).to_contain_text(
		"Đã in 2/3 nhãn; 0 nhãn chờ phần mềm trạm; 1 nhãn không in được.", timeout=60000
	)
	for code in ready:
		expect(result_row(dialog, code)).to_contain_text("Đã in")
	expect(result_row(dialog, retired)).to_contain_text("Không in được")

	fake_printer.wait_for(ready)
	assert fake_printer.labels_for(retired) == []


def test_reprint_issued_roll_label_from_item(codes_page, codes_demo, fake_printer):
	"""Mã cuộn đã cấp (vd lần in trước lỗi) in lại được từ nút "In nhãn cuộn" trên form Item."""
	open_form(codes_page, "item", codes_demo["label_item"])
	codes_page.get_by_role("button", name="Cấp mã cuộn").click()
	issue = codes_page.locator(LABEL_OBJECT_DIALOG, has=codes_page.locator("input[data-fieldname='count']"))
	issue.locator("input[data-fieldname='count']").fill("1")
	issue.get_by_role("button", name="Cấp mã", exact=True).click()
	issued = codes_page.locator(LABEL_OBJECT_DIALOG, has_text="Đã cấp 1 mã cuộn cho")
	expect(issued).to_be_visible(timeout=30000)
	code = re.findall(r"CN-\d{5}", issued.inner_text())[0]
	issued.locator(".btn-modal-close").click()  # không in ngay: giả lập lần in trước bị bỏ dở
	expect(issued).to_be_hidden()

	codes_page.get_by_role("button", name="In nhãn cuộn").click()
	picker = codes_page.locator(LABEL_OBJECT_DIALOG, has_text="Đánh dấu mã cuộn cần in")
	expect(picker).to_be_visible(timeout=30000)
	# chưa chọn gì: báo lỗi inline, không mở hộp thoại in
	picker.get_by_role("button", name="In mã đã chọn", exact=True).click()
	expect(picker).to_contain_text("Chưa chọn mã cuộn nào.")
	picker.locator(f"input[type='checkbox'][data-unit='{code}']").check()
	dialog = open_print_dialog(
		codes_page, picker.get_by_role("button", name="In mã đã chọn", exact=True).click
	)
	choose_printer(dialog, codes_demo["printer"])
	dialog.get_by_role("button", name="In", exact=True).click()
	expect(result_row(dialog, code)).to_contain_text("Đã in", timeout=60000)
	assert len(fake_printer.wait_for([code])[code]) == 1


def gateway_error_once(page, method, status):
	"""Lần gọi đầu tới `method` nhận trang lỗi HTML của proxy (`status`), các lần sau đi tới server thật.

	Trả danh sách `(X-Idempotency-Key, body)` của mọi lần gọi để test so khóa/body giữa lần đầu và lần gửi lại.
	"""
	calls = []

	def handle(route, request):
		calls.append((request.headers.get("x-idempotency-key"), request.post_data))
		if len(calls) == 1:
			route.fulfill(status=status, content_type="text/html", body="<html><h1>Bad Gateway</h1></html>")
		else:
			route.continue_()

	page.route(f"**/api/method/{method}", handle)
	return calls


def test_issue_rolls_gateway_error_keeps_dialog_and_request(codes_page, codes_demo):
	"""502 của proxy = chưa biết đã cấp chưa: hộp thoại không đóng, bấm lại gửi đúng khóa + body cũ (không cấp hai lần)."""
	calls = gateway_error_once(codes_page, "tracecore.v1.codes.issue_rolls", 502)
	open_form(codes_page, "item", codes_demo["label_item"])
	codes_page.get_by_role("button", name="Cấp mã cuộn").click()
	issue = codes_page.locator(LABEL_OBJECT_DIALOG, has=codes_page.locator("input[data-fieldname=count]"))
	issue.locator("input[data-fieldname=count]").fill("2")
	issue.get_by_role("button", name="Cấp mã", exact=True).click()

	expect(issue).to_contain_text("Máy chủ không trả lời", timeout=30000)
	expect(issue).to_contain_text("HTTP 502")
	expect(issue).to_be_visible()

	issue.get_by_role("button", name="Cấp mã", exact=True).click()
	issued = codes_page.locator(LABEL_OBJECT_DIALOG, has_text="Đã cấp 2 mã cuộn cho")
	expect(issued).to_be_visible(timeout=30000)
	assert len(calls) == 2, calls
	assert calls[0][0] and calls[0] == calls[1], calls  # cùng X-Idempotency-Key, cùng body (kể cả client_ts)


def test_print_gateway_error_offers_resend_with_same_request(codes_page, codes_demo, fake_printer):
	code = codes_demo["equipment_2"]
	calls = gateway_error_once(codes_page, "tracecore.v1.print.object_label", 503)
	open_form(codes_page, "equipment", code)
	dialog = open_print_dialog(codes_page, codes_page.get_by_role("button", name="In nhãn QR").click)
	choose_printer(dialog, codes_demo["printer"])
	dialog.get_by_role("button", name="In", exact=True).click()

	resend = dialog.get_by_role("button", name="Gửi lại nhãn chưa gửi được", exact=True)
	expect(resend).to_be_visible(timeout=30000)
	expect(result_row(dialog, code)).to_contain_text("HTTP 503")
	resend.click()
	expect(result_row(dialog, code)).to_contain_text("Đã in", timeout=60000)
	assert len(calls) == 2, calls
	assert calls[0][0] and calls[0] == calls[1], calls
	assert fake_printer.wait_for([code])[code]
