"""BOM của loại bộ theo phiên bản (Set BOM Item, DT-SETBOM): đọc dòng BOM kèm tên và ảnh dụng cụ.

Đọc BOM cho trạm (FEAT-015 S11, architecture §8): ``payload`` cache Redis theo site (``frappe.cache`` thêm tiền tố
``db_name``) khóa ``tc_bom:<set_type>:<version>`` TTL ``CACHE_TTL``; ngày hiệu lực của các phiên bản (để tính
``status`` và phiên bản hiệu lực) cache ở ``tc_bom:<set_type>:dates``. Phiên bản bất biến nên nội dung một khóa chỉ đổi
khi tên/ảnh dụng cụ, tên/phương pháp/ảnh khay của loại bộ đổi: ``invalidate`` được gọi ở ``Instrument.on_update``,
``InstrumentSetType.on_update`` và khi ``bom_versions`` tạo loại bộ / phiên bản (xóa ngay và xóa lại sau commit).
"""

import hashlib
import json
from functools import partial

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import bom_versions, media

TRAY_FIELDS = ("tray_image", "tray_image_2", "tray_image_3")  # ảnh bộ đã xếp 1..3 (FEAT-015 S6)
TRAY_THUMBS = tuple(media.TARGETS[(media.SET_TYPE, field)].thumb_field for field in TRAY_FIELDS)
CACHE_TTL = 600  # giây (architecture §8)
CACHE_PREFIX = "tc_bom"
SET_TYPE = "Instrument Set Type"
# trường của loại bộ / dụng cụ nằm trong payload: đổi → xóa cache (InstrumentSetType/Instrument.on_update)
SET_TYPE_PAYLOAD_FIELDS = ("set_type_name", "method", *TRAY_FIELDS, *TRAY_THUMBS)
INSTRUMENT_PAYLOAD_FIELDS = ("instrument_name", "image", "image_thumbnail")


def lines(set_type, version):
	"""Các dòng BOM của `set_type` ở phiên bản `version`, sắp theo `position` (hòa thì theo `name`).

	Mỗi dòng là dict: ``instrument, instrument_name, image, thumbnail, qty, position`` (``thumbnail`` = URL ảnh
	thu nhỏ 320 px cho trạm, FR-M1-01.6; None khi chưa có).
	"""
	rows = frappe.get_all(
		"Set BOM Item",
		filters={"set_type": set_type, "bom_version": cint(version)},
		fields=["name", "instrument", "qty", "position"],
		order_by="position asc, name asc",
	)
	if not rows:
		return []
	instruments = {
		row.name: row
		for row in frappe.get_all(
			"Instrument",
			filters={"name": ["in", list({row.instrument for row in rows})]},
			fields=["name", "instrument_name", "image", "image_thumbnail"],
		)
	}
	return [
		{
			"instrument": row.instrument,
			"instrument_name": instruments[row.instrument].instrument_name,
			"image": instruments[row.instrument].image,
			"thumbnail": instruments[row.instrument].image_thumbnail or None,
			"qty": cint(row.qty),
			"position": cint(row.position),
		}
		for row in rows
	]


def pack_context(ctx):
	"""Hook ``tracecore_pack_context`` (FEAT-018 D9): BOM áp dụng của bộ và ảnh khay của loại bộ cho màn T4.

	Phiên bản = ``bom_versions.version_for_set_unit(ctx["set_unit"])``: bộ đang trong chu trình giữ phiên bản đã ghim
	khi tiếp nhận, kể cả khi có phiên bản mới hiệu lực giữa chu trình (FR-M1-04.1, FEAT-015 S3). Chỉ đọc, không ghi.
	Trả ``{"bom": [dòng của lines()], "bom_version": int, "tray_image": str | None, "tray_images": [str, …]}``
	(``tray_image`` = ảnh 1 như FEAT-018; ``tray_images`` = các ảnh 1..3 có giá trị theo thứ tự).
	Ngữ cảnh không có ``set_unit`` (chỉ loại bộ, vd xem trước) → ``set_type["current_bom_version"]`` như FEAT-018.
	"""
	set_type = ctx["set_type"]
	if ctx.get("set_unit"):
		version = cint(bom_versions.version_for_set_unit(ctx["set_unit"]))
	else:
		version = cint(set_type.get("current_bom_version"))
	images = frappe.db.get_value("Instrument Set Type", set_type["name"], TRAY_FIELDS, as_dict=True) or {}
	return {
		"bom": lines(set_type["name"], version),
		"bom_version": version,
		"tray_image": set_type.get("tray_image") or None,
		"tray_images": [images.get(field) for field in TRAY_FIELDS if images.get(field)],
	}


def receipt_context(ctx):
	"""Hook ``tracecore_receipt_context`` (FEAT-019, A-32): BOM áp dụng và ảnh khay tại ngày tiếp nhận cho màn T1.

	``ctx = {"set_unit", "set_type" (mã loại bộ), "on"}``; ``on`` là giờ hệ thống như hợp đồng của
	``bom_versions.pin_cycle_version`` (cùng phiên bản mà ``step_gate.start_cycle`` sẽ ghim lúc ghi sổ phiếu). Chỉ đọc.
	Trả ``{"bom_version": int, "bom": [dòng của payload()], "tray_images": [{position, image_url, thumbnail_url, etag}]}``;
	loại bộ chưa có dòng BOM nào → phiên bản 0, danh sách rỗng.
	"""
	version = bom_versions.pin_cycle_version(ctx)
	if not version:
		return {"bom_version": 0, "bom": [], "tray_images": []}
	data = payload(ctx["set_type"], version)
	return {"bom_version": data["bom_version"], "bom": data["lines"], "tray_images": data["tray_images"]}


# --- Đọc BOM cho trạm: payload, etag, cache (FEAT-015 S11) -------------------------------------------------------


def _key(set_type: str, suffix) -> str:
	# frappe.cache.make_key thêm tiền tố db_name của site: không lẫn giữa các site dùng chung Redis
	return f"{CACHE_PREFIX}:{set_type}:{suffix}"


def version_not_found_block(set_type, version=None) -> Block:
	return Block(
		"BOM_VERSION_NOT_FOUND",
		_("BOM version not found"),
		_("Set type {0} has no BOM version {1}.").format(set_type, version)
		if version is not None
		else _("Set type {0} has no effective BOM version.").format(set_type),
		_("Choose a BOM version from the version list, or ask R02 to save the BOM."),
	)


def _version_meta(set_type: str) -> dict[int, list]:
	"""``{phiên bản: [ngày hiệu lực ISO | None, ngày lưu ISO | None]}`` (cache ``dates`` cùng TTL, một truy vấn)."""
	key = _key(set_type, "dates")
	meta = frappe.cache.get_value(key, expires=True)
	# giá trị cache dạng cũ (chỉ ngày hiệu lực, trước khi có ngày lưu) → dựng lại
	if meta is None or any(not isinstance(value, list | tuple) for value in meta.values()):
		meta = {
			version: [
				None if day == bom_versions.NO_DATE else day.isoformat(),
				saved.isoformat() if saved else None,
			]
			for version, (day, saved) in bom_versions.dates_by_set_type([set_type], with_saved=True)
			.get(set_type, {})
			.items()
		}
		frappe.cache.set_value(key, meta, expires_in_sec=CACHE_TTL)
	return meta


def version_dates(set_type: str) -> dict[int, str | None]:
	"""``{phiên bản: ngày hiệu lực ISO | None}`` của mọi phiên bản BOM của loại bộ (cache cùng TTL, một truy vấn)."""
	return {version: values[0] for version, values in _version_meta(set_type).items()}


def _statuses(set_type: str) -> dict[int, str]:
	meta = _version_meta(set_type)
	return bom_versions.statuses_on(
		{version: getdate(day) if day else bom_versions.NO_DATE for version, (day, _saved) in meta.items()},
		bom_versions.today(),
		{version: getdate(saved) if saved else None for version, (_day, saved) in meta.items()},
	)


def etag(data: dict) -> str:
	"""SHA-256 (16 ký tự hex đầu) của JSON chuẩn hóa (``sort_keys``) của payload, bỏ ``etag`` và ``status``.

	Payload chứa tên/ảnh/etag ảnh (``content_hash`` của thumbnail) dụng cụ và ảnh khay: đổi → etag đổi; ``status``
	tính theo ngày nên không vào etag (cùng nội dung → cùng etag).
	"""
	body = {key: value for key, value in data.items() if key not in ("etag", "status")}
	text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
	return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _file_hashes(pairs: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], str]:
	"""``{(doctype, tên, file_url): content_hash}`` của File đính vào bản ghi, một truy vấn."""
	urls = sorted({url for _doctype, _name, url in pairs if url})
	if not urls:
		return {}
	marks = ", ".join(["%s"] * len(urls))
	hashes = {}
	for doctype, name, url, content_hash in frappe.db.sql(
		f"""
		select attached_to_doctype, attached_to_name, file_url, content_hash from `tabFile`
		where file_url in ({marks}) and attached_to_doctype in ('Instrument', %s)
		order by creation asc, name asc
		""",  # nosec B608 - chỉ chèn chuỗi giữ chỗ %s
		[*urls, SET_TYPE],
	):
		if content_hash:
			hashes.setdefault((doctype, name, url), content_hash)
	return hashes


def _first_hash(hashes, doctype, name, urls):
	# như media._etag: content_hash của File đầu tiên (thumbnail trước ảnh gốc) đính vào chính bản ghi
	for url in urls:
		if url and (doctype, name, url) in hashes:
			return hashes[(doctype, name, url)]
	return None


def _build(set_type: str, version: int, effective_from: str | None) -> dict:
	"""Dựng payload (chưa có ``status``) bằng 3 truy vấn cố định: loại bộ, dòng + dụng cụ, File (etag ảnh)."""
	header = frappe.db.get_value(
		SET_TYPE, set_type, ["name", "set_type_name", "method", *TRAY_FIELDS, *TRAY_THUMBS], as_dict=True
	)
	if not header:
		raise BlockedError(bom_versions.not_found_block(set_type))
	rows = frappe.db.sql(
		"""
		select b.instrument, b.qty, b.position, i.instrument_name, i.image, i.image_thumbnail
		from `tabSet BOM Item` b
		left join `tabInstrument` i on i.name = b.instrument
		where b.set_type = %s and b.bom_version = %s
		order by b.position asc, b.name asc
		""",
		(header.name, cint(version)),
		as_dict=True,
	)
	pairs = [("Instrument", row.instrument, url) for row in rows for url in (row.image_thumbnail, row.image)]
	pairs += [(SET_TYPE, header.name, header.get(field)) for field in (*TRAY_THUMBS, *TRAY_FIELDS)]
	hashes = _file_hashes(pairs)
	lines = [
		{
			"instrument": row.instrument,
			"instrument_name": row.instrument_name,
			"image": row.image or None,
			"thumbnail": row.image_thumbnail or None,
			"image_etag": _first_hash(hashes, "Instrument", row.instrument, (row.image_thumbnail, row.image)),
			"qty": cint(row.qty),
			"position": cint(row.position),
		}
		for row in rows
	]
	tray_images = [
		{
			"position": position,
			"image_url": header.get(field),
			"thumbnail_url": header.get(thumb) or None,
			"etag": _first_hash(hashes, SET_TYPE, header.name, (header.get(thumb), header.get(field))),
		}
		for position, (field, thumb) in enumerate(zip(TRAY_FIELDS, TRAY_THUMBS, strict=True), 1)
		if header.get(field)
	]
	data = {
		"set_type": header.name,
		"set_type_name": header.set_type_name,
		"method": header.method,
		"bom_version": cint(version),
		"effective_from": effective_from,
		"lines": lines,
		"tray_images": tray_images,
		"total_lines": len(lines),
		"total_qty": sum(line["qty"] for line in lines),
	}
	data["etag"] = etag(data)
	return data


def resolve_version(set_type: str, version: int | None = None) -> int:
	"""Phiên bản cần đọc: `version` nếu loại bộ có phiên bản đó; trống → phiên bản hiệu lực hôm nay (theo ngày đã cache).

	Không có → ``BlockedError(BOM_VERSION_NOT_FOUND)``.
	"""
	dates = version_dates(set_type)
	if version is None:
		effective = [
			number
			for number, status in _statuses(set_type).items()
			if status == bom_versions.STATUS_EFFECTIVE
		]
		if not effective:
			raise BlockedError(version_not_found_block(set_type))
		return effective[0]
	if cint(version) not in dates:
		raise BlockedError(version_not_found_block(set_type, version))
	return cint(version)


def payload(set_type: str, version: int | None = None) -> dict:
	"""BOM của loại bộ ở phiên bản `version` (trống → phiên bản hiệu lực hôm nay) cho trạm/PDA (S11).

	Trả ``{set_type, set_type_name, method, bom_version, effective_from, status, lines, tray_images, total_lines,
	total_qty, etag}``; ``lines`` như ``lines()`` thêm ``image_etag``; ``tray_images`` = ``[{position, image_url,
	thumbnail_url, etag}]`` (như ``media.set_type_photos``). Đọc cache ``tc_bom:<set_type>:<version>``, thiếu thì dựng
	bằng 3 truy vấn cố định và lưu ``CACHE_TTL`` giây; ``status`` gắn sau khi đọc cache (không vào cache, không vào
	``etag``). Phiên bản không có → ``BlockedError(BOM_VERSION_NOT_FOUND)``. Không kiểm quyền (RPC kiểm).
	"""
	version = resolve_version(set_type, version)
	dates = version_dates(set_type)
	key = _key(set_type, version)
	data = frappe.cache.get_value(key, expires=True)
	if data is None:
		data = _build(set_type, version, dates.get(version))
		frappe.cache.set_value(key, data, expires_in_sec=CACHE_TTL)
	return {**data, "status": _statuses(set_type).get(version)}


def _delete(keys: list[str]) -> None:
	frappe.cache.delete_value(keys)


def invalidate(set_type: str | None = None, instrument: str | None = None) -> None:
	"""Xóa cache BOM: mọi phiên bản (và ngày hiệu lực) của `set_type`, và/hoặc mọi phiên bản chứa dụng cụ `instrument`.

	Khóa tính từ dòng ``Set BOM Item`` hiện có (không quét Redis). Xóa ngay và xóa lại sau commit
	(``frappe.db.after_commit``): request khác lỡ dựng lại cache từ dữ liệu trước commit trong lúc ghi vẫn bị xóa.
	"""
	keys = set()
	if set_type:
		keys.add(_key(set_type, "dates"))
		for version in frappe.db.sql(
			"select distinct bom_version from `tabSet BOM Item` where set_type = %s", (set_type,), pluck=True
		):
			keys.add(_key(set_type, cint(version)))
	if instrument:
		for owner, version in frappe.db.sql(
			"select distinct set_type, bom_version from `tabSet BOM Item` where instrument = %s",
			(instrument,),
		):
			keys.add(_key(owner, cint(version)))
	keys = sorted(keys)
	if not keys:
		return
	_delete(keys)
	frappe.db.after_commit.add(partial(_delete, keys))


def payload_changed(doc, fields) -> bool:
	"""Lần lưu `doc` có đổi trường nằm trong payload BOM (so với bản trước khi lưu)."""
	before = doc.get_doc_before_save()
	if before is None:
		return False
	return any((before.get(field) or None) != (doc.get(field) or None) for field in fields)
