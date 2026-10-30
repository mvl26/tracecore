"""Real Employee, competency and bearer-session fixtures for station RPC tests."""

import uuid

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import station_auth


def make_station_employee(user):
	name = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if name:
		return frappe.get_doc("Employee", name)
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "Station RPC",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": today(),
			"company": "_Test Company",
			"status": "Active",
			"user_id": user,
			"tc_card_id": "RPC-" + uuid.uuid4().hex,
			"tc_card_enabled": 1,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)


def make_station_session(user, station="TR-004"):
	employee = make_station_employee(user)
	frappe.get_doc(
		{
			"doctype": "Station Competency",
			"employee": employee.name,
			"station": station,
			"valid_from": add_to_date(now_datetime(), hours=-1),
			"valid_until": add_to_date(now_datetime(), hours=8),
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	return station_auth.login(employee.tc_card_id, station)
