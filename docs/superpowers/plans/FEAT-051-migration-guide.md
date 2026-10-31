# FEAT-051 Hướng dẫn migration cho site đang chạy (Amendment A-64)

Áp dụng cho site `miyano` (yhct) trên VPS, bench `/home/mvl/frappe-bench`, chạy bằng user `mvl`. Mọi lệnh dưới đây do **người vận hành** chạy, theo thứ tự. Site dùng chung với erpnext, hrms và các app khác nên `migrate` ảnh hưởng cả site.

## Trước khi bắt đầu

- Chọn giờ không có người thao tác trạm. Báo người dùng site.
- Code trên VPS đang ở `da057ce`, cũ hơn `develop` 56 commit. Lần cập nhật này kéo cả phần đó, gồm chất thải (FEAT-047..050), sổ tiệt khuẩn (FEAT-007), xuất hồ sơ (FEAT-012).
- Phải có PR FEAT-051 đã merge vào `develop`.
- Bước 4 (CSV năng lực) cần R02 duyệt trước giờ chuyển đổi.

## Bước 0. Kiểm tra trước (chỉ đọc)

```bash
cd /home/mvl/frappe-bench
sudo -u mvl bench --site miyano backup --with-files
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.preflight
```

`preflight` in số bản ghi (`Station Competency`, Equipment, Sterile Location, Step Gate Result, Zone Station), chứng từ đã phát sinh ở từng trạm, chứng từ đang dở (Wash Batch đang chạy, bản nháp), số xung đột đồng bộ đang mở. **Lưu lại kết quả** để đối soát ở bước 5.

Trước khi chuyển:
- Đồng bộ hết hàng đợi offline của kiosk và PDA. Lệnh ghi còn trong hàng đợi theo nghĩa trạm cũ có thể bị từ chối sau chuyển đổi.
- Hoàn tất hoặc hủy chứng từ nháp gắn trạm sẽ đổi chức năng.
- Ghi tên file backup vừa tạo ở `sites/miyano/private/backups/`.

## Bước 1. Cập nhật code và migrate

```bash
cd /home/mvl/frappe-bench/apps/tracecore
sudo -u mvl git fetch upstream
sudo -u mvl git merge --ff-only upstream/develop
cd /home/mvl/frappe-bench
sudo -u mvl bench --site miyano migrate
sudo -u mvl bench build --app tracecore
sudo supervisorctl restart all
```

`migrate` chạy ba patch, chạy lại không đổi thêm gì:

| Patch | Việc |
| --- | --- |
| `a64_configurable_stations` | Tạo danh mục chức năng và loại khu mặc định. Gán chức năng cho trạm theo mã cũ (T2 → nạp và dỡ máy rửa, T5 → nạp và dỡ máy tiệt khuẩn, T5b → dỡ máy tiệt khuẩn). Đặt số trạm từ mã cũ. Chép `station_step` sang `legacy_step`. Đổi khóa bài hướng dẫn trạm. Xóa Property Setter tạm `Zone Station-station_step-options`. |
| `a64_zone_type_next_zone` | Chỉ có tác dụng với site đã chạy bản đầu của A-64, không đổi gì trên site mới. |
| `a64_catalog_manual_wash` | Bổ sung chức năng Rửa thủ công. |

Trạm có mã ngoài bảng ánh xạ (T9, T10 từ Property Setter) không được gán chức năng, patch ghi vào Error Log và không báo lỗi. Sơ đồ riêng của site áp ở bước 3.

## Bước 2. Kiểm tra sau migrate

```bash
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.preflight
```

Phải thấy:
- Số bản ghi `Station Competency`, Equipment, Sterile Location, Step Gate Result **bằng** bước 0.
- Mỗi trạm đã có chức năng, `temp_property_setter` là `false`.
- Mở `/app/tracecore` bằng tài khoản R10: thấy các trạm, mở được màn trạm.

## Bước 3. Áp sơ đồ 10 trạm của yhct

Sơ đồ nằm ở `tracecore/setup/yhct_plan.json`: T1 đến T10 theo yêu cầu, thêm một trạm quét sử dụng ở khu khoa không đánh số.

Chạy thử trước. Chế độ này hoàn tác toàn bộ sau khi chạy, lỗi validate nếu có sẽ hiện ra ở đây:

```bash
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.apply_yhct --kwargs "{'dry_run': 1}"
```

Đọc kết quả. Với mỗi trạm có chứng từ đã phát sinh mà chức năng đổi, kết quả ghi `replaced`: trạm cũ bị **tắt** (không xóa), trạm mới mang cùng số T được tạo với mã `TR-` kế tiếp. Trạm mới cần **in lại nhãn QR**. Khi nào thấy kế hoạch đúng thì áp thật:

```bash
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.apply_yhct --kwargs "{'dry_run': 0}"
```

Script ghi một dòng Audit Log tóm tắt. Trạm trống chứng từ thì đổi tên, vùng, chức năng ngay trên trạm cũ.

## Bước 4. 98 bản ghi Station Competency

Năng lực gắn với người ở một công việc, nên nghĩa các trạm đổi thì năng lực phải được duyệt lại. Không bản ghi nào bị xóa.

Xuất file cho R02:

```bash
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.competency_csv --args "['/home/mvl/f051-competency.csv']"
```

R02 mở file, với mỗi dòng điền:
- `approved`: `1` nếu năng lực chuyển sang trạm mới, `0` nếu không giữ.
- `new_stations`: các trạm mới, cách nhau dấu `;` (cột `suggested_stations` gợi ý trạm cùng chức năng cũ).

Thiếu quyết định ở bất kỳ dòng nào thì cả file bị từ chối. Chạy thử rồi áp thật:

```bash
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.apply_competency_csv --args "['/home/mvl/f051-competency.csv']" --kwargs "{'dry_run': 1}"
sudo -u mvl bench --site miyano execute tracecore.setup.migrate_a64.apply_competency_csv --args "['/home/mvl/f051-competency.csv']" --kwargs "{'dry_run': 0}"
```

Bản cũ chuyển `is_active = 0` kèm lý do `A-64`, giữ làm lịch sử. Bản mới giữ chứng chỉ bắt buộc, người đánh giá và hiệu lực. **Trong lúc chờ duyệt, nhân viên có thể không đăng nhập được trạm mới**, nên chốt CSV trước giờ chuyển đổi.

## Bước 5. Đối soát

- Chạy lại `preflight`: số `Station Competency` hoạt động khớp với CSV, Equipment, Sterile Location, Step Gate Result không đổi.
- Equipment `zone_in` và `zone_out` còn trỏ đúng khu (khu không bị đổi hay xóa).
- Đi thử **một bộ dụng cụ** qua đủ 10 trạm trên giao diện: tiếp nhận, nạp máy rửa, dỡ máy rửa, lắp ráp, đóng gói, nạp máy tiệt khuẩn, dỡ máy tiệt khuẩn và giải phóng, nhập kho, cấp phát, sử dụng.
- Thử một trạm đóng gói thứ hai: hai trạm Đóng gói 1 và 2 đều mở được màn đóng gói.

## Quay lui

Cách chắc chắn là khôi phục backup của bước 0. **Mọi dữ liệu phát sinh sau backup sẽ mất**, nên quyết định sớm, trước khi có người thao tác trở lại.

```bash
cd /home/mvl/frappe-bench
sudo -u mvl bench --site miyano restore sites/miyano/private/backups/<file-database>.sql.gz --with-public-files <file-public>.tar --with-private-files <file-private>.tar
cd apps/tracecore && sudo -u mvl git checkout da057ce
cd ../.. && sudo -u mvl bench build --app tracecore && sudo supervisorctl restart all
```

Patch không xóa cột `station_step`, nhưng không có lệnh hoàn tác riêng, vì vậy không nên quay lui bằng cách sửa tay.

## Sau khi xong

- Xóa khóa SSH tạm khỏi `/root/.ssh/authorized_keys` trên VPS nếu đã cấp cho việc này.
- Cột `legacy_step` giữ một bản phát hành rồi bỏ ở amendment sau.
