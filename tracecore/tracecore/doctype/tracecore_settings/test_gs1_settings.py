"""Nhóm GS1 của TraceCore Settings (A-76): định dạng prefix, số chỉ thị, bộ đếm chỉ đọc, khóa prefix đã dùng."""

from unittest.mock import patch

import frappe

from tracecore.core import code_registry, gs1
from tracecore.setup.gs1_settings import copy_site_config_prefix
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

SETTINGS = "TraceCore Settings"
SET_TYPE = "Instrument Set Type"


def save(**values):
	doc = frappe.get_single(SETTINGS)
	doc.update(values)
	doc.save()
	return doc


class TestGs1Settings(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")

	def test_fields(self):
		meta = frappe.get_meta(SETTINGS)
		self.assertEqual(meta.get_field("gs1_company_prefix").fieldtype, "Data")
		indicator = meta.get_field("gtin_indicator_digit")
		self.assertEqual(indicator.options.split("\n"), [str(n) for n in range(9)])
		self.assertEqual(indicator.default, "0")
		self.assertTrue(meta.get_field("gtin_next_item_ref").read_only)

	def test_prefix_must_be_7_to_11_digits(self):
		for bad in ("893000", "893000123456", "89300A1", "893 001"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				save(gs1_company_prefix=bad)
		for good in ("8930001", "89300012345"):
			frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")
			self.assertEqual(save(gs1_company_prefix=good).gs1_company_prefix, good)

	def test_demo_prefix_only_on_dev_sites(self):
		save(gs1_company_prefix="9529999")
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")
		production = {"developer_mode": 0, "allow_tests": 0}
		flags = frappe.flags.in_test
		frappe.flags.in_test = False
		self.addCleanup(setattr, frappe.flags, "in_test", flags)
		with patch.dict(frappe.conf, production):
			with self.assertRaises(frappe.ValidationError):
				save(gs1_company_prefix="9529999")

	def test_counter_comes_from_series_not_from_the_form(self):
		save(gs1_company_prefix="8930001")
		code_registry.next_gtin(SET_TYPE, "AA")
		# form cũ gửi lại số cũ: bộ đếm thật không đổi, ô hiển thị theo bộ đếm thật
		doc = save(gtin_next_item_ref="00001")
		self.assertEqual(doc.gtin_next_item_ref, "00002")
		self.assertEqual(code_registry.gtin_range()["next_ref"], 2)
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "BB"), gs1.make_gtin14("0", "8930001", 2))

	def test_onload_shows_counter(self):
		save(gs1_company_prefix="8930001")
		doc = frappe.get_single(SETTINGS)
		doc.run_method("onload")
		self.assertEqual(doc.gtin_next_item_ref, "00001")

	def test_real_prefix_locked_after_code_issued(self):
		save(gs1_company_prefix="8930001")
		save(gs1_company_prefix="8930002")  # chưa cấp mã nào: còn sửa được gõ nhầm
		code_registry.next_gtin(SET_TYPE, "AA")
		for other in ("8930003", ""):
			with self.assertRaises(frappe.ValidationError, msg=other):
				save(gs1_company_prefix=other)
		save(gs1_company_prefix="8930002")

	def test_real_prefix_locked_after_set_id_issued(self):
		save(gs1_company_prefix="8930001")
		code_registry.next_set_id("GS9")
		with self.assertRaises(frappe.ValidationError):
			save(gs1_company_prefix="8930002")

	def test_demo_prefix_may_be_replaced_after_use(self):
		save(gs1_company_prefix="9529999")
		code_registry.next_gtin(SET_TYPE, "AA")
		self.assertEqual(save(gs1_company_prefix="8930001").gs1_company_prefix, "8930001")

	def test_only_r10_writes(self):
		r02 = make_user("gs1-r02@example.com", ["TC R02"])
		r10 = make_user("gs1-r10@example.com", ["TC R10"])
		frappe.set_user(r02)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			save(gs1_company_prefix="8930001")
		frappe.set_user(r10)
		self.assertEqual(save(gs1_company_prefix="8930001").gs1_company_prefix, "8930001")

	def test_migrate_copies_real_site_config_prefix_once(self):
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930007"}):
			copy_site_config_prefix()
		self.assertEqual(gs1.declared_company_prefix(), "8930007")
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930008"}):
			copy_site_config_prefix()
		self.assertEqual(gs1.declared_company_prefix(), "8930007")

	def test_migrate_ignores_demo_and_invalid_site_config(self):
		for value in ("9520000", "12345", None):
			with patch.dict(frappe.conf, {"tc_gs1_company_prefix": value}):
				copy_site_config_prefix()
			self.assertEqual(gs1.declared_company_prefix(), "")
