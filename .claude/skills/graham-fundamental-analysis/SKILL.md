---
name: graham-fundamental-analysis
description: Use when the user asks to analyze a stock, company, or ticker; asks whether a stock is cheap, expensive, undervalued, a good buy, or worth investing in; asks for intrinsic value, a stock screen, a Graham checklist, margin of safety, earning power, net-net, liquidation value, or a comparison of stocks — even if they never say the words "fundamental analysis". Also trigger for Vietnamese phrasing such as "phân tích cổ phiếu", "định giá cổ phiếu", "cổ phiếu này có đáng mua không", "mã này có rẻ không".
---

# Graham Fundamental Stock Analysis

Analyze stocks the way Benjamin Graham and David Dodd taught: value the business, not the ticker. Every analysis must end with (a) an estimate of intrinsic value stated as a range, (b) an explicit margin of safety, and (c) a verdict on how the stock scores against Graham's criteria — never a personal command to buy or sell.

## Core philosophy (non-negotiable)

1. **Investment vs. speculation.** "An investment operation is one which, upon thorough analysis, promises safety of principal and a satisfactory return. Operations not meeting these requirements are speculative." Corollaries: it is the *operation* that is or isn't an investment — no security is an investment at every price; diversification can make a group operation an investment even where single issues alone would not qualify; "thorough analysis" means studying the facts against established standards of safety and value — "great prospects, so buy at 40× earnings" is not analysis; "safety" means protection against loss under all normal or reasonably likely conditions, never an absolute.
2. **Intrinsic value is a range, not a point.** It is the value justified by the facts — assets, earnings, dividends, definite prospects — as distinct from quoted price. State it as an approximate range that widens as uncertainty grows. The analyst's job is only to compare price with that range: you can tell a man is overweight without knowing his exact weight. Draw a conclusion only when price falls clearly below or above the range; when price sits inside it, say so honestly ("no analytical edge at this price").
3. **The market is a voting machine, not a weighing machine.** Quotations register countless choices born partly of reason, partly of emotion; they do not precisely record value. Use Mr. Market's quotes to transact when they are foolish; never let them define value, which comes from operating results and financial position.
4. **Margin of safety is the central concept.** Buy only when price is comfortably below your conservative value estimate, so that an imprecise or somewhat-wrong forecast still doesn't produce a loss of principal. Its function is precisely to render an accurate forecast of the future unnecessary.
5. **Prefer verifiable arithmetic over forecasts.** Base value on demonstrated (multi-year average, normalized) earnings, assets, and dividends. The past trend is a fact; a "future trend" is only an assumption — corrective forces (new competition, capacity, mean reversion) work against the indefinite continuation of any trend, so never capitalize a projected trend as if it were established earning power. Trend is a qualitative factor even when dressed in numbers.
6. **Know the limits of analysis.** Three obstacles: inadequate or misleading data (accounting artifices the analyst must uncover), the uncertainty of the future, and the irrational behavior of the market. Analysis is most powerful for inherently stable businesses, senior claims, and normal conditions — weakest for glamour stocks and rapidly changing situations. When a favorable conclusion would rest mainly on qualitative hopes (price far above what the figures justify), analysis cannot approve it: satisfactory statistics are a necessary, never a sufficient, condition.
7. **Know which investor you serve.** Defensive (safety and freedom from effort first) vs. enterprising (willing to devote serious effort for a better return). The checklist and price limits differ — ask if unclear.

## The four elements of every commitment

Every question reduces to: *should person I buy security S at price P at time T?* Restate it as: which **business**, and on what **terms**? Price is an integral part of every decision — the risk of paying the wrong price is roughly as large as the risk of buying the wrong business. Person matters (temperament, tax, need for effort → defensive/enterprising); time matters mainly through prevailing interest rates and the position of the market cycle, not through prediction.

## Workflow overview

Follow the four-stage funnel (top-down when advising on market/sector allocation; bottom-up when the user brings a specific stock — but always complete all four stages):

1. Economy → 2. Industry → 3. Company → 4. Valuation & margin of safety

Investment process context (state assumptions when unknown): objective (return & risk tolerance) → suitable stock types → asset allocation → find opportunities → analyze → deploy → monitor, take profit / cut loss. Graham's allocation anchor for a defensive investor: 25–75% in stocks, remainder in high-grade bonds, 50–50 as the default; shift toward 25% stocks when the market seems dangerously high, toward 75% after major declines.

## Step −1 — Intake, screening path, event gate (added 2026-10-03, mảng Q)

These three rules exist because the same user got three different answers to near-identical questions (03/09 → IDC, 10/09 → banks, 12/09 → an 11-stock basket) and then watched a name from that basket collapse. The causes were process, not data: the metric, threshold and classification level changed silently between sessions, screening was ad-hoc SQL, and nothing checked for live events before valuing.

### Intake card (hard gate — before any data call)

The only calls allowed before the card is confirmed: reading prior analyses (`docs/analyses/`, `Artifact action:"list"`).

| Field | Values | How to fill |
|---|---|---|
| Question type | screen → basket · single stock · compare · tactics (entry/size/exit) · re-check | From wording: "mã nào/top/lọc" → screen; ticker + "phân tích" → single stock |
| Lens | `gia_tri` (value + margin of safety) · `tang_truong` (growth + quality) | **Always ask** unless the user named it in this message — the user explicitly does not want a default lens |
| Holding horizon | multi-year (this user's default) · weeks | "tuần này", "đầu tháng 10" = short. Say plainly: this framework and data cannot forecast 1–4 week prices; it selects businesses to hold |
| Prior analyses | name · date · lens · conclusion · thresholds | Read them; if the new result differs, the report MUST contain a section explaining the difference **in numbers** |

Ask the lens with one short question. If no answer can be obtained (non-interactive run), do not screen: deliver the card, the prior-analysis comparison, and the question.

### Screening — one path only

- Every "which stock / top N / filter the market" question → MCP `screen_graham(lens)`. Report `config_version`, the remaining count after every step, `phan_tich_tiep`, `cho`, and the VN-Index benchmark it returns.
- Never rank with hand-written SQL. `run_sql` is for digging into one symbol, not for choosing symbols.
- Never output "the single best stock". Graham works at basket level (10–30 issues); return the basket and say why concentration is the risk.
- Changing a threshold means editing `config/graham_screen.yml` **and** bumping `version` — never apply a modified threshold silently inside a conversation.

### Event gate (mandatory before Step 4 scoring and Step 5 valuation)

For every symbol you are about to score or value:

1. Call `get_risk_flags(symbol)`.
   - `cho_bctc_ke_tiep` (real loss quarter in the last 4, or latest quarterly profit down >50% YoY) → **stop**. Output "chưa định giá được" with the flags; no value range, no X/7 score. Name the next report that would settle it.
   - `doc_tin_truoc` (deep drawdown, dilution, insider sell registrations, stale ratios, no quarterly statements) → search the web for the last 90 days (the warehouse news covers only the 5 portfolio symbols) and explain each flag with source and date before continuing.
   - `qua` → still search the web for the last 30 days.
2. **Unbounded contingent liabilities** (buy-back/exchange guarantees, lawsuits, guarantees for related parties, provisioning still in progress): if the size cannot be bounded from the statements, intrinsic value cannot be estimated — do not compute a range. A margin of safety absorbs estimation error inside a known range; it does not absorb an unknown liability.
3. **Relaxed criteria:** if 2 or more of the 7 defensive criteria pass only under relaxed rules, write "7/7, N relaxed" and never "meets the defensive standard" without that qualifier.

Case that produced these rules — PNJ, 12/09/2026: scored 7/7 at 38,200 đ with a value range of 38,000–65,000 đ. The warehouse already held a Q2/2026 loss of 739 bn đ in the raw income statement and two insider-family sell registrations totalling 25 M shares (published 04/09). On 28/09 PNJ guided a full-year loss of ~6,271 bn đ; the stock closed at 23,050 đ on 02/10.

### Record every analysis

After answering a screening or valuation question, write `docs/analyses/YYYY-MM-DD-<topic>.md` (format in `docs/analyses/README.md`): question, intake card, `config_version`, price/ratio `as_of`, step counts, basket, gate results, value ranges and thresholds, sources. The next analysis of the same symbol or sector reads it first.

### Platform limits that must be stated

Full list and wording: `docs/han-che-nen-tang.md`. In every report state at least: news exists only for 5 portfolio symbols; quarterly statements cover ~8 quarters and annual 8 years; revenue/profit in the marts are inferred from multiples; ownership is a monthly snapshot; no bond yield, CPI or rates in the warehouse; no forecasts or consensus; one data source (VCI) with no cross-check.

## Step 0 — Setup and data gathering

- Identify: ticker, exchange, country, currency, fiscal-year convention, and the user's investor profile (defensive / enterprising). Default to defensive if unstated.
- **In this repo, the warehouse comes first.** Call the `vn-stock-analysis` MCP tools before any web search, and never ask the user for a figure a tool can return. Web search or the user are the fallback only for the rows marked "not in the warehouse" below.
- Never invent numbers. Label every figure with its source and its `as_of`.

### Where each Graham input comes from

| Graham needs | Source |
|---|---|
| Current assets by class, current liabilities, total and long-term debt, equity — the inputs to current ratio, NCAV, liquidating value, tangible book | `get_financial_statement(symbol, 'balance_sheet', period_type='year')` — raw reported BCTC lines |
| Non-recurring items, interest expense, detail for normalizing earnings, earnings vs. operating cash flow | `get_financial_statement(..., 'income_statement')` and `(..., 'cash_flow')` |
| Price, market cap, EPS, BVPS, P/E, P/B, valuation band, scorecard | `get_stock_profile`, `get_valuation_history`, `get_financial_history` |
| **Current** P/E, P/B, valuation band, market cap (price of the latest session) | `get_stock_profile` → `valuation_current` (`pe_current`, `pb_current`, `valuation_band_current`). The `valuation` block is **quarter-end** — never call a stock cheap from it, and never divide `last_close` by a quarter-end EPS (wrong after a stock dividend) |
| Real loss quarters (not trailing-12-month) | `get_stock_profile` → `quarterly_profit` (`loss_quarters_4q_actual`); `is_loss_making` only looks at TTM profit |
| Event gate | `get_risk_flags` |
| Screening a market or sector | `screen_graham(lens)` — the only allowed path |
| Market benchmark | `run_sql` on `fct_index_daily` (VNINDEX, VN30, HNXINDEX). The ticker `VNI` is a stock, not the index |
| Dividend record, stock dividends, rights issues | `get_distribution_history` |
| Management and governance evidence (insider %, major holders, board changes) | `get_ownership`, plus `get_recent_news` |
| Peer P/E and P/B context | `get_sector_snapshot`, `compare_stocks` |
| What changed since the last review | `get_thesis_update` |
| Anything the tools above do not cover | `run_sql` (SELECT only) |
| **10-year government bond yield — the hurdle rate for E/P and earnings-power value** | **Not in the warehouse.** Ask the user or search the web; state source and date. If unavailable, say the E/P test could not be anchored rather than guessing a rate. |
| **Macro indicators for Step 1** | Mostly not in the warehouse (only FX, via `get_exchange_rate_history`). Web or user; label them as external. |

### Reading the raw balance sheet without double-counting (verified on REE, FY2018–FY2025)

- Use the **top-level rows** for Graham's arithmetic: `current_assets` (TÀI SẢN NGẮN HẠN), `current_liabilities` (Nợ ngắn hạn), `liabilities` (NỢ PHẢI TRẢ), `owners_equity`, `minority_interests`, `goodwill`, `intangible_fixed_assets`. Never sum the sub-items to rebuild a subtotal.
- `item_id` is **not unique** within a statement — `short_term_investments` appears twice, `cost` and `accumulated_depreciation` three times each (tangible / leased / investment property). Key on `item_vi` + `row_seq`, and show `item_vi` to the user.
- Deduct `minority_interests` before computing book value per share for the common — it sits inside consolidated equity.
- **Shares outstanding:** read `number_of_shares_mkt_cap` from `fct_financial_quarterly` (via `run_sql`) — it is stated, so no derivation is needed. Do **not** compute shares from `common_shares / 10,000` on the annual balance sheet: it lags stock dividends. REE's FY2025 sheet implies 541.7M shares, but a 15% stock dividend went ex on 2026-05-18 and the warehouse carries 622,899,036 as of 2026-Q2 — the stale count would inflate every per-share figure by ~15%. The same trap applies **after** the latest quarter: if `get_distribution_history` shows a stock dividend or bonus with ex-date after `ratio_as_of`, divide every per-share figure by (1 + ratio) before comparing it with today's price — PHR (80% bonus, ex 11/09/2026) looked half-price in the 12/09 screen for exactly this reason.
- **Several ratios are already stated — read them, don't recompute.** `fct_financial_quarterly` carries `current_ratio`, `quick_ratio`, `cash_ratio`, `debt_to_equity`, `roe`, `roa`, `eps`, `bvps` per quarter (REE 2026-Q2: current_ratio 2.36). Compute only what no column provides — NCAV, the Graham number, liquidating value, multi-year averages and dispersion.

Check `data_quality.has_data` before concluding anything about a symbol. Some symbols — small caps especially — have no financial statements through this source at all; that is missing data, not a failing company.

### Which numbers may feed a Graham formula

The MCP server's rules forbid deriving new metrics from existing numbers; Graham's method requires arithmetic. The two reconcile as follows, and this is binding:

- **Compute Graham formulas only from raw reported BCTC lines** returned by `get_financial_statement`, or from quantities a tool states directly (price, EPS, BVPS, P/E, P/B).
- **Never compute from derived marts figures.** Revenue and profit in the marts are *inferred* from `market_cap / ps` and `market_cap / pe` — they are not read off the financial statements. Component scores are peer percentiles, not accounting quantities. Neither may enter a valuation formula.
- **Label every computed number** — e.g. "NCAV computed by this skill from the FY2025 balance sheet" — and keep it visually distinct from figures read straight out of a tool.
- If the raw lines a formula needs are missing, say the test could not be run. Never substitute a marts proxy to fill the hole.

### Data-quality gates inherited from the MCP server (all mandatory)

- State `as_of` for every claim. Price date and ratio date differ — the ratios follow the latest closed quarter. Never merge them into a single "as of" date.
- State `peer_basis` and `peer_count` whenever you call something cheap or expensive relative to its industry. The basis is `com_class+icb_lv2`, and the group size swings widely — REE sits against 154 peers, VCB against 27. "Cheaper than 27 peers" and "cheaper than 154" are different claims.
- `data_quality_score < 60` → say plainly that the data does not support a firm conclusion, list `quality_flags`, and downgrade the verdict. Do not bury this in a footnote.
- **NULL ≠ 0.** A NULL component score means not measurable; 0 means worst in the peer group. Never read one as the other.
- `valuation_band` is a percentile of the stock's *own* P/E over the past 5 years, not a comparison against the market. Say so whenever you cite it.
- When comparing symbols of different `com_class`, state that the metrics are not equivalent.
- Note the accounting basis (VAS / IFRS-convergence for Vietnam) and any audit qualification or consolidation quirk visible in the statements.

## Step 1 — Economic analysis

Goal: decide whether the macro environment supports equity investment and which industries benefit. Analyze past + present, then forecast direction of:

1. **Macro indicators:** GDP growth, inflation, unemployment, exchange rate, interest rates, public debt, NPL ratio, ICOR, investment flows (FDI, FII, ODA, public and private investment), consumption, budget balance, exports/imports, balance of payments.
2. **Policy & law:** monetary policy stance, fiscal policy, capital-attraction policies, significant new regulations.
3. **Social lifestyles:** how people live, work, consume, learn, and play — demand-side shifts.
4. **Technology trends** that could reshape demand or cost structures.

Output: 3–6 sentences — macro verdict (favorable / neutral / unfavorable for equities), key risks, and the industries most advantaged in this environment. Inflation matters doubly for Graham: it erodes bond coupons and inflates nominal earnings — insist on real, not just nominal, earning power.

## Step 2 — Industry analysis

Goal: judge whether this is a good industry and forecast its growth.

- **Classification:** place the company by its principal business activity (the one generating most revenue over a long period), using a standard system (GICS, ICB, ISIC, NAICS, or VSIC 2007 for Vietnam). If the company is a conglomerate, analyze the dominant segment and say so.
- **Growth test:** compare the industry's weighted-average growth (≥5 years of data) against GDP growth. Prefer industries growing faster than GDP *and* suited to the current phase of the economic cycle.
- **Porter's Five Forces** — answer each with its effect on industry revenue, profit, and future growth:
  1. *Entry barriers:* economies of scale, product differentiation, access to distribution channels, capital requirements, switching costs, government policy. How penetrable are they, at what cost to entrants?
  2. *Buyer power:* who are the customers; are they concentrated or large-volume; is the product a big share of their costs; is it differentiated; switching costs; buyers' profitability; threat of backward integration; how informed are they?
  3. *Supplier power:* who supplies; are suppliers concentrated/dominant; do their products compete with substitutes; is the industry an important customer to them; is the input critical; differentiation and switching costs; threat of forward integration?
  4. *Substitutes:* what substitutes exist, how they differ, and their impact on the industry's product economics.
  5. *Rivalry intensity:* number and size of competitors; industry growth rate and life-cycle stage (emerging / fast growth / maturing); fixed-cost and inventory-cost pressure.
- **SWOT** the industry briefly.
- **Mean-reversion caution (Graham & Dodd):** abnormally good or abnormally bad industry conditions rarely persist — corrective forces restore profits where they vanished and compress returns where they were excessive. Do not extend today's industry verdict indefinitely into the future.

Output: industry attractiveness (attractive / average / unattractive), expected growth vs. GDP, and the 2–3 forces that dominate the story.

## Step 3 — Company analysis

**Frame it as Graham & Dodd do — two files of evidence:**
- *Quantitative (the statistical exhibit):* (1) capitalization, (2) earnings and dividends, (3) assets and liabilities, (4) operating statistics.
- *Qualitative:* nature of the business, relative position in the industry, physical/geographic/operating characteristics, character of management, outlook for company, industry, and economy.

Rule of engagement: conclusions must rest on the figures and on established tests and standards — but figures alone never suffice. Adverse qualitative findings (untrustworthy management, a deteriorating business) veto satisfactory statistics. **Inherent stability** — stability that comes from the nature of the business, not merely a smooth past record — is the chief qualitative virtue, because it makes the past a usable guide to the future.

Evaluate Graham's five components of value:

1. **Long-term prospects** — durability of demand, competitive position within the Five-Forces map, dependence on a single product/customer/policy.
2. **Management** — judge by long-run results, capital allocation, and candor, not press coverage. Weight it mainly when a recent management change hasn't yet shown up in the numbers. Do not double-count "great management" on top of great results — that is how overpaying happens. Judge from the owner's seat: shareholders are owners and management are their hired stewards; ask whether dividend, buyback, and retention policy serve owners or entrench managers.
3. **Financial strength & capital structure** — surplus cash and a clean structure beat identical EPS carrying heavy debt and senior securities. Compute: current ratio, long-term debt vs. working capital, debt/equity, interest coverage. **Capitalization-structure doctrine:** senior securities leverage the common — EPS rises and falls faster than operating results; a thin sliver of equity atop heavy debt is *speculatively capitalized* and its stock behaves like an option, so demand a much larger margin of safety or treat it as speculation outright. A conservative structure is itself an investment virtue.
4. **Dividend record** — uninterrupted payments for 20+ years is one of the strongest quality signals (adapt the span to young markets — see Adaptations).
5. **Current dividend rate & payout policy** — compare payout ratio to the company's reinvestment opportunities; a growth company retaining earnings must justify it with returns.

**Earning power discipline (Security Analysis, chs. 24–29 & The Intelligent Investor, ch. 12) — do this before using any EPS figure:**
- *Earning power* = what the company has actually earned over a period of years, plus a reasonable expectation that it will continue absent major change. The record must span enough years to absorb the business cycle.
- An average is only meaningful when the annual figures cluster around it. Always report the dispersion (min–max, deficit years) next to the mean: the average of ten violently scattered numbers is arithmetic, not earning power.
- Normalize: strip one-off gains/losses, asset-sale profits, reserve releases, unusual tax items; use fully diluted EPS (convertibles, options, warrants); check depreciation/amortization policy for adequacy and consistency; watch for earnings inflated or hidden through subsidiaries and consolidation choices.
- Red flags: earnings persistently above operating cash flow, frequent "special charges", serial acquisitions muddying comparability, related-party transactions, receivables/inventory growing much faster than sales, auditor changes or qualified opinions.

**Balance-sheet analysis (Security Analysis, chs. 33–36).** The balance sheet earns more attention than the market gives it. Use it for five things: (1) how much capital is invested in the business; (2) the working-capital condition; (3) the capitalization structure; (4) a **check on reported earnings** — over a decade, the change in net worth plus dividends paid should roughly reconcile with the sum of reported earnings; a large gap means the income statements flattered reality; (5) the sources of income. Compute book value properly: tangible assets − all liabilities − senior claims at their *effective* value (call or market value of preferred, not an understated par), ÷ shares.

## Step 4 — Graham screens

Score the stock explicitly, criterion by criterion, in a table with Pass/Fail/Borderline and the actual numbers.

**Gate on `com_class` before scoring — this is not optional.** The criteria below assume an industrial company:

- `NONFIN` — run the full screen as written.
- `BANK` — the current-ratio, long-term-debt-vs-working-capital, NCAV and liquidating-value tests are meaningless for a bank; the warehouse leaves `current_ratio`, `quick_ratio`, `roic`, `ebit`, `ebitda` NULL for them by design. Mark those **N/A by com_class** — a NULL there is the schema saying "not applicable", not a bad score. Substitute the columns that do exist in `fct_financial_quarterly`: `net_interest_margin`, `npl`, `cir`, `casa_ratio`, `ldr_loan_deposit_ratio`, `loans_loss_reserve_to_loans`, `provision_to_outstanding_loans`, `equity_to_loans`, `total_equity_total_asset`. **`car` is NULL across the warehouse** — say capital adequacy is unavailable rather than reporting it. Keep the P/E, P/B, dividend-record and earnings-stability tests. Also note bank leverage reads alarming on industrial standards (VCB `debt_to_equity` ≈ 9.7): that is the business model, not speculative capitalization — judge it against `total_equity_total_asset` and peers instead.
- `OTHERFIN` (insurers, brokers) — same exclusions as banks; lean on earnings stability and dispersion, leverage, and book value, and say the industrial tests do not apply.

Marking an inapplicable test "Fail" fabricates a negative verdict; marking it "Pass" fabricates a positive one. Mark it N/A and say why.

### A. Defensive investor — the seven criteria (The Intelligent Investor, ch. 14)

| # | Criterion | Threshold (Graham, 1972) |
|---|-----------|--------------------------|
| 1 | Adequate size | ≥ $100M annual sales (industrial); ≥ $50M assets (utility) — inflation-adjust, see Adaptations |
| 2 | Strong financial condition | Current ratio ≥ 2; long-term debt ≤ net current assets (working capital). Utilities: debt ≤ 2× equity at book |
| 3 | Earnings stability | Positive EPS in each of the last 10 years |
| 4 | Dividend record | Uninterrupted dividends for 20 years |
| 5 | Earnings growth | EPS up ≥ 1/3 over 10 years, comparing 3-year averages at start and end (≈ 2.9%/yr compounded) |
| 6 | Moderate P/E | Price ≤ 15 × average EPS of the last 3 years |
| 7 | Moderate P/B | Price ≤ 1.5 × latest book value; rule of thumb: **P/E × P/B ≤ 22.5** (allows e.g. 9× earnings at 2.5× book) |

Plus the portfolio-level floor: the portfolio's earnings yield (E/P) should be at least the current high-grade bond yield. Also apply the chapter-5 rules: 10–30 issues; large, prominent, conservatively financed companies; long dividend records; as an outer bound never pay more than 25× 7-year average earnings or 20× trailing-12-month earnings.

### B. Enterprising investor — relaxed screen (The Intelligent Investor, ch. 15)

1. Financial condition: current ratio ≥ 1.5; debt ≤ 110% of net current assets (industrials)
2. Earnings stability: no deficit in the last 5 years
3. Some current dividend being paid
4. Latest year's earnings above those of 5–6 years ago
5. Price < 120% of net tangible assets

A strong plus on one factor may offset a small minus on another — but never pay a high price (relative to earnings and assets) out of enthusiasm for a company or industry. Second-tier, unpopular companies in cyclical industries bought when near-term prospects look bad are the natural hunting ground.

### C. Bargain / net-net check (always compute if data allows)

Net Current Asset Value (NCAV) = current assets − total liabilities (ignore plant and other fixed assets). If **price ≤ ⅔ × NCAV per share**, flag as a classic Graham bargain issue — rare in modern large caps, more common in small caps and bear markets. Diversify widely if pursuing these; prefer net-nets that are currently profitable and paying some dividend over those burning cash.

For a sharper floor, estimate rough **liquidating value** the Graham & Dodd way: liabilities are real and count at 100%; asset values must be questioned — as rough discount factors take cash & equivalents ≈ 100%, receivables ≈ 75–90%, inventories ≈ 50–75%, fixed and intangible assets ≈ 1–50% (often ~15%). The goal is not a precise figure but whether the stock sells below what owners could realize by winding up. Doctrine: current-asset value is a rough index of liquidating value; a stock *persistently* selling below it is prima facie illogical — either the market is wrong (opportunity), or management should act (return capital, buy back stock, or liquidate), or shareholders are asleep. Flag it as both a value signal and a governance question.

### D. Bond-grade strength check (for any company carrying debt)

Apply Graham's fixed-value principles to the company's own obligations: safety rests on the enterprise's ability to pay — its earning power — not on collateral, liens, or covenants; judge coverage of total fixed charges on a multi-year average that *includes recession years* (test "on a depression basis", not on the best year); and remember that no extra yield compensates for inadequate safety of principal. A company whose debt would fail Graham's bond tests is, for the stockholder, speculatively financed — say so in the report.

## Step 5 — Valuation and margin of safety

Compute several independent estimates; present a value range, not false precision.

1. **Graham growth formula (a cross-check, not gospel):**
   `Value = normalized current EPS × (8.5 + 2g)`
   where g = expected annual EPS growth (%) over the next 7–10 years. 8.5 is the fair multiple for a no-growth company. Cap g conservatively (rarely above 15 even for admired growers) — and run it in reverse to extract the growth rate the current price implies, then ask whether the figures support that assumption.
2. **Graham number (defensive fair-price ceiling):** `√(22.5 × EPS₃yr-avg × BVPS)`.
3. **Earnings-power value:** normalized average EPS ÷ high-grade bond yield (capitalize demonstrated earning power at the bond hurdle); compare E/P directly to the local government/AAA bond yield.
4. **Central value (Graham & Dodd, ch. 22):** capitalize the multi-year average EPS at a multiplier tied to prevailing long-term interest rates to get a "normal value"; sound policy buys well below it and sells well above it. Know its three admitted difficulties: signals can be mistimed, the market's character can change, and the method demands fortitude — buying amid pessimism, selling amid optimism, and sometimes standing aside for years.
5. **Asset floor:** book value, tangible book value, NCAV, rough liquidating value (Step 4C).
6. Sanity-check against peers' multiples and the company's own historical multiple range — comparative analysis is most reliable between companies in the same industry on the same accounting basis.

**Margin of safety rule:** state the central value estimate and the range, then the maximum price that leaves an adequate margin — require roughly one-third below central value for enterprising picks (Graham bought net-nets at ≤ ⅔ of value); for defensive picks rely on the hard price caps (criteria 6–7) plus E/P ≥ bond yield. Margin of safety exists in either of two forms: buying representative stocks when the whole market is demonstrably cheap, or buying individual issues below intrinsic value at any time. If the current price offers neither, the correct output is "outside the buy zone at today's price" — a good company is not a good investment at any price, and a price inside the value range is a "no-edge" answer, not a buy.

## Step 6 — Report format

ALWAYS structure the final answer as:

```
# [Company] ([TICKER]) — Graham Fundamental Analysis
Price [x] as of [price_as_of] · Ratios as of [ratio_as_of] · com_class [NONFIN|BANK|OTHERFIN]
Data quality [score]/100 [quality_flags if any] · Peers: [peer_basis], n = [peer_count]
Sources: vn-stock-analysis warehouse + [external sources with dates]
Lens [gia_tri|tang_truong] · Horizon [..] · Screen config [config_version, if screened] · Risk gate [qua|doc_tin_truoc|cho_bctc_ke_tiep]
Differences vs prior analysis [name, date] — required when a prior analysis exists

## 1. Snapshot & business
## 2. Macro context (brief)
## 3. Industry: Five Forces summary + attractiveness
## 4. Company: prospects, management & governance, financial strength
      & capital structure, dividends, earning power (mean + dispersion),
      balance-sheet check on earnings
## 5. Graham scorecard (table: criterion | value | threshold | Pass/Fail)
   — Defensive: X/7 · Enterprising: Y/5 · Net-net: yes/no · Debt: bond-grade?
## 6. Valuation: methods table → intrinsic value RANGE (low–central–high)
      → margin of safety at current price
## 7. Verdict & risks
```

In the verdict: classify the stock (e.g., "meets the defensive standard", "enterprising candidate on a pullback below ___", "speculatively capitalized — treat as speculation", "no analytical edge at this price"), list the 3 biggest risks, and name what would change the thesis. Close with a one-line reminder that this is an analytical framework applied to public data, not personalized financial advice — the decision and position sizing belong to the investor.

## Behavioral rules

- **Short horizons:** when asked what to buy "this week" or "early next month", say first that neither this framework nor this data forecasts 1–4 week prices, then answer the long-horizon question. Judging a method by two weeks of one stock's price is noise; judging it by a business outcome (PNJ's loss) is signal — separate the two in post-mortems.
- Market analysis is not security analysis: price forecasting — charts, momentum, timing signals — carries no margin of safety and competes on prediction, where the analyst has no protective cushion. Never justify a valuation by recent price action or market forecasts; Graham's investor profits from fluctuations, never predicts them.
- Distinguish the two averages: only call a mean "earning power" when the yearly figures cluster around it; otherwise present the record year by year and say the average is unreliable.
- If key data is missing, compute what you can, mark gaps clearly, and downgrade confidence — do not fabricate or silently substitute.
- When the user is excited about a glamour/growth stock, still run the numbers; show the growth rate the current price implies via the reversed Graham formula and let the arithmetic speak. If the case for buying rests mainly on the story rather than the figures, label it speculation — politely, but in those words.
- Treat shareholders as owners: comment on whether retained earnings, dividends, and buybacks serve them, especially when price sits below liquidating value.
- Distinguish clearly, in every report, which parts are fact (reported figures), which are estimates, and which are opinion.
- **No buy or sell recommendation.** State the margin-of-safety price as an analytical threshold ("below X the figures leave an adequate cushion"), never as an instruction to transact, and always pair the thesis with its counter-risk. Close with the note that this is reference information, not advice.
- Respond in the user's language (e.g., Vietnamese for Vietnamese users); keep formula names in English with a translation on first use.

## Adaptations for modern & local markets

- **Size:** inflation-adjust Graham's 1972 thresholds (~$100M sales then ≈ $700M+ today, or roughly the top ~half of the local exchange by revenue; in Vietnam, think multi-thousand-billion-VND revenue leaders on HOSE).
- **Dividend history:** in young markets (e.g., Vietnam, listed histories often < 20 years) require dividends in ≥ 7 consecutive years, or since listing, and say you relaxed the rule. See the measured window below — 20 years is not reachable from this data.
- **Bond hurdle:** use the local 10-year government bond yield (or best local corporate yield) as the earnings-yield benchmark, not US rates, for stocks earning in local currency.
- **Sector exclusions:** driven by `com_class`, not by judgement — see the gate at the top of Step 4.
- **Intangibles:** Graham's book-value tests use tangible assets; for asset-light businesses, lean more on earning power, dispersion, and the bond-yield hurdle, and say the asset floor is weak rather than pretending it exists.
- **Data:** for Vietnam, VSIC 2007 classifies industries; financials follow VAS/IFRS-convergence — check for revaluation and consolidation quirks before comparing book values internationally.

## Warehouse reality check — what this data can and cannot test

Measured on `md:vn_market` on 2026-08-24. Re-measure if the pipeline has since been backfilled; treat the numbers below as the current ceiling, not a permanent one.

| Series | Window available | Consequence |
|---|---|---|
| Annual financial statements | FY2018–FY2025 — **8 years**, ~1,564 symbols | Graham's 10-year tests cannot be run in full |
| Quarterly ratios (`fct_financial_quarterly`) | 2018-Q1 – 2026-Q2 (34 quarters), ~1,585 symbols | Enough for TTM, dispersion and trend work |
| Quarterly **raw statements** (`get_financial_statement`, `period_type='quarter'`) | **8 most recent quarters** for 1,142 symbols (measured 2026-10-03; sliding window of the B2 ingest) | Quarterly loss checks see ~8 quarters, not 12 |
| `cash_dividend_by_fiscal_year` (from `get_distribution_history`) | up to 8 fiscal years | The usable series for the dividend-record test |
| `distribution_events` (same tool) | **per symbol, often 1–2 years** — the source only exposes the 50 most recent events | Never infer a dividend streak from this block |
| Ratios and scorecard | latest closed quarter | The `ratio_as_of` lag behind price is real; never present them as one date |

Consequences when scoring the defensive criteria:

- **#3 earnings stability (positive EPS in each of 10 years)** → run it over the years actually available and label the result, e.g. "8/8 years positive — relaxed from Graham's 10".
- **#4 dividend record (20 uninterrupted years)** → unreachable. Require ≥ 7 consecutive years or since listing, and say the rule was relaxed. Score it from `cash_dividend_by_fiscal_year` plus `dividend_years_consecutive` in the profile — **not** from `distribution_events`, whose window is capped at the 50 most recent events and for an active symbol can cover barely a year (REE: `event_window_years` = 1.2, 4 events, while its fiscal-year series runs 2018–2025). Always quote `event_window_years` when you discuss the streak.
- **`dividend_yield` = 0 is ambiguous** — it means "paid nothing" or "source had no data", and the two are indistinguishable here. REE shows 0.0 for FY2020 inside an otherwise continuous record. Report it as a gap in the streak, never as proof the company skipped a payment.
- **#5 earnings growth (+⅓ over 10 years, comparing 3-year averages at each end)** → with 8 years the two windows sit closer together than Graham intended. Report the actual span used and treat the outcome as indicative rather than a clean pass.
- A criterion that cannot be tested is **"not tested — insufficient history"**, never "Pass". Never quietly score a 10-year test on 5 years of data.
