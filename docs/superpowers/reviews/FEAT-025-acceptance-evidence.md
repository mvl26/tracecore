# FEAT-025 T6 Kho vô khuẩn — bằng chứng nghiệm thu

Plan: `docs/superpowers/plans/FEAT-025-t6-sterile-storage.md`. Amendment: architecture A-08.

| Yêu cầu | Hành vi | Test |
| :- | :- | :- |
| FR-M2-13 | Quét Cycle ID + mã kệ → Pack `In Sterile Stock`, có vị trí, có Sterile Putaway ghi sổ | `reprocessing/tests/test_storage.py::TestPutaway`, `v1/tests/test_putaway_api.py::TestScan` |
| FR-M2-13.1 | Gói chưa Released / bộ thiếu cổng bị từ chối, nêu bước thiếu | `test_putaway_rejects_pack_not_released`, `test_putaway_rejects_set_with_missing_gates_and_lists_them` |
| FR-M2-13.2 | Dashboard: tồn theo loại bộ/vị trí, gói hết hạn trong 7 ngày | `TestOverviewAndFefo::test_overview_*` |
| FR-M2-13.3, .4 | FEFO gợi ý và cảnh báo gói hạn xa | `test_fefo_*` |
| FR-M2-13.5 | Mã kệ không tồn tại bị từ chối (404) | `test_putaway_rejects_unknown_location`, `test_unknown_shelf_is_404_and_audited` |
| FR-M2-14 | Quá hạn lúc 00:00 hoặc báo rách → Pack Void, Set Unit `Awaiting Receipt` | `TestDamagedAndExpiry`, `core/tests/test_step_gate_storage.py` |
| FR-M2-14.2 | Danh sách gói cần đưa về khu bẩn (dữ liệu; in qua FEAT-007) | `test_return_list_*` |

BRU: BRU-FLOW-004, BRU-REP-008, BRU-ID-003, BRU-ID-001 (marker `@bru`).

Kết quả chạy (22/10/2026, `test_site`): full suite 1100 test, 1 fail không liên quan (`test_system_settings_localized`: site `en`, không kiểm trên baseline). Coverage changed-code (`diff-cover`, so với `328398d`): 97 %. `ruff check`/`ruff format`, `prettier`, `eslint` sạch.

Chưa có: e2e Playwright và thử màn SCR-11 trên trình duyệt (UI mới kiểm cú pháp và bằng test hook/script); sinh nhãn QR in cho kệ `KE-` (nút in thuộc FEAT-005).
