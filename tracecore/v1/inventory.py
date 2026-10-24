"""RPC tracecore.v1.inventory.*: nhập kho vật tư hàng loạt từ file Excel mẫu (FEAT-041 Task 4, FR-M6-01.2).

``receipt_template`` (tải mẫu) và ``receipt_check`` (kiểm, không ghi) không ``@idempotent``; chỉ ``receipt_import``
ghi sổ nên có ``X-Idempotency-Key``. Quyền R09/R06/System Manager kiểm trước mọi thao tác. File Excel phải là file
**riêng tư** do chính người gọi tải lên (Desk ``FileUploader``), đuôi ``.xlsx``, không nhận đường dẫn tuỳ ý.
"""

import os

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.inventory import receipt_import as importer
from tracecore.inventory.receipt_import import ImportFileError
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

RECEIPT_ROLES = ("TC R09", "TC R06", "System Manager")
TEMPLATE_FILE_NAME = "receipt-template.xlsx"


def _arguments(file_url, warehouse):
	if not isinstance(file_url, str) or not file_url.strip():
		raise BadRequestError(_("file_url must be the URL of an uploaded Excel file."))
	if warehouse is not None and not isinstance(warehouse, str):
		raise BadRequestError(_("warehouse must be text."))
	return file_url.strip(), (warehouse or "").strip() or None


def _read_upload(file_url: str) -> bytes:
	"""Nội dung file riêng tư ``.xlsx`` của người gọi; mọi trường hợp khác là ``ImportFileError`` (không lộ lý do)."""
	invalid = ImportFileError(
		_("The file was not found among your private uploads. Upload the Excel file again.")
	)
	names = frappe.get_all(
		"File",
		filters={
			"file_url": file_url,
			"is_private": 1,
			"is_folder": 0,
			"owner": frappe.session.user,
		},
		pluck="name",
		limit=1,
	)
	if not names:
		raise invalid
	doc = frappe.get_doc("File", names[0])
	if not (doc.file_name or "").lower().endswith(".xlsx"):
		raise ImportFileError(
			_("Only Excel .xlsx files are accepted. Save the workbook as .xlsx and upload it again.")
		)
	prefix = "/private/files/"
	parts = (doc.file_url or "").split("/")
	if not doc.file_url.startswith(prefix) or ".." in parts or "" in parts[1:]:
		raise invalid
	try:
		path = frappe.get_site_path(*parts[1:])  # đọc thẳng từ thư mục private của site, không qua get_url()
		if os.path.getsize(path) > importer.MAX_BYTES:
			raise ImportFileError(
				_("The file is larger than {0} MB. Split it into smaller files.").format(
					importer.MAX_BYTES // (1024 * 1024)
				)
			)
		with open(path, "rb") as handle:
			return handle.read()
	except OSError:
		raise invalid from None


def _run(file_url, warehouse, dry_run, timestamp=None):
	require_any_role(*RECEIPT_ROLES)
	frappe.has_permission("Stock Entry", "create", throw=True)
	file_url, warehouse = _arguments(file_url, warehouse)
	try:
		return importer.import_receipts(_read_upload(file_url), warehouse, dry_run=dry_run)
	except ImportFileError as error:
		block = importer.file_block(error.reason)
	except BlockedError as error:
		block = error.block
	return reject_block(block, "Stock Entry", None, client_ts=timestamp)


@frappe.whitelist(methods=["GET"])
def receipt_template():
	"""Tải file Excel mẫu (``Receipt`` + ``Guide``); chỉ đọc, trả file nhị phân qua ``frappe.response``."""
	require_any_role(*RECEIPT_ROLES)
	frappe.response["type"] = "binary"
	frappe.response["filename"] = TEMPLATE_FILE_NAME
	frappe.response["filecontent"] = importer.build_template()


@frappe.whitelist(methods=["POST"])
def receipt_check(file_url=None, warehouse=None):
	"""Kiểm file (không ghi): ``{"ok": true, "rows", "documents", "warnings"}`` hoặc từ chối ``IMPORT_ROWS_INVALID`` /
	``IMPORT_FILE_INVALID`` (422), ``COMPANY_NOT_CONFIGURED`` (409); ``error.items`` = mọi dòng lỗi theo số dòng Excel.
	"""
	return _run(file_url, warehouse, dry_run=True)


@frappe.whitelist(methods=["POST"])
@idempotent
def receipt_import(file_url=None, warehouse=None, client_ts=None):
	"""Kiểm rồi ghi sổ toàn bộ file (tất cả hoặc không gì): ``{"ok": true, "rows", "stock_entries", "warnings"}``.

	Cùng ``X-Idempotency-Key`` gửi lại trả đúng kết quả đã lưu (không nhân đôi tồn); khóa mới là lần nhập thứ hai.
	Từ chối như ``receipt_check``.
	"""
	timestamp = parse_client_ts(client_ts)
	return _run(file_url, warehouse, dry_run=False, timestamp=timestamp)
