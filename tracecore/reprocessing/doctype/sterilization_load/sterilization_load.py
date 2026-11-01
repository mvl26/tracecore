"""Sterilization Load: mẻ tiệt khuẩn trên máy hấp hơi nước hoặc plasma (FEAT-022, UC-09, WF-03).

Mã ``ME-YYMMDD-NN`` do hệ thống sinh khi người vận hành bấm Hoàn thành nạp và ghi Code Registry (FR-M2-09.1); không
nhập tay. Mẻ chỉ do dịch vụ tiệt khuẩn (`tracecore.reprocessing.sterilizing`) tạo và đổi, bằng cờ
``doc.flags.tc_sterilizing``: R05/System Manager có quyền write (để ghi sổ ở FEAT-023) nhưng lưu từ Desk không được
tự đổi trạng thái, gói hay dữ liệu máy. Không hủy chứng từ, không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from tracecore.core import audit, code_registry

CODE_PREFIX = "ME"
SERVICE_FIELDS = (
	"equipment",
	"program",
	"operator",
	"is_priority",
	"requires_bi",
	"status",
	"loaded_by_scan",
	"load_completed_at",
	"started_at",
	"ended_at",
	"data_source",
	"data_complete",
	"needs_review",
	"manual_reason",
	"manual_confirmed_by",
	"manual_confirmed_at",
	"params",
	"machine_data",
	"machine_alerts",
	"machine_report",
	"chart_files",
	"unload_scan_equipment",
	"unload_scan_at",
	"unloaded_by",
	"cycle_result",
	"result_source",
	"released_by",
	"released_at",
	"review_confirmed",
	"bi_result",
	"redo_from",
	"release_reason",
)


class SterilizationLoad(Document):
	def autoname(self):
		# mã không bao giờ lấy từ người dùng; bỏ qua số đã dùng
		while True:
			name = make_autoname("ME-.YY.MM.DD.-.##", doc=self)
			if not frappe.db.exists("Sterilization Load", name):
				self.name = name
				return

	def before_insert(self):
		if not self.flags.tc_sterilizing:
			frappe.throw(
				_(
					"A sterilization load is created only when loading is completed on the sterilizer loading screen."
				)
			)

	def validate(self):
		self._validate_program()
		self._validate_rows()
		if not self.flags.tc_sterilizing:
			self._guard_service_fields()

	def before_update_after_submit(self):
		if not self.flags.tc_sterilizing:
			self._guard_service_fields()

	def after_insert(self):
		if not code_registry.is_issued(self.name):
			code_registry.register(self.name, CODE_PREFIX, "Sterilization Load", self.name)

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def before_cancel(self):
		frappe.throw(_("A sterilization load cannot be cancelled."))

	def _validate_program(self):
		# mẻ chỉ dùng cho dụng cụ; lần chạy test ghi ở Daily Test (A-83, D1). `load_repair` đóng mẻ cũ bằng cờ riêng
		if self.flags.tc_load_repair:
			return
		if frappe.db.get_value("Process Program", self.program, "program_kind") == "Test":
			frappe.throw(
				_("Program {0} is a test program: it cannot be used for a sterilization load.").format(
					self.program
				)
			)

	def _validate_rows(self):
		packs = [row.pack for row in self.packs]
		if len(set(packs)) != len(packs):
			frappe.throw(_("A pack appears more than once in the sterilization load."))

	def _guard_service_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [f for f in SERVICE_FIELDS if str(before.get(f) or "") != str(self.get(f) or "")]
		if changed or [row.pack for row in before.packs] != [row.pack for row in self.packs]:
			frappe.throw(_("A sterilization load is changed only by the sterilizer loading service."))
