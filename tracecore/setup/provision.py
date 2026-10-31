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

from tracecore.core import zones

# Frappe không chấp nhận email "x@local" (thiếu dấu chấm ở domain)
USER_DOMAIN = "tracecore.local"
# Role kiosk theo chức năng đầu tiên của trạm (A-64); quét sử dụng ở khu khoa (FEAT-027) do nhân viên khoa R08
STATION_ROLE_BY_FUNCTION = {
	"RECEIVE": "TC R03",
	"MANUAL_WASH": "TC R03",
	"WASH_LOAD": "TC R03",
	"WASH_UNLOAD": "TC R04",
	"ASSEMBLE": "TC R04",
	"PACK": "TC R04",
	"STERI_LOAD": "TC R04",
	"STERI_UNLOAD": "TC R06",
	"PUTAWAY": "TC R06",
	"ISSUE": "TC R06",
	"USE": "TC R08",
	"LINEN": "TC R07",
	"WASTE": "TC R07",
}


def agent_user_email(station):
	"""User kỹ thuật của agent một trạm — mỗi agent chỉ được thao tác cho đúng trạm này."""
	return f"agent-{station.lower()}@{USER_DOMAIN}"


def _station(station):
	row = frappe.db.get_value(
		"Zone Station", {"name": station, "is_zone": 0}, ["name", "station_no"], as_dict=True
	)
	if not row:
		frappe.throw(_("Station {0} does not exist.").format(station))
	return row


def _ensure_user(email, first_name, roles):
	from tracecore.core.account import require_r10

	require_r10()
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
	user = _ensure_user(agent_user_email(row.name), f"Agent {row.name}", ["TC Agent"])
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
	"""User station-t<số trạm>@… cho kiosk, trạm chưa đánh số dùng mã trạm (role theo chức năng của trạm)."""
	from tracecore.core.account import validate_password

	validate_password(password)
	row = _station(station)
	functions = zones.station_functions(row.name)
	role = STATION_ROLE_BY_FUNCTION.get(functions[0]) if functions else None
	if not role:
		frappe.throw(_("No station role is defined for station {0}.").format(row.name))
	label = f"t{row.station_no}" if row.station_no else row.name.lower()
	user = _ensure_user(f"station-{label}@{USER_DOMAIN}", f"Station {label.upper()}", [role])
	update_password(user, password)
	frappe.db.set_value("User", user, "last_password_reset_date", frappe.utils.today())
	return user


def desk_user(role, name, password):
	"""User Desk (System User) cho e2e cấu hình: <name>@tracecore.local với một role TC; idempotent."""
	from tracecore.core.account import validate_password

	validate_password(password)
	user = _ensure_user(f"{name}@{USER_DOMAIN}", name, [role])
	update_password(user, password)
	frappe.db.set_value("User", user, "last_password_reset_date", frappe.utils.today())
	return user
