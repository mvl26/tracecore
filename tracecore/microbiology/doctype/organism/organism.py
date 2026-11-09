"""Organism — danh mục vi sinh vật theo mã WHONET (FEAT-067, FR-M14-01)."""

from frappe.model.document import Document


class Organism(Document):
	def validate(self):
		# mã WHONET viết thường (eco, kpn, sau); tên và nhóm bỏ khoảng trắng thừa
		self.organism_code = "".join((self.organism_code or "").split()).lower()
		self.organism_name = " ".join((self.organism_name or "").split())
		self.organism_group = " ".join((self.organism_group or "").split()) or None
