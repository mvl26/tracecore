"""TraceCore Settings: cờ tính năng toàn site (FEAT-014 A-06 I7).

Single trong module ``TraceCore``. Chỉ TC R10 và System Manager ghi (quyền DocType); đổi cờ ghi Audit Log qua
doc_events (``hooks.py``), không xóa được. Đọc cờ qua dịch vụ của phân hệ (vd ``instrument.catalog.giai_enabled``).
"""

from frappe.model.document import Document


class TraceCoreSettings(Document):
	pass
