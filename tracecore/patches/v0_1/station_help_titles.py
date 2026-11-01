"""#1831 S-03: bài hướng dẫn trạm còn tên mặc định còn khóa kỹ thuật đổi sang tên trạm; bài R10 đã đặt tên thì giữ."""

import frappe

from tracecore.ui import station_help


def execute():
	if not frappe.get_meta("Help Article").has_field("tc_station_key"):
		return
	for key in station_help.STATION_KEYS:
		if key == station_help.GENERAL:
			continue
		defaults = {f"Station guide: {key}", frappe._("Station guide: {0}", lang="vi").format(key)}
		for row in frappe.get_all("Help Article", filters={"tc_station_key": key}, fields=["name", "title"]):
			if row.title in defaults:
				frappe.db.set_value(
					"Help Article", row.name, "title", station_help.article_title(key), update_modified=False
				)
