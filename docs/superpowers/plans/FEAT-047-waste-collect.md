# FEAT-047 Loại chất thải và thu gom theo khoa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps dùng checkbox (`- [ ]`).

**Goal:** R02/R10 khai báo Loại chất thải; R07 tại trạm thu gom quét thẻ người giao, nhập loại, số túi, kg, xác nhận → phiếu ghi sổ, mỗi túi/thùng có mã QR `CT-` và nhãn in tại trạm, tính giờ lưu từ lúc thu gom.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-047; `docs/srs.md` FR-M10-01 (.1–.5), FR-M10-02 (.1–.6), BRU-WST-001, BRU-WST-002, BRU-ID-006; `docs/use-cases.md` UC-34; `docs/ux-foundations.md` SCR-38; `docs/architecture.md` §5.3 (Waste Type, Waste Container, Waste Collection), §5.3.3 (`CT-`, `TG-`), ADR-013.

**Nhánh:** `feat/FEAT-047-waste-collect` cắt từ `develop` (b7c87f8), bench `~/tracecore-f043`, site test `test_f043`. Không đụng `~/tracecore-dev` (tab song song). Số amendment: **A-60** (A-55 FEAT-008, A-56 FEAT-013, A-57 FEAT-007, A-58 FEAT-012, A-59 loại chứng chỉ tự điền).

## Quyết định (Amendment A-60)

Người dùng chốt W1–W4 ngày 30/10/2026; W5–W14 là chi tiết hiện thực theo tài liệu, chủ đầu tư chưa duyệt.

| # | Quyết định |
| --- | --- |
| W1 | Nhãn `CT-` in tại trạm qua agent như nhãn lô rửa (`core.print`, Print Job). Trạm/PDA không có máy in → đẩy lệnh sang máy in của trạm `WST` khác đang hoạt động; không có nữa → Print Job `Waiting` kèm cảnh báo, phiếu vẫn ghi sổ. |
| W2 | Chưa offline: mất mạng thì màn hiện offline và không ghi (UC-34 A3 và dải mã `CT-` cấp trước để FEAT sau). Lệch ux-foundations "PDA offline bắt buộc": ghi nhận là gap có chủ đích. |
| W3 | Phân loại sai tạo ngay NC tối thiểu: `incident_type` mới `Waste Misclassification` qua hook `tracecore_waste_nc` (M10 không import M2); FEAT-050 bổ sung `incident_category`, `waste_type`, báo cáo. |
| W4 | Biên nhận: quét lại thẻ người giao (`acknowledged_by`, `acknowledged_at`) và in Print Format `TC Waste Receipt` khổ A5. Không có ký cảm ứng. |
| W5 | Bước trạm mới `WST` (`Zone Station.station_step`, `zones`: khu Waste → `WST`; `navigation`: R07). FEAT-048/049 thêm chế độ trên cùng màn. |
| W6 | `Waste Type`: autoname `field:type_name`; `waste_group` 7 nhóm TT 20/2021 (Sharp Infectious, Non-sharp Infectious, High-risk Infectious, Anatomical → Yellow; Hazardous Non-infectious → Black; General → Green; Recyclable → White); `color_code` read-only do server gán; bắt buộc nhóm, `packaging` (Link Item), `std_weight_kg`, `max_storage_hours`; `max_storage_cold_hours` tùy chọn. |
| W7 | Giờ lưu mặc định 48 / 168 giờ; giá trị khác mặc định cần `storage_override_reason` (FR-M10-01.3). |
| W8 | `Waste Type Rate` (child: `effective_from`, `rate_per_kg`): chỉ thêm dòng, dòng cũ không sửa/xóa, không trùng ngày (FR-M10-01.4). |
| W9 | `Waste Collection`: naming `TG-.YYYY.-.#####`, submittable; `delivered_by` Link Employee từ thẻ, khoa lấy từ Employee của thẻ, không nhận khoa do client gửi. Thẻ không hợp lệ hoặc nhân viên không thuộc khoa đang dùng → từ chối + Audit `Reject` (FR-M10-02.5). |
| W10 | Dòng phiếu: `waste_type`, `qty`, `weight_kg`, `weight_source` (Scale/Manual/Converted), `weight_confirmed`, `misclassified`, `misclass_note`, `photo`. Server bắt buộc tick xác nhận khi Manual (đồ vải chỉ kiểm ở client). `total_kg` (UC-34 A2) chia theo `qty × std_weight_kg`, nguồn Converted. |
| W11 | `Waste Container`: `CT-YYMMDD-NNNNN` do `code_registry.next_container_code`; kg dòng chia đều cho túi, phần dư vào túi cuối; `storage_due` = `collected_at` + `max_storage_hours`. Trạng thái `Collected`, `Held`; FEAT-048/049 thêm trạng thái sau. |
| W12 | Dòng `misclassified`: túi `Held`, không tính vào tổng kg phiếu, tạo NC. R02 mở bằng `v1.waste.release_held` (Desk) → `Collected`, cộng kg vào `released_kg` của phiếu đã ghi sổ. |
| W13 | Ảnh dòng phiếu (FR-M10-02.2, Should) chỉ có trên Desk ở FEAT-047; kiosk chưa chụp ảnh. UC-34 A1 (nhãn in trước theo định mức) phụ thuộc FR-M10-08 nên để FEAT-050. |
| W14 | RPC `tracecore.v1.waste.catalog`, `giver`, `collect`, `acknowledge`, `release_held`. Mã QR túi không nhập tay: `Waste Container` chỉ tạo qua dịch vụ. Quyền: Waste Type R02, R10 RW; R01, R07, R09 R. Waste Collection R07 RWS; R02 RA; R01, R09, R10 R. Waste Container R07, R02, R01, R10 R. |

## Tasks

- [x] **Task 0 — Tài liệu:** A-60, ghi chú dòng FEAT-047 trong implementation-plan, plan này.
- [x] **Task 1 — Nền:** bước `WST`, `next_container_code`, nhãn `Waste Container` + patch mẫu nhãn, loại NC + hook (FR-M10-01.5, FR-M10-02.4, BRU-ID-006).
- [x] **Task 2 — `Waste Type` + `Waste Type Rate`** (FR-M10-01, .1–.4; BRU-WST-001, BRU-WST-002).
- [x] **Task 3 — `Waste Collection`, Line, `Waste Container`, dịch vụ `waste/collection.py`** (FR-M10-02, .1, .3–.6; BRU-WST-001, BRU-WST-002).
- [x] **Task 4 — RPC `v1/waste.py`, quyền, Print Format biên nhận** (FR-M10-02.5, .6; W4, W14).
- [x] **Task 5 — Màn trạm `station_waste.js`** (SCR-38, FR-M9-14). Test tĩnh viết trước.
- [x] **Task 6 — Hoàn thiện:** `vi.csv`, `rtm.md`, launcher, ghi chú hiện thực; full test + diff-cover ≥ 70 %, lint; merge `develop` trước khi push.

## Acceptance (EARS, theo FR)

- AC1 Khi lưu Loại chất thải thiếu nhóm, bao bì hoặc giờ lưu, hệ thống phải từ chối và chỉ rõ trường thiếu (FR-M10-01.1).
- AC2 Khi chọn nhóm, hệ thống phải tự gán màu theo TT 20/2021 và không cho sửa (FR-M10-01.2).
- AC3 Khi đổi đơn giá, hệ thống phải giữ phiên bản cũ và thêm phiên bản có ngày hiệu lực (FR-M10-01.4).
- AC4 Khi xác nhận phiếu, hệ thống phải ghi sổ, sinh `CT-` cho từng túi, in nhãn và bắt đầu tính giờ lưu (FR-M10-01.5, .02.6).
- AC5 Nếu cân lỗi hoặc nhập tay, hệ thống phải bắt buộc xác nhận và ghi nguồn Manual (FR-M10-02.1).
- AC6 Nếu thẻ không hợp lệ hoặc không thuộc khoa, hệ thống phải từ chối và ghi log (FR-M10-02.5).
- AC7 Nếu dòng bị đánh dấu phân loại sai, hệ thống phải tạo NC và giữ túi tới khi R02 xác nhận (FR-M10-02.4).

## Ghi chú hiện thực

- **Lệch so với W12:** dùng `held_kg` thay `released_kg`: phiếu giữ riêng kg bị giữ; mở túi thì trừ `held_kg`, cộng `total_weight_kg`.
- **User Permission:** Employee gắn User sinh User Permission theo chính nhân viên đó, R07 không tạo được phiếu có `delivered_by` là người khác; `delivered_by`, `acknowledged_by` bật `ignore_user_permissions`.
- **Xác nhận cân nhập tay:** kiểm cả ở server (`WASTE_WEIGHT_UNCONFIRMED`), chặt hơn đồ vải; nguồn lạ tính là nhập tay.
- **Mã màu chỉ bằng chữ:** palette `--tc-*` không có màu riêng cho từng nhóm TT 20/2021, nên màn hiện chữ cỡ lớn (Vàng/Đen/Xanh/Trắng), không có ô màu.
- **`test_errors` có sẵn đỏ trên develop:** FEAT-008 thêm `ENV_READING_INVALID` thiếu trong bảng test; đã thêm.
- **Chưa làm (gap có chủ đích):** offline và dải mã `CT-` cấp trước (W2); nhãn in trước UC-34 A1; ảnh dòng phiếu trên kiosk (W13). Màn JS chỉ có test tĩnh, chưa xem trên trình duyệt, chưa E2E.
- **Exit code của test:** `bench run-tests --coverage` trả 0 dù có test fail; phải đọc dòng `FAILED`/`OK` trong log, không tin exit code.
- **Bài hướng dẫn trạm WST:** đã thêm khóa `WST` vào `station_help.STATION_KEYS`, bài mặc định và option `tc_station_key` khi gộp FEAT-013.

