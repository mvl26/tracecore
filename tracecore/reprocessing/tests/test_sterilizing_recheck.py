"""Đổi chương trình khi đang nạp mẻ (A-88, #1844): giữ gói đã quét, kiểm lại từng gói theo chương trình mới."""

import frappe

from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import (
	make_equipment,
	make_load_ready_pack,
	make_pack_type,
	make_sterilize_program,
)
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import load as load_api
from tracecore.v1.tests.test_lookup_api import LookupCase, call

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _asset(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class RecheckCase:
	def prepare(self, capacity=None):
		values = {"capacity": str(capacity)} if capacity else {}
		self.machine = make_equipment(
			"Hấp kiểm lại", "Steam Sterilizer", serial="SN-" + frappe.generate_hash(length=8), **values
		)
		self.packs = [make_load_ready_pack(), make_load_ready_pack()]
		self.fits = make_sterilize_program(self.machine)
		self.other = make_sterilize_program(
			self.machine, pack_types=[make_pack_type("PK-" + frappe.generate_hash(length=6).upper())]
		)


class TestRecheckService(RecheckCase, IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def check(self, program, packs=None):
		names = [pack.name for pack in self.packs] if packs is None else packs
		return sterilizing.recheck_packs(self.machine.name, program.name, names)

	def test_compatible_packs_stay_ok(self):
		self.prepare()
		rows = self.check(self.fits)
		self.assertEqual([row["cycle_id"] for row in rows], [pack.name for pack in self.packs])
		self.assertTrue(all(row["ok"] for row in rows))

	def test_incompatible_pack_keeps_its_row_with_a_reason(self):
		self.prepare()
		rows = self.check(self.other)
		self.assertEqual(len(rows), 2)
		self.assertFalse(rows[0]["ok"])
		self.assertEqual(rows[0]["code"], "PACK_INCOMPATIBLE")
		self.assertIn(rows[0]["cycle_id"], rows[0]["reason"])

	def test_capacity_counts_each_pack_once(self):
		self.prepare(capacity=2)
		self.assertTrue(all(row["ok"] for row in self.check(self.fits)))

	def test_pack_over_capacity_is_marked(self):
		self.prepare(capacity=1)
		rows = self.check(self.fits)
		self.assertEqual([row["ok"] for row in rows], [True, False])
		self.assertEqual(rows[1]["code"], "LOAD_CAPACITY_EXCEEDED")

	def test_incompatible_pack_does_not_use_up_capacity(self):
		self.prepare(capacity=1)
		foreign = make_load_ready_pack(method="Plasma")
		rows = self.check(self.fits, [foreign.name, self.packs[0].name])
		self.assertEqual([row["ok"] for row in rows], [False, True])

	def test_nothing_is_written(self):
		self.prepare()
		before = frappe.db.get_value("Pack", self.packs[0].name, "status")
		self.check(self.other)
		self.assertEqual(frappe.db.get_value("Pack", self.packs[0].name, "status"), before)


class TestRecheckRpc(RecheckCase, LookupCase):
	def test_rpc_returns_rows_without_reject_audit(self):
		self.prepare()
		station = self.login("T5")
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = call(
			load_api.recheck,
			station,
			equipment=self.machine.name,
			program=self.other.name,
			packs=[pack.name for pack in self.packs],
		)
		self.assertTrue(result["ok"])
		self.assertEqual(len(result["packs"]), 2)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)


class TestStationAssets(IsolatedTestCase):
	def test_program_change_keeps_packs_and_rechecks(self):
		script = _asset("public", "js", "station_t5.js")
		handler = script.split('target.id === "tc-t5-program"', 1)[1].split("else if", 1)[0]
		self.assertNotIn("packs = []", handler)
		self.assertIn("recheckPacks", handler)
		self.assertIn("tracecore.v1.load.recheck", script)

	def test_machine_confirmation_appears_once(self):
		self.assertEqual(
			_asset("public", "js", "station_t5.js").count('__("Sterilizer {0} scanned · {1}"'), 1
		)
		self.assertEqual(_asset("public", "js", "station_t2.js").count('__("Washer {0} scanned · {1}"'), 1)
