"""Cấu hình pytest chung cho toàn bộ test suite.

vnstock/vnai tự kiểm tra bản mới hơn qua mạng NGAY LÚC IMPORT package
`vnstock` và phát UserWarning ("📦 Vnstock/Vnai X.Y.Z is available...") nếu
PyPI có bản mới hơn — cảnh báo của thư viện ngoài, không phải của ta.

`pytest.ini`'s filterwarnings một mình KHÔNG chặn được nó: ngay trước khi
warn(), vnstock tự gọi warnings.simplefilter("always", UserWarning) (xem
vnstock/core/utils/upgrade.py::_display_message), việc này chèn một filter
"always" bắt MỌI UserWarning lên ĐẦU danh sách filter, đè lên filter
`ignore` hẹp trong pytest.ini. Bộ lọc thật sự dập được 2 warning này nằm ở
ĐÂY, không phải ở pytest.ini.

CỐ Ý KHÔNG đặt khối này trong src/ingest.py hay src/ingest_market.py (thử
ở đó trước, đã bị revert): catch_warnings(record=True) không lọc theo
message/category, nó chuyển hướng TOÀN BỘ cảnh báo phát sinh trong khối —
kể cả DeprecationWarning thật về tương thích phụ thuộc — sang một list bị
vứt đi. Đặt trong module sản xuất nghĩa là build_warehouse.py/scripts/*
cũng bị nuốt cảnh báo thật vĩnh viễn, đi ngược đúng nguyên tắc "không che
giấu thất bại" mà src/dq.py được viết ra để bảo vệ. Đặt ở đây, cảnh báo chỉ
bị nuốt trong phạm vi chạy test — hành vi sản xuất không đổi.

Vì `vnstock` được cache trong sys.modules sau lần import đầu (module-level,
không guard theo _initialized), "mồi" import ở đây một lần là đủ: mọi import
`vnstock.api.*` sau đó trong suite (từ src/ingest.py, src/ingest_market.py)
chỉ trả về module đã cache, không init/in lại.
"""
import warnings

with warnings.catch_warnings(record=True):
    import vnstock  # noqa: F401
