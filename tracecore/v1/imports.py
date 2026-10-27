"""RPC tracecore.v1.imports.* — màn SCR-43 import danh mục ban đầu (FEAT-011, FR-M9-11, UC-39; A-41).

Chạy bằng phiên Desk của R10/R02 (System Manager). ``kinds``, ``template``, ``check``, ``batch`` chỉ đọc; ``run`` ghi
sổ nên ``@idempotent`` (bấm Ghi sổ hai lần cùng khóa → một Import Batch). File là File riêng tư người gọi vừa tải lên;
lỗi file trả ``{"ok": false, "error": IMPORT_FILE_INVALID}`` kèm mã HTTP 422.
"""

import frappe
from frappe import _

from tracecore.core import audit, importer
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

IMPORT_ROLES = ("TC R10", "TC R02", "System Manager")
BATCH_FIELDS = (
	"name",
	"kind",
	"status",
	"total",
	"created",
	"skipped",
	"failed",
	"started_at",
	"finished_at",
	"error",
)
ROW_FIELDS = ("row_no", "code", "result", "field", "error_code", "ref_doctype", "ref_name", "message")


def _kind(key):
	require_any_role(*IMPORT_ROLES)
	kind = importer.kinds().get(key or "")
	if not kind:
		raise BadRequestError(_("Unknown import type {0}.").format(key))
	require_any_role(*kind.roles)
	# import không lách quyền: cần quyền tạo bản ghi như khi nhập tay trên Desk (ma trận quyền)
	if not importer.can_import(kind):
		raise frappe.PermissionError(_("You are not allowed to create {0}.").format(_(kind.doctype)))
	return kind


@frappe.whitelist(methods=["GET", "POST"])
def kinds():
	"""Các loại danh mục import được: ``[{key, label, columns, required}]``."""
	require_any_role(*IMPORT_ROLES)
	roles = set(frappe.get_roles())
	return [
		{
			"key": kind.key,
			"label": _(kind.label),
			"columns": len(kind.columns),
			"required": [_(column.label) for column in kind.columns if column.required],
		}
		for kind in importer.kinds().values()
		if roles & set(kind.roles) and importer.can_import(kind)
	]


@frappe.whitelist(methods=["GET"])
def template(kind=None):
	"""Tải file Excel mẫu của loại danh mục ``kind`` (``Data`` + ``Guide``)."""
	_kind(kind)
	frappe.response["type"] = "binary"
	frappe.response["filename"] = f"tracecore-{kind}-template.xlsx"
	frappe.response["filecontent"] = importer.build_template(kind)


@frappe.whitelist(methods=["POST"])
def check(kind=None, file_url=None):
	"""Kiểm file, không ghi gì: ``{"ok": true, total, valid, existing, issues, previous_batch}``."""
	_kind(kind)
	try:
		return {"ok": True, **importer.check(kind, importer.read_upload(file_url))}
	except importer.ImportFileError as error:
		return reject_block(importer.file_block(error.reason), "Import Batch", None)


@frappe.whitelist(methods=["POST"])
@idempotent
def run(kind=None, file_url=None, client_ts=None):
	"""Ghi sổ các dòng hợp lệ (> 200 dòng chạy nền): ``{"ok": true, "batch", "status"}``; ghi Audit lô import."""
	_kind(kind)
	timestamp = parse_client_ts(client_ts)
	try:
		name = importer.run(kind, importer.read_upload(file_url), file_url)
	except importer.ImportFileError as error:
		return reject_block(importer.file_block(error.reason), "Import Batch", None, client_ts=timestamp)
	status, total = frappe.db.get_value("Import Batch", name, ["status", "total"])
	audit.log(
		"Create",
		"Import Batch",
		name,
		new={"kind": kind, "file": file_url, "rows": total},
		reason="catalog import",
		client_ts=timestamp,
	)
	return {"ok": True, "batch": name, "status": status}


@frappe.whitelist(methods=["GET", "POST"])
def batch(name=None):
	"""Trạng thái và kết quả từng dòng của một Import Batch (màn SCR-43 hỏi lại khi chạy nền)."""
	require_any_role(*IMPORT_ROLES)
	if not name or not frappe.db.exists("Import Batch", name):
		raise BadRequestError(_("Import batch {0} does not exist.").format(name))
	doc = frappe.get_doc("Import Batch", name)
	return {
		**{field: doc.get(field) for field in BATCH_FIELDS},
		"rows": [{field: row.get(field) for field in ROW_FIELDS} for row in doc.rows],
	}
