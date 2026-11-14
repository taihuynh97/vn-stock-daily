"""Lấy dữ liệu thẳng từ nguồn (Vietcap, Vietcombank), không qua thư viện trung gian.

Thay vnstock từ 11/2026: vnstocks.com ngừng phát hành 4.x (HTTP 410 từ
10/11/2026). Endpoint Vietcap là API công khai của web giao dịch, không cần
API key. Đầu ra các hàm ở đây được ingest_market chuẩn hoá; hợp đồng dữ liệu
nạp warehouse được khoá bằng test so với đáp án chụp từ vnstock 4.0.9
(tests/fixtures/vci).
"""
