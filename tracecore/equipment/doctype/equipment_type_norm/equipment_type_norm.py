"""Equipment Type Norm: định mức mặc định theo loại máy (FR-M5-02.1, FEAT-038).

Một dòng cho mỗi loại máy (tên = loại máy). Chương trình bật ``use_default_norms`` lấy các số thiếu từ đây
(``tracecore.equipment.norms``). Không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from tracecore.core import audit

NORM_LABELS = (
	("duration_min", "Duration (min)"),
	("kwh_per_cycle", "Electricity per Cycle (kWh)"),
	("water_l_per_cycle", "Water per Cycle (L)"),
	("steam_kg_per_cycle", "Steam per Cycle (kg)"),
)


class EquipmentTypeNorm(Document):
	def validate(self):
		for fieldname, label in NORM_LABELS:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(label)))

	def on_trash(self):
		audit.block_delete(self, "on_trash")
