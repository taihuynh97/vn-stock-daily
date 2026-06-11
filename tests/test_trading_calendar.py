# tests/test_trading_calendar.py
from datetime import date
from src import ingest_market


def test_weekday_is_trading_day():
    assert ingest_market.is_trading_day(date(2026, 6, 8)) is True   # Thứ 2
    assert ingest_market.is_trading_day(date(2026, 6, 11)) is True  # Thứ 5
    assert ingest_market.is_trading_day(date(2026, 6, 5)) is True   # Thứ 6


def test_weekend_is_not_trading_day():
    assert ingest_market.is_trading_day(date(2026, 6, 6)) is False  # Thứ 7
    assert ingest_market.is_trading_day(date(2026, 6, 7)) is False  # Chủ nhật
