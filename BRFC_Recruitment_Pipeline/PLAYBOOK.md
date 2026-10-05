# Position playbook: from data to video review

This is the routine used for CB, repeated for each position tab in the Google Sheet
**BRFC_Recruitment_Pipeline**.

## Data held (in `data/`, gitignored because it's licensed StatsBomb data)

| File | Covers | Seasons | Feeds tab(s) |
|---|---|---|---|
| `CB_all_leagues_3seasons.xlsx` | Centre backs | 24/25, 25/26, 26/27 | CB |
| `positions/PlayerSeason_GK_EN5_300mins.xlsx` | Goalkeepers | 24/25, 25/26, 26/27 | GK |
| `positions/PlayerSeason_FB_EN5_300mins.xlsx` | Full-backs and wing-backs | 24/25, 25/26, 26/27 | LB (left side), RB (right side) |
| `positions/PlayerSeason_DMCM_EN5_300mins.xlsx` | Defensive and central midfielders | 24/25, 25/26, 26/27 | CM 6 (DMs only), CM 8 (all) |
| `positions/PlayerSeason_AM_EN5_300mins.xlsx` | Attacking midfielders | 24/25, 25/26, 26/27 | CM 10 (central), Winger (wide AMs) |
| `positions/PlayerSeason_CF_EN5_300mins.xlsx` | Centre forwards | 24/25, 25/26, 26/27 | CF Target, CF Runner |
| `positions/Wingers_K_League_1_2025.xlsx` | K League 1 wingers and wide midfielders | 2025 | Winger |

EN5 means Championship, League One, League Two, National League and Scottish Premiership, with players
on 300+ minutes. Every file has the same 226 StatsBomb player-season columns.

**Missing:** there's no English or Scottish wingers export (LW/RW/LM/RM). The Winger tab only has the
wide attacking midfielders from the AM file plus K League. Ask for an EN5 wingers export before the
Winger tab is done.

## Rating (`position_rating.py`)

`python3 position_rating.py "CM 6"` rates every player for that tab:
1. **Season rating:** a weighted average of metric families. Each family is the player's mean percentile
   against the same position pool in the same league-season.
2. **Level-adjusted rating:** `0.6 × rating + 40 × league strength`, so all leagues sit on one scale.
   League strength is Championship 1.0, L1/SPL/K League 1 0.8, L2 0.6 and NL 0.35. K League's figure
   is an assumption.
3. **Player rating:** the level-adjusted season ratings, weighted by recency and by minutes reliability.

The families and weights for each tab come from that tab's "WHAT WE NEED" list. They're set in
`POSITIONS`. Some needs have no metric, such as GK "organises the back line" and 6 "organiser / leader",
so those are left to video.

## Steps for each position

1. **Rate.** Run `position_rating.py` for the tab. Note Bristol's current players in that position: they're the bar to beat.
2. **Cross-match to find options we could get:**
   - higher league (Championship, L1, SPL) with under 500 minutes this season
   - out of contract 2027 (Monday OOC boards)
   - loanees (Monday loan boards)
   - proven at L2/NL level and beating our current players
   - Skip anyone in an Unattainable group, and anyone 33 or older.
   - Prefer Monday's current club and minutes over the data's.
   - Add a Transfermarkt value from the List Data Scores HTML where there is one.
3. **Write a "<Position> Data Options" tab** that is grouped by route, with the method and the bar to beat at the top.
4. **The user picks names.** Add them to the position tab with Name, Club and Mins 26/27. Leave Notes and
   Progress blank for the scouts. Fill DATA Stand Outs with gap metrics only, names only, where the
   player is in the top 30%.
5. **Video.** Progress = Y moves the player to Short List on the Monday board (Apps Script).
6. **Squad Planner.** Rank each slot's Short List with 50% data rating + 50% scouting evidence, and show the top 5.

## Status

| Tab | Rated | Options tab | Players added | Planner |
|---|---|---|---|---|
| CB | ✅ | ✅ CB Data Options | ✅ 10 | ✅ LCB / RCB |
| GK, LB, RB, CM 6, CM 8, CM 10, CF Target, CF Runner | ✅ model ready | – | – | – |
| Winger | ⚠ needs EN5 wingers export | – | – | – |
