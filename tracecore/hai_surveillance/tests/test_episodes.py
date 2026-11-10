"""Đợt thiết bị xâm lấn (FEAT-062; FR-M13-04, FR-M13-04.1, FR-M13-04.2, BRU-HAI-005, ADR-010; A-141 a)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today
from frappe.utils.password import get_decrypted_password

from tracecore.core import patient_code
from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import episodes
from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import bru


def _values(ward, **values):
	return {
		"department": ward,
		"device_type": "Ventilator",
		"patient_code": "BN-0000004821",
		"birth_year": 1960,
		"sex": "Male",
		"inserted_on": add_days(today(), -4),
		**values,
	}


class TestDeviceEpisode(FrappeTestCase):
	def setUp(self):
		self.ward = f.make_ward("KSNK Episode ICU")
		frappe.db.delete("Device Episode", {"department": self.ward})

	def _block(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block

	@bru("BRU-HAI-005")
	def test_patient_code_encrypted_hashed_masked(self):
		doc = episodes.open_episode(_values(self.ward, patient_code=" bn-0000004821 "))
		self.assertEqual(doc.patient_code_masked, "***4821")
		self.assertEqual(doc.patient_code_hash, patient_code.hash_of("BN-0000004821"))
		stored = frappe.db.get_value("Device Episode", doc.name, "patient_code")
		self.assertNotIn("4821", stored or "")
		self.assertEqual(get_decrypted_password("Device Episode", doc.name, "patient_code"), "BN-0000004821")

	def test_open_episode_days_count_both_ends(self):
		doc = episodes.open_episode(_values(self.ward))
		self.assertEqual(doc.status, "Open")
		self.assertEqual(episodes.device_days(doc.inserted_on), 5)  # đặt 4 ngày trước, hôm nay là ngày thứ 5

	def test_close_episode_stores_days(self):
		doc = episodes.open_episode(_values(self.ward))
		closed = episodes.close_episode(doc.name, add_days(today(), -1))
		self.assertEqual((closed.status, closed.device_days), ("Closed", 4))
		block = self._block(episodes.close_episode, doc.name, today())
		self.assertEqual(block.code, "DEVICE_EPISODE_CLOSED")

	def test_removed_before_inserted_blocked(self):
		doc = episodes.open_episode(_values(self.ward))
		block = self._block(episodes.close_episode, doc.name, add_days(today(), -5))
		self.assertEqual(block.code, "DEVICE_EPISODE_DATE_INVALID")
		self.assertEqual(frappe.db.get_value("Device Episode", doc.name, "status"), "Open")

	def test_future_dates_blocked(self):
		block = self._block(episodes.open_episode, _values(self.ward, inserted_on=add_days(today(), 1)))
		self.assertEqual(block.code, "DEVICE_EPISODE_DATE_INVALID")

	def test_birth_year_range(self):
		block = self._block(episodes.open_episode, _values(self.ward, birth_year=1800))
		self.assertEqual(block.code, "DEVICE_EPISODE_DATE_INVALID")

	def test_second_open_episode_same_patient_device_blocked(self):
		episodes.open_episode(_values(self.ward))
		block = self._block(episodes.open_episode, _values(self.ward, patient_code="bn-0000004821"))
		self.assertEqual(block.code, "DEVICE_EPISODE_OPEN")
		other = episodes.open_episode(_values(self.ward, device_type="Urinary Catheter"))
		self.assertTrue(other.name)

	def test_masked_list_only(self):
		episodes.open_episode(_values(self.ward))
		rows = episodes.open_list([self.ward], getdate(today()))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["patient_code_masked"], "***4821")
		self.assertEqual(rows[0]["device_days"], 5)
		self.assertNotIn("patient_code", rows[0])
		self.assertIsNone(rows[0]["bundle_result"])

	def test_days_between(self):
		start = getdate(add_days(today(), -9))
		episodes.open_episode(_values(self.ward, inserted_on=start))
		episodes.open_episode(
			_values(
				self.ward,
				patient_code="BN-X-0002",
				inserted_on=add_days(start, 1),
				removed_on=add_days(start, 2),
			)
		)
		days = episodes.days_between(self.ward, start, add_days(start, 2))
		self.assertEqual(days["Ventilator"], 5)
		self.assertEqual(days["Central Line"], 0)
