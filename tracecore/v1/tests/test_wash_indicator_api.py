"""RPC chỉ thị rửa (A-77): dỡ lô đổi trạng thái, `wash.result` nhận chỉ thị, tra lô, bảng phụ T2, quyền trạm."""

import uuid

import frappe
from frappe.utils import add_days, today

from tracecore.tests.factories import make_batch, make_item, make_wash_ready_set
from tracecore.tests.utils import bru
from tracecore.v1 import wash as wash_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.test_wash_api import STATION, WashApiCase, call, http_status, now_ts

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

ITEM = "CI-RUA-API"


class TestWashIndicatorApi(WashApiCase):
	def setUp(self):
		super().setUp()
		make_item(ITEM, "Chemical Indicator", has_batch_no=1, ci_class="1")
		frappe.db.set_value(
			"Process Program",
			self.program.name,
			{"requires_wash_indicator": 1, "requires_wash_indicator_photo": 1},
		)

	def loaded(self):
		unit = make_wash_ready_set()
		return self.complete([unit.name])["batch"], unit.name

	def awaiting(self):
		batch, set_id = self.loaded()
		self.manual_data(batch)
		context = call(wash_api.unload_context, **self.unload_args(batch))
		self.assertEqual(context["batch"]["status"], "Awaiting Result")
		return batch, set_id

	def indicator(self, **kwargs):
		return {
			"item": ITEM,
			"lot": "API-LOT",
			"lot_expiry": add_days(today(), 30),
			"result": "Pass",
			"photo": "/private/files/ci.jpg",
			**kwargs,
		}

	@bru("BRU-REP-016")
	def test_batch_listed_as_awaiting_after_unload(self):
		batch, _set_id = self.awaiting()
		overview = call(wash_api.redo_queue, station=STATION)
		self.assertIn(batch, [row["batch"] for row in overview["awaiting"]])
		self.assertNotIn(batch, [row["batch"] for row in overview["running"]])

	@bru("BRU-REP-002")
	def test_result_with_indicator_as_json_passes(self):
		batch, set_id = self.awaiting()
		response = call(
			wash_api.result,
			result="Pass",
			clean_test=None,
			indicator=frappe.as_json(self.indicator()),
			**self.unload_args(batch),
		)
		self.assertIs(response["ok"], True, msg=response)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Passed")
		reader = frappe.db.get_value("Load Indicator Result", {"wash_batch": batch}, "read_by")
		self.assertEqual(reader, frappe.db.get_value("Wash Batch", batch, "unloaded_by"))
		self.assertTrue(set_id)

	@bru("BRU-REP-002")
	def test_expired_indicator_is_a_rejection_with_http_status(self):
		batch, _set_id = self.awaiting()
		response = call(
			wash_api.result,
			result="Pass",
			clean_test=None,
			indicator=self.indicator(lot_expiry=add_days(today(), -1)),
			**self.unload_args(batch),
		)
		self.assertEqual(response["error"]["code"], "INDICATOR_EXPIRED")
		self.assertEqual(http_status(), 422)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Awaiting Result")

	def test_replay_same_key_does_not_record_twice(self):
		batch, _set_id = self.awaiting()
		# cùng client_ts: phát lại cùng khóa phải là đúng yêu cầu cũ, lệch giây thì thành xung đột khóa
		args = {
			"result": "Pass",
			"clean_test": None,
			"indicator": self.indicator(),
			"client_ts": now_ts(),
			**self.unload_args(batch),
		}
		key = str(uuid.uuid4())
		first = call(wash_api.result, key=key, **args)
		second = call(wash_api.result, key=key, **args)
		self.assertEqual(first["batch"], second["batch"])
		self.assertEqual(frappe.db.count("Load Indicator Result", {"wash_batch": batch}), 1)

	def test_indicator_must_be_an_object(self):
		batch, _set_id = self.loaded()
		with self.assertRaises(BadRequestError):
			call(
				wash_api.result,
				result="Pass",
				clean_test="Pass",
				indicator="[1]",
				**self.unload_args(batch),
			)

	def test_indicator_lot_lookup(self):
		make_batch(ITEM, "API-LOT-KHO", add_days(today(), 60))
		found = call(wash_api.indicator_lot, raw="API-LOT-KHO", station=STATION)
		self.assertIs(found["ok"], True)
		self.assertEqual(found["item"], ITEM)
		missing = call(wash_api.indicator_lot, raw="KHONG-CO", station=STATION)
		self.assertIs(missing["found"], False)
