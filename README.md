# NFL All-Player Statistics and Status Tracker — automated

**What this is:** A self-contained, position-filtered website, per-position CSV exports (open in Excel), season and weekly stats, official injury-report designations as reproduced in the nflverse injury feed, and an audit report. The workflow updates daily while running on GitHub Actions and publishes to GitHub Pages.

**Current status:** The program and offline synthetic-data tests were run in the creation environment. The real **2026** source CSVs could not be fetched in that environment. **No real-time 2026 player dataset was included or falsely represented as verified.** The first successful hosted refresh must download and pass the checks. If a critical feed fails or fewer than 32 NFL clubs appear, the build fails instead of publishing an incomplete replacement.

## Sources, exact files

- Player box-score stats: `https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv`
- Weekly player rosters: `https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_2026.csv`
- Game/practice injury reports: `https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv`
- Team box-score stats (internal reconciliation): `https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.csv`
- Manually compare discrepancies with [NFL official player stats](https://www.nfl.com/stats/player-stats/) and [NFL official injury reports](https://www.nfl.com/injuries/).

The nflverse CSV URLs above follow the project's documented `nflreadr` loader conventions. nflverse is not an official NFL publisher; team totals vs. player totals is an *internal* consistency check, not a comparison to an independent official data feed.

## Turn on automated daily refresh — one-time configuration

1. On GitHub, create an empty **public** repository named e.g. `nfl-player-tracker` using your account. (A public GitHub Pages site is visible to anyone who has its address.)
2. Upload the contents of this package **preserving folders and names**, including `.github/workflows/update-nfl.yml`, `generate.py`, `template.html`, `tests/test_generate.py`, and `README.md`, to the repository's **main** branch. Using GitHub Desktop or a computer with Git is easiest:

   ```bash
   cd nfl_stats_automation
   git init -b main
   git add .
   git commit -m "Install NFL stats updater"
   git remote add origin https://github.com/YOUR_USERNAME/nfl-player-tracker.git
   git push -u origin main
   ```

   If the GitHub repository contains a starter README, either create it empty or reconcile before pushing.
3. In GitHub repo **Settings → Pages → Build and deployment → Source**, choose **GitHub Actions**.
4. Under **Actions → Update NFL player tracker → Run workflow**, run the workflow once to obtain the first dataset. A green successful run publishes the page; if any stage fails, read its log rather than assuming it refreshed.
5. Open `https://YOUR_USERNAME.github.io/nfl-player-tracker/` to browse the output. The page includes the retrieval timestamp and most recent stats/injury weeks. Download position CSVs or the Excel workbook from the page (Excel export requires internet access for a third-party JS library).

**Automatic schedule:** Daily at approximately 13:15 UTC (8:15 a.m. US Central daylight time / 7:15 a.m. Central standard time). GitHub scheduled jobs can run late and can be disabled after prolonged repository inactivity. Use **Run workflow** for an immediate refresh. GitHub Pages typically requires a public repository for free hosting on individual accounts; review your own GitHub plan.

## Local manual refresh (Windows / macOS / Linux)

Install Python 3.10+ and run from the unzipped project folder:

```bash
python generate.py --season 2026 --out site
```

Then open `site/index.html` in your browser. An internet connection is required for the refresh, but the generated page contains its data for offline viewing. No API tokens or pip packages are required to run the importer. Chrome, Edge, or another desktop browser is recommended for the optional Excel exporter.

## What the automated audits do

- **Coverage:** Require the latest weekly roster to represent 32 clubs and at least 1,200 player IDs; require at least 300 players with stat rows and at least 30 teams in the stats feed.
- **Identity:** Join rosters, stats, and injury reports by GSIS player ID, not by names. Keep both latest-week roster players *and* season stat participants who were later cut or traded.
- **Calculations:** Sum additive weekly count/yardage stats, recalculate percentages using summed denominators, and preserve the source's missing values as blank rather than zero. GP* represents **weeks with statistical rows**, not guaranteed official games played.
- **Game designations:** Q/D/O come from the latest report-week status only. A practice injury with no official game designation is I; reserve without explicit confirmation of injured reserve is RES, **not IR**. Blank/— does not prove healthy or active.
- **Reconciliation:** For each team-week where both feeds have the field, compare sums of player data with nflverse team box scores. List mismatches in `TEAM_CHECKS.csv`. This is an *internal* provider check, not guaranteed independent validation.
- **Warnings:** `REVIEW_FLAGS.csv` marks stat-only players, no stat rows, unresolved teams, and older injury report data. `VALIDATION_REPORT.json` includes all warnings, sources, last update time, comparison count and team coverage. `data.json` retains per-player provider field names/values and weekly splits.

## Accuracy limits and maintenance

- No provider is error-free. Source updates can lag games, trades, Friday injury designations, Sunday actives/inactives, and corrections. This tracker is a **daily** refresh, not a live play-by-play terminal. Recheck NFL.com before betting, decisions requiring medical availability, or time-sensitive game-day use.
- For offensive linemen, long snappers and players without statistical rows, lack of a stat row **does not mean zero games played**. Use snap counts or actual NFL game participation records if you need independently certified GP or snaps.
- Injury-report week and statistical week differ during some parts of a football week. Always compare the labeled week numbers.
- `RES` can include reserve categories other than IR. It is intentionally not upgraded to IR without a matching description.
- The github workflow is deliberately pinned to **2026**. Change both `--season 2026` and package title/config for 2027 after the 2026 postseason; it will not silently switch to an incomplete new season.
- To verify a specific player, compare their GSIS ID and stat line against the official box score. A second licensed independent provider would be needed for exhaustive cross-provider validation; this package does not claim that.
- CSV exports include BOM for Excel compatibility and neutralize formula-injection-like text input.

## Run tests

```bash
python -m unittest discover -s tests -v
```

Output directory after refresh: `site/` contains the offline HTML, `data.json`, `ALL_PLAYERS.csv`, `ALL_METRICS.csv`, position-specific CSVs, `REVIEW_FLAGS.csv`, `TEAM_CHECKS.csv`, and `VALIDATION_REPORT.json`.
