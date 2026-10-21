import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, time_diff_in_hours


class StationCompetency(Document):
	def validate(self):
		self._validate_period()
		self._validate_station()
		self._validate_temporary_access()

	def _validate_period(self):
		if get_datetime(self.valid_until) <= get_datetime(self.valid_from):
			frappe.throw(_("Valid until must be after valid from."))

	def _validate_station(self):
		is_zone = frappe.db.get_value("Zone Station", self.station, "is_zone")
		if is_zone is None or is_zone:
			frappe.throw(_("Competency must be assigned to a station, not a zone."))

	def _validate_temporary_access(self):
		if not self.is_temporary:
			return
		if not self.temporary_reason or not self.approved_by:
			frappe.throw(_("Temporary competency requires a reason and approver."))
		if time_diff_in_hours(self.valid_until, self.valid_from) > 24:
			frappe.throw(_("Temporary competency cannot exceed 24 hours."))

	def on_trash(self):
		frappe.throw(_("Station Competency {0} cannot be deleted.").format(self.name))
