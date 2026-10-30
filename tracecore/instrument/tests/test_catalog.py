"""Danh mục dụng cụ (FEAT-014 Task 1): chuẩn hóa mã, trùng mã + gợi ý mã kế tiếp, tập phương pháp (A-06 I2, I10)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.instrument import catalog
from tracecore.tests.factories import make_instrument

# Instrument liên kết Item (ERPNext); site CI chưa chạy Setup Wizard (dữ liệu tạo qua factories)
test_ignore = ["Item", "User", "Batch"]

FULL_WIDTH_KC = chr(0xFF2B) + chr(0xFF23)  # "KC" full-width (Review Focus 1)


def _doc(code, **kwargs):
	return frappe.get_doc(
		{
			"doctype": "Instrument",
			"instrument_code": code,
			"instrument_name": "Catalog test instrument",
			"spaulding_class": "Critical",
			"compatible_methods": [{"method": "Steam 134"}],
			**kwargs,
		}
	)


class _Everything(set):
	"""Tập 'chứa mọi mã': giả lập không còn mã trống trong giới hạn thử."""

	def __contains__(self, item):
		return True


class TestCatalog(FrappeTestCase):
	def test_code_normalization_nfkc_case_space(self):
		# Review Focus 1: khoảng trắng, chữ thường, full-width, tab đều về cùng một mã
		for raw in (" kc-01 ", FULL_WIDTH_KC + "-01", "KC-01\t", "kc-01"):
			self.assertEqual(catalog.normalize_code(raw), "KC-01", msg=repr(raw))
		for bad in ("KC 01", "KĐ-01", "K" * 41, "", "   ", "KC_01", "KC/01", None):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad)):
				catalog.normalize_code(bad)
		self.assertEqual(catalog.normalize_code("K" * 40), "K" * 40)

		doc = _doc(FULL_WIDTH_KC + "-NF1").insert()
		self.assertEqual(doc.name, "KC-NF1")
		with self.assertRaises(frappe.DuplicateEntryError):
			_doc(" kc-nf1\t").insert()
		self.assertEqual(frappe.db.count("Instrument", {"name": ["like", "KC-NF1%"]}), 1)

	def test_duplicate_code_suggests_next_free_code(self):
		make_instrument("KC-012")
		make_instrument("KC-013")
		with self.assertRaises(frappe.DuplicateEntryError) as raised:
			_doc("kc-012").insert()
		self.assertIn("KC-012", str(raised.exception))
		self.assertIn("KC-014", str(raised.exception))
		self.assertFalse(frappe.db.exists("Instrument", "KC-014"))

		# mã của dụng cụ đã Ngừng sử dụng vẫn bị chặn (không cấp lại)
		retired = make_instrument("KC-RET")
		retired.db_set("status", "Retired")
		with self.assertRaises(frappe.DuplicateEntryError) as raised:
			_doc("KC-RET").insert()
		self.assertIn("KC-RET-01", str(raised.exception))

	def test_concurrent_insert_same_code_keeps_one_record(self):
		# hai request cùng mã: request thứ hai qua được bước kiểm tra trước khi request đầu ghi xong
		make_instrument("KC-RACE")
		with patch.object(catalog, "code_exists", return_value=False):
			with self.assertRaises(frappe.DuplicateEntryError) as raised:
				_doc("KC-RACE").insert()
		self.assertIn("KC-RACE-01", str(raised.exception))
		self.assertEqual(frappe.db.count("Instrument", {"name": "KC-RACE"}), 1)

	def test_suggest_code_rules(self):
		self.assertEqual(catalog.suggest_code("KC-099"), "KC-100")
		self.assertEqual(catalog.suggest_code("kc-9"), "KC-10")
		self.assertEqual(catalog.suggest_code("KELLYSG"), "KELLYSG-01")
		make_instrument("KELLYSG-01")
		make_instrument("KELLYSG-02")
		self.assertEqual(catalog.suggest_code("KELLYSG"), "KELLYSG-03")
		make_instrument("SG-0007")
		make_instrument("SG-0008")
		self.assertEqual(catalog.suggest_code("SG-0006"), "SG-0009")
		# gợi ý vượt 40 ký tự thì không hợp lệ: báo lỗi thay vì gợi ý mã không lưu được
		with self.assertRaises(frappe.ValidationError):
			catalog.suggest_code("K" * 40)
		with patch.object(catalog, "_codes_with_prefix", return_value=_Everything()):
			with self.assertRaises(frappe.ValidationError) as raised:
				catalog.suggest_code("KC-001")
		self.assertIn("1000", str(raised.exception))

	def test_method_set_and_families(self):
		self.assertEqual(catalog.METHODS, ("Steam 121", "Steam 134", "Plasma", "EO"))
		self.assertEqual(
			catalog.METHOD_FAMILY,
			{"Steam 121": "Steam", "Steam 134": "Steam", "Plasma": "Plasma", "EO": "EO"},
		)
		doc = _doc(
			"KC-MS1",
			compatible_methods=[{"method": "Plasma"}, {"method": "Steam 121"}, {"method": "Steam 134"}],
		)
		self.assertEqual(catalog.method_set(doc), frozenset({"Plasma", "Steam 121", "Steam 134"}))
		self.assertEqual(catalog.method_set(doc.compatible_methods), catalog.method_set(doc))
		self.assertEqual(catalog.method_set([{"method": "EO"}, {"method": ""}]), frozenset({"EO"}))
		self.assertEqual(catalog.method_set([]), frozenset())
		self.assertEqual(
			catalog.families(["Steam 121", "Steam 134", "Plasma"]), frozenset({"Steam", "Plasma"})
		)
		self.assertEqual(catalog.families([]), frozenset())
