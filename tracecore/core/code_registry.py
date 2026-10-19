"""Cấp mã đối tượng và ghi sổ Code Registry (FR-M9-07, BRU-ID-001, BRU-ID-006)."""

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from tracecore.core import gs1

SET_SERIAL_DIGITS = 6


class CodeAlreadyIssuedError(frappe.ValidationError):
	pass


def company_prefix():
	return gs1.configured_company_prefix()


def is_issued(code):
	return bool(frappe.db.exists("Code Registry", code))


def register(code, prefix, ref_doctype=None, ref_name=None, station=None):
	"""Ghi một mã vào sổ; mã đã có (kể cả đã vô hiệu) → CodeAlreadyIssuedError."""
	if is_issued(code):
		raise CodeAlreadyIssuedError(_("Code {0} has already been issued.").format(code))
	doc = frappe.get_doc(
		{
			"doctype": "Code Registry",
			"code": code,
			"prefix": prefix,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"issued_at": station,
			"issued_on": now_datetime(),
			"status": "Active",
		}
	)
	# ref_name có thể là bản ghi đang được tạo trong cùng transaction (Set Unit)
	doc.flags.ignore_links = True
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		raise CodeAlreadyIssuedError(_("Code {0} has already been issued.").format(code))
	return doc.name


def next_set_id(type_code):
	"""Cấp Set ID GIAI mới = tiền tố GS1 + mã loại bộ + số thứ tự 6 chữ số, và ghi sổ."""
	prefix = company_prefix()
	series_key = f"{prefix}{type_code}"
	while True:
		serial = getseries(series_key, SET_SERIAL_DIGITS)
		code = gs1.make_giai(prefix, f"{type_code}{serial}")
		if not is_issued(code):
			register(code, series_key, "Set Unit", code)
			return code
