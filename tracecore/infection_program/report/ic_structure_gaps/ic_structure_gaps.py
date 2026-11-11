"""IC Structure Gaps — "Cơ cấu KSNK còn thiếu" (FEAT-057; FR-M11-01.3, FR-M11-02.2, FR-M11-03; BRU-ICP-001..003).

Mỗi dòng là một mục thiếu: thành phần cơ cấu bắt buộc, khối đại diện Hội đồng, hoặc một khoa thiếu bác sĩ / ĐD-HS-KTV
trong mạng lưới. ``issue`` là chữ đã dịch (luôn có "Thiếu"), ``issue_code`` là mã cố định. Cơ cấu đủ → không có dòng.
FEAT-094 (A-138; AC-094-14): thêm thành phần người theo bộ tiêu chí, mỗi người chưa đạt / chưa xác minh là một dòng có
``reason`` bằng chữ; khối / vai trò Hội đồng lấy từ ``committee.problems``.
"""

from frappe import _

from tracecore.infection_program import structure

COMPONENT_CODES = {
	"committee": "COMMITTEE",
	"ic_department": "IC_DEPARTMENT",
	"network": "NETWORK_UNMARKED",
	"surveillance": "SURVEILLANCE",
	"head": "HEAD",  # FEAT-094
	"head_nurse": "HEAD_NURSE",
	"person_in_charge": "PERSON_IN_CHARGE",
}
PERSON_CODES = {"fail": "PERSON_FAIL", "unverified": "PERSON_UNVERIFIED"}  # FEAT-094
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
		{
			"fieldname": "reason",
			"label": _("Reason", context="IC Structure"),
			"fieldtype": "Data",
			"width": 360,
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
					"reason": component["reasons"],
					"issue_code": COMPONENT_CODES[component["key"]],
				}
			)
		for person in component["people"]:
			if person["status"] not in PERSON_CODES:
				continue
			data.append(
				{
					"item": "{} — {}".format(
						component["label"], person["employee_name"] or person["employee"]
					),
					"requirement": component["requirement"],
					"current": person["employee"],
					"issue": person["status_label"],
					"reason": ", ".join(person["reasons"]),
					"issue_code": PERSON_CODES[person["status"]],
				}
			)
	committee = result["committee"]
	if committee and result.get("committee_required"):
		for problem in committee.get("problems") or []:
			data.append(
				{
					"item": _("IC Committee"),
					"requirement": _("Approved structure criteria"),
					"current": committee["name"],
					"issue": problem["text"],
					"reason": problem["text"],
					"issue_code": "COMMITTEE_" + problem["code"],
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
