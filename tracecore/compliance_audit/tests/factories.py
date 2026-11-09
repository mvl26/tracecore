"""Dữ liệu test của engine phiếu giám sát M12 (FEAT-060)."""

import frappe
from frappe.utils import today

from tracecore.tests import factories

R01, R02, R08, R11, R12, R13 = "TC R01", "TC R02", "TC R08", "TC R11", "TC R12", "TC R13"

PPE_ITEMS = (
	# item_code, section, question, weight, is_critical
	("PNC-01", "Hand hygiene", "Hand hygiene before gloving", 2, 1),
	("PNC-02", "PPE", "PPE matches exposure risk", 2, 1),
	("PNC-03", "PPE", "PPE removed in the right order", 1, 0),
	("PNC-04", "Sharps", "No two-handed needle recapping", 2, 1),
	("PNC-05", "Sharps", "Sharps box below 3/4", 1, 0),
)


def template_values(code="T-PNC", scoring="Weighted Score", items=PPE_ITEMS, **values):
	return {
		"doctype": "Audit Template",
		"template_code": code,
		"title": "Standard precautions - PPE",
		"audit_type": "Standard Precautions - PPE",
		"scoring_method": scoring,
		"effective_from": today(),
		"min_sample": 0,
		"legal_ref": "QD 3671/QD-BYT",
		"items": [
			{
				"item_code": item_code,
				"section": section,
				"question": question,
				"answer_type": "Pass/Fail",
				"weight": weight,
				"is_critical": critical,
			}
			for item_code, section, question, weight, critical in items
		],
		**values,
	}


def make_template(code="T-PNC", submit=True, **values):
	"""Mẫu Nháp (hoặc đã duyệt) tạo bằng Administrator."""
	doc = frappe.get_doc(template_values(code, **values)).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_dept_user(email, role, department):
	"""Người dùng có role và User Permission Department (R08/R12 của khoa)."""
	user = factories.make_user(email, [role])
	if not frappe.db.exists("User Permission", {"user": user, "allow": "Department", "for_value": department}):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user


def make_observer(user=None, department=None, first_name="Audit Observer"):
	"""Employee gắn User (người giám sát)."""
	return factories.make_employee(department=department, first_name=first_name, user_id=user).name


def answers(**by_code):
	"""{item_code: answer} → danh sách dòng trả lời gửi lên RPC/doc."""
	return [{"item_code": code, "answer": answer} for code, answer in by_code.items()]
