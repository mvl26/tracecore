#!/usr/bin/env bash
# Chuẩn bị một site DEV/TEST cho e2e kiosk (KHÔNG dùng cho production):
#   1. Hoàn tất Setup Wizard ERPNext bằng dữ liệu test (Desk ép user về Setup Wizard nếu chưa xong)
#   2. Định dạng Việt Nam (System Settings)
#   3. User trạm cho smoke FEAT-001 (TR-003, không phải T4) và user trạm T4 (TR-004); mật khẩu ngẫu nhiên
#      lưu trong file quyền 600
#      và user Desk TC R10 (r10-e2e@…, mật khẩu ngẫu nhiên riêng, khác mật khẩu kiosk) cho tests_e2e/test_desk_admin.py
#   4. Set Unit demo để quét (smoke) và dữ liệu demo T4 (devdata.ensure_t4_demo: bộ hấp/plasma/gate-fail,
#      lô chỉ thị, mã cuộn nhãn, máy in)
# Kết quả ghi vào $TC_E2E_ENV (mặc định ~/.tracecore-e2e.env): TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID,
# TC_E2E_STATION/CARD_ID/EMPLOYEE (smoke), TC_E2E_R10_USER/PASSWORD và TC_E2E_T4_USER/PASSWORD/STATION/CARD_ID/EMPLOYEE
# + TC_E2E_T4_SECOND_STATION và TC_E2E_T4_<khóa của ensure_t4_demo>.
# Employee/card/competency demo được dùng lại; không tạo PIN cố định. Site phải bật developer_mode hoặc allow_tests.
# OTP App seed ngẫu nhiên riêng cho mỗi user demo chỉ ghi vào file env quyền 600; browser hoàn tất 2FA thật.
#   5. Máy và chương trình demo thiết bị (devdata.ensure_equipment_demo, FEAT-038) → TC_E2E_EQ_<khóa> cho tests_e2e/test_desk_equipment.py
#   6. In nhãn QR đối tượng (devdata.ensure_codes_demo, FEAT-005): máy in mạng demo tại TR-001, host 127.0.0.1, cổng
#      $TC_E2E_CODES_PRINTER_PORT (mặc định 19101; tests_e2e dựng socket TCP giả ở cổng này, worker của bench gửi ZPL tới)
#      và user r10-codes-e2e@… (TC R10 + Stock User: R10 không đọc được Item của ERPNext nên người cấp mã cuộn cần thêm
#      một role kho; cùng mật khẩu với user R10) → TC_E2E_CODES_USER/PASSWORD + TC_E2E_CODES_<khóa> cho
#      tests_e2e/test_desk_codes.py. Lệnh in đi đường server: cần worker (bench start / bench worker) đang chạy.
#      Bật `tracecore_allow_local_printers` trong site_config của site này (sau chốt chặn site test): core.print_server
#      (lúc gửi) từ chối máy in IP loopback nếu không có cờ này. CI dùng chính script này nên cũng có cờ.
#   7. Danh mục dụng cụ Desk (devdata.ensure_instrument_demo, FEAT-014): nhóm có ngưỡng, dụng cụ đủ dữ liệu có ảnh trong
#      BOM hiện hành của hai loại bộ demo (hấp/plasma, mỗi loại một bộ qua T1-T3 để mở ở T4), dụng cụ thiếu cơ số, dụng
#      cụ để ngừng sử dụng, dụng cụ để cấp mã GIAI; user r02-instr-e2e@… (TC R02, cùng mật khẩu với user R10)
#      → TC_E2E_INSTR_USER/PASSWORD + TC_E2E_INSTR_<khóa> cho tests_e2e/test_desk_instrument.py. Ngừng sử dụng và cấp
#      mã GIAI là một chiều: chạy lại script này trước mỗi lần chạy test đó (dụng cụ đã dùng được thay bằng dụng cụ mới).
#   8. Vật tư tiêu hao và nhập kho Desk (devdata.ensure_inventory_demo, FEAT-041): Company thử + kho, nhà cung cấp, bốn
#      vật tư mẫu (chỉ thị hóa học lớp 5, chỉ thị sinh học, bao gói, hóa chất) có tồn tối thiểu theo kho; user
#      r09-inv-e2e@… (TC R09, cùng mật khẩu với user R10) → TC_E2E_INV_USER/PASSWORD + TC_E2E_INV_<khóa> cho
#      tests_e2e/test_desk_inventory.py. Stock Entry và Item không xóa được: test tự sinh mã lô và số chứng từ duy nhất.
# Bộ demo T4 bị tiêu thụ khi test đóng gói chạy (và cuộn nhãn của máy in demo bị test_desk_admin đổi): chạy lại script này trước mỗi lần chạy tests_e2e/test_station_t4.py.
#
# AN TOÀN: script tạo user, máy in, thiết bị, Set Unit demo mà test đơn vị không ngờ tới, nên TỪ CHỐI chạy trên site tên
# `test_site` hoặc site có `allow_tests` bật trong site_config.json hoặc sites/common_site_config.json (in lỗi, thoát mã 2): site test là nơi chạy
# `bench run-tests`, dữ liệu e2e rò vào đó làm hỏng test. Dùng site dev (vd tracecore-dev.local). Riêng CI, nơi site
# test_site được dựng mới và bỏ đi sau job, đặt TC_E2E_ALLOW_TEST_SITE=1 để bỏ qua kiểm tra.
# TC_E2E_CHECK_ONLY=1 chỉ chạy kiểm tra rồi thoát (dùng cho tracecore/tests/test_e2e_prepare_guard.py).
#
# Dùng: scripts/e2e_prepare.sh <site>    (BENCH_DIR mặc định ~/tracecore-dev)
set -euo pipefail

SITE="${1:?usage: scripts/e2e_prepare.sh <site>}"
BENCH_DIR="${BENCH_DIR:-$HOME/tracecore-dev}"
ENV_FILE="${TC_E2E_ENV:-$HOME/.tracecore-e2e.env}"
STATION="${TC_E2E_STATION:-TR-003}"
T4_STATION="${TC_E2E_T4_STATION:-TR-004}"
CODES_PORT="${TC_E2E_CODES_PRINTER_PORT:-19101}"
SECOND_STATION="${TC_E2E_T4_SECOND_STATION:-TR-005}"

# Từ chối site test: tên test_site hoặc site_config.json / common_site_config.json có allow_tests bật (1/true/"1").
allow_tests_in() {
	[ -f "$1" ] && python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("allow_tests") in (1, True, "1", "true") else 1)' "$1"
}
refuse_test_site() {
	local site="$1" config="$BENCH_DIR/sites/$1/site_config.json" common="$BENCH_DIR/sites/common_site_config.json"
	[ "${TC_E2E_ALLOW_TEST_SITE:-0}" = "1" ] && return 0
	if [ "$site" = "test_site" ]; then
		echo "error: e2e_prepare.sh refuses to run on test_site (it would leak e2e data into the unit-test site); use a dev site" >&2
		return 2
	fi
	if allow_tests_in "$config"; then
		echo "error: e2e_prepare.sh refuses to run on $site: allow_tests is enabled in its site_config.json (test site)" >&2
		return 2
	fi
	if allow_tests_in "$common"; then
		echo "error: e2e_prepare.sh refuses to run on $site: allow_tests is enabled in sites/common_site_config.json (applies to every site)" >&2
		return 2
	fi
}
refuse_test_site "$SITE" || exit 2
[ "${TC_E2E_CHECK_ONLY:-0}" = "1" ] && exit 0

cd "$BENCH_DIR"
bench_exec() { bench --site "$SITE" execute "$@" | tail -n 1; }

if [ "$(bench_exec frappe.is_setup_complete)" != "true" ]; then
	year=$(date +%Y)
	bench_exec frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs "{'args': {
		'language': 'English', 'country': 'Vietnam', 'timezone': 'Asia/Ho_Chi_Minh', 'currency': 'VND',
		'full_name': 'TraceCore Test', 'company_name': 'TraceCore Test', 'company_abbr': 'TCT',
		'chart_of_accounts': 'Standard', 'fy_start_date': '${year}-01-01', 'fy_end_date': '${year}-12-31',
		'setup_demo': 0}}" > /dev/null
	echo "setup wizard completed on $SITE"
fi
bench_exec tracecore.setup.install.apply_system_settings > /dev/null

umask 077
random_password() { echo "Tc-$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)-9!"; }
password=""
r10_password=""
if [ -s "$ENV_FILE" ]; then
	password=$(sed -n 's/^TC_E2E_PASSWORD=//p' "$ENV_FILE")
	r10_password=$(sed -n 's/^TC_E2E_R10_PASSWORD=//p' "$ENV_FILE")
fi
if [ -z "$password" ]; then
	password=$(random_password)
fi
# user Desk R10 có mật khẩu riêng (file env cũ dùng chung mật khẩu kiosk thì tạo mới)
if [ -z "$r10_password" ] || [ "$r10_password" = "$password" ]; then
	r10_password=$(random_password)
fi
users=$(bench_exec tracecore.setup.devdata.ensure_e2e_users --kwargs "{'station': '$STATION', 't4_station': '$T4_STATION', 'password': '$password', 'r10_password': '$r10_password'}")
user=$(printf '%s' "$users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["user"])')
t4_user=$(printf '%s' "$users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["t4_user"])')
r10_user=$(printf '%s' "$users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["r10_user"])')
station_demo=$(bench_exec tracecore.setup.devdata.ensure_station_demo --kwargs "{'station': '$STATION', 'user': '$user'}")
t4_station_demo=$(bench_exec tracecore.setup.devdata.ensure_station_demo --kwargs "{'station': '$T4_STATION', 'user': '$t4_user', 'second_station': '$SECOND_STATION'}")
desk_users=$(bench_exec tracecore.setup.devdata.ensure_desk_users --kwargs "{'password': '$r10_password', 'specs': [{'key': 'codes', 'role': 'TC R10', 'name': 'r10-codes-e2e', 'extra_roles': ['Stock User']}, {'key': 'instr', 'role': 'TC R02', 'name': 'r02-instr-e2e'}, {'key': 'inv', 'role': 'TC R09', 'name': 'r09-inv-e2e'}]}")
codes_user=$(printf '%s' "$desk_users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["codes_user"])')
instr_user=$(printf '%s' "$desk_users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["instr_user"])')
inv_user=$(printf '%s' "$desk_users" | python3 -c 'import json, sys; print(json.load(sys.stdin)["inv_user"])')
set_id=$(bench_exec tracecore.setup.devdata.ensure_demo_set | tr -d '"')
t4_demo=$(bench_exec tracecore.setup.devdata.ensure_t4_demo)
eq_demo=$(bench_exec tracecore.setup.devdata.ensure_equipment_demo)
bench --site "$SITE" set-config tracecore_allow_local_printers 1 > /dev/null
codes_demo=$(bench_exec tracecore.setup.devdata.ensure_codes_demo --kwargs "{'port': '$CODES_PORT'}")
instr_demo=$(bench_exec tracecore.setup.devdata.ensure_instrument_demo)
inv_demo=$(bench_exec tracecore.setup.devdata.ensure_inventory_demo)

{
	printf 'TC_E2E_USER=%s\nTC_E2E_PASSWORD=%s\nTC_E2E_SET_ID=%s\nTC_E2E_STATION=%s\n' \
		"$user" "$password" "$set_id" "$STATION"
	printf 'TC_E2E_R10_USER=%s\nTC_E2E_R10_PASSWORD=%s\n' "$r10_user" "$r10_password"
	printf 'TC_E2E_T4_USER=%s\nTC_E2E_T4_PASSWORD=%s\nTC_E2E_T4_STATION=%s\n' "$t4_user" "$password" "$T4_STATION"
	printf 'TC_E2E_T4_SECOND_STATION=%s\n' "$SECOND_STATION"
	printf '%s' "$desk_users" | python3 -c 'import json, sys; [print("TC_E2E_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items() if k.endswith("otp_secret")]'
	printf '%s' "$users" | python3 -c 'import json, sys; [print("TC_E2E_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items() if k.endswith("otp_secret")]'
	printf '%s' "$station_demo" | python3 -c 'import json, sys; [print("TC_E2E_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf '%s' "$t4_station_demo" | python3 -c 'import json, sys; [print("TC_E2E_T4_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf '%s' "$t4_demo" | python3 -c 'import json, sys; [print("TC_E2E_T4_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf '%s' "$eq_demo" | python3 -c 'import json, sys; [print("TC_E2E_EQ_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf 'TC_E2E_CODES_USER=%s\nTC_E2E_CODES_PASSWORD=%s\n' "$codes_user" "$r10_password"
	printf '%s' "$codes_demo" | python3 -c 'import json, sys; [print("TC_E2E_CODES_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf 'TC_E2E_INSTR_USER=%s\nTC_E2E_INSTR_PASSWORD=%s\n' "$instr_user" "$r10_password"
	printf '%s' "$instr_demo" | python3 -c 'import json, sys; [print("TC_E2E_INSTR_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
	printf 'TC_E2E_INV_USER=%s\nTC_E2E_INV_PASSWORD=%s\n' "$inv_user" "$r10_password"
	printf '%s' "$inv_demo" | python3 -c 'import json, shlex, sys; [print("TC_E2E_INV_%s=%s" % (k.upper(), shlex.quote(str(v)))) for k, v in json.load(sys.stdin).items()]'
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "e2e ready on $SITE: smoke user $user ($STATION), T4 user $t4_user ($T4_STATION), set $set_id (credentials in $ENV_FILE)"
