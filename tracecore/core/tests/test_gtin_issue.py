"""Cấp GTIN-14 từ mã doanh nghiệp GS1 (A-76): công thức, bộ đếm theo prefix, không trùng, không cấp lại, nguồn prefix."""

import threading
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1
from tracecore.core.notification import ensure_default_rules
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

SETTINGS = "TraceCore Settings"
PREFIX = "8930001"
SET_TYPE = "Instrument Set Type"


def declare(prefix=PREFIX, indicator="0"):
	frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", prefix)
	frappe.db.set_single_value(SETTINGS, "gtin_indicator_digit", indicator)


class TestMakeGtin14(FrappeTestCase):
	def test_known_gs1_sample(self):
		# mã mẫu đã biết: 0 + 0012345 + 60001, số kiểm tra 2
		self.assertEqual(gs1.make_gtin14("0", "0012345", 60001), "00012345600012")

	def test_reference_is_left_padded_to_fill_twelve_digits(self):
		for prefix, ref, body in (
			("8930001", 7, "0893000100007"),
			("893000123", 7, "0893000123007"),
			("89300012345", 7, "0893000123457"),
		):
			gtin = gs1.make_gtin14("0", prefix, ref)
			self.assertEqual(gtin[:13], body)
			self.assertTrue(gs1.is_valid_gtin14(gtin), msg=gtin)

	def test_indicator_is_first_digit(self):
		self.assertEqual(gs1.make_gtin14("3", PREFIX, 1)[0], "3")

	def test_rejects_bad_input(self):
		for args in (
			("9", PREFIX, 1),
			("0", "893000", 1),
			("0", "893000123456", 1),
			("0", "89300A1", 1),
			("0", PREFIX, 0),
			("0", PREFIX, 100000),
		):
			with self.assertRaises(gs1.GS1Error, msg=args):
				gs1.make_gtin14(*args)

	def test_capacity_by_prefix_length(self):
		self.assertEqual(gs1.gtin_ref_capacity("8930001"), 99999)
		self.assertEqual(gs1.gtin_ref_capacity("89300012345"), 9)

	def test_demo_gtin_recognized_with_any_indicator(self):
		# trên yhct mã thử có dạng 1952…: nhãn phải in dòng TEST
		self.assertTrue(gs1.is_test_gtin("19520000000056"))
		self.assertTrue(gs1.is_test_gtin("09520000000011"))
		self.assertFalse(gs1.is_test_gtin("18930000000000"))


class TestPrefixSource(IsolatedTestCase):
	def test_settings_win_over_site_config(self):
		declare("8931234")
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930000"}):
			self.assertEqual(gs1.configured_company_prefix(), "8931234")
			self.assertEqual(code_registry.company_prefix(), "8931234")

	def test_site_config_then_demo_when_not_declared(self):
		declare("")
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930000"}):
			self.assertEqual(gs1.configured_company_prefix(), "8930000")
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": None}):
			self.assertEqual(gs1.configured_company_prefix(), gs1.DEFAULT_COMPANY_PREFIX)

	def test_set_id_uses_declared_prefix(self):
		declare("8931234")
		self.assertTrue(code_registry.next_set_id("GT1").startswith("8931234GT1"))


class TestNextGtin(IsolatedTestCase):
	def test_not_declared_issues_nothing(self):
		declare("")
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": "8930000"}):
			self.assertIsNone(code_registry.next_gtin(SET_TYPE, "AA"))
			self.assertIsNone(code_registry.gtin_range())

	def test_issues_in_sequence_and_counter_moves_by_one(self):
		declare()
		self.assertEqual(code_registry.gtin_range()["next_ref"], 1)
		first = code_registry.next_gtin(SET_TYPE, "AA")
		self.assertEqual(first, gs1.make_gtin14("0", PREFIX, 1))
		self.assertEqual(code_registry.gtin_range()["next_ref"], 2)
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "BB"), gs1.make_gtin14("0", PREFIX, 2))

	def test_indicator_from_settings(self):
		declare(indicator="2")
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "AA")[0], "2")

	def test_skips_gtin_already_on_a_record(self):
		declare()
		from tracecore.tests.factories import make_set_type

		make_set_type("GTSKIP", gtin=gs1.make_gtin14("0", PREFIX, 1))
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "AA"), gs1.make_gtin14("0", PREFIX, 2))

	@bru("BRU-ID-001")
	def test_issued_gtin_is_in_the_registry_even_when_disabled(self):
		declare()
		gtin = code_registry.next_gtin(SET_TYPE, "AA")
		self.assertTrue(code_registry.is_issued(gtin))
		frappe.db.set_value("Code Registry", gtin, "status", "Disabled")
		# bộ đếm về lại cũng không cấp lại mã đã có trong sổ
		frappe.db.sql("update tabSeries set current=0 where name=%s", code_registry.gtin_series_key(PREFIX))
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "BB"), gs1.make_gtin14("0", PREFIX, 2))

	def test_each_prefix_has_its_own_counter(self):
		declare()
		code_registry.next_gtin(SET_TYPE, "AA")
		declare("8930002")
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "BB"), gs1.make_gtin14("0", "8930002", 1))
		declare()
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "CC"), gs1.make_gtin14("0", PREFIX, 2))

	def test_exhausted_range_raises(self):
		declare("89300012345")
		frappe.db.sql(
			"insert into tabSeries (name, current) values (%s, 9)",
			code_registry.gtin_series_key("89300012345"),
		)
		with self.assertRaises(code_registry.SeriesExhaustedError):
			code_registry.next_gtin(SET_TYPE, "AA")

	def test_peek_predicts_without_consuming(self):
		declare()
		self.assertEqual(
			code_registry.peek_gtins(SET_TYPE, 2),
			[gs1.make_gtin14("0", PREFIX, 1), gs1.make_gtin14("0", PREFIX, 2)],
		)
		self.assertEqual(code_registry.gtin_range()["next_ref"], 1)
		self.assertEqual(code_registry.next_gtin(SET_TYPE, "AA"), gs1.make_gtin14("0", PREFIX, 1))

	def test_low_flag_below_ten_percent(self):
		declare("893000123")  # dải 999 mã
		key = code_registry.gtin_series_key("893000123")
		frappe.db.sql("insert into tabSeries (name, current) values (%s, 899)", key)
		state = code_registry.gtin_range()
		self.assertEqual((state["capacity"], state["remaining"], state["low"]), (999, 100, False))
		frappe.db.sql("update tabSeries set current=900 where name=%s", key)
		self.assertTrue(code_registry.gtin_range()["low"])

	def test_notifies_r10_once_when_crossing_threshold(self):
		ensure_default_rules()
		r10 = make_user("gtin-low-r10@example.com", ["TC R10"])
		declare("893000123")
		key = code_registry.gtin_series_key("893000123")
		frappe.db.sql("insert into tabSeries (name, current) values (%s, 898)", key)
		event = {"event_code": "GTIN_RANGE_LOW", "recipient": r10}

		code_registry.next_gtin(SET_TYPE, "AA")  # còn 100: chưa dưới 10 %
		self.assertEqual(frappe.db.count("Notification Delivery", event), 0)
		code_registry.next_gtin(SET_TYPE, "BB")  # còn 99: vừa vượt ngưỡng
		first = frappe.db.count("Notification Delivery", event)
		self.assertGreaterEqual(first, 1)
		code_registry.next_gtin(SET_TYPE, "CC")  # còn 98: không báo lại
		self.assertEqual(frappe.db.count("Notification Delivery", event), first)


class TestConcurrentIssue(FrappeTestCase):
	"""Kết nối DB thật cho từng luồng, có commit: khóa dòng ``tabSeries`` phải giữ tới hết transaction."""

	PREFIX = "8939991"

	def _cleanup(self):
		frappe.db.rollback()
		frappe.db.delete("Code Registry", {"prefix": code_registry.gtin_series_key(self.PREFIX)})
		frappe.db.delete("Series", {"name": code_registry.gtin_series_key(self.PREFIX)})
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")
		frappe.db.commit()

	def test_existing_counter_row_gets_no_insert_before_the_lock(self):
		# INSERT IGNORE trùng khóa giữ shared lock tới commit; hai người cùng nâng lên FOR UPDATE thì deadlock
		self.addCleanup(self._cleanup)
		declare(self.PREFIX)
		code_registry._ensure_gtin_series(self.PREFIX)
		with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
			code_registry._ensure_gtin_series(self.PREFIX)
		statements = [str(call.args[0]).upper() for call in sql.call_args_list]
		self.assertFalse([sql_text for sql_text in statements if "INSERT" in sql_text], statements)

	def test_two_writers_never_get_the_same_gtin(self):
		self.addCleanup(self._cleanup)
		declare(self.PREFIX)
		frappe.db.commit()
		site, sites_path = frappe.local.site, frappe.local.sites_path
		results, errors = [], []
		barrier = threading.Barrier(2)

		def writer(tag):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				barrier.wait(timeout=10)
				for index in range(10):
					results.append(code_registry.next_gtin(SET_TYPE, f"{tag}{index}"))
					frappe.db.commit()
			except Exception as error:
				errors.append(error)
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=writer, args=(tag,)) for tag in "AB"]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(errors, [])
		self.assertEqual(len(results), 20)
		self.assertEqual(len(set(results)), 20)
		self.assertEqual(code_registry.gtin_range()["next_ref"], 21)
