# Claude Code brief: BRFC Recruitment Pipeline × Monday.com

**Owner:** Dhillon (Recruitment Intelligence, Bristol Rovers FC)
**Run on:** Dhillon's Mac. Monday API access works from there.
**Goal:** when Dhillon marks a player **Progress = Y** in the pipeline workbook (after video), that player moves to the **Shortlist** group on the matching Monday position board **and** is added to the **Live Watchlist**.

Read the whole brief before writing code. **Step 1 is discovery only.** Don't write to Monday until Dhillon confirms the discovery report.

---

## 0. Files

| File | What it is |
|---|---|
| `BRFC_Recruitment_Pipeline.xlsx` | Pipeline workbook. One tab per Monday position board. **It's empty on purpose:** players are only added once they've been through the process (§1). Structure is in §3. |
| `pipeline_sync.py` | Reference implementation, written without live API access. Use its logic, but **check every assumption against the live boards** (the ⚠ items below). |
| `monday-api-reference.md` | Board inventory, gotchas and rate limits. |
| `~/Documents/monday-minutes/` | **Existing working repo** (own git, 55 tests). It already resolves columns by title, matches players by name with club disambiguation, and never writes an uncertain match. **Reuse its client, matcher and alias table. Don't rebuild them.** |

**Token:** read `MONDAY_API_KEY` from the environment or a `.env` file. Never commit or print it, and make sure `.env` is in `.gitignore`. ⚠ The old token was pasted into a chat, so ask Dhillon to rotate it before you start.

---

## 1. The process (code is only the last step)

```
1  Dhillon prompts the requirement        ("CB required")
2  Dhillon uploads the data               (to Claude in chat)
3  Claude says who fits and why
4  Dhillon agrees  →  player is added to that position's tab in the workbook
5  Video work      →  Dhillon sets Progress = Y / N
6  Progress = Y    →  [THIS CODE]
                      (a) move to the SHORTLIST group on the tab's Monday board (create if missing)
                      (b) add to the LIVE WATCHLIST
                          https://bristolrovers-company.monday.com/boards/5092355536
```

---

## 2. What to build

Build a small CLI, preferably inside `monday-minutes` so it shares the client and matcher. Ask Dhillon which he wants.

| Command | Behaviour |
|---|---|
| `discover` | **Read-only.** For the 10 position boards and the Live Watchlist, report the groups, columns (title / type / id) and top-level item count. Also report which group is the shortlist group on each board, and the Live Watchlist's full column list. Write the result to `discovery_report.md`, then **stop and show Dhillon.** |
| `sync` | **Dry run by default:** prints the plan. `--apply` writes. Rules are in §5. |
| `pull --board "CB List"` | Optional, read-only. Exports a board to CSV, skipping Unattainable groups, so Dhillon can hand it to Claude. |

### Non-negotiables
- Resolve **columns by title at runtime**. Column ids and types differ per board.
- Match group titles on **prefix / contains, case-insensitive**. "Unattainable" and "Unattainable List" are both excluded groups.
- Use `items_page` with a cursor, limit 200. Ignore the "Subitems of …" boards.
- Pace writes at **0.35 s**. A 429 can come back as an **HTML page**, so detect it from the HTTP status. Back off 15 / 30 / 45 / 60 s.
- **Idempotent:** decide each action from the live Monday state. If the player is already in the shortlist group, or already on the Live Watchlist, do nothing. A second run must make no changes.
- **Never write an uncertain match.** Use the `monday-minutes` matcher: the boards use known names, and club names are abbreviated or misspelt, so it needs the alias table. If a match is ambiguous, report it and skip the player.

---

## 3. Workbook structure

Each tab maps to exactly one Monday board:

| Tab | Monday board | id |
|---|---|---|
| CB | CB List | `1405453688` |
| GK | GK Lists | `1405448899` |
| CM 6 | CM - 6 | `1630835327` |
| LB | LB List | `1405455920` |
| Winger | Winger List | `1405463991` |
| CM 8 | CM - 8 | `1630854223` |
| CM 10 | CM - 10 | `1630854673` |
| RB | RB List | `1405459501` |
| CF Target | CF - Type A (Target) | `1630857074` |
| CF Runner | CF - Type B (Runner) | `1630857775` |

On each tab:
- The header block at the top (title plus the bullet list of traits we need) is information only.
- The **table header row** is the row whose column A says `Name`. Find it by that text, because the trait lists vary in length.
- Columns: **A Name · B Club · C Mins 26/27 · D Notes · E Progress (Y/N)**.
- **Read-only:** never write to the workbook. If Excel has it open (a `~$` lock file exists), refuse to run and say why.

---

## 4. Live Watchlist

Board `5092355536`: https://bristolrovers-company.monday.com/boards/5092355536

⚠ Its groups and columns are unknown. Use `discover` to agree with Dhillon:
- which group new players go into
- which column takes **Club** (column B)
- which column takes **Position** (the tab name)
- whether a column takes **Notes** (column D)

---

## 5. Sync rules (for each row with Progress = Y)

**(a) Position board shortlist**
1. Find the player on that tab's board with the matcher, ignoring Unattainable groups:
   - **Already in the shortlist group:** do nothing.
   - **In another group:** `move_item_to_group` into the shortlist group.
   - **Only in an Unattainable group:** skip him and report it. Dhillon decides by hand.
   - **Not on the board:** `create_item` in the shortlist group with his name, then set Current Club (resolved by title) from column B. Report it as "created" so Dhillon can check for duplicates.
2. ⚠ The shortlist group is assumed to be the group whose title contains "short". Confirm this for each board in `discover`. If a board has no such group, stop and ask. Don't create one.

**(b) Live Watchlist**
1. **Already on the board:** do nothing.
2. **Not on the board:** create him in the confirmed group and fill the mapped columns with `change_simple_column_value`. Status/dropdown labels must already exist; if one doesn't, skip that column and report it.

**Never** delete items, change any column other than those above, or touch Unattainable groups. Progress = N means no Monday action.

---

## 6. Tests (pytest, no network, mocked API in `monday-minutes` style)

- The header row is found from the "Name" text on tabs with different trait-list lengths.
- Only Progress = Y rows sync. N and blank rows are ignored.
- Matcher cases:
  - exact match
  - known name vs full legal name
  - misspelt club
  - ambiguous match → skipped
  - only in Unattainable → skipped
  - not found → created
- A dry run makes no writes. Running `--apply` twice makes no writes the second time.
- A run killed halfway resumes cleanly, because state is read from Monday.
- A 429 returned as HTML triggers the backoff.
- The workbook file is unchanged after a run (checksum).

---

## 7. Order of work

1. Read the `monday-minutes` README and code, the API reference and `pipeline_sync.py`.
2. Build `discover` and run it. **Wait** for Dhillon to confirm the shortlist group on each board and the Live Watchlist mapping.
3. Build `sync` and its tests. Dry-run it on a test row and show Dhillon. Only run `--apply` when he says so.
4. Write a short README covering the commands and the routine: set Progress = Y in Excel → `sync` (dry run) → `sync --apply`.

## 8. Done when

- The discovery report has been reviewed and the mappings confirmed.
- With Progress = Y on a test row, `sync --apply` moves or creates the player in the correct shortlist group **and** adds him to the Live Watchlist. A second run does nothing.
- All tests pass, and the workbook is untouched.
