"""Zone Station (khung FEAT-001): khu và trạm quét; trạm thuộc đúng một khu (FR-M9-03)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class ZoneStation(Document):
	def autoname(self):
		# Mã trạm TR-### (§5.3.3); bỏ qua số đã dùng bởi fixtures TR-001..TR-007
		while True:
			name = make_autoname("TR-.###", doc=self)
			if not frappe.db.exists("Zone Station", name):
				self.name = name
				return

	def validate(self):
		if self.is_zone:
			self.parent_zone = None
			self.station_step = None
			if not self.zone_type:
				frappe.throw(_("Zone Type is required for a zone."))
			return

		parent = self.parent_zone and frappe.db.get_value(
			"Zone Station", self.parent_zone, ["is_zone", "zone_type"], as_dict=True
		)
		if not parent or not parent.is_zone:
			frappe.throw(_("A station must belong to a zone."))
		self.zone_type = parent.zone_type
