"""Hướng dẫn theo trạm từ Frappe Help Article (FEAT-013, FR-M9-15, A-56 D2, D4, D5).

Bước = mục của danh sách đầu tiên trong `content`, ảnh = `<img>` đầu tiên của mục; bài gắn trạm (`tc_station_key`)
phải có 3 đến 5 bước và ảnh chỉ là file công khai. Trạm không có bài riêng dùng bài General.
"""

import frappe

from tracecore.patches.v0_1 import receive_help_steps
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import station_help

STEPS_HTML = (
	"<p>Intro</p><ol>"
	'<li>Scan the <b>set</b> label <img src="/files/t4-1.png" alt="label"></li>'
	"<li>Check the instruments</li>"
	'<li>Print the pack label <img src="/files/t4-3.jpg"><img src="/files/extra.png"></li>'
	"</ol><ol><li>Not a step</li></ol>"
)


def _texts(html):
	return [step["text"] for step in station_help.steps_from_html(html)]


class TestReceiveGuidePatch(IsolatedTestCase):
	def _receive(self, content):
		frappe.db.delete("Help Article", {"tc_station_key": "RECEIVE"})
		article = _article("RECEIVE", content=content, title="Help RECEIVE " + frappe.generate_hash(length=6))
		return article.insert(ignore_permissions=True)

	def test_guide_follows_the_order_on_screen(self):
		steps = station_help.DEFAULT_STEPS["RECEIVE"]
		self.assertEqual(len(steps), 5)
		self.assertIn("employee card", steps[0])
		self.assertIn("handing over", steps[1])
		self.assertIn("Confirm", steps[4])

	def test_patch_updates_an_unedited_article_in_either_language(self):
		for lang in ("en", "vi"):
			article = self._receive(station_help.default_content(receive_help_steps.OLD_STEPS, lang=lang))
			receive_help_steps.execute()
			self.assertEqual(
				_texts(frappe.db.get_value("Help Article", article.name, "content")),
				_texts(station_help.default_content(station_help.DEFAULT_STEPS["RECEIVE"], lang=lang)),
			)

	def test_patch_keeps_an_edited_article(self):
		article = self._receive("<ol><li>Một</li><li>Hai</li><li>Ba</li></ol>")
		receive_help_steps.execute()
		self.assertEqual(
			_texts(frappe.db.get_value("Help Article", article.name, "content")), ["Một", "Hai", "Ba"]
		)


def _article(key, content=STEPS_HTML, published=1, title=None):
	return frappe.get_doc(
		{
			"doctype": "Help Article",
			"title": title or f"Help {key}",
			"category": station_help.ensure_category(),
			"content": content,
			"published": published,
			"tc_station_key": key,
		}
	)


def _steps(count):
	return "<ol>" + "".join(f"<li>Step {n}</li>" for n in range(count)) + "</ol>"


class TestStepsFromHtml(IsolatedTestCase):
	def test_first_list_items_become_steps_with_first_image(self):
		self.assertEqual(
			station_help.steps_from_html(STEPS_HTML),
			[
				{"text": "Scan the set label", "image": "/files/t4-1.png"},
				{"text": "Check the instruments", "image": None},
				{"text": "Print the pack label", "image": "/files/t4-3.jpg"},
			],
		)

	def test_no_list_means_no_steps(self):
		self.assertEqual(station_help.steps_from_html("<p>Only text</p>"), [])
		self.assertEqual(station_help.steps_from_html(None), [])

	def test_unsafe_image_sources_are_dropped(self):
		html = (
			'<ol><li>A <img src="javascript:alert(1)"></li><li>B <img src="/private/files/x.png"></li>'
			'<li>C <img src="https://evil.example/x.png"></li><li>D <img src="/files/../x.png"></li></ol>'
		)
		self.assertEqual([step["image"] for step in station_help.steps_from_html(html)], [None] * 4)


class TestValidateArticle(IsolatedTestCase):
	def test_station_article_needs_three_to_five_steps(self):
		for count in (2, 6):
			with self.assertRaises(frappe.ValidationError):
				_article("PACK", content=_steps(count)).insert(ignore_permissions=True)
		for count in (3, 5):
			_article("PACK", content=_steps(count), title=f"T4 {count}").insert(ignore_permissions=True)

	def test_station_article_refuses_private_or_external_images(self):
		for src in ("/private/files/x.png", "https://example.com/x.png"):
			with self.assertRaises(frappe.ValidationError):
				_article(
					"WASH_LOAD", content=f'<ol><li>A <img src="{src}"></li><li>B</li><li>C</li></ol>'
				).insert(ignore_permissions=True)

	def test_plain_help_article_is_not_checked(self):
		doc = _article(None, content="<p>Free text</p>")
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name)


class TestArticleForStation(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Help Article", {"tc_station_key": ["is", "set"]})

	def test_station_step_article(self):
		_article("PACK").insert(ignore_permissions=True)
		_article("General", content=_steps(3)).insert(ignore_permissions=True)
		article = station_help.article_for("TR-004")
		self.assertEqual(article["key"], "PACK")
		self.assertEqual(len(article["steps"]), 3)
		self.assertTrue(article["modified"])

	def test_falls_back_to_general_then_none(self):
		self.assertIsNone(station_help.article_for("TR-004"))
		_article("General", content=_steps(3)).insert(ignore_permissions=True)
		self.assertEqual(station_help.article_for("TR-004")["key"], "General")

	def test_unpublished_article_is_ignored(self):
		_article("PACK", published=0).insert(ignore_permissions=True)
		self.assertIsNone(station_help.article_for("TR-004"))

	def test_station_key_of_station(self):
		self.assertEqual(station_help.station_key("TR-004"), "PACK")
		self.assertEqual(station_help.station_key(None), "General")


class TestSeed(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Help Article", {"tc_station_key": ["is", "set"]})

	def test_seed_creates_one_article_per_key_and_keeps_edits(self):
		station_help.ensure_station_help()
		rows = frappe.get_all(
			"Help Article", filters={"tc_station_key": ["is", "set"]}, fields=["name", "tc_station_key"]
		)
		self.assertEqual(sorted(row.tc_station_key for row in rows), sorted(station_help.STATION_KEYS))
		for key in station_help.STATION_KEYS:
			self.assertTrue(3 <= len(station_help.article_for_key(key)["steps"]) <= 5, key)
		edited = next(row.name for row in rows if row.tc_station_key == "RECEIVE")
		frappe.db.set_value("Help Article", edited, "title", "Edited by R10")
		station_help.ensure_station_help()
		self.assertEqual(frappe.db.get_value("Help Article", edited, "title"), "Edited by R10")
		self.assertEqual(frappe.db.count("Help Article", {"tc_station_key": ["is", "set"]}), len(rows))

	def test_keys_match_station_steps(self):
		screens = frappe.get_all("Station Function", filters={"screen_key": ["is", "set"]}, pluck="name")
		self.assertEqual(set(station_help.STATION_KEYS) - {"General"}, set(screens))
		field_options = frappe.get_meta("Help Article").get_field("tc_station_key").options.split("\n")
		self.assertEqual({option for option in field_options if option}, set(station_help.STATION_KEYS))


class TestStationHelpTitles(IsolatedTestCase):
	"""#1831 S-03: tên bài hướng dẫn không để lộ khóa kỹ thuật."""

	def test_title_is_station_number_dash_name(self):
		from tracecore.core import zones

		self.assertEqual(
			station_help.article_title("RECEIVE"), f"T1 \u2013 {zones.function_label('RECEIVE')}"
		)

	def test_unedited_titles_show_the_station_name(self):
		expected = station_help.article_title("RECEIVE")
		for stored in (
			"Hướng dẫn trạm: T1",
			"Station guide: T1",
			"Station guide: RECEIVE",
			"Hướng dẫn trạm T1 \u2013 Tiếp nhận",
			"Station guide T1 - Receiving",
			"T1 \u2013 Receiving",
		):
			with self.subTest(stored=stored):
				self.assertEqual(station_help.display_title("RECEIVE", stored), expected)

	def test_edited_titles_are_kept(self):
		for stored in ("Edited by R10", "Hướng dẫn trạm: Lắp bộ mới", "T1 riêng của viện"):
			with self.subTest(stored=stored):
				self.assertEqual(station_help.display_title("RECEIVE", stored), stored)

	def test_title_uses_station_number_and_function_name(self):
		title = station_help.article_title("RECEIVE")
		self.assertNotIn("RECEIVE", title)
		self.assertIn("T1", title)
