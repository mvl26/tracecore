"""Zone Station: khu và trạm quét (FR-M9-03, FEAT-002).

Khu mã ``ZONE-.##`` (loại khu bắt buộc); trạm mã ``TR-.###`` ghi Code Registry, thuộc đúng một khu,
chức năng (bước T1-T8) giới hạn theo loại khu (``core.zones``). Trạm chưa gán khu luôn không hoạt động.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint

from tracecore.core import audit, code_registry, zones

STATION_PREFIX = "TR"
DEFAULT_BAUD_RATE = 9600


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
		self._validate_is_zone_unchanged()
		if self.is_zone:
			self._validate_zone()
		else:
			self._validate_station()
		self._validate_peripherals()

	def after_insert(self):
		if not self.is_zone and not code_registry.is_issued(self.name):
			code_registry.register(self.name, STATION_PREFIX, "Zone Station", self.name)

	def on_update(self):
		before = self.get_doc_before_save()
		if self.is_zone and before and before.zone_type != self.zone_type:
			self._propagate_zone_type()

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _validate_is_zone_unchanged(self):
		"""Khu không thành trạm và ngược lại (``is_zone`` set_only_once; chặn cả ở server, F3)."""
		if self.is_new():
			return
		stored = frappe.db.get_value("Zone Station", self.name, "is_zone")
		if stored is not None and cint(stored) != cint(self.is_zone):
			frappe.throw(_("{0}: Is Zone cannot be changed after the record is created.").format(self.name))

	def _validate_zone(self):
		self.parent_zone = None
		self.station_step = None
		if not self.zone_type:
			frappe.throw(_("Zone Type is required for a zone."))
		before = self.get_doc_before_save()
		if before and before.zone_type != self.zone_type:
			self._check_active_stations_fit_new_type()

	def _propagate_zone_type(self):
		"""Chép loại khu mới xuống mọi trạm con (hoạt động hay không); db.set_value bỏ qua doc_events nên ghi Audit Log tay."""
		for station in frappe.get_all(
			"Zone Station", filters={"parent_zone": self.name, "is_zone": 0}, pluck="name"
		):
			old = frappe.db.get_value("Zone Station", station, "zone_type")
			frappe.db.set_value("Zone Station", station, "zone_type", self.zone_type)
			audit.log(
				"Update", "Zone Station", station, old={"zone_type": old}, new={"zone_type": self.zone_type}
			)

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

	def _validate_peripherals(self):
		"""Thiết bị ngoại vi (E4): chỉ trạm có; TCP cần host:port, Serial cần cổng; không trùng điểm kết nối."""
		rows = self.get("peripherals") or []
		if self.is_zone:
			if rows:
				frappe.throw(_("A zone cannot have peripherals."))
			return
		endpoints = set()
		for row in rows:
			self._validate_peripheral_row(row)
			key = self._peripheral_endpoint(row)
			if not row.is_active or not key:
				continue
			if key in endpoints:
				frappe.throw(
					_(
						"Row {0}: endpoint {1} is already used by another active peripheral of this station."
					).format(row.idx, key[1])
				)
			endpoints.add(key)

	def _validate_peripheral_row(self, row):
		if row.peripheral_type == "Scale" and row.connection == "USB HID":
			frappe.throw(_("Row {0}: a scale cannot use USB HID.").format(row.idx))
		if row.connection == "TCP":
			row.host = (row.host or "").strip()
			if not row.host:
				frappe.throw(_("Row {0}: Host is required for a TCP connection.").format(row.idx))
			if not 1 <= (row.port or 0) <= 65535:
				frappe.throw(_("Row {0}: Port must be between 1 and 65535.").format(row.idx))
		elif row.connection == "Serial":
			row.serial_port = (row.serial_port or "").strip()
			if not row.serial_port:
				frappe.throw(_("Row {0}: Serial Port is required for a Serial connection.").format(row.idx))
			if not row.baud_rate:
				row.baud_rate = DEFAULT_BAUD_RATE

	@staticmethod
	def _peripheral_endpoint(row):
		if row.connection == "TCP":
			return ("TCP", f"{row.host.lower()}:{row.port}")
		if row.connection == "Serial":
			return ("Serial", row.serial_port.lower())
		return None

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
