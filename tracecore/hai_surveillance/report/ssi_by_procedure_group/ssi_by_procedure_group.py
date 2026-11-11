"""Script Report "NKVM theo nhóm phẫu thuật" (FEAT-064; FR-M13-09, FR-M13-12; BRU-RPT-002; A-147 h, k).

Mỗi nhóm phẫu thuật một dòng trong khoảng kỳ (tháng ngày mổ): số ca, ca NKVM, tỷ lệ chung và theo NNIS 0 đến 3, tỷ lệ có
kháng sinh dự phòng, tỷ lệ đúng thời điểm. Chỉ số liệu tổng hợp (R13 xem được); tỷ lệ mẫu số 0 để trống ("Không tính").
"""

from frappe import _

from tracecore.hai_surveillance import ssi_indicators


def columns():
	def col(fieldname, label, fieldtype="Int", width=100):
		return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}

	out = [
		col("group_name", _("Procedure Group"), "Data", 200),
		col("surgeries", _("Surgeries")),
		col("ssi", _("SSI Cases")),
		col("ssi_rate", _("SSI Rate (%)"), "Percent"),
	]
	for bucket in ssi_indicators.NNIS_BUCKETS:
		out.append(col(f"ssi_rate_nnis_{bucket}", _("SSI Rate NNIS {0} (%)").format(bucket), "Percent", 120))
	out += [
		col("nnis_unknown", _("NNIS Not Calculated"), "Int", 120),
		col("prophylaxis_rate", _("Prophylaxis Rate (%)"), "Percent", 120),
		col("on_time_rate", _("On Time Rate (%)"), "Percent", 120),
	]
	return out


def execute(filters=None):
	filters = filters or {}
	start = filters.get("period_from")
	if not start:
		return columns(), []
	return columns(), ssi_indicators.summary(start, filters.get("period_to") or start)
