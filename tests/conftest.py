"""Cấu hình pytest chung cho toàn bộ test suite.

Từ 11/2026 dự án không còn dùng vnstock (gọi thẳng nguồn qua src/sources),
nên phần "mồi" import vnstock để dập cảnh báo cập nhật của nó đã được gỡ.
"""
import pytest


@pytest.fixture(autouse=True)
def _khong_goi_mang(request, monkeypatch):
    """Không test nào trong bộ mặc định được gọi mạng thật (12/11/2026: test cũ
    còn vá lớp vnstock đã gọi thẳng iq.vietcap.com.vn và treo vì thử lại/nghỉ
    của cầu chì). Test cần mạng đánh dấu @pytest.mark.network."""
    if request.node.get_closest_marker("network"):
        return
    from tests.vci_fixtures import block_network
    block_network(monkeypatch)
