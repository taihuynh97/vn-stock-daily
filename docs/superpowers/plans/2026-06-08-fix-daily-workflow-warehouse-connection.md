# Fix Daily Workflow — Warehouse-First Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect `daily.yml` (newsletter job) to MotherDuck cloud so `ingest.fetch_history` reads from warehouse instead of calling API every time.

**Architecture:** The warehouse-first logic in `src/ingest.py` already exists and is tested — it only needs the `WAREHOUSE_DB` env var to activate. Additionally, `daily.yml` cron is shifted 30 minutes later than `warehouse.yml` so today's EOD prices are already loaded before the newsletter reads them.

**Tech Stack:** GitHub Actions YAML, DuckDB/MotherDuck (no Python changes)

---

## Root Cause Summary

Two problems found in `.github/workflows/daily.yml`:

| Problem | Current state | Impact |
|---|---|---|
| Missing `WAREHOUSE_DB` | Not set → uses `data/warehouse.duckdb` (local, empty) | `fetch_history` always calls API, never reads warehouse |
| Same cron as warehouse | Both run `30 8 * * 1-5` simultaneously | Even after fix, today's prices may not be loaded yet when newsletter reads |

Python files (`src/ingest.py`, `src/warehouse.py`) are **correct** — no Python changes needed.

---

## File Map

| File | Action | Why |
|---|---|---|
| `.github/workflows/daily.yml` | Modify | Add `WAREHOUSE_DB` + `motherduck_token` env vars; shift cron to 09:00 UTC |
| `docs/learning/06-tu-dong-hoa.md` | Modify | Fix timing table; add section explaining data flow between jobs |
| `docs/learning/01-kien-truc-tong-quan.md` | Modify | Note that warehouse-first requires daily.yml to point to MotherDuck |

---

## Task 1: Fix `daily.yml` — Connect to MotherDuck and stagger timing

**Files:**
- Modify: `.github/workflows/daily.yml`

- [ ] **Step 1: Verify the current state of the file**

Run:
```bash
cat .github/workflows/daily.yml
```

Expected output: "Run digest" step has NO `WAREHOUSE_DB` or `motherduck_token` env vars. Cron is `"30 8 * * 1-5"`.

- [ ] **Step 2: Apply the fix**

Replace the entire file with the corrected version (two changes: cron + env vars):

```yaml
name: daily-stock-digest

on:
  schedule:
    # VN đóng cửa 15:00 ICT = 08:00 UTC.
    # Warehouse job chạy 08:30 UTC → chạy newsletter 09:00 UTC để đọc từ warehouse có đủ data hôm nay.
    - cron: "0 9 * * 1-5"
  workflow_dispatch: {}   # cho phép chạy tay từ tab Actions

jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      # Khôi phục DB của lần chạy trước (best-effort, để chống lặp tin)
      - name: Restore DB cache
        uses: actions/cache@v4
        with:
          path: data
          key: market-db-${{ github.run_id }}
          restore-keys: market-db-

      - name: Run digest
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          CLAUDE_MODEL: claude-sonnet-4-6
          VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
        run: python main.py
```

Changes made:
1. Cron: `"30 8 * * 1-5"` → `"0 9 * * 1-5"` (08:30 → 09:00 UTC, 30 min after warehouse starts)
2. Added `WAREHOUSE_DB: "md:vn_market"` to env
3. Added `motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}` to env

- [ ] **Step 3: Verify the diff makes sense**

Run:
```bash
git diff .github/workflows/daily.yml
```

Expected diff shows:
- `-    - cron: "30 8 * * 1-5"`
- `+    - cron: "0 9 * * 1-5"`
- `+          WAREHOUSE_DB: "md:vn_market"`
- `+          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}`

- [ ] **Step 4: Verify MOTHERDUCK_TOKEN secret exists in GitHub**

Check that `MOTHERDUCK_TOKEN` is referenced in other working workflows:
```bash
grep -r "MOTHERDUCK_TOKEN" .github/workflows/
```

Expected: warehouse.yml, warehouse-weekly.yml, warehouse-monthly.yml all reference it → secret already exists in GitHub repository settings, no action needed.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/daily.yml
git commit -m "fix(ci): connect daily newsletter to MotherDuck warehouse

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Update learning docs to reflect correct data flow

**Files:**
- Modify: `docs/learning/06-tu-dong-hoa.md`
- Modify: `docs/learning/01-kien-truc-tong-quan.md`

- [ ] **Step 1: Update timing table in `06-tu-dong-hoa.md`**

Find the table (around line 72–78):
```markdown
| Workflow | Cron | UTC | ICT | Nội dung |
|---|---|---|---|---|
| `daily.yml` | `30 8 * * 1-5` | T2-T6 8:30 | 15:30 | Bản tin |
| `warehouse.yml` | `30 8 * * 1-5` | T2-T6 8:30 | 15:30 | Giá EOD |
```

Replace with:
```markdown
| Workflow | Cron | UTC | ICT | Nội dung |
|---|---|---|---|---|
| `warehouse.yml` | `30 8 * * 1-5` | T2-T6 8:30 | 15:30 | Giá EOD (chạy trước) |
| `daily.yml` | `0 9 * * 1-5` | T2-T6 9:00 | 16:00 | Bản tin (chạy sau) |
| `warehouse-weekly.yml` | `30 8 * * 6` | T7 8:30 | 15:30 | + Financials |
| `warehouse-monthly.yml` | `0 9 1 * *` | Ngày 1, 9:00 | 16:00 | + Company info |
```

- [ ] **Step 2: Add a new section "Job Ordering — Tại sao newsletter chạy sau warehouse?" to `06-tu-dong-hoa.md`**

Append after the timing table section, before the "Secrets Management" section:

```markdown
---

## Job Ordering — Tại sao newsletter chạy sau warehouse?

Hai job `warehouse.yml` và `daily.yml` **không độc lập** về mặt dữ liệu:

```
warehouse.yml (08:30 UTC):
  vnstock API → MotherDuck (ghi giá EOD hôm nay)

daily.yml (09:00 UTC — 30 phút sau):
  MotherDuck → ingest.fetch_history → signals → newsletter
```

**Nếu chạy đồng thời (08:30):**
- Newsletter đọc MotherDuck ngay lúc warehouse đang ghi
- Có thể thiếu giá hôm nay → MA/RSI tính từ dữ liệu cũ một ngày

**Sau khi fix (daily.yml = 09:00 UTC):**
- Warehouse có 30 phút để hoàn thành (bulk API call, thường <15 phút)
- Newsletter đọc MotherDuck → có đủ lịch sử + giá hôm nay → threshold `max(days//2, 10)` đạt
- `fetch_history` trả từ warehouse, **không gọi API** → tiết kiệm ~31 giây

**Lưu ý**: `fetch_ratios`, `fetch_industry`, `fetch_news` vẫn gọi API trực tiếp (chưa có warehouse-first). Chỉ `fetch_history` (OHLCV lịch sử) là phần tốn thời gian nhất và đã được tối ưu.
```

- [ ] **Step 3: Update `01-kien-truc-tong-quan.md` — fix warehouse-first description**

Find the line (around line 31–33):
```markdown
- Kể từ Phase 2B: luồng bản tin **ưu tiên đọc từ warehouse** (nhanh hơn nhiều) thay vì gọi API lại.
```

Replace with:
```markdown
- Kể từ Phase 2B + fix daily.yml: luồng bản tin **ưu tiên đọc từ warehouse** (nhanh hơn nhiều) thay vì gọi API lại. Yêu cầu `WAREHOUSE_DB=md:vn_market` được set trong `daily.yml`.
```

- [ ] **Step 4: Verify docs compile correctly**

Run:
```bash
grep -n "WAREHOUSE_DB\|motherduck\|09:00\|9:00\|0 9" docs/learning/06-tu-dong-hoa.md
```

Expected: thấy các dòng vừa thêm.

- [ ] **Step 5: Commit**

```bash
git add docs/learning/06-tu-dong-hoa.md docs/learning/01-kien-truc-tong-quan.md
git commit -m "docs: update learning docs to reflect warehouse-first fix

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

### Spec coverage
- [x] `daily.yml` gets `WAREHOUSE_DB` env var → warehouse-first activates on CI ✅ Task 1
- [x] `daily.yml` cron delayed to 09:00 → today's prices available before newsletter reads ✅ Task 1
- [x] `MOTHERDUCK_TOKEN` secret existence verified ✅ Task 1 Step 4
- [x] Docs reflect corrected timing ✅ Task 2

### Scope boundary (YAGNI)
- No Python code changes (not needed — logic already correct)
- No new tests (existing `test_ingest_warehouse_fallback.py` covers the logic)
- No changes to warehouse workflows (already correct)
- No changes to `storage.py` / SQLite cache (orthogonal concern)

### Risks
- `MOTHERDUCK_TOKEN` secret must exist in GitHub → verified in Task 1 Step 4
- 30-minute gap might be insufficient if warehouse job is slow → acceptable, `fetch_history` has API fallback
