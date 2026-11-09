"""Organism — danh mục vi sinh vật theo mã WHONET (FEAT-067, FR-M14-01).

Mã WHONET viết thường (eco, kpn, sau), chuẩn hóa trước khi đặt tên để tên bản ghi trùng mã.
"""

from frappe.model.document import Document


def _code(value):
	return "".join((value or "").split()).lower()


class Organism(Document):
	def before_naming(self):
		self.organism_code = _code(self.organism_code)

	def validate(self):
		self.organism_code = _code(self.organism_code)
		self.organism_name = " ".join((self.organism_name or "").split())
		self.organism_group = " ".join((self.organism_group or "").split()) or None
