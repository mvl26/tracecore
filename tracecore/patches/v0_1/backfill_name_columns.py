"""Cột Tên cạnh cột mã (A-65): điền tên cho dữ liệu cũ vào các trường ``<link>_name`` vừa thêm.

Đọc cấu hình từ Meta (trường Data có ``fetch_from = <link>.<trường tên>``) nên không lặp lại bảng quy tắc. Chạy theo lô
khóa ``name`` nên bảng lớn không giữ khóa lâu; chỉ điền ô còn trống nên chạy lại an toàn; SQL trực tiếp không đổi ``modified``.
"""

import frappe

from tracecore.core.name_columns import MODULES

BATCH_SIZE = 5000


def _targets():
	"""(doctype, link, name_field, đích, trường nguồn) của mọi cột tên tự điền."""
	found = []
	for doctype in frappe.get_all(
		"DocType", filters={"module": ["in", MODULES]}, pluck="name", order_by="name"
	):
		meta = frappe.get_meta(doctype)
		for df in meta.fields:
			if df.fieldtype != "Data" or not df.fetch_from or "." not in df.fetch_from:
				continue
			link, source = df.fetch_from.split(".", 1)
			link_df = meta.get_field(link)
			if df.fieldname != f"{link}_name" or not link_df or link_df.fieldtype != "Link":
				continue
			found.append((doctype, link, df.fieldname, link_df.options, source))
	# Set Unit trước: các bảng khác lấy ``set_unit.set_type_name``
	return sorted(found, key=lambda t: (t[0] != "Set Unit", t[0], t[1]))


def _fill(doctype, link, name_field, target, source, batch_size):
	table, target_table = f"tab{doctype}", f"tab{target}"
	if not (frappe.db.has_column(doctype, name_field) and frappe.db.has_column(target, source)):
		return 0
	filled, last = 0, ""
	while True:
		names = frappe.db.sql_list(
			f"""select name from `{table}`
			where name > %s and ifnull(`{link}`, '') != '' and ifnull(`{name_field}`, '') = ''
			order by name limit {int(batch_size)}""",  # nosec B608 - table/column names come from Meta
			last,
		)
		if not names:
			return filled
		marks = ", ".join(["%s"] * len(names))
		frappe.db.sql(
			f"""update `{table}` t join `{target_table}` s on s.name = t.`{link}`
			set t.`{name_field}` = s.`{source}` where t.name in ({marks})""",  # nosec B608 - table/column names come from Meta
			names,
		)
		filled += len(names)
		last = names[-1]
		if not frappe.flags.in_test:
			frappe.db.commit()  # keep transactions short on large tables


def execute(batch_size=BATCH_SIZE):
	for doctype, link, name_field, target, source in _targets():
		_fill(doctype, link, name_field, target, source, batch_size)
