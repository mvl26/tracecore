"""Par Level: cơ số tái xử lý và cơ số tồn khoa (DT-PARLEVEL, M8); luật ở ``tracecore.par.config``.

Không xóa (audit hook ``block_delete``): ngừng dùng bằng ``is_active``. Lịch sử thay đổi ở bảng con
``Par Level History`` (bất biến, FR-M8-01.3).
"""

from frappe.model.document import Document

from tracecore.par import config


class ParLevel(Document):
	def validate(self):
		config.validate(self)

	def on_update(self):
		config.sync_instrument(self)
