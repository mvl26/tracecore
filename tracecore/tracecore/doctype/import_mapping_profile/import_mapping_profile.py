"""Import Mapping Profile — hồ sơ ánh xạ cột nhập file ngoài (FEAT-056; FR-M9-28, F-21, EI-SW-010; D3 không tích hợp HIS).

Mỗi hồ sơ gắn một loại import (`core.importer`): đổi tên cột của file nguồn sang mã cột của loại import, định dạng
ngày, và với CSV là bảng mã + dấu phân cách. Khung import đọc hồ sơ ở `importer.load_profile`.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import importer


class ImportMappingProfile(Document):
	def validate(self):
		kind = importer.kinds().get(self.import_kind or "")
		if not kind:
			frappe.throw(_("Unknown import type {0}.").format(self.import_kind))
		fields = {column.field for column in kind.columns}
		sources, targets = set(), set()
		for row in self.columns:
			row.source_column = " ".join((row.source_column or "").split())
			row.target_field = (row.target_field or "").strip()
			if row.target_field not in fields:
				frappe.throw(
					_("Row {0}: {1} is not a column of import type {2}.").format(
						row.idx, row.target_field, _(kind.label)
					)
				)
			if row.target_field in targets:
				frappe.throw(_("Row {0}: column {1} is mapped twice.").format(row.idx, row.target_field))
			if row.source_column.casefold() in sources:
				frappe.throw(_("Row {0}: file column {1} is listed twice.").format(row.idx, row.source_column))
			targets.add(row.target_field)
			sources.add(row.source_column.casefold())
