"""IC Structure Gaps — "Cơ cấu KSNK còn thiếu" (FEAT-057; FR-M11-01.3, FR-M11-02.2, FR-M11-03; BRU-ICP-001..003).

Mỗi dòng là một mục thiếu: thành phần cơ cấu bắt buộc, khối đại diện Hội đồng, hoặc một khoa thiếu bác sĩ / ĐD-HS-KTV
trong mạng lưới. ``issue`` là chữ đã dịch (luôn có "Thiếu"), ``issue_code`` là mã cố định. Cơ cấu đủ → không có dòng.
"""

from frappe import _

from tracecore.infection_program import structure

COMPONENT_CODES = {
	"committee": "COMMITTEE",
	"ic_department": "IC_DEPARTMENT",
	"network": "NETWORK_UNMARKED",
	"surveillance": "SURVEILLANCE",
}
DEPARTMENT_CODES = {"doctor": "NETWORK_DOCTOR", "nurse": "NETWORK_NURSE"}


def _columns():
	return [
		{"fieldname": "item", "label": _("Component or Department"), "fieldtype": "Data", "width": 240},
		{
			"fieldname": "department",
			"label": _("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"width": 160,
		},
		{"fieldname": "requirement", "label": _("Requirement"), "fieldtype": "Data", "width": 300},
		{
			"fieldname": "current",
			"label": _("Current", context="IC Structure"),
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"fieldname": "issue",
			"label": _("Issue", context="IC Structure"),
			"fieldtype": "Data",
			"width": 260,
		},
		{"fieldname": "issue_code", "label": _("Issue Code"), "fieldtype": "Data", "hidden": 1},
	]


def _rows(result):
	data = []
	for component in result["components"]:
		# mạng lưới thiếu theo khoa liệt kê từng khoa bên dưới; dòng tổng chỉ khi chưa đánh dấu khoa nào
		if component["key"] == "network" and result["departments"]:
			continue
		if component["status"] == "missing":
			data.append(
				{
					"item": component["label"],
					"requirement": component["requirement"],
					"current": component["current"],
					"issue": component["status_label"],
					"issue_code": COMPONENT_CODES[component["key"]],
				}
			)
	committee = result["committee"]
	if committee and result["scale"] == "large":
		for group in committee["missing_representatives"]:
			data.append(
				{
					"item": _("IC Committee"),
					"requirement": _("Representative: {0}").format(_(group)),
					"current": committee["name"],
					"issue": _("Missing representative: {0}").format(_(group)),
					"issue_code": "COMMITTEE_REPRESENTATIVE",
				}
			)
	for row in result["departments"]:
		for group in row["missing"]:
			data.append(
				{
					"item": row["department_name"],
					"department": row["department"],
					"requirement": _("≥ 1 doctor + ≥ 1 nurse/midwife/technician"),
					"current": _("{0} doctors, {1} nurses/midwives/technicians").format(
						row["doctors"], row["nurses"]
					),
					"issue": _("Missing doctor")
					if group == "doctor"
					else _("Missing nurse/midwife/technician"),
					"issue_code": DEPARTMENT_CODES[group],
				}
			)
	return data


def execute(filters=None):
	return _columns(), _rows(structure.compute())
