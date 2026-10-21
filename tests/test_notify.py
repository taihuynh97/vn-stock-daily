"""Thông báo lỗi Telegram không được chứa bot token (repo public, 21/10/2026).

URL gọi API là https://api.telegram.org/bot<TOKEN>/sendMessage — `raise_for_status()`
và lỗi kết nối của requests đều in nguyên URL. GitHub chỉ che đúng chuỗi secret;
bản bị mã hoá URL (":" → "%3A") sẽ lọt vào log công khai.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src import notify

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")


def _assert_no_token(msg: str):
    assert TOKEN not in msg
    assert requests.utils.quote(TOKEN, safe="") not in msg
    assert "AAFakeTokenForTestsOnly" not in msg


def test_lỗi_http_không_lộ_token(capsys):
    resp = requests.Response()
    resp.status_code = 401
    resp._content = b'{"ok":false,"description":"Unauthorized"}'
    resp.url = f"https://api.telegram.org/bot{requests.utils.quote(TOKEN, safe='')}/sendMessage"
    with patch("src.notify.requests.post", return_value=resp):
        with pytest.raises(RuntimeError) as ei:
            notify.send("xin chào")
    _assert_no_token(str(ei.value))
    _assert_no_token(capsys.readouterr().out)
    assert "401" in str(ei.value)


def test_lỗi_mạng_không_lộ_token():
    err = requests.ConnectionError(
        f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded "
        f"with url: /bot{requests.utils.quote(TOKEN, safe='')}/sendMessage")
    with patch("src.notify.requests.post", side_effect=err):
        with pytest.raises(RuntimeError) as ei:
            notify.send("xin chào")
    _assert_no_token(str(ei.value))
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_gửi_thành_công_chia_nhỏ_tin_dài():
    ok = MagicMock(status_code=200)
    with patch("src.notify.requests.post", return_value=ok) as post:
        notify.send("x" * (notify.LIMIT + 1))
    assert post.call_count == 2
