"""Nền dùng chung cho test tiếp nhận T1 (FEAT-019): khoa, người giao có thẻ, người nhận, loại bộ có BOM, bộ ở trạng thái cho trước."""

import uuid

import frappe

from tracecore.core import client_time
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import receiving
from tracecore.tests.factories import make_department, make_employee, make_set_type, make_set_unit
from tracecore.tests.utils import IsolatedTestCase

STATION = "TR-001"  # T1 Receiving
BOM = [("RV-KC-01", 2), ("RV-KC-02", 1), ("RV-KC-03", 4)]


class ReceivingCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.department = make_department("Test operating room")
		self.card = "DLV-" + uuid.uuid4().hex[:10].upper()
		self.deliverer = make_employee(card=self.card, department=self.department, first_name="Deliverer")
		self.receiver = make_employee(first_name="Receiver").name
		self.set_type = make_set_type("RCV1", bom=BOM).name

	def now(self):
		return client_time.utc_now()

	def new_set(self, status="At Department", set_type=None):
		"""Set Unit ở `status` (đặt thẳng trong test, không qua dịch vụ vòng đời)."""
		unit = make_set_unit(set_type or self.set_type).name
		frappe.db.set_value("Set Unit", unit, "status", status, update_modified=False)
		return unit

	def open(self, raw=None, **kwargs):
		kwargs.setdefault("client_ts", self.now())
		return receiving.open_receipt(STATION, self.receiver, raw=raw, **kwargs)

	def opened(self):
		"""Phiếu nháp mở bằng thẻ người giao; trả tên phiếu."""
		return self.open(self.card)["receipt"]

	def scan(self, receipt, raw, **kwargs):
		kwargs.setdefault("client_ts", self.now())
		return receiving.scan_set(receipt, raw, STATION, self.receiver, **kwargs)

	def code_of(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block.code
