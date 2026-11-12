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

# TẠM tới PR 3: vnstock đã gỡ khỏi requirements.txt (11/2026); máy dev có thể
# còn cài nên vẫn mồi nếu có.
with warnings.catch_warnings(record=True):
    try:
        import vnstock  # noqa: F401
    except ImportError:
        pass

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _khong_goi_mang(request, monkeypatch):
    """Không test nào trong bộ mặc định được gọi mạng thật (12/11/2026: test cũ
    còn vá lớp vnstock đã gọi thẳng iq.vietcap.com.vn và treo vì thử lại/nghỉ
    của cầu chì). Test cần mạng đánh dấu @pytest.mark.network."""
    if request.node.get_closest_marker("network"):
        return
    from tests.vci_fixtures import block_network
    block_network(monkeypatch)


@pytest.fixture(autouse=True)
def _gia_dinh_co_vnstock(monkeypatch):
    """TẠM tới PR 3: build_warehouse bỏ qua giai đoạn còn cần vnstock khi máy
    không cài (ingest_market.VNSTOCK_CO_SAN). Test cũ kiểm hành vi chọn giai
    đoạn như trước, nên mặc định coi như có vnstock để kết quả không phụ thuộc
    máy chạy; tests/test_giai_doan_chua_chuyen.py tự đặt giá trị."""
    from src import ingest_market
    monkeypatch.setattr(ingest_market, "VNSTOCK_CO_SAN", True)
