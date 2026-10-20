"""Zone Station: khu và trạm quét (FR-M9-03, FEAT-002).

Khu mã ``ZONE-.##`` (loại khu bắt buộc); trạm mã ``TR-.###`` ghi Code Registry, thuộc đúng một khu,
chức năng (bước T1-T8) giới hạn theo loại khu (``core.zones``). Trạm chưa gán khu luôn không hoạt động.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from tracecore.core import audit, code_registry, zones

STATION_PREFIX = "TR"


class ZoneStation(Document):
	def autoname(self):
		# Khu ZONE-## và trạm TR-### (§5.3.3); bỏ qua số đã dùng
		series = "ZONE-.##" if self.is_zone else "TR-.###"
		while True:
			name = make_autoname(series, doc=self)
			if not frappe.db.exists("Zone Station", name):
				self.name = name
				return

	def validate(self):
		if self.is_zone:
			self._validate_zone()
		else:
			self._validate_station()

	def after_insert(self):
		if not self.is_zone and not code_registry.is_issued(self.name):
			code_registry.register(self.name, STATION_PREFIX, "Zone Station", self.name)

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _validate_zone(self):
		self.parent_zone = None
		self.station_step = None
		if not self.zone_type:
			frappe.throw(_("Zone Type is required for a zone."))
		before = self.get_doc_before_save()
		if before and before.zone_type != self.zone_type:
			self._check_active_stations_fit_new_type()

	def _check_active_stations_fit_new_type(self):
		stations = frappe.get_all(
			"Zone Station",
			filters={"parent_zone": self.name, "is_zone": 0, "is_active": 1, "station_step": ("is", "set")},
			fields=["name", "station_step"],
		)
		for station in stations:
			if station.station_step not in zones.allowed_steps(self.zone_type):
				frappe.throw(
					_(
						"Cannot change the zone type: active station {0} has step {1}, which zone type {2} does not allow."
					).format(station.name, station.station_step, _(self.zone_type, context="Zone Station"))
				)

	def _validate_station(self):
		if not self.parent_zone:
			self._validate_station_without_zone()
			return

		parent = frappe.db.get_value("Zone Station", self.parent_zone, ["is_zone", "zone_type"], as_dict=True)
		if not parent or not parent.is_zone:
			frappe.throw(_("A station must belong to a zone."))
		self.zone_type = parent.zone_type
		zones.check_step(parent.zone_type, self.station_step)

	def _validate_station_without_zone(self):
		"""Trạm chưa gán khu: lưu được nhưng không hoạt động (FR-M9-03.3)."""
		before = self.get_doc_before_save()
		self.zone_type = None
		if not self.is_active:
			return
		if before and not before.is_active:
			frappe.throw(_("A station without a zone cannot be activated."))
		self.is_active = 0
		if before:
			frappe.msgprint(
				_("Station {0} has no zone: it was deactivated.").format(self.name),
				indicator="orange",
			)
