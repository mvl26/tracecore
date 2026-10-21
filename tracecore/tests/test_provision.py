import configparser
import io
import os
import tempfile
from contextlib import redirect_stdout

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import check_password, get_decrypted_password

from tracecore.setup import provision


class TestProvision(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")

	def test_provision_agent_user_writes_config(self):
		path = os.path.join(tempfile.mkdtemp(), "agent.ini")
		out = io.StringIO()
		with redirect_stdout(out):
			user = provision.agent_user("TR-004", path, server_url="http://127.0.0.1:8000")
		self.assertEqual(user, "agent-tr-004@tracecore.local")
		self.assertIn("TC Agent", frappe.get_roles(user))

		config = configparser.ConfigParser()
		config.read(path)
		secret = get_decrypted_password("User", user, "api_secret")
		self.assertEqual(config["server"]["url"], "http://127.0.0.1:8000")
		self.assertEqual(config["server"]["api_key"], frappe.db.get_value("User", user, "api_key"))
		self.assertEqual(config["server"]["api_secret"], secret)
		self.assertEqual(config["station"]["id"], "TR-004")
		self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
		self.assertNotIn(secret, out.getvalue())

	def test_provision_station_user(self):
		user = provision.station_user("TR-004", password="Kiosk-Test-2026!")
		self.assertEqual(user, "station-t4@tracecore.local")
		self.assertIn("TC R04", frappe.get_roles(user))
		self.assertEqual(check_password(user, "Kiosk-Test-2026!"), user)

	def test_provision_desk_user_r10(self):
		user = provision.desk_user("TC R10", "r10-e2e", password="Desk-Test-2026!")
		self.assertEqual(user, "r10-e2e@tracecore.local")
		self.assertIn("TC R10", frappe.get_roles(user))
		self.assertEqual(frappe.db.get_value("User", user, "user_type"), "System User")
		self.assertEqual(check_password(user, "Desk-Test-2026!"), user)
		self.assertEqual(provision.desk_user("TC R10", "r10-e2e", password="Desk-Test-2026!"), user)

	def test_provision_rejects_zone(self):
		with self.assertRaises(frappe.ValidationError):
			provision.station_user("ZONE-CLEAN", password="x")
