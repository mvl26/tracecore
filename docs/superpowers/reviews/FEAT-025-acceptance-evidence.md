# FEAT-025 T6 Kho vô khuẩn — bằng chứng nghiệm thu

Plan: `docs/superpowers/plans/FEAT-025-t6-sterile-storage.md`. Amendment: architecture A-10 (đánh lại số khi đưa lên `develop`: A-08 thuộc FEAT-003, A-09 thuộc FEAT-015).

| Yêu cầu | Hành vi | Test | E2E SCR-11 (`tests_e2e/test_station_t6.py`) |
| :- | :- | :- | :- |
| FR-M2-13 | Quét Cycle ID + mã kệ → Pack `In Sterile Stock`, có vị trí, có Sterile Putaway ghi sổ | `reprocessing/tests/test_storage.py::TestPutaway`, `v1/tests/test_putaway_api.py::TestScan` | `test_t6_putaway_released_pack_without_taps` (0 chạm sau quét, badge Trong kho vô khuẩn, kệ trên thẻ gói) |
| FR-M2-13.1 | Gói chưa Released / bộ thiếu cổng bị từ chối, nêu bước thiếu | `test_putaway_rejects_pack_not_released`, `test_putaway_rejects_set_with_missing_gates_and_lists_them` | `test_t6_pack_not_released_is_blocked_with_inline_red_alert` (alert-error inline kết quả → lý do → hành động, không modal/toast) |
| FR-M2-13.2 | Dashboard: tồn theo loại bộ/vị trí, gói hết hạn trong 7 ngày | `TestOverviewAndFefo::test_overview_*` | `test_t6_scan_box_on_top_with_stock_by_location_and_expiring`; tồn theo vị trí tăng sau nhập kho trong `test_t6_putaway_released_pack_without_taps` |
| FR-M2-13.3, .4 | FEFO gợi ý và cảnh báo gói hạn xa | `test_fefo_*` | — (RPC để FEAT-026 gọi, màn T6 không hiển thị) |
| FR-M2-13.5 | Mã kệ không tồn tại bị từ chối (404) | `test_putaway_rejects_unknown_location`, `test_unknown_shelf_is_404_and_audited` | `test_t6_unknown_shelf_keeps_pack_open` (giữ thẻ gói để quét kệ khác) |
| FR-M2-14 | Quá hạn lúc 00:00 hoặc báo rách → Pack Void, Set Unit `Awaiting Receipt` | `TestDamagedAndExpiry`, `core/tests/test_step_gate_storage.py` | `test_t6_report_torn_requires_reason_then_voids_pack` (lý do bắt buộc, gói Đã hủy hiệu lực, hết nút báo rách) |
| FR-M2-14.2 | Danh sách gói cần đưa về khu bẩn (dữ liệu; in qua FEAT-007) | `test_return_list_*` | gói vừa báo rách vào bảng "Gói cần đưa về khu bẩn" trong `test_t6_report_torn_requires_reason_then_voids_pack` |
| FR-M9-14, design.md STN | Ô quét trên cùng có focus; loading/empty/error/offline; nút ≥ 48 px, chữ ≥ 16 px | `tests/test_station_page.py` | `test_t6_scan_box_on_top_with_stock_by_location_and_expiring`, `test_t6_touch_targets_and_font_sizes`, `test_t6_offline_shows_offline_state` |

BRU: BRU-FLOW-004, BRU-REP-008, BRU-ID-003, BRU-ID-001 (marker `@bru`).

Kết quả chạy (22/10/2026, `test_site`): full suite 1100 test, 1 fail không liên quan (`test_system_settings_localized`: site `en`, không kiểm trên baseline). Coverage changed-code (`diff-cover`, so với `328398d`): 97 %. `ruff check`/`ruff format`, `prettier`, `eslint` sạch.

**Tích hợp FEAT-003 (sau khi đưa lên `develop` a3e9518, 22/10/2026):** RPC màn T6 (`v1.putaway.scan/overview/fefo`, `v1.pack.mark_damaged`) dùng `@station_session` như T4 (POST, `allow_guest`, token phiên trong body, đúng trạm; `@idempotent` chạy sau khi xác thực phiên). Test: `v1/tests/test_putaway_api.py::TestStationSession` (không token/token sai → `SESSION_INVALID` 401 kể cả Administrator và không ghi Idempotency Key; phiên trạm khác → `SESSION_STATION_MISMATCH` 403; Guest có phiên T6 nhập kho với actor là người của phiên, replay sau logout bị chặn). Client: `rpc()` gắn token cho `tracecore.v1.putaway.*`; `T6Storage.clearSession()` xóa gói/tồn/yêu cầu dở khi hết phiên và bỏ câu trả lời muộn (`scripts/tests/station_auth.test.js`, 18/18 pass).

Kết quả chạy sau tích hợp (`test_site` đã migrate): full suite 1301 test, 23 lỗi/fail đều ngoài FEAT-025 (inventory receipt import thiếu kho test, `test_count_sheet` gọi `pack.scan` không token, số dòng Audit Log khi tạo user, quyền S12, asset FEAT-015, savepoint `test_account`); toàn bộ test T6 pass. `diff-cover` so với `origin/develop`: 97 %. `pre-commit run --all-files` sạch.

**E2E Playwright SCR-11 (22/10/2026, site dev `tracecore-dev.local`, chromium headless, viewport kiosk 1366×768):** `tests_e2e/test_station_t6.py` đăng nhập Desk + OTP rồi quét thẻ trạm TR-006 (user `station-t6@…`, TC R06). Dữ liệu từ `scripts/e2e_prepare.sh` bước 10 (`devdata.ensure_t6_e2e_user`, `ensure_station_demo`, `ensure_t6_demo`: hai kệ `KE-`, gói Released, gói Packed, gói trong kho hạn 30 ngày, gói trong kho hạn 3 ngày; test `tests/test_devdata.py::TestT6DemoData`, `test_e2e_prepare_guard.py`). Kết quả: `7 passed in 17.80s` (ba lần liên tiếp, mỗi lần chuẩn bị lại dữ liệu); `test_station_t4.py` vẫn `5 passed`. Cùng đợt: bước 9 của `e2e_prepare.sh` (user `r02-settype-e2e`) chuyển sang `ensure_desk_users` vì `provision.desk_user` gọi thẳng bị guard FEAT-003 chặn.

Chưa có: sinh nhãn QR in cho kệ `KE-` (nút in thuộc FEAT-005); FEFO trên màn (FEAT-026).
