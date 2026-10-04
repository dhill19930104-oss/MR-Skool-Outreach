# Auto-sync from the Google Sheet to Monday

`MondaySync.gs` runs inside the **BRFC_Recruitment_Pipeline** Google Sheet. When **Y** goes into
**Progress (Y/N)** on any position tab, the player is moved into **Short List** on that tab's Monday
board, or created there if he isn't on the board yet. The outcome is written as a note on the Progress cell.
To read it, hover over the cell.

| Tab | Monday board |
|---|---|
| CB | CB List |
| GK | GK Lists |
| CM 6 / CM 8 / CM 10 | CM - 6 / CM - 8 / CM - 10 |
| LB / RB | LB List / RB List |
| Winger | Winger List |
| CF Target / CF Runner | CF - Type A (Target) / CF - Type B (Runner) |

## Install (once, about 3 minutes)

1. In the Google Sheet, open **Extensions → Apps Script**.
2. Delete the placeholder code, paste in all of `MondaySync.gs`, and save.
3. Open **Project Settings** (cog icon) → **Script properties** → **Add script property**:
   name `MONDAY_API_KEY`, value = your Monday API token. Save.
4. Back in the editor, choose the `setup` function in the toolbar and click **Run**. Approve the Google
   permission prompt (it needs to edit this sheet and call api.monday.com).
5. Reload the sheet. A **Monday** menu appears, with **Sync all Y rows now** and **Dry run (no changes)**.

`setup` installs two triggers:
- **On edit:** reacts as soon as someone types or pastes Y.
- **Every 15 minutes:** a sweep that catches Ys added in other ways, such as by another tool, or a run that hit Monday's rate limit.

## What it does with each Y row

| On the tab's board | Result (note on the Progress cell) |
|---|---|
| Already in Short List | `already in Short List`, nothing changes |
| In another group | `moved <group> -> Short List` |
| Only in Unattainable | `SKIPPED`: move by hand if that has changed |
| Not on the board | `created in Short List`, Current Club set from column B. Check for duplicates |
| Several possible rows, or a loose name match at a different club | `SKIPPED`: check by hand. It never guesses |

Every decision is made from live Monday state, so a Y that is checked again by the sweep never repeats a change.
It never deletes anything, never touches Unattainable groups, and only changes the item's group, plus the
Current Club on a newly created item. N or blank means no action. Removing a Y does not move anyone back.

## Notes

- Anyone with edit access to the sheet can open Apps Script and see the token. Keep editors to the
  recruitment team, and rotate the token if that changes.
- To pause the sync, open the Apps Script editor → **Triggers** (clock icon) and delete both triggers.
  Run `setup` again to turn it back on.
