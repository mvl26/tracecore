"""E2E màn SCR-43 import danh mục (FEAT-011, FR-M9-11, UC-39; Desk 1366x768, user TC R10).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>``. Dụng cụ tạo với mã ngẫu nhiên nên chạy lại không đụng dữ liệu cũ.
"""

import re
import uuid

from openpyxl import Workbook
from playwright.sync_api import expect

HEADER = ["Instrument Code", "Instrument Name", "Spaulding Class", "Compatible Methods"]


def workbook(path, rows):
	book = Workbook()
	sheet = book.active
	sheet.append(HEADER)
	for row in rows:
		sheet.append(list(row))
	book.save(path)
	return str(path)


def choose_file(page, path):
	page.get_by_role("button", name="Chọn tệp Excel").click()
	uploader = page.locator(".modal.show .file-uploader").last
	expect(uploader).to_be_visible(timeout=10000)
	uploader.locator("input[type=file]").first.set_input_files(path)
	with page.expect_response(lambda response: "upload_file" in response.url) as upload:
		page.locator(".modal.show .modal-footer .btn-primary", has_text="Tải lên").last.click()
	assert upload.value.ok, upload.value.text()
	# Frappe thêm hậu tố hash khi trùng tên file đã tải trước đó
	stem = re.escape(path.rsplit("/", 1)[-1].removesuffix(".xlsx"))
	expect(page.locator('[data-region="file"]')).to_have_text(re.compile(stem + r"\w*\.xlsx"), timeout=15000)


def test_import_instruments_reports_row_errors_then_skips_existing(r10_page, tmp_path):
	page = r10_page
	page.goto("/app/tc-import")
	page.locator('[data-fieldname="kind"] select').select_option("instrument")
	codes = [f"E2E-{uuid.uuid4().hex[:6].upper()}" for _ in range(3)]
	path = workbook(
		tmp_path / "dung-cu.xlsx",
		[
			(codes[0], "Kéo Mayo E2E", "Critical", "Steam 134"),
			(codes[1], "Kẹp Kelly E2E", "Semi-critical", "Steam 134, Plasma"),
			(codes[2], "Dụng cụ lỗi", "Critical", "Gamma"),
		],
	)
	result = page.locator('[data-region="result"]')
	save = page.get_by_role("button", name="Lưu các dòng đúng")
	expect(save).to_be_disabled()  # chưa kiểm thì không ghi sổ được

	choose_file(page, path)
	page.get_by_role("button", name="Kiểm tra tệp").click()
	expect(result).to_contain_text("Đã kiểm 3 dòng", timeout=15000)
	expect(result.locator("table")).to_contain_text("Gamma")  # dòng 4 sai phương pháp, nêu đúng dòng Excel
	expect(result.locator("table td").first).to_have_text("4")

	save.click()
	expect(result).to_contain_text("2 tạo mới, 0 đã có, 1 có lỗi", timeout=20000)

	# import lại cùng file: báo file đã import, dòng đã có được bỏ qua (UC-39 A1); không còn dòng mới nên không ghi sổ
	choose_file(page, path)
	page.get_by_role("button", name="Kiểm tra tệp").click()
	expect(result).to_contain_text("Tệp này đã được nhập", timeout=15000)
	expect(result).to_contain_text("0 bản ghi sẵn sàng lưu, 2 đã có, 1 lỗi dòng.")
	expect(result).to_contain_text(f"Đã có (bỏ qua): {codes[0]}, {codes[1]}")
	expect(save).to_be_disabled()
