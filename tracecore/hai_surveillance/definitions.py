"""Định nghĩa ca NKBV có phiên bản `HAI Case Definition` (FEAT-063; FR-M13-01, 01.1, 06.1; BRU-HAI-001; D10,
NFR-MAINT-04; A-144 a).

Ghi sổ = R01 duyệt và khóa phiên bản ``DN-<mã>-V<n>`` (`core.versioning`). Sửa = nhân bản phiên bản đang dùng (Desk
"Duplicate") thành Nháp V(n+1); mỗi mã chỉ một bản Nháp. Ca dùng phiên bản đã duyệt mới nhất có ``effective_from`` ≤
ngày khởi phát (`effective_for`). Tiêu chí và ngưỡng thời gian là dữ liệu của định nghĩa, không nằm trong code.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.core import versioning

DOCTYPE = "HAI Case Definition"
PREFIX = "DN"
AFTER_APPROVAL = frozenset({"superseded_by", "modified", "modified_by", "_comments", "_assign", "_liked_by"})
THRESHOLDS = ("min_hours_after_admission", "min_device_days_before_onset")


def normalize_code(raw):
	try:
		return versioning.normalize_code(raw)
	except ValueError:
		frappe.throw(
			_("Definition code {0} is invalid. Use Latin letters without accents, digits and dashes.").format(
				frappe.bold(raw or "")
			)
		)


def _versions(code):
	return frappe.get_all(
		DOCTYPE,
		filters={"def_code": code},
		fields=["name", "version_no", "docstatus"],
		order_by="version_no desc",
	)


def next_version(code):
	versions = _versions(code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		frappe.throw(
			_("Definition {0} already has a draft version {1}. Open and edit that draft instead.").format(
				code, draft.name
			)
		)
	return (versions[0].version_no if versions else 0) + 1


def autoname(doc):
	doc.def_code = normalize_code(doc.def_code)
	doc.version_no = next_version(doc.def_code)
	doc.name = versioning.make_versioned_code(PREFIX, doc.def_code, doc.version_no)


def validate(doc):
	if doc.amended_from:
		frappe.throw(
			_(
				"A definition version cannot be amended. Duplicate the approved version to create the next version."
			)
		)
	if not doc.is_new() and doc.def_code != frappe.db.get_value(DOCTYPE, doc.name, "def_code"):
		frappe.throw(_("The definition code cannot be changed after the version is created."))
	rows = [row for row in doc.criteria or [] if (row.criterion or "").strip()]
	if not rows:
		frappe.throw(_("Add at least one criterion to the case definition."))
	for field in THRESHOLDS:
		if doc.get(field) not in (None, "") and cint(doc.get(field)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(doc.meta.get_label(field))))
	doc.device_type = doc.device_type or None


def guard_locked(doc):
	"""Phiên bản đã duyệt bất biến: chỉ ``superseded_by`` đổi được sau ghi sổ."""
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [
		field.fieldname
		for field in doc.meta.fields
		if field.fieldtype not in ("Table", "Section Break", "Column Break")
		and field.fieldname not in AFTER_APPROVAL
		and doc.get(field.fieldname) != before.get(field.fieldname)
	]
	if [r.criterion for r in doc.criteria] != [r.criterion for r in before.criteria]:
		changed.append("criteria")
	if changed:
		frappe.throw(
			_(
				"Version {0} is approved and locked. Duplicate it to create version V{1}; cases already recorded keep their version."
			).format(doc.name, cint(doc.version_no) + 1),
			title=_("Approved definition is locked"),
		)


def on_approve(doc):
	for row in _versions(doc.def_code):
		if row.docstatus == 1 and row.version_no < doc.version_no:
			if not frappe.db.get_value(DOCTYPE, row.name, "superseded_by"):
				frappe.db.set_value(DOCTYPE, row.name, "superseded_by", doc.name, update_modified=False)


def on_trash(doc):
	if cint(doc.docstatus) == 1:
		frappe.throw(_("An approved case definition is never deleted."))


def effective_for(code, onset):
	"""Tên phiên bản đã duyệt mới nhất của ``code`` có hiệu lực tại ngày khởi phát; None khi chưa có (BRU-HAI-001)."""
	if not code or not onset:
		return None
	rows = frappe.get_all(
		DOCTYPE,
		filters={"def_code": code, "docstatus": 1, "effective_from": ["<=", getdate(onset)]},
		fields=["name"],
		order_by="version_no desc",
		limit=1,
	)
	return rows[0].name if rows else None


def approved_codes():
	"""Mã định nghĩa có ít nhất một phiên bản đã duyệt (phiên bản mới nhất) — cho ô chọn trên form ca."""
	chosen = {}
	for row in frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1},
		fields=["name", "def_code", "title", "infection_site", "device_type", "version_no"],
		order_by="version_no desc",
	):
		chosen.setdefault(row.def_code, row)
	return [dict(row) for _code, row in sorted(chosen.items())]
