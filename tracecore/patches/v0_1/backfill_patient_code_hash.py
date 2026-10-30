"""FEAT-028: điền `Usage Record.patient_code_hash` cho bản ghi tạo trước khi có trường (tra cứu theo mã BN, FR-M2-19).

Giải mã từng mã trong `__Auth` chỉ để băm; không ghi mã rõ ra đâu. Chạy lại an toàn: bản ghi đã có hash bỏ qua.
"""

import frappe
from frappe.utils.password import get_decrypted_password

from tracecore.core import crypto


def execute():
	if not frappe.db.has_column("Usage Record", "patient_code_hash"):
		frappe.reload_doc("reprocessing", "doctype", "usage_record")
	names = frappe.get_all(
		"Usage Record",
		filters={"patient_code_hash": ["is", "not set"]},
		pluck="name",
		order_by="creation asc",
	)
	for name in names:
		code = get_decrypted_password("Usage Record", name, "patient_code", raise_exception=False)
		if code:
			frappe.db.set_value(
				"Usage Record", name, "patient_code_hash", crypto.patient_hash(code), update_modified=False
			)
