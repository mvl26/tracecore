"""Danh mục loại đồ vải: khối lượng chuẩn, định mức theo khoa (FEAT-033, FR-M3-02, .1, .3; architecture §5.3 DT-LINENTYPE)."""

import frappe
from frappe import _


def before_naming(doc):
	"""Bỏ khoảng trắng đầu/cuối để "Áo mổ" và " Áo mổ " là cùng một tên (FR-M3-02.3)."""
	doc.type_name = (doc.type_name or "").strip()


def validate(doc):
	if (doc.std_weight_kg or 0) <= 0:
		frappe.throw(_("The standard weight must be greater than 0."))
	seen = set()
	for row in doc.quotas:
		if (row.min_qty or 0) < 0 or (row.max_qty or 0) < 0:
			frappe.throw(_("Row {0}: quotas cannot be negative.").format(row.idx))
		if (row.min_qty or 0) > (row.max_qty or 0):
			frappe.throw(_("Row {0}: the minimum cannot exceed the maximum.").format(row.idx))
		if row.department in seen:
			frappe.throw(_("Row {0}: department {1} already has a quota.").format(row.idx, row.department))
		seen.add(row.department)
