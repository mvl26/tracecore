"""IC Reporting Period — kỳ báo cáo tháng `KY-<YYYY>-<MM>` (FEAT-063; FR-M13-11; A-144 Q1). Chỉ dịch vụ
``hai_surveillance.periods`` ghi (cờ ``tc_period``); không xóa."""

from frappe.model.document import Document

from tracecore.hai_surveillance import periods


class ICReportingPeriod(Document):
	def autoname(self):
		self.name = periods.period_name(self.month)

	def validate(self):
		periods.validate(self)

	def on_trash(self):
		periods.on_trash(self)
