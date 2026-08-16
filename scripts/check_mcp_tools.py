"""Chạy cả 7 tool MCP trên dữ liệu thật để nghiệm thu.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.check_mcp_tools
"""
import json
import sys

from dotenv import load_dotenv

from mcp_server import db, tools

load_dotenv()


def show(name, result):
    print("=" * 70)
    print(name)
    if isinstance(result, dict) and "error" in result:
        print("  LỖI:", result["error"])
        return False
    preview = json.dumps(result, ensure_ascii=False, default=str)[:600]
    print(" ", preview, "...")
    return True


def main():
    con, readonly = db.get_readonly_conn()
    print(f"read_only = {readonly}")
    ok = True

    ok &= show("search_stocks(bluechip_dividend)",
               tools.search_stocks(con, "bluechip_dividend", limit=10))
    ok &= show("get_stock_profile(HPG)", tools.get_stock_profile(con, "HPG"))
    ok &= show("get_valuation_history(HPG)",
               tools.get_valuation_history(con, "HPG", years=5))
    ok &= show("get_financial_history(HPG)",
               tools.get_financial_history(con, "HPG", quarters=8))
    ok &= show("compare_stocks(HPG, VCB)",
               tools.compare_stocks(con, ["HPG", "VCB"]))
    ok &= show("get_sector_snapshot(BANK)",
               tools.get_sector_snapshot(con, "BANK"))
    ok &= show("run_sql", {"rows": db.run_query(
        con, "select symbol, quality_score from mart_stock_scorecard "
             "order by quality_score desc nulls last", limit=5)})

    print("=" * 70)
    try:
        db.assert_safe_sql(con, "DROP TABLE mart_stock_scorecard")
        print("LỖI NGHIÊM TRỌNG: rào chắn SQL không chặn DROP")
        ok = False
    except db.SqlGuardError:
        print("Rào chắn SQL chặn DROP đúng như mong đợi.")

    con.close()
    print("\n" + ("TẤT CẢ ĐẠT" if ok else "CÓ TOOL KHÔNG ĐẠT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
