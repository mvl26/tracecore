"""Phiếu gói dự phòng gắn đợt thiết bị (FEAT-062; FR-M12-07, FR-M12-07.1, BRU-AUD-003; A-141 e).

Đợt thiết bị (M13) tạo bằng `frappe.get_doc`, không import module M13 (không import chéo).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tracecore.compliance_audit.tests import factories as af
from tracecore.core.errors import BlockedError
from tracecore.tests import factories
from tracecore.tests.utils import bru

VAP_ITEMS = tuple((f"VAP-0{i}", "VAP", f"Bundle item {i}", 1, 0) for i in range(1, 7))


def _episode(department, device="Ventilator", inserted_on=None, removed_on=None, code="BN-BUNDLE-0412"):
	return frappe.get_doc(
		{
			"doctype": "Device Episode",
			"department": department,
			"device_type": device,
			"patient_code": code,
			"inserted_on": inserted_on or add_days(today(), -4),
			"removed_on": removed_on,
		}
	).insert(ignore_permissions=True)


class TestBundleSession(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.ward = factories.make_department("KSNK Bundle ICU")
		cls.other = factories.make_department("KSNK Bundle Ward B")
		code = f"T-VAP-{frappe.generate_hash(length=6)}"
		cls.template = af.make_template(
			code,
			scoring="All or None",
			items=VAP_ITEMS,
			audit_type="Prevention Bundle",
			bundle_type="VAP",
			title="VAP bundle",
		).name
		cls.observer = af.make_observer(first_name="Bundle Observer")

	def _session(self, episode=None, answers=None, department=None):
		answers = answers or {code: "Pass" for code, *_rest in VAP_ITEMS}
		return frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": self.template,
				"department": department or self.ward,
				"observer": self.observer,
				"device_episode": episode,
				"answers": [
					{"item_code": code, "answer": answer, "note": "x" if answer == "Fail" else None}
					for code, answer in answers.items()
				],
			}
		)

	def _block(self, doc):
		with self.assertRaises(BlockedError) as caught:
			doc.insert(ignore_permissions=True)
		return caught.exception.block

	@bru("BRU-AUD-003")
	def test_six_items_five_pass_fails(self):
		episode = _episode(self.ward).name
		answers = {code: "Pass" for code, *_rest in VAP_ITEMS}
		answers["VAP-06"] = "Fail"
		doc = self._session(episode, answers).insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.result, "Fail")
		self.assertEqual(doc.device_episode, episode)

	@bru("BRU-AUD-003")
	def test_all_pass_with_na_passes(self):
		answers = {code: "Pass" for code, *_rest in VAP_ITEMS}
		answers["VAP-05"] = "N/A"
		doc = self._session(_episode(self.ward, code="BN-BUNDLE-0413").name, answers).insert(
			ignore_permissions=True
		)
		self.assertEqual(doc.result, "Pass")

	def test_episode_required_for_device_bundle(self):
		self.assertEqual(self._block(self._session()).code, "AUDIT_EPISODE_REQUIRED")

	def test_episode_of_other_department_rejected(self):
		episode = _episode(self.other, code="BN-BUNDLE-0414").name
		self.assertEqual(self._block(self._session(episode)).code, "AUDIT_EPISODE_INVALID")

	def test_episode_of_wrong_device_rejected(self):
		episode = _episode(self.ward, device="Urinary Catheter", code="BN-BUNDLE-0415").name
		self.assertEqual(self._block(self._session(episode)).code, "AUDIT_EPISODE_INVALID")

	def test_closed_episode_before_audit_day_rejected(self):
		episode = _episode(
			self.ward,
			inserted_on=add_days(today(), -5),
			removed_on=add_days(today(), -2),
			code="BN-BUNDLE-0416",
		).name
		self.assertEqual(self._block(self._session(episode)).code, "AUDIT_EPISODE_INVALID")

	def test_non_bundle_template_rejects_episode(self):
		template = af.make_template(f"T-PNC-{frappe.generate_hash(length=6)}").name
		episode = _episode(self.ward, code="BN-BUNDLE-0417").name
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": template,
				"department": self.ward,
				"observer": self.observer,
				"device_episode": episode,
			}
		)
		self.assertEqual(self._block(doc).code, "AUDIT_EPISODE_INVALID")
