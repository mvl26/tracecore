"""Điền mặc định phần đầu cho Instrument Set Type có từ trước FEAT-015 (S13); chạy lại không đổi gì thêm.

``assembly_minutes`` trống → 0 (= chưa nhập), ``is_implant`` trống → 0. Ghi thẳng DB (không qua validate) vì dòng cũ
có thể chưa có khoa/loại gói; **không** tự điền khoa, loại gói mặc định hay cờ cấy ghép thật (dữ liệu lâm sàng): lưu
lại bản ghi cũ trên Desk sẽ yêu cầu R02/R10 điền. Cột Int/Check mới thường đã nhận mặc định 0 khi migrate, nên patch
chỉ là lưới an toàn cho dòng còn NULL. Mỗi dòng đổi có một Audit Log Update.
"""

import frappe
from frappe import _

from tracecore.core import audit

DOCTYPE = "Instrument Set Type"
FIELDS = ("assembly_minutes", "is_implant")


def execute():
	rows = frappe.db.sql(
		"""
		select name, assembly_minutes, is_implant
		from `tabInstrument Set Type`
		where assembly_minutes is null or is_implant is null
		order by name
		""",
		as_dict=True,
	)
	for row in rows:
		values = {field: 0 for field in FIELDS if row.get(field) is None}
		frappe.db.set_value(DOCTYPE, row.name, values, update_modified=False)
		audit.log(
			"Update",
			DOCTYPE,
			row.name,
			old={field: None for field in values},
			new=values,
			reason=_("Set type header defaults filled in by the data patch"),
		)
