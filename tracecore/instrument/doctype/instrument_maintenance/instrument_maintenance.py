"""Instrument Maintenance: bộ đếm chu trình kể từ lần bảo dưỡng và lịch sử hoãn của một dụng cụ trong một bộ.

Mỗi cặp (Set Unit, Instrument) có đúng một dòng; tên = `{set_unit}-{instrument}` nên trùng cặp bị
DuplicateEntryError (DT-INSTRMAINT, FR-M1-09).

Bộ đếm và lần bảo dưỡng/hoãn cuối chỉ đổi qua ``tracecore.instrument.maintenance`` (T4 ``apply_pack``, giải phóng
``on_set_released``, khởi tạo ``init_counter``), đánh dấu bằng ``flags.tc_maintenance``. Sửa tay trên form hay qua
API (kể cả System Manager) bị chặn (FEAT-014 Review Focus 4).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, get_datetime

COUNTER_FIELDS = ("cycles_since_maint", "deferred_count")
DATETIME_FIELDS = ("last_maint_on", "last_defer_on")
TEXT_FIELDS = ("last_maint_by", "last_oil_batch", "last_defer_reason", "last_release_cycle")


def _comparable(field, value):
	if field in COUNTER_FIELDS:
		return cint(value)
	if field in DATETIME_FIELDS:
		return get_datetime(value) if value else None
	return cstr(value)


class InstrumentMaintenance(Document):
	def validate(self):
		self._guard_counters()

	def _guard_counters(self):
		if self.flags.tc_maintenance:
			return
		before = None if self.is_new() else self.get_doc_before_save()
		for field in (*COUNTER_FIELDS, *DATETIME_FIELDS, *TEXT_FIELDS):
			old = before.get(field) if before else None
			if _comparable(field, self.get(field)) != _comparable(field, old):
				frappe.throw(
					_(
						"Maintenance counters are changed only by packing (T4), set release and counter initialization."
					)
				)
