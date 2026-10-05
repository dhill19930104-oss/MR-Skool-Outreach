#!/usr/bin/env python3
"""CB data rating from the StatsBomb 3-season export (data/CB_all_leagues_3seasons.xlsx, one tab per league).

Season rating (0-100): weighted family scores, each family = mean percentile vs CBs in the same league-season.
Families and weights follow Bristol's CB gaps:
    aerial 20 | security under pressure 20 | winning it back 15 | 1v1 15 | clearances/blocks 10 |
    set-piece goals 10 | pressure regains 5 | defensive OBV 5
Level-adjusted rating puts leagues on one scale:  0.6 * rating + 40 * league strength.
Player rating: seasons weighted by recency (26/27 .30, 25/26 .45, 24/25 .25) x minutes reliability (mins/900, max 1).
"""
import os, re, unicodedata
from datetime import date
from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT = os.path.join(HERE, "data", "CB_all_leagues_3seasons.xlsx")
TODAY = date(2026, 10, 5)

FAMILIES = {  # family: (weight, [(column, higher_is_better), ...])
    "aerial":   (20, [("aerial_ratio", True), ("aerial_wins_90", True)]),
    "secure":   (20, [("pressured_passing_ratio", True), ("errors_90", False), ("turnovers_90", False),
                      ("dispossessions_90", False)]),
    "winback":  (15, [("padj_tackles_and_interceptions_90", True), ("ball_recoveries_90", True),
                      ("defensive_action_regains_90", True)]),
    "1v1":      (15, [("challenge_ratio", True), ("dribbled_past_90", False)]),
    "clear":    (10, [("padj_clearances_90", True), ("blocks_per_shot", True)]),
    "setpiece": (10, [("npg_90", True), ("np_xg_90", True)]),
    "press":    (5,  [("pressure_regains_90", True)]),
    "value":    (5,  [("obv_defensive_action_90", True)]),
}
FAMILY_LABEL = {"aerial": "Aerial", "secure": "Secure under press", "winback": "Wins it back", "1v1": "1v1",
                "clear": "Clearances/blocks", "setpiece": "Set-piece goals", "press": "Pressure regains",
                "value": "Defensive OBV"}
STRENGTH = {"Championship": 1.0, "League One": 0.8, "Scotland Premiership": 0.8, "League Two": 0.6,
            "National League": 0.35}
SEASON_W = {"2026/2027": 0.30, "2025/2026": 0.45, "2024/2025": 0.25}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).split()


def load():
    wb = load_workbook(EXPORT, read_only=True, data_only=True)
    rows, seen = [], set()
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        head = [h.replace("player_season_", "") for h in next(it)]
        for r in it:
            if not r[0]: continue
            d = dict(zip(head, r))
            key = (d["player_id"], d["season_name"], d["team_id"])
            if key in seen: continue  # the export repeats some players under a second spelling
            seen.add(key)
            d["name"] = d.get("player_known_name") or d["player_name"]
            rows.append(d)
    return rows


def pct(v, vals, hi):
    if not isinstance(v, (int, float)): return None
    vals = [x for x in vals if isinstance(x, (int, float))]
    better = sum(1 for x in vals if (x < v if hi else x > v))
    return 100 * (better + 0.5 * sum(1 for x in vals if x == v)) / len(vals)


def rate(rows):
    """Adds season rating, family scores and level-adjusted rating to every row."""
    groups = {}
    for r in rows: groups.setdefault((r["league"], r["season_name"]), []).append(r)
    for peers in groups.values():
        cols = {c: [p.get(c) for p in peers] for _, ms in FAMILIES.values() for c, _ in ms}
        for r in peers:
            fam, tot, wsum = {}, 0, 0
            for f, (w, ms) in FAMILIES.items():
                ps = [pct(r.get(c), cols[c], hi) for c, hi in ms]
                ps = [p for p in ps if p is not None]
                if not ps: continue
                fam[f] = sum(ps) / len(ps); tot += w * fam[f]; wsum += w
            r["fam"] = fam
            r["rating"] = tot / wsum if wsum else None
            r["adj"] = 0.6 * r["rating"] + 40 * STRENGTH[r["league"]] if r["rating"] is not None else None
    return rows


def players(rows):
    """One record per player: recency x minutes weighted rating, latest season, trend."""
    by = {}
    for r in rows: by.setdefault(r["player_id"], []).append(r)
    out = []
    for pid, rs in by.items():
        rs = [r for r in rs if r["adj"] is not None]
        if not rs: continue
        w = [(SEASON_W[r["season_name"]] * min(r["minutes"] / 900, 1), r) for r in rs]
        tw = sum(x for x, _ in w)
        latest = max(rs, key=lambda r: (r["season_name"], r["minutes"]))
        fam = {}
        for f in FAMILIES:
            vals = [(x, r["fam"][f]) for x, r in w if f in r["fam"]]
            if vals: fam[f] = sum(x * v for x, v in vals) / sum(x for x, _ in vals)
        by_season = {}
        for r in rs:  # a mid-season move gives two rows; keep the bigger one per season
            if r["season_name"] not in by_season or r["minutes"] > by_season[r["season_name"]]["minutes"]:
                by_season[r["season_name"]] = r
        seasons = sorted(by_season)
        trend = (by_season[seasons[-1]]["adj"] - by_season[seasons[-2]]["adj"]) if len(seasons) > 1 else None
        bd = latest.get("birth_date")
        age = None
        if bd:
            y, m, d = map(int, bd[:10].split("-"))
            age = TODAY.year - y - ((TODAY.month, TODAY.day) < (m, d))
        mins_now = sum(r["minutes"] for r in rs if r["season_name"] == "2026/2027")
        lfr = sum(r["minutes"] * (r.get("left_foot_ratio") or 0) for r in rs) / sum(r["minutes"] for r in rs)
        out.append({
            "id": pid, "name": latest["name"], "team": latest["team_name"], "league": latest["league"],
            "season": latest["season_name"], "age": age, "height": latest.get("player_height"),
            "foot": "L" if lfr > 0.5 else "R", "mins_2627": round(mins_now),
            "rating": sum(x * r["adj"] for x, r in w) / tw, "raw": sum(x * r["rating"] for x, r in w) / tw,
            "fam": fam, "trend": trend, "n_seasons": len(seasons),
            "history": "; ".join(f"{s[2:4]}/{s[7:9]} {by_season[s]['team_name']} ({by_season[s]['league']}, "
                                 f"{round(by_season[s]['minutes'])}') {by_season[s]['adj']:.0f}" for s in seasons),
        })
    return out


def strengths(p, n=3):
    top = sorted(p["fam"].items(), key=lambda kv: -kv[1])
    return ", ".join(FAMILY_LABEL[f] for f, v in top[:n] if v >= 65) or "-"


if __name__ == "__main__":
    ps = players(rate(load()))
    for p in sorted(ps, key=lambda p: -p["rating"])[:25]:
        print(f"{p['rating']:5.1f} {p['name']:28} {p['team']:24} {p['league']:20} age {p['age']} {p['foot']} "
              f"26/27 {p['mins_2627']}' | {strengths(p)}")
