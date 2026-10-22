"""Điền dữ liệu phiên bản cho dòng Set BOM Item có từ trước FEAT-015 (S1, S2); chạy lại không đổi gì thêm.

- ``effective_from`` trống → ngày tạo sớm nhất của phiên bản (mọi dòng của một phiên bản cùng một ngày).
- ``change_reason`` trống → "Initial version" (v1) / "Recorded before BOM versioning" (phiên bản sau).
- ``based_on_version`` = phiên bản - 1 cho phiên bản > 1 còn 0.
- ``current_bom_version`` của loại bộ = ``bom_versions.effective_version`` hôm nay nếu khác.
- Nhóm dòng trùng dụng cụ / trùng thứ tự xếp trong một phiên bản cũ chỉ được **báo** (in ra), không sửa: phiên bản bất
  biến; trùng dụng cụ còn chặn tạo chỉ mục unique (``set_bom_item.on_doctype_update`` tạo ở lần migrate sau khi xử lý).

Ghi thẳng DB (không qua validate: phiên bản đã lưu không sửa được qua Document). Mỗi phiên bản / loại bộ đổi có một
Audit Log Update.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.core import audit
from tracecore.instrument import bom_versions
from tracecore.instrument.doctype.set_bom_item.set_bom_item import duplicate_lines

SET_TYPE = "Instrument Set Type"


def _reason():
	return _("BOM version data filled in by the FEAT-015 data patch")


def execute():
	_backfill_versions()
	_sync_current_versions()
	_report_duplicates()


def _backfill_versions():
	rows = frappe.db.sql(
		"""
		select set_type, bom_version, min(creation) as created,
			sum(effective_from is null) as no_date,
			sum(ifnull(change_reason, '') = '') as no_reason,
			sum(bom_version > 1 and ifnull(based_on_version, 0) = 0) as no_base
		from `tabSet BOM Item`
		group by set_type, bom_version
		having no_date > 0 or no_reason > 0 or no_base > 0
		order by set_type, bom_version
		""",
		as_dict=True,
	)
	for row in rows:
		version = cint(row.bom_version)
		changes = {}
		if cint(row.no_date):
			changes["effective_from"] = str(getdate(row.created))
			frappe.db.sql(
				"update `tabSet BOM Item` set effective_from = %s "
				"where set_type = %s and bom_version = %s and effective_from is null",
				(changes["effective_from"], row.set_type, version),
			)
		if cint(row.no_reason):
			changes["change_reason"] = (
				_("Initial version") if version <= 1 else _("Recorded before BOM versioning")
			)
			frappe.db.sql(
				"update `tabSet BOM Item` set change_reason = %s "
				"where set_type = %s and bom_version = %s and ifnull(change_reason, '') = ''",
				(changes["change_reason"], row.set_type, version),
			)
		if cint(row.no_base):
			changes["based_on_version"] = version - 1
			frappe.db.sql(
				"update `tabSet BOM Item` set based_on_version = %s "
				"where set_type = %s and bom_version = %s and ifnull(based_on_version, 0) = 0",
				(version - 1, row.set_type, version),
			)
		audit.log("Update", SET_TYPE, row.set_type, new={"bom_version": version, **changes}, reason=_reason())


def _sync_current_versions():
	for name, current in frappe.db.sql(
		"select name, current_bom_version from `tabInstrument Set Type` order by name"
	):
		effective = bom_versions.effective_version(name)
		if effective and effective != cint(current):
			frappe.db.set_value(SET_TYPE, name, "current_bom_version", effective, update_modified=False)
			audit.log(
				"Update",
				SET_TYPE,
				name,
				old={"current_bom_version": cint(current)},
				new={"current_bom_version": effective},
				reason=_reason(),
			)
			print(f"Set type {name}: current BOM version {cint(current)} -> {effective}")


def _report_duplicates():
	for row in duplicate_lines():
		print(
			f"Set type {row.set_type} BOM version {row.bom_version}: instrument {row.instrument} "
			f"is listed {row.line_count} times (left unchanged; unique index not created)"
		)
	for row in frappe.db.sql(
		"""
		select set_type, bom_version, position, count(*) as line_count
		from `tabSet BOM Item`
		group by set_type, bom_version, position
		having count(*) > 1
		order by set_type, bom_version, position
		""",
		as_dict=True,
	):
		print(
			f"Set type {row.set_type} BOM version {row.bom_version}: position {row.position} "
			f"is used by {row.line_count} lines (left unchanged)"
		)
