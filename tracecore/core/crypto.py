"""Băm mã bệnh nhân để tra cứu mà không giải mã (FEAT-028, FR-M2-19, NFR-SEC-02, architecture §8 mã BN).

``patient_hash`` = HMAC-SHA256 của mã đã chuẩn hóa (bỏ khoảng trắng hai đầu, viết hoa). Khóa là
``tc_patient_hash_key`` trong site_config; site chưa đặt khóa riêng thì dùng ``encryption_key`` của site (cùng khóa
Frappe mã hóa trường Password). Đổi khóa thì phải chạy lại patch điền hash. Chỉ khớp chính xác, không tìm gần đúng.
"""

import hashlib
import hmac

import frappe
from frappe.utils.password import get_decrypted_password, get_encryption_key, set_encrypted_password


def _key():
	return (frappe.conf.get("tc_patient_hash_key") or get_encryption_key()).encode()


def normalise_patient_code(code):
	return (code or "").strip().upper()


def patient_hash(code):
	"""Hash 64 ký tự hex của mã bệnh nhân; mã trống → None."""
	text = normalise_patient_code(code)
	if not text:
		return None
	return hmac.new(_key(), text.encode(), hashlib.sha256).hexdigest()


# --- Mã bệnh nhân trong hàng đợi offline của PDA (FEAT-009, A-40 D2) ------------------------------------------
# PDA mã hóa mã BN bằng public key RSA-OAEP (SHA-256) của site trước khi lưu IndexedDB; chỉ server có private key
# (bảng mã hóa ``__Auth`` của Frappe, như trường Password). Khóa sinh một lần, không xoay vòng: gói chờ đồng bộ đã
# mã hóa bằng khóa cũ sẽ không giải được nếu đổi.

SETTINGS = "TraceCore Settings"
PATIENT_KEY_FIELD = "tc_patient_offline_key"
_KEY_LOCK = "tc_patient_offline_key"


def _stored_private_pem():
	return get_decrypted_password(SETTINGS, SETTINGS, PATIENT_KEY_FIELD, raise_exception=False)


def _private_key():
	from cryptography.hazmat.primitives import serialization
	from cryptography.hazmat.primitives.asymmetric import rsa

	pem = _stored_private_pem()
	if not pem:
		# khóa tên trong MariaDB: hai request đầu tiên không sinh hai khóa khác nhau
		frappe.db.sql("select get_lock(%s, 10)", _KEY_LOCK)
		try:
			pem = _stored_private_pem()
			if not pem:
				key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
				pem = key.private_bytes(
					serialization.Encoding.PEM,
					serialization.PrivateFormat.PKCS8,
					serialization.NoEncryption(),
				).decode()
				set_encrypted_password(SETTINGS, SETTINGS, pem, PATIENT_KEY_FIELD)
		finally:
			frappe.db.sql("select release_lock(%s)", _KEY_LOCK)
	return serialization.load_pem_private_key(pem.encode(), password=None)


def patient_public_key() -> str:
	"""Public key PEM (SubjectPublicKeyInfo) để PDA mã hóa mã BN khi offline; sinh cặp khóa nếu chưa có."""
	from cryptography.hazmat.primitives import serialization

	return (
		_private_key()
		.public_key()
		.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
		.decode()
	)
