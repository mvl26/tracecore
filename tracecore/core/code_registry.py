"""Cấp mã đối tượng và ghi sổ Code Registry (FR-M9-07, BRU-ID-001, BRU-ID-006)."""

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import now_datetime

from tracecore.core import gs1

SET_SERIAL_DIGITS = 6
ROLL_PREFIX = "CN"  # cuộn nhãn `CN-#####` do FEAT-005 cấp, ref_doctype = Item nhãn (D2)
CYCLE_PREFIX = "CY"  # Cycle ID `CY-YYMMDD-NNNN` của gói, ref_doctype = Pack (§5.3.3)
CYCLE_SERIAL_DIGITS = 4


class CodeAlreadyIssuedError(frappe.ValidationError):
	pass


def company_prefix():
	return gs1.configured_company_prefix()


def is_issued(code):
	return bool(frappe.db.exists("Code Registry", code))


def roll_label_item(roll_code):
	"""Item nhãn của cuộn `CN-#####`, hoặc None.

	Chỉ nhận dòng sổ có prefix ``CN``, ``ref_doctype = Item`` và còn Active; Item đó có phải nhãn hay không
	do nơi gọi kiểm (`core.print.set_roll`).
	"""
	if not roll_code:
		return None
	row = frappe.db.get_value(
		"Code Registry", roll_code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
	)
	if row and (row.prefix, row.ref_doctype, row.status) == (ROLL_PREFIX, "Item", "Active"):
		return row.ref_name or None
	return None


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


def disable(code, reason):
	"""Vô hiệu một mã đã cấp (vd Cycle ID của gói bị hủy); mã vẫn nằm trong sổ nên không bao giờ cấp lại."""
	if not is_issued(code):
		frappe.throw(_("Code {0} has not been issued.").format(code), frappe.DoesNotExistError)
	doc = frappe.get_doc("Code Registry", code, for_update=True)
	doc.update({"status": "Disabled", "disabled_reason": reason, "disabled_on": now_datetime()})
	doc.save(ignore_permissions=True)


def next_cycle_id(packed_at, station=None):
	"""Cấp Cycle ID `CY-YYMMDD-NNNN` và ghi sổ (prefix ``CY``, ref Pack = chính mã đó).

	Series đếm theo ngày của `packed_at` (giờ hệ thống, D13): khóa ``CY-YYMMDD-``; số đã có trong sổ thì bỏ qua.
	"""
	series_key = f"{CYCLE_PREFIX}-{packed_at:%y%m%d}-"
	while True:
		code = series_key + getseries(series_key, CYCLE_SERIAL_DIGITS)
		if not is_issued(code):
			register(code, CYCLE_PREFIX, "Pack", code, station)
			return code


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
