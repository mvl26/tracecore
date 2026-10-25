# FEAT-040 Test hằng ngày và khóa máy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Máy tiệt khuẩn/máy rửa chỉ tạo được mẻ/lô khi đã có test hằng ngày Đạt, kiểm định còn hạn, không Sửa chữa; test Không đạt khóa máy; R02 mở khóa tạm ≤ 24 giờ có lý do (không với thiết bị áp lực quá hạn kiểm định).

**Architecture:** DocType `Daily Test` (M5, DT-DAILYTEST) + dịch vụ `equipment/daily_test.py` (một hàm `equipment_block` đăng ký vào hook `tracecore_load_equipment_checks` của T5 và hook mới `tracecore_wash_equipment_checks` của T2; M2 không import M5). Trạng thái máy vẫn chỉ đổi qua `equipment.status.set_status`; thêm trường khóa/mở khóa tạm trên `Equipment`. RPC `tracecore.v1.daily_test.*`; màn SCR-23 là chế độ "Test hằng ngày" của màn T5 và T2.

**Tech Stack:** Frappe v15, `IsolatedTestCase`, Page `station`.

**Spec:** `docs/srs.md` FR-M5-05 (.1–.3), FR-M5-06 (.1–.2); `docs/use-cases.md` UC-23; `docs/architecture.md` §5.3 (DT-DAILYTEST), WF-07; Amendment A-21.

## Global Constraints
- RPC ghi dùng `@station_session` + `@idempotent`, `client_ts` ISO 8601 có offset; từ chối nghiệp vụ là `BlockedError` → body lỗi + Audit `Reject`.
- Chỉ R02 mở khóa tạm; lý do bắt buộc, thời hạn 1–24 giờ, Audit `Override`; thiết bị áp lực (máy hấp hơi nước) quá hạn kiểm định thì không ai mở khóa tạm.
- Chuỗi qua `_()`/`__()` có bản dịch; UI chỉ token `--tc-*`; lỗi chặn là `alert-error` inline.
- Không làm: NC tự tạo (FEAT-030, chỉ cờ `nc_pending`), thông báo R02 (FEAT-010), kế hoạch kiểm định/bảo trì (FEAT-039), dashboard "máy chưa test" (FEAT-006; chỉ có RPC `overview`).

## Quyết định (Amendment A-21, tạm — chờ chủ đầu tư)
| # | Quyết định |
| :- | :- |
| E1 | Test bắt buộc theo loại máy: hấp hơi nước = `bowie_dick` + `leak`; máy rửa/siêu âm = `washer_cleaning`; plasma và loại khác không có test ngày (plasma dùng chỉ thị hóa học từng mẻ, FR-M5-05.2). Một loại test "đạt trong ngày" khi lần ghi mới nhất của ngày hôm nay là Đạt. |
| E2 | Ghi test cần lô test còn hạn (`TEST_LOT_EXPIRED`) và đúng loại test cho loại máy (`TEST_INVALID`); thiếu ảnh Bowie-Dick chỉ cảnh báo (UC-23 E3). |
| E3 | Test Không đạt: máy `Locked` (`lock_reason = Daily Test`), `nc_pending = 1`, Audit; test Đạt đủ bộ test của ngày thì tự mở lại máy bị khóa vì test. |
| E4 | Khóa theo FR-M5-06 do `equipment_block`: kiểm định quá hạn (`inspection_due` < hôm nay) → `EQUIPMENT_INSPECTION_EXPIRED`; thiếu test ngày → `DAILY_TEST_REQUIRED` kèm danh sách; máy `Locked`/`Repair` đã bị chặn sẵn bởi `EQUIPMENT_NOT_READY`. |
| E5 | Mở khóa tạm: R02, lý do, 1–24 giờ; đặt `Equipment.unlock_until`, `unlocked_by`, `unlock_reason`, trạng thái `Ready`; bỏ qua `DAILY_TEST_REQUIRED` và kiểm định quá hạn của máy không áp lực trong thời hạn; hết hạn thì chặn lại (không cần job). Máy `Repair` và máy hấp quá hạn kiểm định → `UNLOCK_NOT_ALLOWED`. |

## Review Focus
- Máy chưa test ngày nào tạo mẻ/lô: bị chặn, lý do và danh sách test thiếu hiện ở màn tạo mẻ.
- Test Đạt hôm qua không có giá trị hôm nay; lô test hết hạn không dùng được.
- Mở khóa tạm hết hạn đúng giờ; hai lần mở khóa không kéo dài vượt 24 giờ từ lần sau.
- R05/R03 gọi mở khóa tạm: chặn, không ghi.

## Tasks
### Task 1: DocType Daily Test + trường khóa của Equipment
**Files:** Create `tracecore/equipment/doctype/daily_test/{__init__,daily_test.json,daily_test.py}`; Modify `tracecore/equipment/doctype/equipment/{equipment.json,equipment.py}`, `tracecore/tests/factories.py` (`make_equipment(daily_tested=True)`).
### Task 2: Dịch vụ `equipment/daily_test.py` + hook + mã lỗi
**Interfaces:** `record(equipment, test_type, result, station, lot, lot_expiry, photo=None, employee=None, note=None, client_ts=None) -> dict`, `equipment_block(equipment) -> Block | None`, `unlock_temp(equipment, reason, hours, station=None, client_ts=None) -> dict`, `overview() -> list[dict]`. Mã mới: `DAILY_TEST_REQUIRED`, `EQUIPMENT_INSPECTION_EXPIRED`, `UNLOCK_NOT_ALLOWED` (409), `TEST_INVALID`, `TEST_LOT_EXPIRED`, `UNLOCK_INVALID` (422).
### Task 3: RPC `tracecore.v1.daily_test.{overview,record,unlock_temp}`
### Task 4: Màn SCR-23 (chế độ "Test hằng ngày" của T5/T2)
### Task 5: Tài liệu, kiểm tra, PR (base `feat/FEAT-023-t5b-unload`)

## Gap ghi nhận
NC tự tạo, thông báo R02, dashboard máy chưa test, R03 ghi test máy rửa (ma trận SEC chỉ cho R05/R02 ghi), kế hoạch kiểm định (FEAT-039).
