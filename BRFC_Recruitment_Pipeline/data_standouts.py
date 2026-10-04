#!/usr/bin/env python3
"""Pick each CB's 3 data stand-outs vs CBs in the same league-season export.

A trait marked * helps a current Bristol gap (first balls / direct play, 1v1, winning the ball back,
security under pressure, set-piece threat). Usage:  python3 data_standouts.py "Joe Wright" "Kaelan Casey" ...
"""
import os, re, sys, unicodedata
from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
# newest first: a player is judged on his most recent export
EXPORTS = [("L2 26/27", "data/CB_L2_2627.xlsx", 300), ("L1 25/26", "data/CB_L1_2526.xlsx", 500),
           ("L2 25/26", "data/CB_L2_2526.xlsx", 500),
           ("L1 24/25", "data/CB_L1_2425.xlsx", 500), ("L2 24/25", "data/CB_L2_2425.xlsx", 500)]

# (label, column titles to try, higher is better, helps our gaps, family - one stand-out per family)
METRICS = [
    ("Aerial Win%", ["Aerial Win%"], True, True, "aerial"),
    ("Aerial Wins", ["Aerial Wins"], True, True, "aerial"),
    ("Dribbles Stopped%", ["Dribbles Stopped%"], True, True, "1v1"),
    ("Dribbled Past", ["Dribbled Past"], False, True, "1v1"),
    ("PAdj Tack&Int", ["PAdj Tack&Int"], True, True, "ballwin"),
    ("PAdj Interceptions", ["PAdj Interceptions"], True, True, "ballwin"),
    ("PAdj Tackles", ["PAdj Tackles"], True, True, "ballwin"),
    ("Ball Recoveries", ["Ball Recoveries"], True, True, "recover"),
    ("Pressure Regains", ["Pressure Regains"], True, True, "press"),
    ("PAdj Clearances", ["PAdj Clearances"], True, True, "clear"),
    ("Pressured Pass%", ["Pr. Pass%"], True, True, "secure"),
    ("Errors", ["Errors"], False, True, "secure"),
    ("Turnovers", ["Turnovers"], False, True, "secure"),
    ("NP Goals", ["NP Goals", "Non Penalty Goals"], True, True, "setpiece"),
    ("Blocks/Shot", ["Blocks/Shot"], True, False, "block"),
    ("Passing%", ["Passing%"], True, False, "passing"),
    ("Long Ball%", ["Long Ball%"], True, False, "long"),
    ("Deep Progressions", ["Deep Progressions"], True, False, "progress"),
    ("xGBuildup", ["xGBuildup"], True, False, "progress"),
    ("PAdj Pressures", ["PAdj Pressures"], True, False, "pressvol"),
]
PCT = {"Aerial Win%", "Dribbles Stopped%", "Pressured Pass%", "Passing%", "Long Ball%"}

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).split()

def same_player(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or (a[-1] == b[-1] and a[0] == b[0]))

def load(path, min_mins):
    rows = list(load_workbook(os.path.join(HERE, path), read_only=True, data_only=True).active.iter_rows(values_only=True))
    head = list(rows[0])
    out = [dict(zip(head, r)) for r in rows[1:] if r and r[0]]
    return [r for r in out if isinstance(r.get("Minutes"), (int, float)) and r["Minutes"] >= min_mins]

def standouts(name, exports=EXPORTS):
    for league, path, min_mins in exports:
        if not os.path.exists(os.path.join(HERE, path)): continue
        peers = load(path, min_mins)
        me = [r for r in peers if same_player(r["Name"], name)]
        if not me: continue
        me = max(me, key=lambda r: r["Minutes"])
        scored = []
        for label, cols, hi, star, fam in METRICS:
            col = next((c for c in cols if c in me), None)
            if col is None or not isinstance(me[col], (int, float)): continue
            vals = [r[col] for r in peers if isinstance(r.get(col), (int, float))]
            better = sum(1 for v in vals if (v < me[col] if hi else v > me[col]))
            equal = sum(1 for v in vals if v == me[col])
            pct = round(100 * (better + 0.5 * equal) / len(vals))
            scored.append((pct, label, me[col], star, fam))
        picks, fams = [], set()
        for s in sorted(scored, key=lambda s: (-s[0], not s[3])):
            if s[4] in fams: continue
            picks.append(s); fams.add(s[4])
            if len(picks) == 3: break
        def fmt(p):
            pct, label, v, star, _ = p
            val = f"{v:.0f}%" if label in PCT else (f"{v:.2f}" if v < 10 else f"{v:.1f}")
            suffix = "th" if 10 <= pct % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th")
            return f"{'*' if star else ''}{label} {val} ({pct}{suffix} pct)"
        return f"vs {league} CBs ({int(me['Minutes'])}'): " + " · ".join(fmt(p) for p in picks)
    return None

if __name__ == "__main__":
    for n in sys.argv[1:]:
        print(f"{n}: {standouts(n) or 'no CB data in the exports'}")
