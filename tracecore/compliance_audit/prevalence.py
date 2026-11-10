"""Phiếu điều tra cắt ngang (tỷ lệ hiện mắc) trên engine M12 (FEAT-072; FR-M13-14, FR-M13-14.1; UC-50; A-149 Q1).

- Mẫu cắt ngang = mẫu có mục mã ``PREV-HAI`` (Có/Không NKBV, kiểu Lựa chọn), thường kèm ``PREV-ABX`` (Có/Không dùng
  kháng sinh). Nội dung mẫu là của bệnh viện (seed Nháp ``CAT-NGANG``), code chỉ dựa vào mã mục.
- Mỗi người bệnh khảo sát = 1 `Audit Session`. Mã BN ở bộ ba ``patient_code`` (Password) / che / hash của phiếu
  (`core.patient_code`, ADR-010 mở rộng), hoặc chép từ `Device Episode` cùng khoa đang đặt vào ngày điều tra (đọc qua
  ``frappe.db`` theo Link, không import M13). Không có trường họ tên (BRU-HAI-005).
- Cùng người bệnh (hash) cùng mã mẫu cùng ngày chỉ một phiếu; phiếu không phải cắt ngang không được có mã BN.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from tracecore.core import patient_code
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Audit Session"
TEMPLATE_DOCTYPE = "Audit Template"
ITEM_DOCTYPE = "Audit Template Item"
EPISODE_DOCTYPE = "Device Episode"
HAI_ITEM, ABX_ITEM = "PREV-HAI", "PREV-ABX"
YES, NO = "Yes", "No"
CHOICES = (YES, NO)


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def is_prevalence_template(template) -> bool:
	return bool(
		template
		and frappe.db.exists(
			ITEM_DOCTYPE, {"parent": template, "parenttype": TEMPLATE_DOCTYPE, "item_code": HAI_ITEM}
		)
	)


def template_codes() -> list[str]:
	"""Mã mẫu (mọi phiên bản) có mục ``PREV-HAI``."""
	parents = frappe.get_all(
		ITEM_DOCTYPE, filters={"parenttype": TEMPLATE_DOCTYPE, "item_code": HAI_ITEM}, pluck="parent"
	)
	if not parents:
		return []
	return sorted(
		set(frappe.get_all(TEMPLATE_DOCTYPE, filters={"name": ["in", parents]}, pluck="template_code"))
	)


def is_prevalence(doc) -> bool:
	"""Phiếu cắt ngang: bản chụp mục của phiếu có ``PREV-HAI``."""
	return any(row.item_code == HAI_ITEM for row in doc.get("answers") or ())


def answer(doc, item_code):
	row = next((row for row in doc.get("answers") or () if row.item_code == item_code), None)
	return (row.value or "").strip() if row else ""


def _has_patient(doc) -> bool:
	return bool(doc.get("patient_code") or doc.get("patient_code_hash"))


def reject_patient(doc):
	"""Phiếu thường không mang mã người bệnh (NFR-PRIV-01)."""
	if _has_patient(doc):
		raise blocked(
			"PREVALENCE_PATIENT_NOT_ALLOWED",
			_("Patient code not allowed"),
			_("Only a point prevalence survey records a patient code."),
			_("Remove the patient code from this audit."),
			items=["patient_code"],
		)


def _episode_invalid(reason):
	return blocked(
		"PREVALENCE_EPISODE_INVALID",
		_("Device episode not valid for this survey"),
		reason,
		_(
			"Choose an episode of this patient that is open in this department on the survey day, or enter the patient code."
		),
		items=["device_episode"],
	)


def _from_episode(doc):
	row = frappe.db.get_value(
		EPISODE_DOCTYPE,
		doc.device_episode,
		["department", "inserted_on", "removed_on", "patient_code_hash", "patient_code_masked"],
		as_dict=True,
	)
	if not row:
		raise _episode_invalid(_("Device episode {0} does not exist.").format(doc.device_episode))
	day = getdate(doc.audit_date)
	if row.department != doc.department:
		raise _episode_invalid(
			_("Device episode {0} belongs to another department.").format(doc.device_episode)
		)
	if getdate(row.inserted_on) > day or (row.removed_on and getdate(row.removed_on) < day):
		raise _episode_invalid(
			_("Device episode {0} is not open on {1}.").format(doc.device_episode, frappe.format(day, "Date"))
		)
	if doc.patient_code_hash and row.patient_code_hash != doc.patient_code_hash:
		raise _episode_invalid(
			_("The patient code does not match device episode {0}.").format(doc.device_episode)
		)
	doc.patient_code_hash = row.patient_code_hash
	doc.patient_code_masked = row.patient_code_masked


def _check_choices(doc, required=False):
	bad = []
	for item_code in (HAI_ITEM, ABX_ITEM):
		value = answer(doc, item_code)
		if (value and value not in CHOICES) or (required and item_code == HAI_ITEM and not value):
			bad.append(item_code)
	present = {row.item_code for row in doc.answers or ()}
	bad = [code for code in bad if code in present]
	if bad:
		raise blocked(
			"PREVALENCE_ANSWER_MISSING",
			_("Survey answer missing"),
			_("Items {0} need Yes or No.").format(", ".join(bad)),
			_("Answer Yes or No for whether the patient has a healthcare-associated infection, then post."),
			items=bad,
		)


def _check_duplicate(doc):
	filters = {
		"template_code": doc.template_code
		or frappe.db.get_value(TEMPLATE_DOCTYPE, doc.audit_template, "template_code"),
		"audit_date": getdate(doc.audit_date),
		"patient_code_hash": doc.patient_code_hash,
		"docstatus": ["<", 2],
	}
	if not doc.is_new():
		filters["name"] = ["!=", doc.name]
	other = frappe.db.get_value(DOCTYPE, filters, "name")
	if other:
		raise blocked(
			"PREVALENCE_DUPLICATE",
			_("Patient already surveyed"),
			_("Patient {0} is already recorded on {1} in survey form {2}.").format(
				doc.patient_code_masked or "***", frappe.format(doc.audit_date, "Date"), other
			),
			_("Open form {0} instead of recording the patient again.").format(other),
			object_type=DOCTYPE,
			object_name=other,
		)


def validate(doc):
	"""Gọi từ ``sessions.validate`` cho phiếu cắt ngang (sau khi đã chụp mục của mẫu)."""
	patient_code.apply(doc)
	if doc.device_episode:
		_from_episode(doc)
	if not doc.patient_code_hash:
		raise blocked(
			"PREVALENCE_PATIENT_REQUIRED",
			_("Patient required"),
			_("A point prevalence survey form records one patient by code."),
			_(
				"Enter the patient code or choose the patient's open device episode. Do not enter the patient's name."
			),
			items=["patient_code"],
		)
	_check_duplicate(doc)
	_check_choices(doc)


def before_submit(doc):
	_check_choices(doc, required=True)
