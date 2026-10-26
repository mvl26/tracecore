# Chạy song song (bench run-parallel-tests, CI chia shard): mỗi shard tự tạo bản ghi test của các DocType này trước
# khi chạy, vì test_dependencies của module khác có thể nằm ở shard khác (Employee thử dùng _Test Company)
global_test_dependencies = ["Company"]
