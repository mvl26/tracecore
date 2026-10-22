"""E2E Desk hồ sơ thiết bị và chương trình xử lý (SCR-21, FEAT-038; WEB 1366x768, user TC R10).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên test_site) ghi TC_E2E_EQ_* cho máy và chương trình demo
của ``devdata.ensure_equipment_demo``. Equipment và Process Program không xóa được và Retired là một chiều, nên:
máy demo chỉ được đọc; test ngừng sử dụng tạo máy riêng (serial duy nhất mỗi lần chạy, hãng/model riêng để không lọt
vào hộp thoại sao chép) và để nó ở trạng thái Ngừng sử dụng; test sao chép tạo chương trình mới mã duy nhất.
"""

import os
import re
import uuid

import pytest
from playwright.sync_api import expect


def require_env(name):
	value = os.environ.get(name)
	if not value:
		pytest.skip(f"{name} is not set - run scripts/e2e_prepare.sh first")
	return value


def demo(key):
	return require_env(f"TC_E2E_EQ_{key.upper()}")


def open_form(page, doctype_slug, name):
	page.goto(f"/app/{doctype_slug}/{name}")
	expect(page.locator(".page-head .indicator-pill")).to_be_visible(timeout=30000)


def indicator(page):
	return page.locator(".page-head .indicator-pill")


def pick_link(page, fieldname, value, title):
	field = page.locator(f"input[data-fieldname='{fieldname}']")
	field.fill(value)
	page.locator("ul[role='listbox'] [role='option']", has_text=value).first.click()
	expect(field).to_have_value(title)


def pick_zone_in_and_wait_suggestion(page, value, title):
	with page.expect_response(lambda r: "tracecore.v1.zone.next_zone" in r.url):
		pick_link(page, "zone_in", value, title)


def clear_zone_out(page):
	page.evaluate("cur_frm.set_value('zone_out', '')")
	page.wait_for_function("!cur_frm.doc.zone_out")


def test_equipment_form_zone_out_follows_zone_in(r10_page):
	r10_page.goto("/app/equipment/new")
	zone_out = r10_page.locator("input[data-fieldname='zone_out']")
	expect(r10_page.locator("input[data-fieldname='zone_in']")).to_be_visible(timeout=30000)

	pick_zone_in_and_wait_suggestion(r10_page, "ZONE-DIRTY", "Dirty zone")
	expect(zone_out).to_have_value("Clean zone", timeout=15000)
	# khu cửa ra đã có giá trị: đổi khu cửa vào không ghi đè (chỉ gợi ý khi còn trống)
	pick_link(r10_page, "zone_in", "ZONE-CLEAN", "Clean zone")
	r10_page.wait_for_timeout(1500)
	expect(zone_out).to_have_value("Clean zone")
	clear_zone_out(r10_page)
	pick_zone_in_and_wait_suggestion(r10_page, "ZONE-DIRTY", "Dirty zone")
	expect(zone_out).to_have_value("Clean zone", timeout=15000)
	# khu cuối của luồng: máy một cửa, khu cửa ra để trống
	clear_zone_out(r10_page)
	pick_zone_in_and_wait_suggestion(r10_page, "ZONE-STERILE", "Sterile zone")
	expect(zone_out).to_have_value("")


def test_equipment_status_and_depreciation_shown(r10_page):
	# máy hấp demo: 600.000.000 / (10 năm x 3000 mẻ) = 20.000 VND mỗi mẻ; trạng thái luôn có chữ
	open_form(r10_page, "equipment", demo("steam"))
	expect(indicator(r10_page)).to_have_text("Sẵn sàng", timeout=15000)
	depreciation = r10_page.locator("[data-fieldname='depreciation_per_load']")
	expect(depreciation).to_contain_text("20.000")
	expect(r10_page.get_by_role("button", name="Ngừng sử dụng")).to_be_visible()

	open_form(r10_page, "equipment", demo("retired"))
	expect(indicator(r10_page)).to_have_text("Ngừng sử dụng", timeout=15000)
	expect(r10_page.get_by_role("button", name="Ngừng sử dụng")).to_have_count(0)

	# danh sách: cột trạng thái có chữ, không chỉ màu. Lọc theo mã: mỗi lần chạy e2e thêm một máy "E2E ngừng" (không
	# xóa được) nên quá 20 máy thì máy demo rơi khỏi trang đầu của danh sách
	for key, status in (("steam", "Sẵn sàng"), ("retired", "Ngừng sử dụng")):
		r10_page.goto(f"/app/equipment?name={demo(key)}")
		row = r10_page.locator(".list-row", has_text=demo(key)).first
		expect(row).to_contain_text(status, timeout=30000)


def create_machine(page):
	"""Máy riêng cho test ngừng sử dụng (qua frappe.client.insert từ trang Desk, dùng phiên đăng nhập của R10)."""
	page.goto("/app/equipment")
	page.wait_for_function("window.frappe && frappe.csrf_token && frappe.csrf_token !== '{{ csrf_token }}'")
	suffix = uuid.uuid4().hex[:8].upper()
	return page.evaluate(
		"""async (suffix) => (await frappe.xcall("frappe.client.insert", {doc: {
			doctype: "Equipment", equipment_name: "E2E ngừng " + suffix, equipment_type: "Steam Sterilizer",
			manufacturer: "E2E Retire Maker", model: "E2E-R" + suffix, serial_no: "E2E-RET-" + suffix,
			zone_in: "ZONE-CLEAN", zone_out: "ZONE-STERILE", purchase_value: 600000000,
			depreciation_years: 10, planned_loads_year: 3000}})).name""",
		suffix,
	)


def test_retire_requires_reason_then_marks_retired(r10_page):
	name = create_machine(r10_page)
	open_form(r10_page, "equipment", name)
	expect(indicator(r10_page)).to_have_text("Sẵn sàng", timeout=15000)
	r10_page.get_by_role("button", name="Ngừng sử dụng").click()
	dialog = r10_page.locator(".modal.show", has=r10_page.locator("textarea[data-fieldname='reason']"))
	expect(dialog).to_be_visible()

	# lý do trống: Frappe chặn, hộp thoại còn nguyên và máy chưa đổi trạng thái
	dialog.get_by_role("button", name="Ngừng sử dụng", exact=True).click()
	expect(dialog).to_be_visible()
	expect(indicator(r10_page)).to_have_text("Sẵn sàng")

	dialog.locator("textarea[data-fieldname='reason']").fill("E2E: máy hỏng không sửa được")
	dialog.get_by_role("button", name="Ngừng sử dụng", exact=True).click()
	expect(indicator(r10_page)).to_have_text("Ngừng sử dụng", timeout=15000)
	expect(r10_page.get_by_role("button", name="Ngừng sử dụng")).to_have_count(0)
	saved = r10_page.request.get(f"/api/resource/Equipment/{name}").json()["data"]
	assert saved["status"] == "Retired"
	assert saved["retired_reason"] == "E2E: máy hỏng không sửa được"


def test_program_norm_status_and_outside_range_hint(r10_page):
	hint = r10_page.locator(".form-message")
	open_form(r10_page, "process-program", demo("program_complete"))
	expect(indicator(r10_page)).to_have_text("Đủ định mức", timeout=15000)
	expect(hint).to_have_count(0)

	open_form(r10_page, "process-program", demo("program_missing"))
	expect(indicator(r10_page)).to_have_text("Thiếu định mức", timeout=15000)

	# 150 °C vượt dải an toàn 105-140 °C của máy: cảnh báo cam, vẫn lưu được
	open_form(r10_page, "process-program", demo("program_outside"))
	expect(hint).to_contain_text("ngoài dải an toàn", timeout=15000)

	open_form(r10_page, "process-program", demo("program_inactive"))
	expect(r10_page.locator("input[data-fieldname='is_active']")).not_to_be_checked(timeout=15000)


def test_copy_program_to_same_model_machine(r10_page):
	source, target = demo("program_complete"), demo("steam_copy_target")
	new_code = f"E2E-COPY-{uuid.uuid4().hex[:8].upper()}"
	open_form(r10_page, "process-program", source)
	r10_page.get_by_role("button", name="Sao chép sang máy khác").click()
	dialog = r10_page.locator(".modal.show", has=r10_page.locator("input[data-fieldname='new_code']"))
	expect(dialog).to_be_visible()

	# chỉ máy cùng hãng + model, chưa ngừng sử dụng, khác máy nguồn
	field = dialog.locator("input[data-fieldname='target_equipment']")
	field.click()
	options = r10_page.locator("ul[role='listbox'] [role='option']")
	expect(options.filter(has_text=target).first).to_be_visible(timeout=15000)
	# dòng cuối của danh sách ghi lại bộ lọc đang áp dụng (có nhắc mã máy nguồn): chỉ xét các dòng kết quả (tên, rồi mã TB-####)
	results = [text for text in options.all_inner_texts() if re.search(r"\nTB-\d+$", text)]
	offered = [text.rsplit("\n", 1)[-1] for text in results]
	assert offered == [target], offered
	options.filter(has_text=target).first.click()
	expect(field).to_have_value(
		re.compile(r"E2E steam sterilizer 2")
	)  # ô Link hiện tên máy (title), không phải mã

	dialog.locator("input[data-fieldname='new_code']").fill(new_code)
	dialog.get_by_role("button", name="Sao chép", exact=True).click()
	expect(r10_page).to_have_url(re.compile(rf"/app/process-program/{new_code}$"), timeout=30000)
	expect(r10_page.locator("[data-fieldname='equipment']").first).to_contain_text(
		"E2E steam sterilizer 2", timeout=15000
	)
	copied = r10_page.request.get(f"/api/resource/Process Program/{new_code}").json()["data"]
	assert copied["equipment"] == target
