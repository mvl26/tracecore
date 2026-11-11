"""Cài app trên site trắng (CI ``setup-bench``): vai trò TC có trước khi ``after_install`` tạo Notification Rule.

Frappe v15 chạy ``after_install`` trước ``sync_fixtures``; vai trò TC R11..R13 (A-113) chỉ có trong ``fixtures/role.json``
nên ``ensure_default_rules`` gặp LinkValidationError "Không thể tìm thấy Vai trò: TC R11" khi cài mới.
"""

import json
import os
import tempfile
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.setup import install

TEST_ROLE = "TC ZZ Install Test"


class TestInstallRoles(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Has Role", {"role": TEST_ROLE})
		frappe.db.delete("Role", {"name": TEST_ROLE})

	def _fixture(self, rows):
		handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
		json.dump(rows, handle)
		handle.close()
		self.addCleanup(os.remove, handle.name)
		return handle.name

	def test_ensure_roles_creates_missing_fixture_roles_with_their_flags(self):
		path = self._fixture(
			[
				{
					"doctype": "Role",
					"name": TEST_ROLE,
					"role_name": TEST_ROLE,
					"desk_access": 1,
					"two_factor_auth": 1,
					"disabled": 0,
				}
			]
		)
		self.assertFalse(frappe.db.exists("Role", TEST_ROLE))
		install.ensure_roles(path)
		role = frappe.db.get_value("Role", TEST_ROLE, ["desk_access", "two_factor_auth"], as_dict=True)
		self.assertEqual((role.desk_access, role.two_factor_auth), (1, 1))
		install.ensure_roles(path)  # chạy lại không lỗi, không tạo trùng
		self.assertEqual(frappe.db.count("Role", {"name": TEST_ROLE}), 1)

	def test_default_fixture_lists_every_ksnk_role(self):
		with open(install.ROLE_FIXTURE, encoding="utf-8") as handle:
			names = {row["name"] for row in json.load(handle)}
		self.assertTrue({f"TC R{n:02d}" for n in range(1, 14)} <= names)

	def test_after_install_creates_roles_before_anything_links_to_them(self):
		order = []
		steps = [name for name in dir(install) if name.startswith(("ensure_", "apply_"))]
		with patch.multiple(
			install,
			**{name: (lambda name=name: lambda *a, **k: order.append(name))() for name in steps},
		):
			install.after_install()
		self.assertEqual(order[0], "ensure_roles")
		self.assertLess(order.index("ensure_roles"), order.index("ensure_default_rules"))
		# site trắng không chạy migrate: Role Profile R11..R13 phải tạo ngay lúc cài (A-113 D4)
		self.assertIn("ensure_role_profiles", order)
		self.assertLess(order.index("ensure_roles"), order.index("ensure_role_profiles"))
