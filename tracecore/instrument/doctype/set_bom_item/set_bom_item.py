"""Set BOM Item: một dòng BOM của loại bộ theo phiên bản (DT-SETBOM); đọc qua `tracecore.instrument.bom`.

FEAT-015 (S1, S4, S12): một phiên bản = các dòng cùng (`set_type`, `bom_version`). Dòng chỉ tạo qua
`tracecore.instrument.bom_versions` (cờ ``flags.tc_bom``); phiên bản đã lưu **bất biến**: không sửa (kể cả System
Manager, kể cả có cờ), không xóa (audit hook ``block_delete``). Luật dòng (tương thích, trùng, số lượng, giới hạn) ở
``bom_versions``; ở đây chỉ còn chốt chặn cuối của chính bản ghi.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import audit

UNIQUE_FIELDS = ("set_type", "bom_version", "instrument")
UNIQUE_CONSTRAINT = "unique_set_type_bom_version_instrument"


class SetBOMItem(Document):
	def validate(self):
		if self.is_new():
			if not self.flags.tc_bom:
				frappe.throw(_("BOM lines can only be created through Edit BOM."))
		elif self._changed():
			frappe.throw(_("A saved BOM version cannot be changed. Create a new BOM version."))
		if cint(self.qty) < 1:
			frappe.throw(_("Quantity must be at least 1."))
		self._reject_retired_instrument()

	def _changed(self) -> bool:
		# so trường dữ liệu như Audit Log (bỏ trường meta chuẩn); lưu lại y nguyên không phải là sửa
		before = self.get_doc_before_save()
		return before is not None and bool(audit.changes(before, self))

	def _reject_retired_instrument(self):
		# FR-M1-01, A-06 I13, FR-M1-03.6: dòng mới không nhận dụng cụ đã Ngừng sử dụng; dòng cũ giữ nguyên
		if not self.instrument or not self.is_new():
			return
		if frappe.db.get_value("Instrument", self.instrument, "status") == "Retired":
			frappe.throw(_("Instrument {0} is retired and cannot be added to a BOM.").format(self.instrument))


def duplicate_lines() -> list[dict]:
	"""Nhóm dòng trùng (`set_type`, `bom_version`, `instrument`) có từ trước FEAT-015 (chặn tạo chỉ mục unique)."""
	return frappe.db.sql(
		"""
		select set_type, bom_version, instrument, count(*) as line_count
		from `tabSet BOM Item`
		group by set_type, bom_version, instrument
		having count(*) > 1
		order by set_type, bom_version, instrument
		""",
		as_dict=True,
	)


def on_doctype_update():
	# bom.lines tra theo (loại bộ, phiên bản)
	frappe.db.add_index("Set BOM Item", ["set_type", "bom_version"])
	# chốt cuối chống lẫn dòng hai phiên bản cùng số (S4); dữ liệu cũ còn trùng thì chưa tạo được: patch
	# set_bom_item_version_meta báo các nhóm trùng, lần migrate sau khi đã xử lý sẽ tạo
	if not duplicate_lines():
		frappe.db.add_unique("Set BOM Item", list(UNIQUE_FIELDS), constraint_name=UNIQUE_CONSTRAINT)
