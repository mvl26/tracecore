"""Zone Station: khu và trạm quét (FR-M9-03, FEAT-002).

Khu mã ``ZONE-.##`` (loại khu bắt buộc); trạm mã ``TR-.###`` ghi Code Registry, thuộc đúng một khu, có số trạm
``station_no`` (hiển thị T{n}) và các chức năng giới hạn theo cấu hình loại khu (``core.zones``, A-64). Trạm chưa gán khu
luôn không hoạt động.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint

from tracecore.core import audit, code_registry, zones

STATION_PREFIX = "TR"
DEFAULT_BAUD_RATE = 9600
# (tối thiểu, tối đa, chỉ số) của ngưỡng môi trường khu (FEAT-008)
ENV_LIMITS = (
	("temp_min", "temp_max", "Temperature"),
	("humidity_min", "humidity_max", "Humidity"),
	("pressure_min", "pressure_max", "Pressure Difference"),
)


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
		self.station_no = 0
		self.set("functions", [])
		if not self.zone_type:
			frappe.throw(_("Zone Type is required for a zone."))
		self._validate_env_limits()
		before = self.get_doc_before_save()
		if before and before.zone_type != self.zone_type:
			self._check_active_stations_fit_new_type()
		if before and cint(before.is_active) and not cint(self.is_active):
			self._check_zone_can_be_turned_off()

	def _check_zone_can_be_turned_off(self):
		"""Tắt vùng (A-64): không còn trạm, máy hay vị trí kệ đang hoạt động dùng vùng này."""
		blockers = frappe.get_all(
			"Zone Station", filters={"parent_zone": self.name, "is_zone": 0, "is_active": 1}, pluck="name"
		)
		blockers += frappe.get_all(
			"Equipment",
			filters={"status": ["!=", "Retired"]},
			or_filters={"zone_in": self.name, "zone_out": self.name},
			pluck="name",
		)
		for doctype in ("Sterile Location", "Waste Storage Location"):
			blockers += frappe.get_all(
				doctype, filters={"zone_station": self.name, "is_active": 1}, pluck="name"
			)
		if blockers:
			frappe.throw(
				_("Cannot turn off zone {0}: still used by {1}.").format(
					self.zone_station_name, ", ".join(sorted(blockers))
				),
				frappe.ValidationError,
			)

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
		allowed = zones.allowed_functions(self.zone_type)
		stations = frappe.get_all(
			"Zone Station", filters={"parent_zone": self.name, "is_zone": 0, "is_active": 1}, pluck="name"
		)
		for station in stations:
			for function in zones.station_functions(station):
				if function not in allowed:
					frappe.throw(
						_(
							"Cannot change the zone type: active station {0} has function {1}, which zone type {2} does not allow."
						).format(
							station, zones.function_label(function), _(self.zone_type, context="Zone Station")
						)
					)

	def _validate_env_limits(self):
		"""Ngưỡng môi trường của khu (FEAT-008, A-55 Q2): ô trống = không kiểm; có cả hai thì tối thiểu ≤ tối đa.

		Ngưỡng là ô Data (Float của Frappe không để trống được), lưu số đã chuẩn hóa dấu chấm thập phân.
		"""
		from tracecore.admin_reports.environment import to_number

		for low, high, label in ENV_LIMITS:
			bounds = []
			for fieldname in (low, high):
				value = to_number(self.get(fieldname), _(label))
				self.set(fieldname, None if value is None else f"{value:g}")
				bounds.append(value)
			if None not in bounds and bounds[0] > bounds[1]:
				frappe.throw(_("{0}: the minimum is greater than the maximum.").format(_(label)))

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
		# bỏ thông số của kiểu kết nối khác, để không lưu host/cổng cũ sau khi đổi kết nối
		if row.connection != "TCP":
			row.host, row.port = None, 0
		if row.connection != "Serial":
			row.serial_port, row.baud_rate = None, 0
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
		self.env_monitored = 0  # chỉ khu có nhật ký môi trường
		self.station_no = cint(self.station_no)
		self._validate_station_no()
		functions = self._function_codes()
		if len(set(functions)) != len(functions):
			frappe.throw(_("A station cannot list the same function twice."))
		if not self.parent_zone:
			self._validate_station_without_zone()
			return

		parent = frappe.db.get_value(
			"Zone Station", self.parent_zone, ["is_zone", "zone_type", "is_active"], as_dict=True
		)
		if not parent or not parent.is_zone:
			frappe.throw(_("A station must belong to a zone."))
		if not cint(parent.is_active) and cint(self.is_active):
			frappe.throw(_("Zone {0} is turned off, so this station cannot be active.").format(self.parent_zone))
		self.zone_type = parent.zone_type
		zones.check_functions(parent.zone_type, functions)
		self._warn_number_against_process_order(functions)

	def _function_codes(self):
		return [row.station_function for row in self.get("functions") or []]

	def _validate_station_no(self):
		"""Số trạm: không trùng giữa các trạm đang hoạt động; 0 = không đánh số (đồ vải, chất thải, khoa)."""
		number = cint(self.station_no)
		if not number or not cint(self.is_active):
			return
		other = frappe.db.get_value(
			"Zone Station",
			{"is_zone": 0, "is_active": 1, "station_no": number, "name": ["!=", self.name or ""]},
			"name",
		)
		if other:
			frappe.throw(_("Station No {0} is already used by active station {1}.").format(number, other))

	def _warn_number_against_process_order(self, functions):
		"""Số trạm chỉ để hiển thị và sắp xếp: trái thứ tự quy trình thì cảnh báo, không chặn (A-64)."""
		number = cint(self.station_no)
		if not number or not functions or not cint(self.is_active):
			return
		order = min(_process_order(functions))
		for row in frappe.get_all(
			"Zone Station",
			filters={"is_zone": 0, "is_active": 1, "station_no": [">", 0], "name": ["!=", self.name or ""]},
			fields=["name", "station_no"],
		):
			other = _process_order(zones.station_functions(row.name))
			if other and (cint(row.station_no) < number) != (min(other) < order) and min(other) != order:
				frappe.msgprint(
					_("Station No {0} is out of order with the process: compare station {1} (No {2}).").format(
						number, row.name, row.station_no
					),
					indicator="orange",
				)
				return

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


def _process_order(functions):
	return frappe.get_all(
		"Station Function", filters={"name": ["in", list(functions)]}, pluck="process_order"
	)
