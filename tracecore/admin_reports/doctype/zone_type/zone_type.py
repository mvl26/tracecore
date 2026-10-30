"""Zone Type: loại vùng và chức năng được phép (A-64, FEAT-051); ``core.zones`` đọc bảng này."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import audit


class ZoneType(Document):
	def validate(self):
		seen = set()
		for row in self.functions:
			if row.station_function in seen:
				frappe.throw(_("Row {0}: function {1} is listed twice.").format(row.idx, row.station_function))
			seen.add(row.station_function)
		if cint(self.flow_order):
			self._validate_flow_order_free()
		self._validate_active_stations_fit(seen)

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _validate_flow_order_free(self):
		other = frappe.db.get_value(
			"Zone Type", {"flow_order": cint(self.flow_order), "name": ["!=", self.name or ""]}, "name"
		)
		if other:
			frappe.throw(_("Flow Order {0} is already used by zone type {1}.").format(self.flow_order, other))

	def _validate_active_stations_fit(self, allowed):
		"""Không bỏ chức năng khi trạm đang hoạt động thuộc loại vùng này còn dùng nó."""
		if self.is_new():
			return
		stations = frappe.get_all(
			"Zone Station", filters={"is_zone": 0, "is_active": 1, "zone_type": self.name}, pluck="name"
		)
		if not stations:
			return
		rows = frappe.get_all(
			"Zone Station Function",
			filters={"parent": ["in", stations], "parenttype": "Zone Station"},
			fields=["parent", "station_function"],
		)
		used = sorted(f"{row.parent}: {row.station_function}" for row in rows if row.station_function not in allowed)
		if used:
			frappe.throw(
				_("Cannot remove functions still used by active stations: {0}.").format(", ".join(used)),
				frappe.ValidationError,
			)
