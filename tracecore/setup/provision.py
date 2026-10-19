"""Tạo user kỹ thuật cho trạm (F-7): agent-<trạm>@… (TC Agent, API key) và station-<bước>@… (kiosk).

Chạy: ``bench --site <SITE> execute tracecore.setup.provision.agent_user --kwargs "{...}"``.
Secret không bao giờ in ra màn hình: ghi thẳng vào file cấu hình agent (quyền 600).
"""

import configparser
import os

import frappe
from frappe import _
from frappe.core.doctype.user.user import generate_keys
from frappe.utils.password import update_password

# Frappe không chấp nhận email "x@local" (thiếu dấu chấm ở domain)
USER_DOMAIN = "tracecore.local"
STATION_ROLE_BY_ZONE = {"Dirty": "TC R03", "Clean": "TC R04", "Sterile": "TC R06"}


def _station(station):
	row = frappe.db.get_value(
		"Zone Station", {"name": station, "is_zone": 0}, ["name", "station_step", "zone_type"], as_dict=True
	)
	if not row:
		frappe.throw(_("Station {0} does not exist.").format(station))
	return row


def _ensure_user(email, first_name, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles(*roles)
	return user.name


def _write_private(path, config):
	path = os.path.expanduser(path)
	os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
	fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(fd, "w") as handle:
		config.write(handle)
	os.chmod(path, 0o600)
	return path


def agent_user(station, config_path, server_url="http://127.0.0.1:8000"):
	"""User agent-<trạm> (role TC Agent) + API key/secret ghi vào INI của agent."""
	row = _station(station)
	user = _ensure_user(f"agent-{row.name.lower()}@{USER_DOMAIN}", f"Agent {row.name}", ["TC Agent"])
	keys = generate_keys(user)

	config = configparser.ConfigParser()
	config["server"] = {"url": server_url, "api_key": keys["api_key"], "api_secret": keys["api_secret"]}
	config["station"] = {"id": row.name}
	config["printer"] = {"host": "", "port": "9100"}
	config["agent"] = {
		"listen_host": "127.0.0.1",
		"listen_port": "8765",
		"output_dir": "~/.tracecore-agent/labels",
		"db_path": "~/.tracecore-agent/queue.sqlite3",
	}
	path = _write_private(config_path, config)
	print(f"Agent user {user}: config written to {path}")
	return user


def station_user(station, password):
	"""User station-<bước>@… cho kiosk (role theo khu của trạm)."""
	row = _station(station)
	role = STATION_ROLE_BY_ZONE.get(row.zone_type)
	if not role:
		frappe.throw(_("No station role is defined for zone type {0}.").format(row.zone_type))
	user = _ensure_user(
		f"station-{(row.station_step or row.name).lower()}@{USER_DOMAIN}", f"Station {row.station_step}", [role]
	)
	update_password(user, password)
	return user
