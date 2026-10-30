"""Archive Export: một lần xuất gói hồ sơ tiệt khuẩn lưu trữ (FEAT-012, FR-M9-12, OTH-RET-001, UC-39, A-58).

Người dùng (TC R01/R10) chỉ tạo phiếu với phạm vi; sau khi tạo không sửa tham số, không xóa. Kết quả (trạng thái,
file ZIP, SHA-256, manifest) chỉ dịch vụ `admin_reports.archive` ghi, bằng cờ ``flags.tc_archive``. Xuất mã bệnh nhân
đầy đủ chỉ cho TC R01 có lý do, ghi Audit Log `View Patient Code` (UC-39 E3).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from tracecore.core import audit

FULL_CODE_ROLE = "TC R01"
INCLUDES = ("inc_loads", "inc_indicators", "inc_machine_data", "inc_issues", "inc_usage", "inc_audit")
JOB = "tracecore.admin_reports.archive.build"


class ArchiveExport(Document):
	def validate(self):
		if not self.is_new():
			if not self.flags.tc_archive:
				frappe.throw(_("An archive export cannot be changed after it is created."))
			return
		self._validate_scope()
		if not any(self.get(field) for field in INCLUDES):
			frappe.throw(_("Choose at least one kind of record to export."))
		if self.full_patient_code:
			if FULL_CODE_ROLE not in frappe.get_roles():
				frappe.throw(_("Only the head of infection control (R01) can export full patient codes."))
			if not (self.patient_code_reason or "").strip():
				frappe.throw(_("Enter the reason for exporting full patient codes."))
		self.status = "Queued"
		self.requested_by = frappe.session.user
		for field in ("archive_file", "sha256", "file_size", "generated_at", "error", "manifest"):
			self.set(field, None)

	def _validate_scope(self):
		if self.scope_type == "Period":
			if not self.from_date or not self.to_date:
				frappe.throw(_("Choose the period (from date and to date)."))
			if getdate(self.from_date) > getdate(self.to_date):
				frappe.throw(_("The from date is after the to date."))
			self.sterilization_load = self.recall_order = None
		elif self.scope_type == "Load":
			if not self.sterilization_load:
				frappe.throw(_("Choose the sterilization load to export."))
			self.from_date = self.to_date = self.recall_order = None
		elif self.scope_type == "Recall Order":
			if not self.recall_order:
				frappe.throw(_("Choose the recall order to export."))
			self.from_date = self.to_date = self.sterilization_load = None
		else:
			frappe.throw(_("Unknown scope: {0}").format(self.scope_type))

	def after_insert(self):
		audit.log("Create", self.doctype, self.name, new={"scope_type": self.scope_type})
		if self.full_patient_code:
			audit.log("View Patient Code", self.doctype, self.name, reason=self.patient_code_reason.strip())
		frappe.enqueue(
			JOB, queue="long", timeout=1800, enqueue_after_commit=True, name=self.name, lang=frappe.local.lang
		)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
