"""E2E Desk vật tư tiêu hao và nhập kho SCR-24 (FEAT-041; WEB 1366x768, user TC R09).

Chuẩn bị: ``scripts/e2e_prepare.sh <site dev>`` (KHÔNG chạy trên test_site; trong bench riêng đặt BENCH_DIR và TC_E2E_ENV)
ghi TC_E2E_INV_* của ``devdata.ensure_inventory_demo``: Company, kho, nhà cung cấp và bốn vật tư mẫu.
Stock Entry, Item và Batch không xóa được nên mỗi test dùng mã lô và số chứng từ duy nhất (uuid); vật tư mẫu dùng lại.
File Excel tạo tạm trong ``tmp_path`` của pytest. Không dùng ngủ cố định: mọi chờ đều theo điều kiện (expect, response).
"""

import json
import uuid
from datetime import date, timedelta

from openpyxl import Workbook
from playwright.sync_api import expect

# Tiêu đề tiếng Anh của file mẫu: luôn được nhận (receipt_import.ENGLISH_LABELS)
EXCEL_HEADERS = (
	"Item code",
	"Lot number",
	"Expiry date",
	"Received quantity",
	"Unit price",
	"Supplier name",
	"Supplier document number",
	"Receiving warehouse",
)

# Điền phiếu nhập bằng API form của Frappe (nhập ô lưới bằng bàn phím rất chậm và dễ vỡ); lưu, ghi sổ, thông báo lỗi
# và bộ chọn lô của ERPNext vẫn là đường thật của người dùng. Chờ theo điều kiện: dòng đã có đơn vị tính (get_item_details xong).
FILL_RECEIPT = """async (a) => {
  const frm = cur_frm;
  const until = async (test) => {
    for (let i = 0; i < 200 && !test(); i++) await new Promise((r) => setTimeout(r, 50));
    if (!test()) throw new Error("form did not settle");
  };
  await frm.set_value("tc_supplier", a.supplier);
  await frm.set_value("tc_document_no", a.doc_no);
  await frm.set_value("to_warehouse", a.warehouse);
  frm.clear_table("items");
  for (const line of a.lines) {
    const row = frm.add_child("items");
    await frappe.model.set_value(row.doctype, row.name, "item_code", line.item_code);
    await until(() => locals[row.doctype][row.name].uom);
    await frappe.model.set_value(row.doctype, row.name, "t_warehouse", a.warehouse);
    await frappe.model.set_value(row.doctype, row.name, "qty", line.qty);
    await frappe.model.set_value(row.doctype, row.name, "basic_rate", line.rate);
    await frappe.model.set_value(row.doctype, row.name, "tc_batch_id", line.batch);
    await frappe.model.set_value(row.doctype, row.name, "tc_expiry_date", line.expiry || null);
  }
  frm.refresh_field("items");
}"""


def unique(prefix):
	return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def iso(days=0):
	return (date.today() + timedelta(days=days)).isoformat()


def vn(days=0):
	return (date.today() + timedelta(days=days)).strftime("%d/%m/%Y")


def modal(page, text):
	dialog = page.locator(".modal.show", has_text=text).last
	expect(dialog).to_be_visible(timeout=15000)
	return dialog


def close_modals(page):
	for _attempt in range(4):
		shown = page.locator(".modal.show")
		if not shown.count():
			break
		shown.last.locator(".btn-modal-close").first.click()
		expect(shown).to_have_count(max(shown.count() - 1, 0))
	# chờ hiệu ứng đóng của Bootstrap xong (display:none, hết nền mờ): hộp thoại mở lại trong lúc đang đóng bị bỏ qua
	expect(page.locator(".modal:visible, .modal-backdrop")).to_have_count(0)


def api_get(page, path, **params):
	response = page.request.get(path, params=params)
	assert response.ok, response.text()
	return response.json()


def stock_entries(page, document_no):
	rows = api_get(
		page,
		"/api/resource/Stock Entry",
		filters=json.dumps([["tc_document_no", "=", document_no]]),
		fields=json.dumps(["name", "docstatus"]),
		limit_page_length=20,
	)
	return rows["data"]


def batch_qty(page, item_code, batch_id):
	"""Tồn của lô (ERPNext get_batch_qty, cộng mọi kho)."""
	message = api_get(
		page,
		"/api/method/erpnext.stock.doctype.batch.batch.get_batch_qty",
		batch_no=batch_id,
		item_code=item_code,
	)["message"]
	return sum(row["qty"] for row in message)


def new_receipt(page):
	"""Mở phiếu nhập mới bằng nút "Nhập kho vật tư" của danh sách Stock Entry."""
	page.goto("/app/stock-entry")
	page.get_by_role("button", name="Nhập kho vật tư").click()
	expect(page.locator("[data-fieldname='tc_supplier'] input")).to_be_visible(timeout=30000)
	page.wait_for_function(
		"() => window.cur_frm && cur_frm.doctype === 'Stock Entry' && cur_frm.doc.stock_entry_type === 'Material Receipt'"
	)


def fill_receipt(page, inv, doc_no, lines):
	page.evaluate(
		FILL_RECEIPT,
		{"supplier": inv["supplier"], "doc_no": doc_no, "warehouse": inv["warehouse"], "lines": lines},
	)


def save_and_wait(page):
	"""Ctrl+S và chờ server trả lời (savedocs); trả response."""
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as saved:
		page.keyboard.press("Control+s")
	return saved.value


def submit_and_wait(page):
	"""Bấm nút chính (Ghi sổ), xác nhận hộp thoại và chờ server ghi sổ xong."""
	page.locator(".page-actions .primary-action:visible").click()
	with page.expect_response(lambda response: "frappe.desk.form.save.savedocs" in response.url) as submitted:
		page.locator(".modal.show .btn-primary").last.click()
	assert submitted.value.ok, submitted.value.text()


def indicator(page):
	return page.locator(".page-head .indicator-pill:visible").first


def line(item_code, batch, expiry, qty=5, rate=1000):
	return {"item_code": item_code, "batch": batch, "expiry": expiry, "qty": qty, "rate": rate}


def workbook(path, rows):
	book = Workbook()
	sheet = book.active
	sheet.title = "Receipt"
	sheet.append(list(EXCEL_HEADERS))
	for values in rows:
		sheet.append(list(values))
	book.save(path)
	return str(path)


def open_excel_dialog(page):
	page.goto("/app/stock-entry")
	page.get_by_role("button", name="Nhập từ Excel").click()
	dialog = modal(page, "Nhập kho từ Excel")
	expect(dialog.get_by_role("button", name="Ghi sổ nhập kho")).to_be_disabled()
	expect(dialog.get_by_role("button", name="Kiểm tra file")).to_be_disabled()
	return dialog


def choose_file(page, dialog, path):
	"""Chọn file .xlsx qua FileUploader (riêng tư) và chờ hộp thoại nhập Excel hiện tên file."""
	dialog.get_by_role("button", name="Chọn file Excel").click()
	uploader = page.locator(".modal.show .file-uploader").last
	expect(uploader).to_be_visible(timeout=10000)
	uploader.locator("input[type=file]").first.set_input_files(path)
	with page.expect_response(lambda response: "upload_file" in response.url) as upload:
		page.locator(".modal.show .modal-footer .btn-primary", has_text="Tải lên").last.click()
	assert upload.value.ok, upload.value.text()
	expect(dialog.locator(".tc-inv-mono").first).to_contain_text(path.rsplit("/", 1)[-1], timeout=15000)


def check_file(dialog):
	dialog.get_by_role("button", name="Kiểm tra file").click()


def good_rows(inv, document_no, lot, expiry):
	return [
		(inv["ci"], lot, expiry, 5, 1000, inv["supplier"], document_no, inv["warehouse"]),
	]


# --- Item: trường theo nhóm vật tư (SCR-24, FR-M6-02) -----------------------------------------------------


def test_item_form_shows_fields_by_group(inv_page):
	# FR-M6-02, A-07 V1-V5: chọn nhóm thì hiện đúng trường phụ thuộc; nhóm bắt buộc hạn tự tích và khóa cờ lô/hạn
	page = inv_page
	page.goto("/app/item/new")
	group = page.locator("[data-fieldname='tc_item_group_cssd'] select")
	expect(group).to_be_visible(timeout=30000)
	method = page.locator("div.frappe-control[data-fieldname='tc_compatible_method']:visible")
	ci_class = page.locator("div.frappe-control[data-fieldname='tc_ci_class']:visible")
	batch = page.locator("input[data-fieldname='has_batch_no']")
	expiry = page.locator("input[data-fieldname='has_expiry_date']")

	group.select_option("Label")
	expect(method).to_have_count(1)
	expect(ci_class).to_have_count(0)

	group.select_option("Chemical Indicator")
	expect(ci_class).to_have_count(1)
	expect(method).to_have_count(0)
	# cờ lô và hạn dùng được tích sẵn (giá trị của form) và khóa: người dùng không bỏ tích được
	page.wait_for_function("() => cur_frm.doc.has_batch_no === 1 && cur_frm.doc.has_expiry_date === 1")
	expect(batch).to_be_disabled()
	expect(expiry).to_be_disabled()
	assert page.evaluate("cur_frm.doc.valuation_method") == "Moving Average"
	page.get_by_role("tab", name="Hàng tồn kho").click()
	# tồn tối thiểu theo kho
	reorder = page.locator("div.frappe-control[data-fieldname='reorder_levels']:visible")
	expect(reorder).to_have_count(1)
	page.get_by_role("tab", name="Thu mua").click()
	# nhà cung cấp
	suppliers = page.locator("div.frappe-control[data-fieldname='supplier_items']:visible")
	expect(suppliers).to_have_count(1)

	# nhóm không bắt buộc hạn: cờ lô vẫn tích, cờ hạn dùng mở khóa; loại chỉ thị và phương pháp nhãn biến mất
	page.get_by_role("tab", name="Chi tiết").click()
	group.select_option("Packaging")
	expect(ci_class).to_have_count(0)
	expect(method).to_have_count(0)
	expect(expiry).to_be_enabled()
	assert page.evaluate("cur_frm.doc.has_batch_no") == 1
	expect(batch).to_be_disabled()
	assert page.evaluate("cur_frm.doc.tc_ci_class || ''") == ""  # không còn mang loại chỉ thị sang nhóm khác
	assert page.evaluate("cur_frm.is_new()")  # form mới chưa bao giờ được lưu


# --- Phiếu nhập: hạn dùng (FR-M6-01.1, FR-M6-01.3, BRU-INV-001 phía nhập) ---------------------------------


def test_receipt_form_blocks_missing_expiry_and_expired_lot(inv_page, inv_demo):
	page = inv_page
	lot, document_no = unique("E2E-LOT"), unique("E2E-PNK")
	new_receipt(page)

	# hạn thiếu: vật tư chỉ thị hóa học bắt buộc hạn → chặn, nêu dòng và vật tư; không lưu gì
	fill_receipt(page, inv_demo, document_no, [line(inv_demo["ci"], lot, None)])
	response = save_and_wait(page)
	assert not response.ok
	blocked = modal(page, "Không nhập kho được các vật tư này")
	expect(blocked).to_contain_text("Dòng 1")
	expect(blocked).to_contain_text(inv_demo["ci"])
	expect(blocked).to_contain_text("bắt buộc có hạn dùng")
	close_modals(page)
	assert stock_entries(page, document_no) == []

	# hạn hôm qua: lô đã hết hạn → chặn, nêu ngày hết hạn
	page.evaluate(
		"(expiry) => { const row = cur_frm.doc.items[0]; return frappe.model.set_value(row.doctype, row.name, 'tc_expiry_date', expiry); }",
		iso(-1),
	)
	assert not save_and_wait(page).ok
	expired = modal(page, "Không nhập kho được các vật tư này")
	expect(expired).to_contain_text(f"đã hết hạn ngày {vn(-1)}")
	close_modals(page)
	assert stock_entries(page, document_no) == []

	# hạn ngày mai: lưu được, ghi sổ được, tồn của lô tăng đúng số lượng
	page.evaluate(
		"(expiry) => { const row = cur_frm.doc.items[0]; return frappe.model.set_value(row.doctype, row.name, 'tc_expiry_date', expiry); }",
		iso(1),
	)
	assert save_and_wait(page).ok
	expect(indicator(page)).to_have_text("Nháp", timeout=15000)
	submit_and_wait(page)
	expect(indicator(page)).to_have_text("Đã ghi sổ", timeout=15000)
	[entry] = stock_entries(page, document_no)
	assert entry["docstatus"] == 1
	batch = api_get(page, f"/api/resource/Batch/{lot}")["data"]
	assert (batch["item"], batch["expiry_date"]) == (inv_demo["ci"], iso(1))
	assert batch_qty(page, inv_demo["ci"], lot) == 5


# --- Nhập từ Excel (FR-M6-01.2, FR-M9-11, BRU-INV-001) ------------------------------------------------------


def test_excel_dialog_reports_row_errors_then_posts_clean_file(inv_page, inv_demo, tmp_path):
	page = inv_page
	lot, document_no = unique("E2E-XLS"), unique("E2E-PXL")
	# dòng Excel 3: vật tư chỉ thị hóa học thiếu hạn dùng
	no_expiry = (
		inv_demo["ci"],
		unique("E2E-NOEXP"),
		None,
		2,
		1000,
		inv_demo["supplier"],
		document_no,
		inv_demo["warehouse"],
	)
	rows = [*good_rows(inv_demo, document_no, lot, iso(30)), no_expiry]
	bad = workbook(tmp_path / f"{unique('loi')}.xlsx", rows)
	dialog = open_excel_dialog(page)
	choose_file(page, dialog, bad)
	check_file(dialog)
	error = dialog.locator(".tc-inv-alert-error")
	expect(error).to_be_visible(timeout=15000)
	rows_table = error.locator(".tc-inv-table tbody tr")
	expect(rows_table).to_have_count(1)
	expect(rows_table.first.locator("td").nth(0)).to_have_text(
		"3"
	)  # số dòng nhìn thấy trong Excel (tiêu đề = dòng 1)
	expect(rows_table.first.locator("td").nth(1)).to_have_text("Hạn dùng")
	expect(rows_table.first.locator("td").nth(2)).to_contain_text("bắt buộc có hạn dùng")
	expect(dialog.get_by_role("button", name="Ghi sổ nhập kho")).to_be_disabled()
	assert stock_entries(page, document_no) == []  # tất cả hoặc không gì: dòng đúng cũng chưa được ghi

	# sửa file: chỉ còn dòng đúng → kiểm sạch, nút Ghi sổ bật, ghi sổ và phiếu hiện trong hộp thoại
	good = workbook(tmp_path / f"{unique('dung')}.xlsx", good_rows(inv_demo, document_no, lot, iso(30)))
	choose_file(page, dialog, good)
	expect(dialog.get_by_role("button", name="Ghi sổ nhập kho")).to_be_disabled()  # đổi file → phải kiểm lại
	check_file(dialog)
	expect(dialog.locator(".tc-inv-alert-ok")).to_contain_text("File hợp lệ", timeout=15000)
	post = dialog.get_by_role("button", name="Ghi sổ nhập kho")
	expect(post).to_be_enabled()
	post.click()
	saved = dialog.locator(".tc-inv-alert-ok", has_text="Đã ghi sổ phiếu nhập")
	expect(saved).to_be_visible(timeout=30000)
	link = saved.locator("a")
	expect(link).to_have_count(1)
	[entry] = stock_entries(page, document_no)
	assert entry["docstatus"] == 1
	expect(link).to_have_text(entry["name"])
	assert batch_qty(page, inv_demo["ci"], lot) == 5


def test_excel_dialog_double_click_posts_once(inv_page, inv_demo, tmp_path):
	# Review Focus 3: nhấp đúp "Ghi sổ" chỉ ghi một lần (một khóa X-Idempotency-Key cho một lần ghi)
	page = inv_page
	lot, document_no = unique("E2E-DBL"), unique("E2E-PDB")
	good = workbook(tmp_path / f"{unique('dbl')}.xlsx", good_rows(inv_demo, document_no, lot, iso(30)))
	imports = []
	page.on(
		"request",
		lambda request: imports.append(request) if "inventory.receipt_import" in request.url else None,
	)
	dialog = open_excel_dialog(page)
	choose_file(page, dialog, good)
	check_file(dialog)
	expect(dialog.locator(".tc-inv-alert-ok")).to_contain_text("File hợp lệ", timeout=15000)
	dialog.get_by_role("button", name="Ghi sổ nhập kho").dblclick()
	expect(dialog.locator(".tc-inv-alert-ok", has_text="Đã ghi sổ phiếu nhập")).to_be_visible(timeout=30000)
	assert len(imports) == 1, [request.url for request in imports]
	assert len(stock_entries(page, document_no)) == 1
	assert batch_qty(page, inv_demo["ci"], lot) == 5  # không nhân đôi tồn


# --- Trạng thái bằng chữ (F-14, design.md) -------------------------------------------------------------------


def test_status_text_visible_not_color_only(inv_page, inv_demo):
	page = inv_page
	lot, document_no = unique("E2E-STA"), unique("E2E-PST")
	new_receipt(page)
	# hạn dùng quá hạn trên lưới: ký hiệu "!" và chữ "Hết hạn" đi kèm màu cam (chưa lưu, nên không bị server chặn)
	fill_receipt(page, inv_demo, document_no, [line(inv_demo["ci"], lot, iso(-1))])
	cell = page.locator(
		"[data-fieldname='items'] .grid-body .grid-row .grid-static-col[data-fieldname='tc_expiry_date']"
	).first
	expect(cell).to_contain_text("Hết hạn")
	expect(cell).to_contain_text("!")

	page.evaluate(
		"(expiry) => { const row = cur_frm.doc.items[0]; return frappe.model.set_value(row.doctype, row.name, 'tc_expiry_date', expiry); }",
		iso(10),
	)
	assert save_and_wait(page).ok
	expect(indicator(page)).to_have_text("Nháp", timeout=15000)
	submit_and_wait(page)
	expect(indicator(page)).to_have_text("Đã ghi sổ", timeout=15000)
	# hủy sổ (R09 được phép, V11): trạng thái "Đã hủy" cũng bằng chữ
	page.evaluate("cur_frm.savecancel()")
	with page.expect_response(lambda response: "frappe.desk.form.save.cancel" in response.url) as cancelled:
		page.locator(".modal.show .btn-primary").last.click()
	assert cancelled.value.ok, cancelled.value.text()
	expect(indicator(page)).to_have_text("Đã hủy", timeout=15000)
	assert batch_qty(page, inv_demo["ci"], lot) == 0
