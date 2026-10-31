"""E2E Desk cấu hình khu-trạm, máy in, mẫu nhãn (SCR-33, FEAT-002; WEB 1366x768, user TC R10).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước mỗi lần chạy (có user TC R10 và máy in demo của TR-004).
Zone Station không xóa được (E8, Audit Log), nên test trạm không-khu dùng lại một trạm có tên cố định thay vì
tạo mới mỗi lần; test nạp cuộn trả cuộn hấp về máy in để test T4 chạy tiếp được.
"""

import json
import os
import re

import pytest
from playwright.sync_api import expect


def require_env(name):
	value = os.environ.get(name)
	if not value:
		pytest.skip(f"{name} is not set - run scripts/e2e_prepare.sh first")
	return value


NO_ZONE_STATION_NAME = "E2E không khu"


def new_station(page):
	page.goto("/app/zone-station/new")
	expect(page.locator("input[data-fieldname='zone_station_name']")).to_be_visible(timeout=30000)


def set_parent_zone(page, zone, title):
	field = page.locator("input[data-fieldname='parent_zone']")
	field.fill(zone)
	page.locator("ul[role='listbox'] [role='option']", has_text=zone).first.click()
	expect(field).to_have_value(title)


def allowed_functions(page, zone):
	"""Chức năng được phép của vùng, đúng RPC mà form dùng để lọc ô chọn."""
	response = page.request.get("/api/method/tracecore.v1.zone.allowed_functions", params={"zone": zone})
	return [row["value"] for row in response.json()["message"]]


def test_station_functions_follow_zone(r10_page):
	assert "PACK" in allowed_functions(r10_page, "ZONE-CLEAN")
	assert "PACK" not in allowed_functions(r10_page, "ZONE-DIRTY")
	assert "RECEIVE" in allowed_functions(r10_page, "ZONE-DIRTY")


def test_station_without_zone_shows_inactive(r10_page):
	existing = r10_page.request.get(
		"/api/resource/Zone Station",
		params={"filters": json.dumps({"zone_station_name": NO_ZONE_STATION_NAME}), "limit_page_length": 1},
	).json()["data"]
	if existing:
		r10_page.goto(f"/app/zone-station/{existing[0]['name']}")
	else:
		new_station(r10_page)
		r10_page.locator("input[data-fieldname='zone_station_name']").fill(NO_ZONE_STATION_NAME)
		r10_page.keyboard.press("Control+s")
		expect(r10_page).to_have_url(re.compile(r"/app/zone-station/TR-\d+"), timeout=15000)
	indicator = r10_page.locator(".page-head .indicator-pill")
	expect(indicator).to_have_text("Không hoạt động", timeout=15000)
	expect(r10_page.locator("input[data-fieldname='parent_zone']")).to_have_value("")


def load_roll(page, printer, roll_code):
	page.goto(f"/app/printer/{printer}")
	page.get_by_role("button", name="Nạp cuộn nhãn").click()
	dialog = page.locator(".modal.show")
	dialog.locator("input[data-fieldname='roll_code']").fill(roll_code)
	return dialog


def test_load_roll_dialog_updates_printer(r10_page):
	printer = require_env("TC_E2E_T4_PRINTER")
	steam, plasma = require_env("TC_E2E_T4_ROLL_STEAM"), require_env("TC_E2E_T4_ROLL_PLASMA")
	label_field = "input[data-fieldname='label_type_loaded']"
	try:
		page = r10_page
		dialog = load_roll(page, printer, plasma)
		expect(page.locator(label_field)).not_to_have_value("")
		# máy in demo nạp nhãn hấp, hoặc plasma nếu test T4 vừa chạy
		before = page.locator(label_field).input_value()

		# chưa tick xác nhận: cảnh báo, chưa nạp
		dialog.get_by_role("button", name="Nạp cuộn", exact=True).click()
		expect(page.locator(".modal.show", has_text="Cần xác nhận")).to_be_visible()
		page.locator(".modal.show", has_text="Cần xác nhận").locator(".btn-modal-close").click()
		expect(page.locator(".modal.show", has_text="Cần xác nhận")).to_have_count(0)
		expect(page.locator(label_field)).to_have_value(before)

		dialog = page.locator(".modal.show", has=page.locator("input[data-fieldname='roll_code']"))
		dialog.locator("input[data-fieldname='confirmed']").check()
		dialog.get_by_role("button", name="Nạp cuộn", exact=True).click()
		loaded = page.locator(".modal.show", has_text="Đã nạp cuộn nhãn")
		expect(loaded).to_be_visible(timeout=15000)
		expect(loaded).to_contain_text("Nhãn còn chờ in")  # Desk không phát hành nhãn chờ (ruling F2)
		expect(page.locator(label_field)).to_have_value("VT-NHAN-PLASMA", timeout=15000)
	finally:
		# trả cuộn hấp để các test T4 dùng tiếp (máy in demo nạp nhãn hấp)
		dialog = load_roll(r10_page, printer, steam)
		dialog.locator("input[data-fieldname='confirmed']").check()
		dialog.get_by_role("button", name="Nạp cuộn", exact=True).click()
		expect(r10_page.locator(".modal.show", has_text="Đã nạp cuộn nhãn")).to_be_visible(timeout=15000)
		expect(r10_page.locator(label_field)).to_have_value("VT-NHAN-HAP", timeout=15000)


def open_preview(page, variant):
	page.goto("/app/label-template/Pack label - Steam")
	page.get_by_role("button", name="Xem trước", exact=True).click()
	page.get_by_role("menuitem", name=variant).or_(page.get_by_text(variant, exact=True)).first.click()


def test_label_template_preview_shows_zpl(r10_page):
	for variant in ("Xem trước có dấu", "Xem trước bỏ dấu"):
		open_preview(r10_page, variant)
		zpl = r10_page.locator(".modal.show pre")
		expect(zpl).to_be_visible(timeout=15000)
		expect(zpl).to_contain_text("^XA")
		assert zpl.inner_text().lstrip().startswith("^XA")

	# mẫu lỗi (mock ở mức route): hộp thoại lỗi có tiêu đề đã dịch, lý do và hành động từ server
	r10_page.route(
		"**/api/method/tracecore.v1.label_template.preview*",
		lambda route: route.fulfill(
			status=422,
			content_type="application/json",
			body=json.dumps(
				{
					"message": {
						"ok": False,
						"error": {
							"code": "LABEL_RENDER_FAILED",
							"reason": "Biến {{ x }} không tồn tại",
							"action": "Sửa nội dung mẫu rồi xem trước lại.",
						},
					}
				}
			),
		),
	)
	open_preview(r10_page, "Xem trước có dấu")
	error = r10_page.locator(".modal.show", has_text="Không dựng được mẫu nhãn")
	expect(error).to_be_visible(timeout=15000)
	expect(error).to_contain_text("Sửa nội dung mẫu rồi xem trước lại.")
