"""IC Network Member — mạng lưới viên KSNK theo khoa (FEAT-057; FR-M11-03; BRU-ICP-003; A-132 d).

Kiểm trùng ở validate hook ``infection_program.structure.check``; sau khi lưu: cảnh báo R01 khi khoa mất người cuối
cùng của một nhóm và đồng bộ Role R12 + User Permission Department (``infection_program.network``).
"""

from frappe.model.document import Document

from tracecore.infection_program import network


class ICNetworkMember(Document):
	def on_update(self):
		network.after_change(self)
