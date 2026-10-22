"""Điền dữ liệu phiên bản cho dòng Set BOM Item có từ trước FEAT-015 (S1, S2); chạy lại không đổi gì thêm.

- ``effective_from`` trống → ngày tạo sớm nhất của phiên bản (mọi dòng của một phiên bản cùng một ngày).
- ``change_reason`` trống → "Initial version" (v1) / "Recorded before BOM versioning" (phiên bản sau).
- ``based_on_version`` = phiên bản - 1 cho phiên bản > 1 còn 0.
- ``current_bom_version`` của loại bộ (phiên bản T4 dùng trước FEAT-015) **không bị đổi** (review cuối I-1): chỉ điền khi
  đang trống/0; khác ``bom_versions.effective_version`` hôm nay thì in chênh lệch để người vận hành xem lại. Bộ đang giữa
  chu trình đã được ghim phiên bản cũ bởi ``pin_cycle_bom_version`` (chạy trước patch này); scheduler 00:00
  (``roll_effective_versions``) sau đó đưa ``current_bom_version`` về phiên bản hiệu lực theo ngày ghi trên dòng, có
  Audit Log.
- Nhóm dòng trùng dụng cụ / trùng thứ tự xếp trong một phiên bản cũ chỉ được **báo** (in ra), không sửa: phiên bản bất
  biến; trùng dụng cụ còn chặn tạo chỉ mục unique (patch ``set_bom_item_unique_index`` tạo khi hết trùng; sau khi gộp
  dòng bằng tay thì chạy lại patch đó, xem docstring của nó).

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
	"""Không âm thầm đổi ``current_bom_version`` (review cuối I-1).

	Trống/0 (không phiên bản nào được dùng) → phiên bản hiệu lực, có Audit. Khác phiên bản hiệu lực → giữ nguyên, in
	chênh lệch: ngày hiệu lực của dòng cũ là ngày patch suy ra (ngày tạo), không đủ căn cứ để đổi phiên bản đang dùng.
	"""
	for name, current in frappe.db.sql(
		"select name, current_bom_version from `tabInstrument Set Type` order by name"
	):
		effective = bom_versions.effective_version(name)
		current = cint(current)
		if not effective or effective == current:
			continue
		if current > 0:
			print(
				f"Set type {name}: current BOM version {current} kept, but by the effective dates of its lines the "
				f"effective version is {effective}. Sets in a running cycle stay on their pinned version; review the "
				"BOM versions (the midnight scheduler applies the effective version)."
			)
			continue
		frappe.db.set_value(SET_TYPE, name, "current_bom_version", effective, update_modified=False)
		audit.log(
			"Update",
			SET_TYPE,
			name,
			old={"current_bom_version": current},
			new={"current_bom_version": effective},
			reason=_reason(),
		)
		print(f"Set type {name}: current BOM version {current} -> {effective}")


def _report_duplicates():
	for row in duplicate_lines():
		print(
			f"Set type {row.set_type} BOM version {row.bom_version}: instrument {row.instrument} "
			f"is listed {row.line_count} times (left unchanged; patch set_bom_item_unique_index creates the unique "
			"index once the lines are merged)"
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
