"""E2E smoke cho kiosk /app/station (Playwright for Python, ADR-012).

Chuẩn bị site trước bằng ``scripts/e2e_prepare.sh <site>``; biến môi trường:
TC_BASE_URL, TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID, TC_E2E_STATION (smoke FEAT-001, trạm tra cứu chung TR-090 không gán bước)
và TC_E2E_T4_* (test_station_t4.py; xem scripts/e2e_prepare.sh), TC_E2E_CODES_* (test_desk_codes.py),
TC_E2E_INSTR_* (test_desk_instrument.py), TC_E2E_INV_* (test_desk_inventory.py),
TC_E2E_SETTYPE_* (test_desk_set_type.py), TC_E2E_T6_* (test_station_t6.py), TC_E2E_T1_* (test_station_t1.py),
TC_E2E_T3_* (test_station_t3.py).

TC_BASE_URL chọn site (mặc định http://127.0.0.1:8000); bench khác đang giữ cổng đó thì phục vụ site dev ở cổng khác
(vd ``bench serve --port 8101``) và đặt TC_BASE_URL=http://127.0.0.1:8101.
"""

import os
import socket
import threading
import time

import pytest

BASE_URL = os.environ.get("TC_BASE_URL", "http://127.0.0.1:8000")
KIOSK_VIEWPORT = {"width": 1366, "height": 768}


def require_env(name):
	value = os.environ.get(name)
	if not value:
		pytest.skip(f"{name} is not set - run scripts/e2e_prepare.sh first")
	return value


def desk_login(page, prefix="TC_E2E"):
	"""Complete the native password + OTP challenge when enabled; never bypass 2FA."""
	user, password = require_env(prefix + "_USER"), require_env(prefix + "_PASSWORD")
	response = page.request.post("/api/method/login", form={"usr": user, "pwd": password})
	assert response.ok, response.text()
	challenge = response.json()
	if challenge.get("tmp_id"):
		import pyotp

		totp = pyotp.TOTP(require_env(prefix + "_OTP_SECRET"))
		# Native Frappe verifies only the current 30-second window. A code generated near the
		# boundary can arrive after it rolled, so retry a bounded number of times with a fresh
		# code, and only for a rejected verification code; other failures remain failures.
		for _ in range(3):
			response = page.request.post(
				"/api/method/login",
				form={"usr": user, "pwd": password, "tmp_id": challenge["tmp_id"], "otp": totp.now()},
			)
			if response.ok or response.status != 401 or "Incorrect Verification code" not in response.text():
				break
			time.sleep(1.5)
		assert response.ok, response.text()
	logged_in = page.request.get("/api/method/frappe.auth.get_logged_user")
	assert logged_in.ok and logged_in.json().get("message") == user


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
	return {**browser_context_args, "viewport": KIOSK_VIEWPORT, "base_url": BASE_URL}


@pytest.fixture
def logged_in_page(page):
	desk_login(page)
	return page


@pytest.fixture
def station_page(logged_in_page):
	station = os.environ.get("TC_E2E_STATION", "TR-090")
	card = require_env("TC_E2E_CARD_ID")
	logged_in_page.goto(f"/app/station?station={station}")
	logged_in_page.locator("#tc-card-input").fill(card)
	logged_in_page.locator("#tc-card-input").press("Enter")
	logged_in_page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return logged_in_page


@pytest.fixture
def set_id():
	return require_env("TC_E2E_SET_ID")


# --- T4 (SCR-08 đóng gói): user trạm TR-004 và dữ liệu demo `devdata.ensure_t4_demo` ---


@pytest.fixture
def t4_demo():
	"""Mã demo T4 từ scripts/e2e_prepare.sh (TC_E2E_T4_SET_STEAM, ...)."""
	keys = (
		"set_steam",
		"set_maint",
		"set_plasma",
		"set_gate_fail",
		"ci_steam",
		"ci_plasma",
		"roll_steam",
		"roll_plasma",
	)
	return {key: require_env(f"TC_E2E_T4_{key.upper()}") for key in keys}


@pytest.fixture
def t4_page(page):
	card = require_env("TC_E2E_T4_CARD_ID")
	desk_login(page, "TC_E2E_T4")
	station = os.environ.get("TC_E2E_T4_STATION", "TR-004")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return page


# --- T2 (SCR-06 lô rửa, FEAT-021): user trạm TR-002 và dữ liệu demo `devdata.ensure_t2_demo` ---

T2_KEYS = (
	"machine",
	"machine_two_door",
	"machine_locked",
	"machine_connected",
	"program",
	"sets",
	"set_no_t1",
	"set_redo",
	"chemical_lot_ok",
	"chemical_lot_expired",
	"batch_running",
)


@pytest.fixture
def t2_demo():
	"""Mã demo T2 từ scripts/e2e_prepare.sh (TC_E2E_T2_MACHINE, ...); ``sets`` là danh sách 3 Set ID."""
	demo = {key: require_env(f"TC_E2E_T2_{key.upper()}") for key in T2_KEYS}
	demo["sets"] = demo["sets"].split(",")
	return demo


@pytest.fixture
def t2_page(page):
	card = require_env("TC_E2E_T2_CARD_ID")
	desk_login(page, "TC_E2E_T2")
	station = os.environ.get("TC_E2E_T2_STATION", "TR-002")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result[data-state='empty'] .tc-t2").wait_for(timeout=30000)
	return page


# --- Desk cấu hình (SCR-33, FEAT-002): user TC R10, viewport WEB 1366x768 ---


@pytest.fixture
def r10_page(page):
	desk_login(page, "TC_E2E_R10")
	return page


# --- In nhãn QR đối tượng (SCR-33, FEAT-005): user TC R10 + Stock User, máy in mạng demo, socket TCP giả ---


@pytest.fixture
def codes_demo():
	"""Mã demo của `devdata.ensure_codes_demo` (TC_E2E_CODES_EQUIPMENT, ..._PRINTER, ..._PRINTER_PORT...)."""
	keys = ("equipment", "equipment_2", "retired", "printer", "printer_port", "label_item")
	return {key: require_env(f"TC_E2E_CODES_{key.upper()}") for key in keys}


@pytest.fixture
def codes_page(page):
	"""User R10 cấp mã cuộn và in nhãn: TC R10 + Stock User (R10 không đọc được Item của ERPNext)."""
	desk_login(page, "TC_E2E_CODES")
	return page


class FakePrinter:
	"""Máy in ZPL giả: socket TCP trên 127.0.0.1:<cổng của máy in demo>, ghi lại mỗi kết nối là một nhãn.

	Worker của bench (đường server, `core.print_server`) mở kết nối, gửi ZPL rồi đóng; mỗi payload là một lệnh in.
	"""

	def __init__(self, port):
		self.payloads = []
		self._cond = threading.Condition()
		self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self._server.bind(("127.0.0.1", port))
		self._server.listen(16)
		self._server.settimeout(0.2)
		self._stopped = threading.Event()
		self._thread = threading.Thread(target=self._serve, daemon=True)
		self._thread.start()

	def _serve(self):
		while not self._stopped.is_set():
			try:
				conn, _addr = self._server.accept()
			except OSError:
				continue
			with conn:
				conn.settimeout(10)
				chunks = []
				try:
					while chunk := conn.recv(65536):
						chunks.append(chunk)
				except OSError:
					pass
			with self._cond:
				self.payloads.append(b"".join(chunks).decode("utf-8", "replace"))
				self._cond.notify_all()

	def labels_for(self, code):
		"""Các ZPL đã nhận có QR mã `code` (payload `^FDMA,<code>^FS`)."""
		with self._cond:
			return [zpl for zpl in self.payloads if f"^FDMA,{code}^FS" in zpl]

	def wait_for(self, codes, timeout=60):
		"""Chờ (không ngủ cố định) tới khi mỗi mã trong `codes` có ít nhất một nhãn; trả {mã: [ZPL]}."""
		with self._cond:
			self._cond.wait_for(
				lambda: all(any(f"^FDMA,{code}^FS" in zpl for zpl in self.payloads) for code in codes),
				timeout=timeout,
			)
		received = {code: self.labels_for(code) for code in codes}
		missing = [code for code, labels in received.items() if not labels]
		assert not missing, f"fake printer got no label for {missing}; payloads: {len(self.payloads)}"
		return received

	def close(self):
		self._stopped.set()
		self._thread.join(timeout=5)
		self._server.close()


@pytest.fixture
def fake_printer():
	printer = FakePrinter(int(require_env("TC_E2E_CODES_PRINTER_PORT")))
	yield printer
	printer.close()


# --- Danh mục dụng cụ Desk (SCR-01, FEAT-014): user TC R02, dữ liệu `devdata.ensure_instrument_demo` ---

INSTR_KEYS = (
	"group",
	"full",
	"no_max",
	"retire",
	"giai",
	"set_type_steam",
	"set_type_plasma",
	"set_type_retire",
	"set_steam",
	"set_plasma",
)


@pytest.fixture
def instr_demo():
	"""Mã demo của `devdata.ensure_instrument_demo` (TC_E2E_INSTR_FULL, ..._SET_STEAM...)."""
	return {key: require_env(f"TC_E2E_INSTR_{key.upper()}") for key in INSTR_KEYS}


@pytest.fixture
def instr_page(page):
	"""User Desk TC R02 (khai báo và sửa danh mục dụng cụ)."""
	desk_login(page, "TC_E2E_INSTR")
	return page


@pytest.fixture
def other_user_page(browser, browser_context_args):
	"""Mở thêm trang của user khác trong cùng test (vd trạm T4 song song với Desk): `other_user_page(user_env, pwd_env)`.

	Mỗi trang một context riêng (cookie phiên riêng); đóng khi test xong.
	"""
	contexts = []

	def open_page(user_env, password_env):
		context = browser.new_context(**browser_context_args)
		contexts.append(context)
		page = context.new_page()
		assert user_env.endswith("_USER") and password_env == user_env[: -len("_USER")] + "_PASSWORD"
		desk_login(page, user_env[: -len("_USER")])
		return page

	yield open_page
	for context in contexts:
		context.close()


# --- Vật tư tiêu hao và nhập kho Desk (SCR-24, FEAT-041): user TC R09, dữ liệu `devdata.ensure_inventory_demo` ---

INV_KEYS = ("company", "warehouse", "supplier", "ci", "bi", "pk", "ch")


@pytest.fixture
def inv_demo():
	"""Mã demo của `devdata.ensure_inventory_demo` (TC_E2E_INV_CI, ..._WAREHOUSE...)."""
	return {key: require_env(f"TC_E2E_INV_{key.upper()}") for key in INV_KEYS}


@pytest.fixture
def inv_page(page):
	"""User Desk TC R09 (nhập kho vật tư, khai báo vật tư)."""
	desk_login(page, "TC_E2E_INV")
	return page


# --- Loại bộ và BOM theo phiên bản Desk (SCR-02, FEAT-015): user TC R02, dữ liệu `devdata.ensure_set_type_demo` ---

SETTYPE_KEYS = (
	"set_type",
	"set_type_inflight",
	"set_type_edit",
	"effective_version",
	"scheduled_version",
	"set_inflight",
	"inflight_version",
	"inflight_effective",
	"pack_short",
	"pack_long",
	"pack_none",
	"pack_r10",
	"steam_1",
	"steam_2",
	"steam_3",
	"plasma",
	"retired",
	"department",
)


@pytest.fixture
def settype_demo():
	"""Mã demo của `devdata.ensure_set_type_demo` (TC_E2E_SETTYPE_SET_TYPE, ..._PLASMA...)."""
	return {key: require_env(f"TC_E2E_SETTYPE_{key.upper()}") for key in SETTYPE_KEYS}


@pytest.fixture
def settype_page(page):
	"""User Desk TC R02 (khai báo loại bộ, sửa BOM, ảnh bộ, phiếu kiểm đếm); hoàn tất OTP như các user Desk khác."""
	desk_login(page, "TC_E2E_SETTYPE")
	return page


# --- T6 (SCR-11 kho vô khuẩn, FEAT-025): user trạm TR-006 và dữ liệu demo `devdata.ensure_t6_demo` ---

T6_KEYS = ("location", "location_2", "pack_released", "pack_not_released", "pack_stored", "pack_expiring")


@pytest.fixture
def t6_demo():
	"""Mã demo T6 từ scripts/e2e_prepare.sh (TC_E2E_T6_LOCATION, ..._PACK_RELEASED...)."""
	return {key: require_env(f"TC_E2E_T6_{key.upper()}") for key in T6_KEYS}


@pytest.fixture
def t6_page(page):
	card = require_env("TC_E2E_T6_CARD_ID")
	desk_login(page, "TC_E2E_T6")
	station = os.environ.get("TC_E2E_T6_STATION", "TR-006")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result .tc-t6").wait_for(timeout=30000)  # tồn kho đã tải xong (overview)
	return page


# --- T3 (SCR-07 kiểm đếm lắp ráp, FEAT-020): user trạm TR-003, R02 có thẻ + PIN và dữ liệu `devdata.ensure_t3_demo` ---

T3_KEYS = ("set_full", "set_short", "set_branch", "set_no_wash", "short_instrument")


@pytest.fixture
def t3_demo():
	"""Mã demo T3 từ scripts/e2e_prepare.sh (TC_E2E_T3_SET_FULL, ...)."""
	return {key: require_env(f"TC_E2E_T3_{key.upper()}") for key in T3_KEYS}


@pytest.fixture
def t3_r02():
	"""Thẻ và PIN 6 số (ngẫu nhiên mỗi lần chuẩn bị) của R02 tại trạm T3."""
	return {"card": require_env("TC_E2E_T3_R02_CARD_ID"), "pin": require_env("TC_E2E_T3_R02_PIN")}


@pytest.fixture
def t3_page(page):
	card = require_env("TC_E2E_T3_CARD_ID")
	desk_login(page, "TC_E2E_T3")
	station = os.environ.get("TC_E2E_T3_STATION", "TR-003")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result[data-state='empty'] .tc-t3").wait_for(timeout=30000)
	return page


# --- T1 (SCR-05 tiếp nhận, SCR-34 PDA, FEAT-019): user trạm TR-001 và dữ liệu demo `devdata.ensure_t1_demo` ---

T1_KEYS = (
	"department",
	"deliverer_card",
	"deliverer_name",
	"sets",
	"set_new",
	"sets_pda",
	"set_sterile",
	"set_unknown",
)
PDA_VIEWPORT = {"width": 412, "height": 915}


@pytest.fixture
def t1_demo():
	"""Mã demo T1 từ scripts/e2e_prepare.sh (TC_E2E_T1_DELIVERER_CARD, ...); ``sets`` và ``sets_pda`` là danh sách."""
	demo = {key: require_env(f"TC_E2E_T1_{key.upper()}") for key in T1_KEYS}
	demo["sets"] = demo["sets"].split(",")
	demo["sets_pda"] = demo["sets_pda"].split(",")
	return demo


def _open_t1(page):
	card = require_env("TC_E2E_T1_CARD_ID")
	desk_login(page, "TC_E2E_T1")
	station = os.environ.get("TC_E2E_T1_STATION", "TR-001")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result .tc-t1").wait_for(timeout=30000)
	if page.locator(".tc-t1-head").count():
		# phiếu nháp của test trước được tiếp tục sau khi đăng nhập lại (đúng nghiệp vụ): bỏ để test bắt đầu sạch
		page.locator("[data-action='discard']").click()
		page.locator("[data-action='discard']").click()  # lần hai là xác nhận bỏ phiếu
	page.locator(".tc-result[data-state='empty'] .tc-t1").wait_for(timeout=30000)
	return page


@pytest.fixture
def t1_page(page):
	return _open_t1(page)


@pytest.fixture
def t1_pda_page(page):
	"""Cùng màn T1 nhưng viewport PDA 412x915 (SCR-34)."""
	page.set_viewport_size(PDA_VIEWPORT)
	return _open_t1(page)
