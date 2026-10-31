import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.factories import make_instrument, make_item, make_user
from tracecore.tests.utils import as_non_deleter

# Instrument liên kết Item (ERPNext) và User (owner); site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc
# tạo bản ghi test tự động (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "User", "Batch"]


def _audit_rows(name, action):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": "Instrument", "ref_name": name, "action": action},
		fields=["new_value"],
	)


def _instrument_doc(code, **kwargs):
	values = {
		"doctype": "Instrument",
		"instrument_code": code,
		"instrument_name": "Test instrument",
		"spaulding_class": "Critical",
		"compatible_methods": [{"method": "Steam 134"}],
	}
	values.update(kwargs)
	return frappe.get_doc(values)


class TestInstrument(FrappeTestCase):
	def test_instrument_code_normalized(self):
		doc = _instrument_doc("kc-01").insert()
		self.assertEqual(doc.name, "KC-01")
		self.assertEqual(doc.instrument_code, "KC-01")
		self.assertTrue(frappe.db.exists("Instrument", "KC-01"))

		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC 01").insert()
		self.assertFalse(frappe.db.exists("Instrument", "KC 01"))

	def test_instrument_code_allows_only_letters_digits_hyphen(self):
		for bad in ("kc_01", "KC/01", "KC.01", "<KC>", "", "  "):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad)):
				_instrument_doc(bad).insert()
		doc = _instrument_doc("  a1-b2-c3 ").insert()
		self.assertEqual(doc.name, "A1-B2-C3")

	def test_instrument_code_unique(self):
		make_instrument("KC-DUP")
		with self.assertRaises(frappe.DuplicateEntryError):
			_instrument_doc("kc-dup").insert()

	def test_maintenance_interval_not_negative_and_optional(self):
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-NEG", maint_interval_cycles=-1).insert()
		blank = _instrument_doc("KC-BLK").insert()
		self.assertFalse(blank.maint_interval_cycles)
		self.assertFalse(blank.maint_type)
		due = _instrument_doc(
			"KC-DUE", maint_interval_cycles=50, maint_type="Lubrication", max_cycles=500
		).insert()
		self.assertEqual(
			(due.maint_interval_cycles, due.maint_type, due.max_cycles), (50, "Lubrication", 500)
		)

	def test_maintenance_type_options(self):
		for index, maint_type in enumerate(
			("Lubrication", "Blade Check", "Screw Tightening", "Battery Replacement")
		):
			doc = _instrument_doc(f"KC-MT{index}", maint_interval_cycles=10, maint_type=maint_type).insert()
			self.assertEqual(doc.maint_type, maint_type)
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-MTX", maint_interval_cycles=10, maint_type="Polishing").insert()

	def test_factory_returns_existing_instrument(self):
		first = make_instrument("KC-FAC", name="Kelly forceps", interval=40, maint_type="Screw Tightening")
		again = make_instrument("KC-FAC")
		self.assertEqual(first.name, again.name)
		self.assertEqual(
			(again.instrument_name, again.maint_interval_cycles, again.maint_type),
			("Kelly forceps", 40, "Screw Tightening"),
		)

	def test_factory_defaults_and_options(self):
		plain = make_instrument("KC-FD1")
		self.assertEqual(plain.spaulding_class, "Critical")
		self.assertEqual([row.method for row in plain.compatible_methods], ["Steam 134"])
		custom = make_instrument(
			"KC-FD2",
			spaulding="Semi-critical",
			methods=("Plasma", "EO"),
			max_cycles=300,
			group="FD-GROUP",
			manufacturer="Aesculap",
		)
		self.assertEqual(custom.spaulding_class, "Semi-critical")
		self.assertEqual([row.method for row in custom.compatible_methods], ["Plasma", "EO"])
		self.assertEqual((custom.max_cycles, custom.max_cycles_status), (300, "Defined"))
		self.assertEqual(custom.instrument_group, "FD-GROUP")
		self.assertTrue(frappe.db.exists("Instrument Group", "FD-GROUP"))
		self.assertEqual(custom.manufacturer, "Aesculap")

	def test_create_writes_audit_log_and_delete_blocked(self):
		doc = make_instrument("KC-AUD", name="Audit scissors", manufacturer="Aesculap")
		created = _audit_rows(doc.name, "Create")
		self.assertEqual(len(created), 1)
		snapshot = frappe.parse_json(created[0].new_value)
		self.assertEqual(snapshot["instrument_name"], "Audit scissors")
		self.assertEqual(snapshot["manufacturer"], "Aesculap")
		self.assertEqual(snapshot["spaulding_class"], "Critical")
		self.assertEqual([row["method"] for row in snapshot["compatible_methods"]], ["Steam 134"])
		with self.assertRaises(frappe.ValidationError), as_non_deleter():
			frappe.delete_doc("Instrument", doc.name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Instrument", doc.name))

	def test_required_fields_listed_in_one_message(self):
		# FR-M1-01.1: mọi trường bắt buộc thiếu nêu trong một thông báo, bằng nhãn
		doc = _instrument_doc("KC-REQ", spaulding_class=None, compatible_methods=[])
		with self.assertRaises(frappe.MandatoryError) as raised:
			doc.insert()
		message = str(raised.exception)
		self.assertIn("Spaulding Class", message)
		self.assertIn("Compatible Methods", message)
		self.assertNotIn("Instrument Name", message)
		self.assertFalse(frappe.db.exists("Instrument", "KC-REQ"))

		# chuỗi chỉ toàn khoảng trắng coi như thiếu; thiếu mã cũng nêu cùng thông báo
		blank = _instrument_doc("   ", instrument_name=" \t ", spaulding_class=None)
		with self.assertRaises(frappe.MandatoryError) as raised:
			blank.insert()
		message = str(raised.exception)
		for label in ("Instrument Code", "Instrument Name", "Spaulding Class"):
			self.assertIn(label, message)
		self.assertNotIn("Compatible Methods", message)

		# sửa bản ghi đã có cũng không được bỏ trường bắt buộc
		saved = make_instrument("KC-REQ2")
		saved.instrument_name = "   "
		saved.set("compatible_methods", [])
		with self.assertRaises(frappe.MandatoryError) as raised:
			saved.save()
		self.assertIn("Instrument Name", str(raised.exception))
		self.assertIn("Compatible Methods", str(raised.exception))

		# hãng, model, ảnh, IFU, cơ số, giá trị, nhóm, Item: tùy chọn
		optional = make_instrument("KC-OPT")
		for field in (
			"manufacturer",
			"model",
			"image",
			"ifu",
			"max_cycles",
			"value",
			"instrument_group",
			"item",
		):
			self.assertFalse(optional.get(field), msg=field)

	def test_text_fields_trimmed(self):
		doc = _instrument_doc(
			"KC-TRIM", instrument_name="  Kelly forceps ", manufacturer=" Aesculap  ", model="\tBH110 "
		).insert()
		self.assertEqual(
			(doc.instrument_name, doc.manufacturer, doc.model), ("Kelly forceps", "Aesculap", "BH110")
		)

	def test_new_instrument_is_active_version_1(self):
		# FR-M1-01: lưu đủ trường → Đang dùng, phiên bản 1
		doc = _instrument_doc(
			"KC-NEW",
			manufacturer="Aesculap",
			model="BH110",
			spaulding_class="Semi-critical",
			compatible_methods=[{"method": "Steam 121"}, {"method": "Plasma"}],
			max_cycles=500,
			value=1250000,
		).insert()
		self.assertEqual((doc.status, doc.version_no), ("Active", 1))
		self.assertEqual(frappe.db.get_value("Instrument", "KC-NEW", ["status", "version_no"]), ("Active", 1))
		self.assertEqual(
			frappe.get_all(
				"Instrument Compatible Method",
				filters={"parent": "KC-NEW", "parenttype": "Instrument"},
				pluck="method",
				order_by="idx asc",
			),
			["Steam 121", "Plasma"],
		)
		for spaulding in ("Critical", "Semi-critical", "Non-critical"):
			self.assertEqual(
				_instrument_doc(f"KC-SP-{spaulding.upper()}", spaulding_class=spaulding)
				.insert()
				.spaulding_class,
				spaulding,
			)
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-SPX", spaulding_class="High").insert()
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-MTHX", compatible_methods=[{"method": "Dry Heat"}]).insert()

	def test_duplicate_compatible_method_rejected(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			_instrument_doc(
				"KC-DM", compatible_methods=[{"method": "Plasma"}, {"method": "EO"}, {"method": "Plasma"}]
			).insert()
		self.assertIn("Plasma", str(raised.exception))
		self.assertFalse(frappe.db.exists("Instrument", "KC-DM"))

	def test_code_cannot_be_renamed(self):
		doc = make_instrument("KC-REN")
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Instrument", "KC-REN", "KC-REN2")
		doc.reload()
		doc.instrument_code = "KC-REN3"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertTrue(frappe.db.exists("Instrument", "KC-REN"))
		self.assertFalse(frappe.db.exists("Instrument", "KC-REN2"))
		self.assertFalse(frappe.db.exists("Instrument", "KC-REN3"))

	def test_max_cycles_blank_is_undefined(self):
		# FR-M1-01.2, UC-01 A2: trống/0 → Chưa xác định, vẫn lưu được (chỉ cảnh báo)
		blank = _instrument_doc("KC-MC0").insert()
		self.assertEqual(blank.max_cycles_status, "Undefined")
		zero = _instrument_doc("KC-MC1", max_cycles=0).insert()
		self.assertEqual(zero.max_cycles_status, "Undefined")
		defined = _instrument_doc("KC-MC2", max_cycles=500).insert()
		self.assertEqual(defined.max_cycles_status, "Defined")
		defined.max_cycles = 0
		defined.save()
		self.assertEqual(frappe.db.get_value("Instrument", "KC-MC2", "max_cycles_status"), "Undefined")
		# trạng thái tính lại từ cơ số, không nhận giá trị nhập tay
		forged = _instrument_doc("KC-MC3", max_cycles_status="Defined").insert()
		self.assertEqual(forged.max_cycles_status, "Undefined")
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-MC4", max_cycles=-5).insert()

	def test_value_rounded_vnd_not_negative(self):
		doc = _instrument_doc("KC-VAL", value=1250000.5).insert()
		self.assertEqual(doc.value, 1250001)
		self.assertEqual(frappe.db.get_value("Instrument", "KC-VAL", "value"), 1250001)
		self.assertEqual(_instrument_doc("KC-VAL2", value=99.49).insert().value, 99)
		self.assertEqual(_instrument_doc("KC-VAL3").insert().value, 0)
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-VALN", value=-1).insert()
		self.assertFalse(frappe.db.exists("Instrument", "KC-VALN"))

	def test_item_link_optional(self):
		# I14: Item tùy chọn; Item bị vô hiệu không gắn được; không đồng bộ tồn kho
		self.assertEqual(frappe.get_meta("Instrument").get_field("item").reqd, 0)
		item = make_item("KC-ITEM-01", "Packaging")
		doc = _instrument_doc("KC-ITM", item=item.name).insert()
		self.assertEqual(doc.item, item.name)
		disabled = make_item("KC-ITEM-02", "Packaging")
		frappe.db.set_value("Item", disabled.name, "disabled", 1)
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-ITM2", item=disabled.name).insert()
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-ITM3", item="NO-SUCH-ITEM").insert()

	def test_status_cannot_be_edited_directly(self):
		# I13: trạng thái, ngày/lý do ngừng, phiên bản chỉ đổi qua dịch vụ danh mục
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-ST1", status="Retired").insert()
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-ST2", version_no=5).insert()
		doc = make_instrument("KC-ST3")
		for field, value in (
			("status", "Retired"),
			("retired_on", "2026-10-21"),
			("retired_reason", "Broken"),
			("version_no", 2),
		):
			doc.reload()
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save()
		self.assertEqual(
			frappe.db.get_value("Instrument", "KC-ST3", ["status", "version_no", "retired_reason"]),
			("Active", 1, None),
		)
		meta = frappe.get_meta("Instrument")
		for field in (
			"status",
			"version_no",
			"max_cycles_status",
			"retired_on",
			"retired_reason",
			"image_thumbnail",
		):
			self.assertTrue(meta.get_field(field).read_only, msg=field)
		self.assertTrue(meta.get_field("image_thumbnail").hidden)

	def test_permissions_match_i15(self):
		validate_permissions_for_doctype("Instrument")
		validate_permissions_for_doctype("Instrument Group")
		for doctype in ("Instrument", "Instrument Group"):
			perms = {row.role: row for row in frappe.get_meta(doctype).permissions}
			for role in ("System Manager", "TC R02", "TC R10"):
				for right in ("read", "write", "create", "report"):
					self.assertEqual(perms[role].get(right), 1, msg=(doctype, role, right))
			for role in [f"TC R{n:02d}" for n in (1, 3, 4, 5, 6, 7, 8, 9)]:
				self.assertEqual(perms[role].read, 1, msg=(doctype, role))
				self.assertFalse(perms[role].write or perms[role].create, msg=(doctype, role))
			# FEAT-004 A-37 d (FR-M9-16): chỉ R10 có delete (on_trash vẫn chặn danh mục đã có giao dịch)
			self.assertLessEqual({row.role for row in perms.values() if row.delete}, {"TC R10"}, msg=doctype)

		writer = make_user("instr-r02@example.com", roles=["TC R02"])
		admin = make_user("instr-r10@example.com", roles=["TC R10"])
		for user in (writer, admin):
			self.assertTrue(frappe.has_permission("Instrument", "create", user=user), user)
			self.assertTrue(frappe.has_permission("Instrument Group", "create", user=user), user)
			# FEAT-004 A-37 d: chỉ R10 có delete (on_trash vẫn chặn khi đã có giao dịch)
			self.assertEqual(frappe.has_permission("Instrument", "delete", user=user), user == admin, user)
		for role in ("TC R01", "TC R04"):
			reader = make_user(f"instr-{role[-3:].lower()}@example.com", roles=[role])
			self.assertTrue(frappe.has_permission("Instrument", "read", user=reader), role)
			for ptype in ("create", "write", "delete"):
				self.assertFalse(frappe.has_permission("Instrument", ptype, user=reader), (role, ptype))

		frappe.set_user(writer)
		try:
			doc = _instrument_doc("KC-PERM").insert()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(doc.owner, writer)

	def test_patch_backfills_without_inventing_clinical_data(self):
		from tracecore.instrument.report.instrument_data_gaps.instrument_data_gaps import execute as data_gaps
		from tracecore.patches.v0_1 import instrument_master_defaults

		legacy = make_instrument("KC-LEG", max_cycles=None)
		bumped = make_instrument("KC-LEG2", max_cycles=500)
		# giả lập dòng có từ trước FEAT-014: chưa có Spaulding, phương pháp, trạng thái, phiên bản
		for name in (legacy.name, bumped.name):
			frappe.db.set_value(
				"Instrument",
				name,
				{"spaulding_class": None, "status": None, "version_no": 0, "max_cycles_status": None},
				update_modified=False,
			)
			frappe.db.delete("Instrument Compatible Method", {"parent": name, "parenttype": "Instrument"})
		frappe.db.set_value("Instrument", bumped.name, "version_no", 3, update_modified=False)

		instrument_master_defaults.execute()
		instrument_master_defaults.execute()  # chạy lại không đổi gì thêm

		self.assertEqual(
			frappe.db.get_value(
				"Instrument", legacy.name, ["status", "version_no", "max_cycles_status", "spaulding_class"]
			),
			("Active", 1, "Undefined", None),
		)
		self.assertEqual(
			frappe.db.get_value("Instrument", bumped.name, ["status", "version_no", "max_cycles_status"]),
			("Active", 3, "Defined"),
		)
		self.assertFalse(frappe.db.exists("Instrument Compatible Method", {"parent": legacy.name}))
		updates = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument", "ref_name": legacy.name, "action": "Update"},
			fields=["new_value"],
		)
		self.assertEqual(len(updates), 1)

		rows = {row["instrument"]: row for row in data_gaps({})[1]}
		self.assertTrue(rows[legacy.name]["spaulding_class"])
		self.assertTrue(rows[legacy.name]["compatible_methods"])
		self.assertTrue(rows[legacy.name]["max_cycles"])

	def test_desk_duplicate_saves_with_new_code(self):
		# Desk "Duplicate" (frappe.copy_doc): ảnh/IFU/thumbnail là File của bản gốc, trạng thái/phiên bản/ngừng sử dụng
		# là của bản gốc → no_copy; bản sao lưu được với mã mới, Đang dùng, phiên bản 1, không kèm file
		import io

		from PIL import Image

		from tracecore.instrument import catalog
		from tracecore.tests.factories import attach_instrument_file

		make_instrument("KC-DUPSRC", methods=("Steam 134",))
		buffer = io.BytesIO()
		Image.new("RGB", (64, 48), (200, 30, 30)).save(buffer, format="PNG")
		photo = attach_instrument_file("KC-DUPSRC", "image", buffer.getvalue(), "kc-dupsrc.png")
		source = frappe.get_doc("Instrument", "KC-DUPSRC")
		source.image = photo.file_url
		source.compatible_methods = []
		source.append("compatible_methods", {"method": "Plasma"})
		source.save()
		catalog.retire("KC-DUPSRC", "Gãy")
		source.reload()
		self.assertTrue(source.image_thumbnail)
		self.assertEqual((source.version_no, source.status), (2, "Retired"))

		copy = frappe.copy_doc(source, ignore_no_copy=False)  # như Desk Duplicate (frappe.model.copy_doc)
		copy.instrument_code = "KC-DUPNEW"
		copy.insert()
		self.assertEqual(copy.name, "KC-DUPNEW")
		self.assertEqual((copy.status, copy.version_no), ("Active", 1))
		for field in ("image", "image_thumbnail", "ifu", "retired_on", "retired_reason", "giai_code"):
			self.assertFalse(copy.get(field), field)
		self.assertEqual([row.method for row in copy.compatible_methods], ["Plasma"])
		self.assertEqual(copy.spaulding_class, source.spaulding_class)
		meta = frappe.get_meta("Instrument")
		for field in (
			"image",
			"ifu",
			"image_thumbnail",
			"status",
			"version_no",
			"retired_on",
			"retired_reason",
		):
			self.assertTrue(meta.get_field(field).no_copy, field)
