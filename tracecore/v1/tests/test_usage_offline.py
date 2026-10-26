"""T8 xác nhận sử dụng offline trên PDA rồi phát lại (FEAT-009 Task 5; UC-13 E3, NFR-SEC-02; A-40 D2)."""

import base64
import uuid
from datetime import datetime, timedelta

import frappe
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import crypto, sync
from tracecore.tests.utils import request_headers
from tracecore.v1 import usage as usage_api
from tracecore.v1.tests.test_usage_api import SESSION_TOKENS, STATION, TIME_ZONE, UsageApiCase

PATIENT = "BN-OFF-778899"


def encrypt(code):
	key = serialization.load_pem_public_key(crypto.patient_public_key().encode())
	cipher = key.encrypt(
		code.encode(),
		padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
	)
	return base64.b64encode(cipher).decode()


class TestUsageOffline(UsageApiCase):
	def replay(self, moment, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		args = {
			"cycle_id": self.pack.name,
			"station": STATION,
			"surgery_code": "CA-OFF-1",
			"client_ts": moment.replace(tzinfo=TIME_ZONE).isoformat(timespec="seconds"),
			"token": SESSION_TOKENS[self.nurse],
			**kwargs,
		}
		headers = {
			"X-Idempotency-Key": key or str(uuid.uuid4()),
			"X-TC-Station": STATION,
			sync.REPLAY_HEADER: "1",
		}
		with request_headers(headers):
			return usage_api.confirm(**args)

	def backdate_session(self, start):
		name = frappe.db.get_value("Station Session", {"user": self.nurse, "is_open": 1})
		frappe.db.set_value(
			"Station Session",
			name,
			{
				"started_at": start,
				"last_activity_at": start,
				"absolute_expires_at": add_to_date(start, hours=8),
			},
		)

	def test_usage_confirm_encrypted_patient_code(self):
		moment = add_to_date(now_datetime(), hours=-2).replace(microsecond=0)
		self.backdate_session(add_to_date(moment, hours=-1))
		result = self.replay(moment, patient_code_enc=encrypt(PATIENT))
		self.assertIs(result["ok"], True, result)
		record = frappe.get_doc("Usage Record", result["usage"])
		self.assertEqual(record.get_password("patient_code"), PATIENT)
		self.assertEqual(get_datetime(record.used_at), moment)  # thời điểm nghiệp vụ = client_ts (ADR-003)
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Used")

	def test_usage_enc_not_in_audit_or_error_log(self):
		enc = encrypt(PATIENT)
		errors = frappe.db.count("Error Log")
		self.replay(now_datetime().replace(microsecond=0), patient_code_enc=enc)
		self.replay(
			now_datetime().replace(microsecond=0), patient_code_enc=enc
		)  # lần 2: PACK_USED → conflict
		frappe.set_user("Administrator")
		for doctype, fields in (
			("Audit Log", ["old_value", "new_value", "reason"]),
			("Sync Conflict", ["client_state", "server_state"]),
			("Idempotency Key", ["response"]),
		):
			for row in frappe.get_all(doctype, fields=fields):
				text = frappe.as_json(row)
				self.assertNotIn(PATIENT, text, doctype)
				self.assertNotIn(enc, text, doctype)
		self.assertEqual(frappe.db.count("Error Log"), errors)

	def test_usage_enc_unreadable_is_rejected(self):
		key = str(uuid.uuid4())
		result = self.replay(now_datetime().replace(microsecond=0), key=key, patient_code_enc="bm90LXJzYQ==")
		self.assertEqual(result["error"]["code"], "PATIENT_CODE_UNREADABLE")
		self.assertEqual(result["error"]["http_status"], 422)
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Issued")

	def test_offline_usage_on_expiry_day_synced_next_day(self):
		# dùng lúc 23:50 ngày hết hạn, đồng bộ hôm sau: hợp lệ theo ngày của client_ts
		yesterday = now_datetime().date() - timedelta(days=1)
		moment = datetime.combine(yesterday, datetime.min.time()).replace(hour=23, minute=50)
		frappe.db.set_value("Pack", self.pack.name, "expiry", yesterday, update_modified=False)
		self.backdate_session(moment.replace(hour=20))
		result = self.replay(moment, patient_code_enc=encrypt(PATIENT))
		self.assertIs(result["ok"], True, result)
