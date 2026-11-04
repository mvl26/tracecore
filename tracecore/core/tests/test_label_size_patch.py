"""Patch đổi khổ nhãn chung sang 50 x 30 mm (A-116): chỉ site còn khổ mặc định cũ 60 x 40 hoặc trống."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.patches.v0_1 import a116_label_size_50x30

SETTINGS = "TraceCore Settings"


class TestLabelSizePatch(FrappeTestCase):
	def size(self):
		get = frappe.db.get_single_value
		return get(SETTINGS, "label_width_mm"), get(SETTINGS, "label_height_mm")

	def set_size(self, width, height):
		frappe.db.set_single_value(SETTINGS, {"label_width_mm": width, "label_height_mm": height})

	def test_old_default_moves_to_50_by_30(self):
		self.set_size(60, 40)
		a116_label_size_50x30.execute()
		self.assertEqual(self.size(), (50, 30))

	def test_empty_size_is_set(self):
		self.set_size(0, 0)
		a116_label_size_50x30.execute()
		self.assertEqual(self.size(), (50, 30))

	def test_custom_size_is_kept(self):
		self.set_size(100, 60)
		a116_label_size_50x30.execute()
		self.assertEqual(self.size(), (100, 60))
		self.set_size(60, 30)  # chỉ một chiều bằng mặc định cũ: người dùng đã chỉnh
		a116_label_size_50x30.execute()
		self.assertEqual(self.size(), (60, 30))

	def test_patch_is_idempotent(self):
		self.set_size(60, 40)
		a116_label_size_50x30.execute()
		a116_label_size_50x30.execute()
		self.assertEqual(self.size(), (50, 30))
