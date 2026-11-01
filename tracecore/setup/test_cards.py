"""Bộ tài khoản và thẻ test theo vai trò (#1829). Script tay, không gắn vào migrate, không chạy trên site đang vận hành.

    bench --site <site> execute tracecore.setup.test_cards.create_test_cards

Mỗi thẻ một vai trò với năng lực khác nhau để kiểm phân quyền; R09 không có trạm theo NAV-04 nên không có năng lực trạm,
chỉ đăng nhập Desk. Chạy lại không đổi thẻ, PIN, mật khẩu đã cấp (đọc lại từ file). PIN và mật khẩu ngẫu nhiên chỉ ghi vào
file riêng tư (quyền 600, ngoài thư mục công khai), không in ra màn hình; không commit file này.
Site không phải developer/test phải truyền `allow_production=1`, tức người chạy xác nhận đây là site test.
"""

import json
import os
import secrets

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, today
from frappe.utils.password import update_password

from tracecore.core import station_auth, zones

DEFAULT_FILE = "tc_test_cards.json"
EMAIL_DOMAIN = "tracecore.test"
PASSWORD_BYTES = 12
# (role, tên hiển thị, chức năng trạm được giao)
SPECS = (
	("TC R03", "KTV khu bẩn", ("RECEIVE", "WASH_LOAD", "WASH_UNLOAD")),
	("TC R04", "KTV khu sạch", ("ASSEMBLE", "PACK")),
	("TC R05", "KTV tiệt khuẩn", ("STERI_LOAD", "STERI_UNLOAD")),
	("TC R06", "KTV kho vô khuẩn", ("PUTAWAY", "ISSUE")),
	("TC R08", "Điều dưỡng khoa", ("USE",)),
	(
		"TC R02",
		"Giám sát CSSD",
		("RECEIVE", "WASH_LOAD", "ASSEMBLE", "PACK", "STERI_LOAD", "STERI_UNLOAD", "PUTAWAY", "ISSUE"),
	),
	("TC R09", "Kho vật tư", ()),
)


def _is_test_site():
	return bool(frappe.conf.get("developer_mode") or frappe.conf.get("allow_tests") or frappe.flags.in_test)


def _require_test_site(allow_production):
	if not _is_test_site() and not allow_production:
		frappe.throw(
			_("Test cards can only be created on a developer or test site, or with allow_production=1.")
		)


def _resolve_path(out_path):
	path = os.path.abspath(out_path or frappe.get_site_path("private", DEFAULT_FILE))
	public = os.path.abspath(frappe.get_site_path("public"))
	private_files = os.path.abspath(frappe.get_site_path("private", "files"))
	if path.startswith((public + os.sep, private_files + os.sep)):
		frappe.throw(_("The test card file must not be stored under the site files."))
	return path


def _read(path):
	if not os.path.exists(path):
		return {}
	with open(path, encoding="utf8") as handle:
		return {row["role"]: row for row in json.load(handle)}


def _write(path, rows):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(descriptor, "w", encoding="utf8") as handle:
		json.dump(rows, handle, ensure_ascii=False, indent=1)
	os.chmod(path, 0o600)


def _pin():
	return f"{secrets.randbelow(1000000):06d}"


def _ensure_user(email, role, full_name, password):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": full_name,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		update_password(email, password)
	if role not in frappe.get_roles(email):
		user.add_roles(role)
	return user


def _ward():
	"""Khoa của thẻ điều dưỡng: khoa lâm sàng đầu tiên; site chưa có khoa thì để trống, báo trong file."""
	return frappe.db.get_value("Department", {"tc_is_ward": 1, "is_group": 0, "disabled": 0}, "name")


def _ensure_employee(email, full_name, role, card):
	name = frappe.db.get_value("Employee", {"user_id": email}, "name")
	if name:
		employee = frappe.get_doc("Employee", name)
	else:
		company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
		if not company:
			frappe.throw(_("Complete company setup before creating test cards."))
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": full_name,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": company,
				"user_id": email,
			}
		)
	employee.status = "Active"
	employee.tc_card_enabled = 1
	employee.tc_card_id = card
	if role == "TC R08" and not employee.department:
		employee.department = _ward()
	employee.save(ignore_permissions=True)
	return employee


def _stations(functions):
	return list(
		dict.fromkeys(station for function in functions for station in zones.stations_with_function(function))
	)


def _ensure_competency(employee, station):
	name = frappe.db.get_value("Station Competency", {"employee": employee, "station": station}, "name")
	doc = (
		frappe.get_doc("Station Competency", name)
		if name
		else frappe.get_doc({"doctype": "Station Competency", "employee": employee, "station": station})
	)
	now = now_datetime()
	doc.update({"valid_from": add_days(now, -1), "valid_until": add_days(now, 365), "is_active": 1})
	doc.save(ignore_permissions=True)


def create_test_cards(out_path=None, allow_production=False):
	"""Tạo hoặc giữ nguyên bộ thẻ test; trả ``{"path", "count"}``, không có PIN, mật khẩu."""
	_require_test_site(frappe.utils.cint(allow_production))
	path = _resolve_path(out_path)
	known = _read(path)
	rows = []
	for role, full_name, functions in SPECS:
		code = role.split()[-1].lower()
		old = known.get(role) or {}
		email = old.get("account") or f"test-{code}@{EMAIL_DOMAIN}"
		card = old.get("card") or station_auth.normalize_card_id(f"TEST-{code}-{secrets.token_hex(6)}")
		pin = old.get("pin") or _pin()
		password = old.get("password") or secrets.token_urlsafe(PASSWORD_BYTES)
		_ensure_user(email, role, full_name, password)
		employee = _ensure_employee(email, full_name, role, card)
		station_auth.set_pin(employee.name, pin)
		frappe.db.set_value("Employee", employee.name, "tc_pin_reset_required", 0)
		stations = _stations(functions)
		for station in stations:
			_ensure_competency(employee.name, station)
		rows.append(
			{
				"role": role,
				"name": full_name,
				"account": email,
				"password": password,
				"card": card,
				"pin": pin,
				"stations": stations,
				"department": employee.department,
			}
		)
	_write(path, rows)
	return {"path": path, "count": len(rows)}
