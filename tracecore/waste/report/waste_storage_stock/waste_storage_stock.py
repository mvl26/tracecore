"""Tồn kho chất thải cho R02 trên Desk (FEAT-048, UC-35 A3, SCR-39 view WEB, A-61): túi gấp nhất trước."""

from frappe import _

from tracecore.waste import storage


def _remaining(minutes):
	sign = "-" if minutes < 0 else ""
	hours, rest = divmod(abs(minutes), 60)
	return f"{sign}{hours} h {rest} min"


def _columns():
	return [
		{
			"fieldname": "container",
			"label": _("Container Code"),
			"fieldtype": "Link",
			"options": "Waste Container",
			"width": 170,
		},
		{
			"fieldname": "waste_type",
			"label": _("Waste Type"),
			"fieldtype": "Link",
			"options": "Waste Type",
			"width": 180,
		},
		{
			"fieldname": "location",
			"label": _("Storage Location"),
			"fieldtype": "Link",
			"options": "Waste Storage Location",
			"width": 120,
		},
		{
			"fieldname": "location_name",
			"label": _("Storage Location Name"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "weight_kg",
			"label": _("Weight (kg)"),
			"fieldtype": "Float",
			"precision": 3,
			"width": 100,
		},
		{"fieldname": "storage_due", "label": _("Storage Due"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "remaining", "label": _("Time Left"), "fieldtype": "Data", "width": 110},
		{"fieldname": "state", "label": _("Storage State"), "fieldtype": "Data", "width": 110},
	]


def execute(filters=None):
	rows = [
		{
			"container": row["name"],
			"waste_type": row["waste_type"],
			"location": row["location"],
			"location_name": row["location_name"],
			"weight_kg": row["weight_kg"],
			"storage_due": row["storage_due"],
			"remaining": _remaining(row["remaining_minutes"]),
			"state": row["state"],
		}
		for row in storage.stock()["containers"]
	]
	return _columns(), rows
