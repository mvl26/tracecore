"""Set Unit: bộ dụng cụ vật lý; Set ID GIAI do hệ thống cấp, không sửa (FR-M1-05, BRU-ID-001).

Chỉ tạo qua ``tracecore.instrument.set_units.issue_batch`` (cờ ``flags.tc_set_issue``, FEAT-016 G4): Desk "Mới",
``frappe.client.insert``, Data Import hay insert trực tiếp đều bị chặn TRƯỚC khi cấp mã (``before_insert`` chạy trước
``autoname``), nên không đốt số series.

Trạng thái (`status`) và các trường vòng đời (`cycles_used`, `current_station`, `active_cycle_id`,
`current_cycle_no`, `cycle_bom_version` — phiên bản BOM ghim khi mở chu trình, FEAT-015 S3) chỉ được đổi bởi
`tracecore.core.step_gate` (ADR-005), kể cả lúc khởi tạo (``step_gate.init_unit``). ``cycles_source`` chỉ ghi khi cấp;
``tag_verified_on/by`` chỉ ghi qua quét kiểm tra thẻ (cờ ``flags.tc_tag_verify``).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import code_registry
from tracecore.core.step_gate import LIFECYCLE_DEFAULTS

ISSUE_FIELDS = ("cycles_source",)  # ghi một lần khi cấp (cờ flags.tc_set_issue)
TAG_FIELDS = ("tag_verified_on", "tag_verified_by")  # ghi qua quét kiểm tra thẻ (cờ flags.tc_tag_verify)

__all__ = ["LIFECYCLE_DEFAULTS", "SetUnit"]


def _changed(before, doc, fields):
	return [f for f in fields if before and str(before.get(f) or "") != str(doc.get(f) or "")]


class SetUnit(Document):
	def before_insert(self):
		self._require_issue_path()

	def before_naming(self):
		# Set ID luôn do hệ thống cấp (FR-M9-07): bỏ mọi tên nhập tay, kể cả khi import
		self.name = None

	def autoname(self):
		type_code = frappe.db.get_value("Instrument Set Type", self.set_type, "type_code")
		if not type_code:
			frappe.throw(_("Set Type {0} not found.").format(self.set_type))
		self.name = self.set_id = code_registry.next_set_id(type_code)

	def validate(self):
		if self.is_new():
			self._require_issue_path()
		if self.set_id != self.name:
			frappe.throw(_("Set ID is issued by the system and cannot be changed."))
		if cint(self.max_cycles) <= 0:
			frappe.throw(_("Max Cycles must be greater than zero."))
		if not self.flags.tc_step_gate:
			self._guard_lifecycle_fields()
		self._guard_service_fields()

	def _require_issue_path(self):
		if not self.flags.tc_set_issue:
			frappe.throw(_("Set Units are created only through Issue Set IDs."))

	def _guard_lifecycle_fields(self):
		if self.is_new():
			self.update(LIFECYCLE_DEFAULTS)
			return
		changed = _changed(self.get_doc_before_save(), self, LIFECYCLE_DEFAULTS)
		if changed:
			frappe.throw(
				_("Status and cycle fields are changed only by the step gate: {0}").format(", ".join(changed))
			)

	def _guard_service_fields(self):
		if self.is_new():
			self.cycles_source = self.cycles_source or "Actual"
			if not self.flags.tc_tag_verify:
				self.update(dict.fromkeys(TAG_FIELDS))
			return
		before = self.get_doc_before_save()
		changed = _changed(before, self, ISSUE_FIELDS)
		if not self.flags.tc_tag_verify:
			changed += _changed(before, self, TAG_FIELDS)
		if changed:
			frappe.throw(
				_("These fields are set only by issuing or verifying Set ID tags: {0}").format(
					", ".join(changed)
				)
			)
