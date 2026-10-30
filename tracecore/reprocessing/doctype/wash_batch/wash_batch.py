"""Wash Batch: lô rửa trên máy rửa khử khuẩn hoặc máy siêu âm (FEAT-021, UC-06, WF-04).

Mã ``LR-YYMMDD-NN`` do hệ thống sinh khi người vận hành bấm Hoàn thành nạp và ghi Code Registry (FR-M2-03.2); không
nhập tay. Lô chỉ do dịch vụ rửa (`tracecore.reprocessing.washing`) tạo và đổi, bằng cờ ``doc.flags.tc_washing``:
R03/R05/System Manager có quyền write (để ghi sổ) nhưng lưu từ Desk không được tự đổi kết quả, trạng thái hay dữ
liệu máy. Lô ghi sổ là lô đã đóng; không hủy chứng từ, không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from tracecore.core import audit, code_registry

CODE_PREFIX = "LR"
SERVICE_FIELDS = (
	"batch_type",
	"equipment",
	"program",
	"operator",
	"status",
	"loaded_by_scan",
	"load_completed_at",
	"started_at",
	"ended_at",
	"data_source",
	"data_complete",
	"needs_review",
	"manual_confirmed_by",
	"manual_confirmed_at",
	"machine_data",
	"machine_files",
	"unload_scan_equipment",
	"unload_scan_at",
	"clean_test_result",
	"cycle_result",
	"result_source",
	"reviewer",
	"reviewed_at",
	"result_note",
	"nc_pending",
	"cost_total",
)


class WashBatch(Document):
	def autoname(self):
		# mã không bao giờ lấy từ người dùng; bỏ qua số đã dùng
		while True:
			name = make_autoname("LR-.YY.MM.DD.-.##", doc=self)
			if not frappe.db.exists("Wash Batch", name):
				self.name = name
				return

	def before_insert(self):
		if not self.flags.tc_washing:
			frappe.throw(_("A wash batch is created only when loading is completed on the wash screen."))

	def validate(self):
		self._validate_rows()
		if not self.flags.tc_washing:
			self._guard_service_fields()

	def after_insert(self):
		if not code_registry.is_issued(self.name):
			code_registry.register(self.name, CODE_PREFIX, "Wash Batch", self.name)

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def before_cancel(self):
		frappe.throw(_("A wash batch cannot be cancelled."))

	def _validate_rows(self):
		sets = [row.set_unit for row in self.set_units]
		if len(set(sets)) != len(sets):
			frappe.throw(_("A set unit appears more than once in the wash batch."))

	def _guard_service_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [f for f in SERVICE_FIELDS if str(before.get(f) or "") != str(self.get(f) or "")]
		if changed or self._rows_signature(before) != self._rows_signature(self):
			frappe.throw(_("A wash batch is changed only by the wash screen service."))

	@staticmethod
	def _rows_signature(doc):
		return (
			[row.set_unit for row in doc.set_units],
			[(row.item, row.lot) for row in doc.chemicals],
		)
