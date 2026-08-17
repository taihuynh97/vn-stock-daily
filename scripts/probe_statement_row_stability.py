"""Kiểm chứng vị trí dòng (row_seq) của income_statement/balance_sheet/
cash_flow có ổn định giữa các lần gọi API hay không.

Toàn bộ thiết kế khoá của B2 (raw_financial_statement) dựa vào giả định
này — item_id KHÔNG unique trong một báo cáo (đã đo: balance_sheet của
HPG có 22/122 dòng trùng item_id, ví dụ "cost"/"accumulated_depreciation"
xuất hiện 4 lần mỗi cái vì 4 nhóm tài sản cố định khác nhau dùng chung
item_id). Chỉ vị trí dòng giữ đúng nhóm ngữ nghĩa — nếu vị trí đó xáo trộn
giữa các lần gọi, khoá `row_seq` sẽ gán nhầm giá trị cho item khác.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_statement_row_stability

Exit code 0 = vị trí dòng ổn định, dùng làm khoá được.
Exit code 1 = KHÔNG ổn định, phải đổi khoá trước khi đi tiếp.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.financial import Finance

# Trộn cả 3 com_class — schema khác nhau hoàn toàn theo loại hình DN nên
# phải kiểm cả 3, không suy từ 1 nhóm ra nhóm khác.
SAMPLES = [
    ("HPG", "income_statement"), ("HPG", "balance_sheet"),
    ("VCB", "balance_sheet"), ("VCB", "cash_flow"),
    ("SSI", "income_statement"), ("SSI", "cash_flow"),
]
SLEEP_BETWEEN_CALLS = 1.05      # khớp VNSTOCK_MIN_INTERVAL của job thật
SLEEP_BETWEEN_ROUNDS = 60       # đủ dài để lộ vị trí sinh theo timestamp/session


def snapshot(symbol: str, statement: str) -> list[tuple[str, str]]:
    """Trả [(item_id, item_vi), ...] theo đúng thứ tự dòng trả về."""
    f = Finance(symbol=symbol, source="VCI", period="quarter")
    df = getattr(f, statement)()
    df = df.reset_index(drop=True)
    return list(zip(df["item_id"].astype(str), df["item"].astype(str)))


def main() -> int:
    print(f"Vòng 1: gọi {len(SAMPLES)} tổ hợp (mã, báo cáo)...")
    first = {}
    for sym, stmt in SAMPLES:
        first[(sym, stmt)] = snapshot(sym, stmt)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu theo VỊ TRÍ DÒNG...")
    ok = True
    for sym, stmt in SAMPLES:
        second = snapshot(sym, stmt)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[(sym, stmt)], second
        if len(a) != len(b):
            print(f"  {sym}/{stmt}: THẤT BẠI — số dòng đổi ({len(a)} → {len(b)})")
            ok = False
            continue
        lech = [i for i in range(len(a)) if a[i] != b[i]]
        if lech:
            print(f"  {sym}/{stmt}: THẤT BẠI — {len(lech)}/{len(a)} vị trí dòng "
                  f"đổi (item_id/item_vi khác nhau ở cùng vị trí). Ví dụ vị trí "
                  f"{lech[0]}: vòng 1={a[lech[0]]!r} vòng 2={b[lech[0]]!r}")
            ok = False
        else:
            print(f"  {sym}/{stmt}: {len(a)} dòng, TOÀN BỘ vị trí khớp")

    print()
    if ok:
        print("KẾT LUẬN: vị trí dòng ỔN ĐỊNH — dùng row_seq làm khoá được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: vị trí dòng KHÔNG ổn định — PHẢI đổi khoá trước khi đi "
          "tiếp (ứng viên: (symbol, statement_type, period_type, "
          "period_label, item_id, item_vi), chấp nhận các dòng thật sự "
          "trùng cả item_id lẫn item_vi bị gộp). BÁO CONTROLLER, KHÔNG tự "
          "đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
