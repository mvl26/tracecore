"""Dữ liệu demo cho site dev/test (developer_mode hoặc allow_tests; không chạy trên production).

``bench --site <SITE> execute tracecore.setup.devdata.ensure_demo_set`` in Set ID GIAI thử để quét ở /app/station.
"""

import frappe
from frappe import _

DEMO_SET_TYPE = "DEMO"


def ensure_demo_set():
	"""Tạo (nếu chưa có) loại bộ DEMO và một Set Unit; trả và in Set ID."""
	if not (frappe.conf.get("developer_mode") or frappe.conf.get("allow_tests") or frappe.flags.in_test):
		frappe.throw(_("Demo data can only be created on a developer or test site."))
	if not frappe.db.exists("Instrument Set Type", DEMO_SET_TYPE):
		frappe.get_doc(
			{
				"doctype": "Instrument Set Type",
				"type_code": DEMO_SET_TYPE,
				"set_type_name": "Demo set",
				"method": "Steam",
			}
		).insert(ignore_permissions=True)
	set_id = frappe.db.get_value("Set Unit", {"set_type": DEMO_SET_TYPE}, "name", order_by="creation asc")
	if not set_id:
		set_id = (
			frappe.get_doc({"doctype": "Set Unit", "set_type": DEMO_SET_TYPE, "max_cycles": 300})
			.insert(ignore_permissions=True)
			.name
		)
	print(set_id)
	return set_id
