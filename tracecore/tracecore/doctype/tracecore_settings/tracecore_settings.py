"""TraceCore Settings: cờ tính năng toàn site (FEAT-014 A-06 I7).

Single trong module ``TraceCore``. Chỉ TC R10 và System Manager ghi (quyền DocType); đổi cờ ghi Audit Log qua
doc_events (``hooks.py``), không xóa được. Đọc cờ qua dịch vụ của phân hệ (vd ``instrument.catalog.giai_enabled``).
"""

import re
from datetime import time

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import code_registry, error_codes, extension, gs1

_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_times(text):
	"""Danh sách giờ ``HH:MM`` cách nhau bởi dấu phẩy → list `time` tăng dần, không trùng (FEAT-008, A-55 Q3)."""
	times = set()
	for part in (text or "").split(","):
		part = part.strip()
		if not part:
			continue
		match = _TIME.match(part)
		if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
			frappe.throw(_("{0} is not a time of day (HH:MM).").format(part))
		times.add(time(int(match.group(1)), int(match.group(2))))
	return sorted(times)


class TraceCoreSettings(Document):
	def onload(self):
		self._show_gtin_counter()

	def _show_gtin_counter(self):
		# bộ đếm thật ở tabSeries (A-76); ô này chỉ hiển thị, giá trị form gửi lên không có tác dụng
		state = code_registry.gtin_range()
		self.gtin_next_item_ref = str(state["next_ref"]).zfill(len(str(state["capacity"]))) if state else None

	def _validate_gs1(self):
		"""Mã doanh nghiệp GS1 (A-76): 7-11 chữ số; dải demo chỉ trên site dev/test; prefix thật đã cấp mã thì khóa."""
		prefix = (self.gs1_company_prefix or "").strip()
		self.gs1_company_prefix = prefix
		if prefix and not gs1.is_valid_gtin_prefix(prefix):
			frappe.throw(_("GS1 Company Prefix must be 7-11 digits."))
		if prefix and gs1.is_demo_prefix(prefix) and not code_registry.demo_prefix_allowed():
			frappe.throw(
				_("GS1 Company Prefix {0} is the demo prefix and cannot be used on this site.").format(prefix)
			)
		old = gs1.configured_company_prefix()
		if prefix != old and code_registry.prefix_in_use(old):
			frappe.throw(
				_("GS1 Company Prefix {0} has already issued codes and cannot be changed.").format(old)
			)
		self.gtin_indicator_digit = self.gtin_indicator_digit or "0"
		self._show_gtin_counter()

	def validate(self):
		self._validate_gs1()
		# giờ nhắc nhật ký môi trường: lưu dạng chuẩn "HH:MM, HH:MM"
		self.env_reminder_times = ", ".join(t.strftime("%H:%M") for t in parse_times(self.env_reminder_times))
		error_codes.validate_rules(self)

	def on_update(self):
		# đổi cấu hình mã lỗi có hiệu lực ngay (FR-M9-18): máy đã khóa vì TB-002 được mở khi viện hạ mức
		error_codes.clear_cache()
		extension.run("tracecore_error_rules_changed")
