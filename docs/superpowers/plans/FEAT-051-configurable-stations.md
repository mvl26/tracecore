# FEAT-051 Cấu hình vùng, trạm và chức năng trạm

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** vùng, trạm và chức năng trạm là dữ liệu cấu hình; site yhct chạy được sơ đồ 10 trạm mà không sửa code.

**Architecture:** tách ba nghĩa của T-code: số trạm (`Zone Station.station_no`), chức năng (`Station Function`, bảng con trên trạm), cổng (`step_gate.STEPS` T1..T5 giữ nguyên, thành mã nội bộ). `core.zones` đọc quy tắc từ `Zone Type`; mọi RPC kiểm trạm qua `zones.station_has_function`.

**Tech Stack:** Frappe v15, Python 3.11, JS Page `station`, `FrappeTestCase`.

**Spec:** Amendment A-64 (`docs/architecture.md`, Revision History và §5.3.1).

## Global Constraints

- `core.step_gate` là nơi duy nhất đổi trạng thái Set Unit; `Step Gate Result` không migrate.
- Thứ tự 5 cổng không cấu hình được (Q5). Quyền RPC ở `_common.py` không cấu hình được.
- Mọi chuỗi qua `_()`/`__()`, bản dịch `translations/vi.csv`. Màn hình không hiện mã cổng T1..T5.
- Màn trạm: nút ≥ 48 px, ≤ 3 chạm, chỉ token `--tc-*`.
- Patch chạy lại được, không xóa cột, không đụng site cụ thể. Script yhct riêng, có `dry_run`, chỉ chạy khi được duyệt.
- `bench run-tests` trả exit 0 cả khi fail: phải đọc log.

## Review Focus

1. Trạm hai chức năng (ASSEMBLE + PACK) đang ở tab này, quét mã của tab kia: không ghi nhầm chứng từ, báo lỗi của màn hiện tại. Test ở Task 5.
2. Trạm không có chức năng nào: mở được, hiện màn tra cứu chung, RPC ghi bị từ chối. Test ở Task 3.
3. Tắt chức năng đang gán cho trạm hoạt động: từ chối và liệt kê trạm. Test ở Task 1.
4. Bỏ chức năng khỏi Zone Type khi còn trạm hoạt động dùng nó: từ chối. Test ở Task 1.
5. Patch chạy trên site có `station_step` = T9/T10 từ Property Setter: không gán chức năng, ghi log, không lỗi. Test ở Task 6.

---

### Task 1: Danh mục và `core.zones` đọc cấu hình (AC-5; FR-M9-03; BRU-FLOW-001)

**Files:** Create doctype `station_function`, `zone_type`, `zone_type_function`, `zone_station_function` (module Admin Reports). Modify `core/zones.py`, `setup/seed.py`, `tracecore/modules`. Test `core/tests/test_zones.py`.

**Interfaces (Produces, `core.zones`):**
`allowed_functions(zone_type) -> tuple[str, ...]`; `check_functions(zone_type, functions) -> None`; `station_functions(station) -> list[str]` (theo `process_order`); `station_has_function(station, *functions) -> bool`; `stations_with_function(function, zone=None) -> list[str]` (theo `station_no`, chỉ trạm hoạt động); `gate_labels() -> dict[str, str]`; `gate_label(step) -> str`; `next_zone_type(zone_type)`; `check_pass_through(zone_in, zone_out)`; `missing_functions() -> list[str]`. `seed.ensure_station_catalog()`.

- [ ] Viết test: mặc định khớp bảng A-64; thêm dòng Zone Type Function làm `check_functions` chấp nhận; lỗi nêu tên vùng và tên chức năng; `flow_order` quyết định `next_zone_type`; Review Focus 3, 4.
- [ ] Chạy test, thấy fail.
- [ ] Hiện thực. Không cache: truy vấn theo khóa, test rollback không bị dữ liệu cũ.
- [ ] Chạy test pass, commit.

### Task 2: `Zone Station` theo chức năng (AC-1, AC-2, AC-5, AC-9; FR-M9-03, FR-M9-03.3)

**Files:** Modify `zone_station.json/.py/.js`, `setup/seed.py`, `v1/zone.py`, `sterile_location.py`, `waste_storage_location.py`, `tests/factories.py`. Test `test_zone_station.py`, `test_zone_api.py`, `test_seed.py`.

- [ ] Test: `station_no` trùng giữa trạm hoạt động bị từ chối; số vượt 8 được; tạo đủ 10 trạm yhct; tắt vùng còn trạm/máy/kệ bị từ chối kèm danh sách; Sterile Location đòi vùng cho phép PUTAWAY; Waste Storage Location đòi vùng cho phép WASTE; số trái thứ tự chức năng chỉ cảnh báo.
- [ ] Chạy test, thấy fail.
- [ ] `zone_type` thành Link; `station_step` thành `legacy_step` (read_only, hidden); `is_active` hiện cho cả vùng. RPC `v1.zone.allowed_functions`, `v1.zone.chain_status`. Form lọc chức năng theo vùng, báo chuỗi còn thiếu.
- [ ] Chạy test pass, commit.

### Task 3: Service và RPC kiểm theo chức năng (AC-3, AC-4)

**Files:** Modify `v1/_common.py` (`require_step` nhận mã chức năng), `reprocessing/{receiving,washing,assembly,packing,sterilizing,storage,issuing,usage}.py` (thêm `FUNCTION`/`LOAD_FUNCTION`; `STEP` giữ là mã cổng), `v1/{receive,wash,assembly,pack,load,putaway,issue,usage,printer,linen,laundry,waste,par/override}.py`, `waste/collection.py`, `v1/{__init__,station,sync,codes,navigation}.py`, `ui/station_help.py`, `setup/provision.py`, `hr/competency.py`, fixture `tc_station_key`.

**Interfaces:** thông tin trạm trả `functions`, `station_no`, `screens`, `gate_labels` thay `step`; `sync.snapshot` trả `function`.

- [ ] Test: mỗi RPC ghi từ chối `STATION_WRONG_STEP` ở trạm thiếu chức năng; hai trạm cùng PACK đều qua; trạm WASH_LOAD không dỡ được máy hai cửa, trạm WASH_UNLOAD ở cửa ra dỡ được; Review Focus 2.
- [ ] Chạy test, thấy fail.
- [ ] Hiện thực; `_next_station` dùng `stations_with_function`; thông điệp chuyển sang tên chức năng.
- [ ] Toàn bộ test app pass, commit.

### Task 4: Thông điệp không còn T-code (AC-3)

**Files:** `core/step_gate.py` (`check`, `check_stored` hiện `gate_label`), `reprocessing/*`, `instrument/{disposal,thresholds}.py`, `translations/vi.csv`.

- [ ] Test: `check` trả lý do chứa tên chức năng, không chứa `T4`; `redo_step` vẫn là mã cổng.
- [ ] Thấy fail, hiện thực, pass, commit.

### Task 5: Page `station` theo màn (AC-3, AC-10)

**Files:** `ui/page/station/station.js`, `public/js/station_t{2,3,4,5,5b,6}.js`, `public/js/station_help.js`, `competency_matrix.js`. Test `tests/test_station_page.py`.

- [ ] Test tĩnh: `station.js` không còn `station.step ===`; có `SCREENS` theo `screen_key`; tab đổi màn; Review Focus 1.
- [ ] Hiện thực: `screens[]` nhiều phần tử thì hiện tab; T2 chỉ hiện chế độ theo chức năng trạm; T5 tương tự; nhãn cổng dùng `gate_labels`.
- [ ] Build assets, test pass, thử tay, commit.

### Task 6: Migration (AC-8)

**Files:** `patches/v0_1/a64_configurable_stations.py`, `patches.txt`, `setup/migrate_a64.py` (`preflight`, `apply_yhct(dry_run=True)`, `competency_csv`, `apply_competency_csv(path, dry_run=True)`). Test `tests/test_a64_migration.py`.

- [ ] Test: map đúng bảng A-64; chạy hai lần không đổi; Property Setter bị xóa; số bản ghi Competency, Equipment, Sterile Location, Step Gate Result giữ nguyên; Review Focus 5; CSV không tự cấp năng lực khi R02 chưa duyệt.
- [ ] Thấy fail, hiện thực, pass, commit.

### Task 7: Luồng 10 trạm và cổng hoàn tất (AC-6, AC-7, AC-10; BRU-FLOW-002, BRU-FLOW-003, BRU-FLOW-004)

**Files:** Create `reprocessing/tests/test_flow_configured.py`.

- [ ] Test: cấu hình yhct, một bộ qua RECEIVE → ... → ISSUE, đủ 5 cổng; bỏ cổng bị chặn; hai trạm PACK dùng máy in và dải mã riêng, bản nháp lắp ráp mở tiếp ở trạm kia; `test_flow_t1_t8` không đổi kịch bản.
- [ ] Chạy toàn app, diff-cover ≥ 70 %, `pre-commit run --all-files`, commit.

### Task 8: Hướng dẫn migration

**Files:** Create `docs/superpowers/plans/FEAT-051-migration-guide.md`.

- [ ] Viết các bước preflight, patch, yhct, CSV, đối soát, quay lui kèm lệnh thật. Commit.
