"""Dữ liệu khởi tạo M14 (FEAT-067; NFR-MAINT-04, D10; A-136): danh mục Organism tối thiểu và 3 quy tắc đa kháng Nháp.

Chạy ở ``after_install`` và ``after_migrate``; chỉ chèn mã còn thiếu, không ghi đè bản bệnh viện đã sửa hay đã duyệt.
Không dùng ``fixtures`` của Frappe vì ``bench migrate`` nạp lại fixtures đè lên chỉnh sửa. Quy tắc ở trạng thái Nháp:
R01 xem, sửa và ghi sổ (duyệt) tại bệnh viện trước khi quy tắc gắn nhãn chủng (BRU-MDR-001); nội dung chỉ là bản nháp
khởi đầu, không phải tiêu chí đã được duyệt.
"""

import frappe

from tracecore.microbiology import rules

ENTEROBACTERALES = "Enterobacterales"
ORGANISMS = (
	("eco", "Escherichia coli", ENTEROBACTERALES),
	("kpn", "Klebsiella pneumoniae", ENTEROBACTERALES),
	("ecl", "Enterobacter cloacae", ENTEROBACTERALES),
	("pmi", "Proteus mirabilis", ENTEROBACTERALES),
	("sma", "Serratia marcescens", ENTEROBACTERALES),
	("aba", "Acinetobacter baumannii", "Acinetobacter"),
	("pae", "Pseudomonas aeruginosa", "Pseudomonas"),
	("sau", "Staphylococcus aureus", "Staphylococcus"),
	("efa", "Enterococcus faecalis", "Enterococcus"),
	("efm", "Enterococcus faecium", "Enterococcus"),
	("spn", "Streptococcus pneumoniae", "Streptococcus"),
)
RULES = (
	{
		"rule_code": "MRSA",
		"label": "MRSA",
		"condition": rules.ANY,
		"precaution_type": "Contact",
		"organisms": [{"organism": "sau"}],
		"criteria": [
			{
				"antibiotic": "OXA",
				"antibiotic_name": "Oxacillin",
				"antibiotic_class": "Penicillinase-stable penicillins",
			},
			{"antibiotic": "FOX", "antibiotic_name": "Cefoxitin", "antibiotic_class": "Cephamycins"},
		],
	},
	{
		"rule_code": "ESBL",
		"label": "ESBL",
		"condition": rules.ANY,
		"precaution_type": "Contact",
		"organisms": [{"organism_group": ENTEROBACTERALES}],
		"criteria": [
			{
				"antibiotic": "CRO",
				"antibiotic_name": "Ceftriaxone",
				"antibiotic_class": "Third-generation cephalosporins",
			},
			{
				"antibiotic": "CTX",
				"antibiotic_name": "Cefotaxime",
				"antibiotic_class": "Third-generation cephalosporins",
			},
			{
				"antibiotic": "CAZ",
				"antibiotic_name": "Ceftazidime",
				"antibiotic_class": "Third-generation cephalosporins",
			},
		],
	},
	{
		"rule_code": "CRE",
		"label": "CRE",
		"condition": rules.ANY,
		"precaution_type": "Contact",
		"organisms": [{"organism_group": ENTEROBACTERALES}],
		"criteria": [
			{"antibiotic": "IPM", "antibiotic_name": "Imipenem", "antibiotic_class": "Carbapenems"},
			{"antibiotic": "MEM", "antibiotic_name": "Meropenem", "antibiotic_class": "Carbapenems"},
			{"antibiotic": "ETP", "antibiotic_name": "Ertapenem", "antibiotic_class": "Carbapenems"},
		],
	},
)


def ensure_organisms():
	created = []
	for code, name, group in ORGANISMS:
		if frappe.db.exists("Organism", code):
			continue
		doc = frappe.get_doc(
			{"doctype": "Organism", "organism_code": code, "organism_name": name, "organism_group": group}
		)
		created.append(doc.insert(ignore_permissions=True).name)
	return created


def ensure_mdro_rules():
	ensure_organisms()
	return rules.install_rules([{**row, "effective_from": "2026-01-01"} for row in RULES])


def ensure_seed():
	"""Hook ``after_install`` / ``after_migrate``."""
	ensure_mdro_rules()
