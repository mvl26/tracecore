"""Waste Storage Location: vị trí kho lưu giữ tạm chất thải, mã `KE-####` (FEAT-048, FR-M10-03, FR-M9-07, A-61).

Cùng bộ đếm và sổ mã với `Sterile Location`, nên một mã `KE-` chỉ thuộc một kho. Vị trí ngừng dùng bằng `is_active = 0`.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from tracecore.core import audit, code_registry

LOCATION_PREFIX = "KE"


class WasteStorageLocation(Document):
	def autoname(self):
		while True:
			name = make_autoname("KE-.####", doc=self)
			if not frappe.db.exists("Waste Storage Location", name) and not code_registry.is_issued(name):
				self.name = name
				return

	def validate(self):
		self.location_name = (self.location_name or "").strip()
		if not self.location_name:
			frappe.throw(_("Location Name is required."), frappe.MandatoryError)
		if not self.allowed_types:
			frappe.throw(_("Choose at least one waste type for this location."), frappe.MandatoryError)
		self._check_zone()
		self._check_types()

	def _check_zone(self):
		if not self.zone_station:
			if self.is_cold:
				frappe.throw(_("A cold room needs a zone for its temperature log."), frappe.MandatoryError)
			return
		zone = frappe.db.get_value("Zone Station", self.zone_station, ["zone_type", "is_zone"], as_dict=True)
		if not zone or zone.zone_type != "Waste":
			frappe.throw(_("Zone Station {0} is not in a waste zone.").format(self.zone_station))
		if self.is_cold and not zone.is_zone:
			frappe.throw(_("A cold room must be linked to a zone, not to a station."))

	def _check_types(self):
		types = [row.waste_type for row in self.allowed_types]
		if len(types) != len(set(types)):
			frappe.throw(_("A waste type is listed twice."))
		for row in self.allowed_types:
			if not row.is_default:
				continue
			other = frappe.get_all(
				"Waste Storage Location Type",
				filters={
					"waste_type": row.waste_type,
					"is_default": 1,
					"parenttype": "Waste Storage Location",
					"parent": ["!=", self.name or ""],
				},
				pluck="parent",
				limit=1,
			)
			if other:
				frappe.throw(_("{0} already has the default location {1}.").format(row.waste_type, other[0]))

	def after_insert(self):
		code_registry.register(self.name, LOCATION_PREFIX, "Waste Storage Location", self.name)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
