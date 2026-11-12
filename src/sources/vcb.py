"""Tỷ giá Vietcombank qua API xuất Excel của chính VCB (không scrape HTML).

GET /api/exchangerates/exportexcel?date=YYYY-MM-DD trả JSON
{"FileName": ..., "Data": <xlsx mã hoá base64>}. Sheet "ExchangeRate" có vài
dòng tiêu đề ở đầu và ghi chú ở cuối; dòng dữ liệu là dòng có mã tiền tệ
3 chữ cái ở cột đầu.
"""
from __future__ import annotations

import base64
import re
import warnings
from io import BytesIO

import pandas as pd

from .http import SourceError, get_json

URL = "https://www.vietcombank.com.vn/api/exchangerates/exportexcel"
COLUMNS = ["currency_code", "currency_name", "buy_cash", "buy_transfer", "sell"]
_CODE = re.compile(r"^[A-Z]{3}$")


def exchange_rate(rate_date: str) -> pd.DataFrame:
    """[currency_code, currency_name, buy_cash, buy_transfer, sell, date].

    Giữ nguyên chuỗi của nguồn ('17,180.25', '-'); fetch_exchange_rate của
    ingest_market chuẩn hoá ('-' → NULL, không phải 0)."""
    doc = get_json(URL, {"date": rate_date})
    if not isinstance(doc, dict) or not doc.get("Data"):
        raise SourceError(f"VCB {rate_date}: phản hồi không có trường Data")
    try:
        xlsx = base64.b64decode(doc["Data"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # "Workbook contains no default style"
            sheet = pd.read_excel(BytesIO(xlsx), sheet_name="ExchangeRate",
                                  header=None, dtype=object, engine="openpyxl")
    except Exception as e:
        raise SourceError(f"VCB {rate_date}: không đọc được file Excel ({e})") from e
    sheet = sheet.iloc[:, :len(COLUMNS)]
    sheet.columns = COLUMNS
    codes = sheet["currency_code"].astype(str).str.strip()
    df = sheet[codes.str.match(_CODE)].reset_index(drop=True)
    df["date"] = rate_date
    return df
