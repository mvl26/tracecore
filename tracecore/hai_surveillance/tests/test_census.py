"""Mẫu số ngày theo khoa (FEAT-062; FR-M13-02, FR-M13-02.1, FR-M13-02.2, FR-M13-04, BRU-HAI-002; A-141)."""

import json
import pathlib

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import census, episodes
from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import bru


class TestCensusRules(FrappeTestCase):
	def setUp(self):
		self.ward = f.make_ward("KSNK Census ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})

	def _code(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block

	@bru("BRU-HAI-002")
	def test_one_census_per_day_and_department(self):
		first = census.save(f.census_values(self.ward))
		block = self._code(census.save, f.census_values(self.ward, patients=20))
		self.assertEqual(block.code, "CENSUS_DUPLICATE")
		self.assertEqual(block.object_name, first.name)
		self.assertEqual(frappe.db.count("Ward Daily Census", {"department": self.ward}), 1)

	@bru("BRU-HAI-002")
	def test_database_rejects_second_row(self):
		census.save(f.census_values(self.ward))
		doc = frappe.get_doc({"doctype": "Ward Daily Census", **f.census_values(self.ward)})
		doc.flags.tc_skip_duplicate_check = True
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			doc.db_insert()

	def test_edit_existing_by_name(self):
		first = census.save(f.census_values(self.ward))
		again = census.save(f.census_values(self.ward, patients=20), name=first.name)
		self.assertEqual(again.name, first.name)
		self.assertEqual(again.patient_count, 20)
		self.assertEqual(again.source, "Manual")

	def test_edit_cannot_move_to_another_day(self):
		first = census.save(f.census_values(self.ward))
		block = self._code(census.save, f.census_values(self.ward, census_date=add_days(today(), -2)), name=first.name)
		self.assertEqual(block.code, "CENSUS_DUPLICATE")

	def test_device_count_above_patients_blocked_with_field(self):
		block = self._code(census.save, f.census_values(self.ward, patients=18, urinary=21))
		self.assertEqual(block.code, "CENSUS_COUNT_INVALID")
		self.assertEqual(block.items, ["urinary_catheter_count"])
		self.assertIn("21", block.reason)
		self.assertIn("18", block.reason)

	def test_negative_count_blocked(self):
		block = self._code(census.save, f.census_values(self.ward, admissions=-1))
		self.assertEqual(block.code, "CENSUS_COUNT_INVALID")

	def test_future_date_blocked(self):
		block = self._code(census.save, f.census_values(self.ward, census_date=add_days(today(), 1)))
		self.assertEqual(block.code, "CENSUS_DATE_INVALID")

	def test_today_allowed(self):
		self.assertTrue(census.save(f.census_values(self.ward, census_date=today())).name)

	@bru("BRU-HAI-002")
	def test_locked_census_cannot_change(self):
		doc = census.save(f.census_values(self.ward))
		frappe.db.set_value("Ward Daily Census", doc.name, "locked", 1)
		block = self._code(census.save, f.census_values(self.ward, patients=19), name=doc.name)
		self.assertEqual(block.code, "CENSUS_PERIOD_LOCKED")
		locked = frappe.get_doc("Ward Daily Census", doc.name)
		locked.flags.tc_period_unlock = True  # FEAT-063: R01 mở khóa kỳ có lý do
		locked.patient_count = 19
		locked.save(ignore_permissions=True)

	def test_import_updates_and_marks_source(self):
		first = census.save(f.census_values(self.ward))
		doc = census.save(f.census_values(self.ward, patients=25), source="Import", upsert=True)
		self.assertEqual(doc.name, first.name)
		self.assertEqual((doc.patient_count, doc.source), (25, "Import"))
		manual = census.save(f.census_values(self.ward, patients=24), name=doc.name)
		self.assertEqual(manual.source, "Manual")

	def test_cannot_delete(self):
		doc = census.save(f.census_values(self.ward))
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Ward Daily Census", doc.name, ignore_permissions=True)

	def test_prefill_and_recent(self):
		yesterday = add_days(today(), -1)
		census.save(f.census_values(self.ward, census_date=add_days(yesterday, -1), patients=17))
		census.save(f.census_values(self.ward, census_date=add_days(yesterday, -3), patients=15))
		self.assertEqual(census.prefill(self.ward, yesterday)["patient_count"], 17)
		rows = census.recent(self.ward, yesterday)
		self.assertEqual([row["patient_count"] for row in rows], [17, 15])
		self.assertIsNone(census.prefill(self.ward, add_days(yesterday, -10)))


class TestDenominators(FrappeTestCase):
	def setUp(self):
		self.ward = f.make_ward("KSNK Denominator ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})
		frappe.db.delete("Device Episode", {"department": self.ward})
		self.start = getdate(add_days(today(), -9))
		for offset, (patients, vent) in enumerate(((10, 2), (12, 3))):
			census.save(f.census_values(self.ward, add_days(self.start, offset), patients, vent, 1, 1))
		episodes.open_episode(
			{
				"department": self.ward,
				"device_type": "Ventilator",
				"patient_code": "BN-DEN-0001",
				"inserted_on": self.start,
				"removed_on": add_days(self.start, 4),
			}
		)

	def test_census_source(self):
		values = census.denominators(self.ward, self.start, add_days(self.start, 1))
		self.assertEqual(values["source"], "Daily Census")
		self.assertEqual((values["patient_days"], values["vent_days"], values["cvc_days"]), (22, 5, 2))

	def test_episode_source(self):
		frappe.db.set_value("Department", self.ward, "tc_device_day_source", "Device Episode")
		values = census.denominators(self.ward, self.start, add_days(self.start, 1))
		self.assertEqual(values["source"], "Device Episode")
		self.assertEqual(values["patient_days"], 22)  # ngày nằm viện luôn từ mẫu số
		self.assertEqual((values["vent_days"], values["cvc_days"]), (2, 0))


class TestNoPatientName(FrappeTestCase):
	@bru("BRU-HAI-005")
	def test_no_patient_name_field_in_m13(self):
		folder = pathlib.Path(frappe.get_app_path("tracecore", "hai_surveillance", "doctype"))
		words = ("name1", "patient_name", "full_name", "first_name", "last_name", "ho_ten")
		for path in folder.glob("*/*.json"):
			meta = json.loads(path.read_text(encoding="utf8"))
			for field in meta.get("fields", []):
				self.assertFalse(
					any(word in field["fieldname"] for word in words), f"{path.name}: {field['fieldname']}"
				)
		self.assertEqual(frappe.get_meta("Device Episode").get_field("patient_code").fieldtype, "Password")
