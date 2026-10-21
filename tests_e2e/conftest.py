"""E2E smoke cho kiosk /app/station (Playwright for Python, ADR-012).

Chuẩn bị site trước bằng ``scripts/e2e_prepare.sh <site>``; biến môi trường:
TC_BASE_URL, TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID, TC_E2E_STATION (smoke FEAT-001, trạm không phải T4)
và TC_E2E_T4_* (test_station_t4.py; xem scripts/e2e_prepare.sh), TC_E2E_CODES_* (test_desk_codes.py).
"""

import os
import socket
import threading

import pytest

BASE_URL = os.environ.get("TC_BASE_URL", "http://127.0.0.1:8000")
KIOSK_VIEWPORT = {"width": 1366, "height": 768}


def require_env(name):
	value = os.environ.get(name)
	if not value:
		pytest.skip(f"{name} is not set - run scripts/e2e_prepare.sh first")
	return value


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
	return {**browser_context_args, "viewport": KIOSK_VIEWPORT, "base_url": BASE_URL}


@pytest.fixture
def logged_in_page(page):
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_USER"), "pwd": require_env("TC_E2E_PASSWORD")},
	)
	assert response.ok, response.text()
	return page


@pytest.fixture
def station_page(logged_in_page):
	station = os.environ.get("TC_E2E_STATION", "TR-003")
	logged_in_page.goto(f"/app/station?station={station}")
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
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_T4_USER"), "pwd": require_env("TC_E2E_T4_PASSWORD")},
	)
	assert response.ok, response.text()
	station = os.environ.get("TC_E2E_T4_STATION", "TR-004")
	page.goto(f"/app/station?station={station}")
	page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return page


# --- Desk cấu hình (SCR-33, FEAT-002): user TC R10, viewport WEB 1366x768 ---


@pytest.fixture
def r10_page(page):
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_R10_USER"), "pwd": require_env("TC_E2E_R10_PASSWORD")},
	)
	assert response.ok, response.text()
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
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_CODES_USER"), "pwd": require_env("TC_E2E_CODES_PASSWORD")},
	)
	assert response.ok, response.text()
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
