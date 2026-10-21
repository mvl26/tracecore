"""Printer: máy in nhãn của một trạm; cuộn nhãn đang lắp quyết định loại nhãn máy in được in (BRU-REP-011).

`label_type_loaded` có thể do System Manager khai báo ban đầu (FR-M2-08.2); `roll_code`, `roll_loaded_on`,
`roll_loaded_by` chỉ đổi qua `tracecore.core.print.set_roll` (cờ ``flags.tc_roll_change``).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, get_datetime

from tracecore.core import print as core_print

# read_only trên form không được Frappe kiểm ở server nên chặn tại đây; chỉ set_roll được đổi.
ROLL_FIELDS = ("roll_code", "roll_loaded_on", "roll_loaded_by")
MAX_PORT = 65535


def _same(fieldname, before, after):
	if fieldname == "roll_loaded_on" and before and after:
		return get_datetime(before) == get_datetime(after)
	return cstr(before) == cstr(after)


class Printer(Document):
	def validate(self):
		core_print.get_dialect(self.language)
		self._validate_station()
		self._validate_numbers()
		self._validate_label_type()
		if not self.flags.tc_roll_change:
			self._guard_roll_fields()

	def _validate_station(self):
		is_zone = frappe.db.get_value("Zone Station", self.station, "is_zone")
		if is_zone is None:
			frappe.throw(_("Station {0} does not exist.").format(self.station))
		if cint(is_zone):
			frappe.throw(_("{0} is a zone, not a station. Choose a station.").format(self.station))

	def _validate_numbers(self):
		if not 1 <= cint(self.port) <= MAX_PORT:
			frappe.throw(_("Port must be between 1 and 65535."))
		if cint(self.dpi) <= 0:
			frappe.throw(_("DPI must be greater than zero."))

	def _validate_label_type(self):
		if not self.label_type_loaded:
			return
		group, method = frappe.db.get_value(
			"Item", self.label_type_loaded, ["tc_item_group_cssd", "tc_compatible_method"]
		) or (None, None)
		if group != "Label" or not method:
			frappe.throw(
				_(
					"{0} is not a label item. Choose an Item of group Label that has a compatible method."
				).format(self.label_type_loaded)
			)

	def _guard_roll_fields(self):
		if self.is_new():
			for fieldname in ROLL_FIELDS:
				self.set(fieldname, None)
			return
		before = self.get_doc_before_save()
		changed = [f for f in ROLL_FIELDS if before and not _same(f, before.get(f), self.get(f))]
		if changed:
			frappe.throw(
				_("The roll is changed only by scanning the label roll at the station: {0}").format(
					", ".join(changed)
				)
			)
