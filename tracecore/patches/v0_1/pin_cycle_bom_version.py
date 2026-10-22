"""Ghim phiên bản BOM cho bộ đang giữa chu trình khi lên FEAT-015 (S3, FR-M1-04.1); chạy lại không đổi gì thêm.

Set Unit ``current_cycle_no > 0`` và ``cycle_bom_version = 0`` → ``cycle_bom_version`` = ``current_bom_version`` của loại
bộ (phiên bản T4 đang dùng trước FEAT-015, đã đồng bộ với phiên bản hiệu lực bởi patch ``set_bom_item_version_meta``).
Bộ chưa có chu trình giữ 0 (chu trình đầu tiên sẽ ghim qua ``step_gate.start_cycle``). Ghi thẳng DB (không qua validate:
trường vòng đời chỉ step_gate ghi qua Document), mỗi bộ đổi có một Audit Log Update.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit

SET_UNIT = "Set Unit"


def execute():
	rows = frappe.db.sql(
		"""
		select su.name, st.current_bom_version
		from `tabSet Unit` su
		join `tabInstrument Set Type` st on st.name = su.set_type
		where ifnull(su.current_cycle_no, 0) > 0 and ifnull(su.cycle_bom_version, 0) = 0
			and ifnull(st.current_bom_version, 0) > 0
		order by su.name
		"""
	)
	for name, version in rows:
		version = cint(version)
		frappe.db.set_value(SET_UNIT, name, "cycle_bom_version", version, update_modified=False)
		audit.log(
			"Update",
			SET_UNIT,
			name,
			old={"cycle_bom_version": 0},
			new={"cycle_bom_version": version},
			reason=_("BOM version pinned for the running cycle by the FEAT-015 data patch"),
		)
	if rows:
		print(f"Pinned the BOM version of {len(rows)} set(s) in a running cycle")
