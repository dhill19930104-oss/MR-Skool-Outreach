# BRFC Recruitment Pipeline → Monday.com

`pipeline_sync.py` moves players marked **Progress = Y** in `BRFC_Recruitment_Pipeline.xlsx` into the
**Short List** group on the matching Monday position board. It also checks what is already on each player's Monday profile.
The Live Watchlist is updated by hand.

## Setup (once)

```bash
pip3 install openpyxl certifi pytest
echo 'MONDAY_API_KEY=<your token>' > .env     # .env is gitignored - never commit it
```

## Routine

1. Set **Progress = Y** on the player's row in Excel, then **save and close** the workbook. The script refuses to run while Excel has it open.
2. `python3 pipeline_sync.py sync` runs a **dry run** that prints the plan and writes nothing.
3. Check the plan, then run `python3 pipeline_sync.py sync --apply`.

Running it again is safe. Every decision is made from live Monday state, so players already on the Short List are left alone, and a run that was cut off just carries on.

## What `sync` does for each Progress = Y row

| On the tab's board | Action |
|---|---|
| Already in **Short List** | nothing |
| In another group (Target List, Long List, Not For Us Currently…) | **move** to Short List |
| Only in **Unattainable** | **skip**: move by hand if that has changed |
| Not on the board | **create** in Short List and set Current Club from column B (check for duplicates afterwards) |
| Several possible rows, or only a loose name match with a different club | **skip**: reported as ambiguous, never guessed |

**Profile check** (read-only, printed under each player):
- **bullet comments**: Monday updates that contain bullet points, and the date of the latest one.
- **report <1yr**: a report subitem with a file attached, dated within the last 12 months. If there isn't one, the date of the last report is shown.

Nothing else is ever changed. The script never deletes anything, never touches Unattainable groups, and never writes to the workbook.

## Other commands

- `python3 pipeline_sync.py discover` is read-only. It writes the groups, columns and item counts for the 10 position boards and the Live Watchlist to `discovery_report.md`.
- `python3 pipeline_sync.py inspect --board "CB List"` is read-only and shows one board.

## Tests

`python3 -m pytest -q tests` runs offline against a fake Monday, so the tests need no network.

## Google Sheet auto-sync

The live pipeline is the Google Sheet. `apps_script/MondaySync.gs` runs inside the sheet and does the same
Short List move automatically whenever Progress is set to Y. Install steps are in `apps_script/README.md`.
