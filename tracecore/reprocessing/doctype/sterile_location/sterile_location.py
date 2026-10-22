"""Sterile Location: vị trí kệ trong kho vô khuẩn, mã `KE-####` (FEAT-025, FR-M2-13, FR-M9-07).

Mã tự cấp theo naming series `KE-.####` (cùng bộ đếm với `code_registry.next_code("KE")`; số đã nằm trong sổ thì bỏ
qua) và ghi Code Registry (prefix KE). Kệ ngừng dùng bằng `is_active = 0`, không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from tracecore.core import audit, code_registry

LOCATION_PREFIX = "KE"


class SterileLocation(Document):
	def autoname(self):
		while True:
			name = make_autoname("KE-.####", doc=self)
			if not frappe.db.exists("Sterile Location", name) and not code_registry.is_issued(name):
				self.name = name
				return

	def validate(self):
		self.location_name = (self.location_name or "").strip()
		if not self.location_name:
			frappe.throw(_("Location Name is required."), frappe.MandatoryError)
		if self.zone_station:
			zone_type = frappe.db.get_value("Zone Station", self.zone_station, "zone_type")
			if zone_type != "Sterile":
				frappe.throw(_("Zone Station {0} is not in the sterile zone.").format(self.zone_station))

	def after_insert(self):
		code_registry.register(self.name, LOCATION_PREFIX, "Sterile Location", self.name)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
