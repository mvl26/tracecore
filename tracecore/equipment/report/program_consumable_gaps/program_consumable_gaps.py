"""Program Consumable Gaps: chương trình đang dùng còn thiếu vật tư (A-111 D7; FR-M5-02.8).

Mỗi dòng là một vấn đề của một chương trình: không có vật tư, chương trình test thiếu gói test bắt buộc, chương trình test
chưa gắn loại test đầu ngày, hoặc dòng vật tư chưa phân vai trò. ``issue_code`` là mã cố định, ``issue`` là chữ đã dịch.
"""

import frappe
from frappe import _
from frappe.utils import cint

NO_CONSUMABLES = "No consumables"
NO_TEST_PACK = "No required test pack"
NO_TEST_TYPE = "No daily test type"
NO_ROLE = "Consumable without role"
NO_CONSUMABLE_TYPES = ("Dryer",)  # máy sấy không cần dòng tiêu hao (A-104 D3)


def _columns():
	return [
		{
			"fieldname": "program",
			"label": _("Program"),
			"fieldtype": "Link",
			"options": "Process Program",
			"width": 150,
		},
		{"fieldname": "program_name", "label": _("Program Name"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "equipment",
			"label": _("Machine"),
			"fieldtype": "Link",
			"options": "Equipment",
			"width": 110,
		},
		{"fieldname": "equipment_name", "label": _("Equipment Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "program_kind", "label": _("Program Kind"), "fieldtype": "Data", "width": 90},
		{"fieldname": "issue", "label": _("Issue"), "fieldtype": "Data", "width": 300},
		{"fieldname": "issue_code", "label": _("Issue Code"), "fieldtype": "Data", "hidden": 1},
	]


def _programs(filters):
	conditions = {"is_active": 1}
	if filters.get("equipment"):
		conditions["equipment"] = filters["equipment"]
	return frappe.get_all(
		"Process Program",
		filters=conditions,
		fields=["name", "program_name", "equipment", "program_kind", "daily_test_type"],
		order_by="equipment asc, program_name asc",
	)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = []
	for program in _programs(filters):
		equipment = (
			frappe.db.get_value(
				"Equipment", program.equipment, ["equipment_name", "equipment_type"], as_dict=True
			)
			or frappe._dict()
		)
		if equipment.equipment_type in NO_CONSUMABLE_TYPES:
			continue
		rows = frappe.get_all(
			"Program Consumable",
			filters={"parent": program.name, "parenttype": "Process Program"},
			fields=["item", "role", "is_required"],
			order_by="idx asc",
		)
		issues = []
		if not rows:
			issues.append((NO_CONSUMABLES, _("The program has no consumables.")))
		if program.program_kind == "Test":
			if not any(row.role == "Test Pack" and cint(row.is_required) for row in rows):
				issues.append((NO_TEST_PACK, _("The test program has no required test pack.")))
			if not program.daily_test_type:
				issues.append((NO_TEST_TYPE, _("The test program is not linked to a daily test type.")))
		unclassified = [row.item for row in rows if not row.role]
		if unclassified:
			issues.append((NO_ROLE, _("Consumables without a role: {0}").format(", ".join(unclassified))))
		for code, text in issues:
			data.append(
				{
					"program": program.name,
					"program_name": program.program_name,
					"equipment": program.equipment,
					"equipment_name": equipment.equipment_name,
					"program_kind": _(program.program_kind or "Regular"),
					"issue": text,
					"issue_code": code,
				}
			)
	return _columns(), data
