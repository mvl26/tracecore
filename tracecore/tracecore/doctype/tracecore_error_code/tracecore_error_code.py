"""Một mã trong danh mục mã lỗi (FEAT-052, A-71, FR-M9-17)."""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import error_codes

CODE_FORMAT = re.compile(r"^(HC|TB|NS|CT|DC|QT)-\d{3}$")
LOGIN = "LOGIN"


class TraceCoreErrorCode(Document):
	def validate(self):
		if not CODE_FORMAT.match(self.code or ""):
			frappe.throw(
				_(
					"Error code {0} must look like HC-001: a group (HC, TB, NS, CT, DC, QT) and 3 digits."
				).format(self.code)
			)
		self.error_group = self.code[:2]
		for row in self.stations:
			if row.station_key != LOGIN and not frappe.db.exists("Station Function", row.station_key):
				frappe.throw(_("Station {0} does not exist.").format(row.station_key))

	def before_save(self):
		"""Mã khóa là kiểm soát an toàn: R10 sửa được nội dung, không sửa được mức độ, cờ khóa và mã nội bộ."""
		before = None if self.is_new() else self.get_doc_before_save()
		if not before or not before.severity_locked or self.flags.get("tc_error_seed"):
			return
		for field in ("default_severity", "severity_locked", "block_codes"):
			if self.get(field) != before.get(field):
				frappe.throw(
					_("Error code {0} is a safety control: it cannot be turned off or changed.").format(
						self.code
					)
				)

	def on_update(self):
		error_codes.clear_cache()
