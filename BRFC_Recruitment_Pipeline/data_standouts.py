#!/usr/bin/env python3
"""Up to 3 data stand-outs per CB, only from metrics that fill a current Bristol gap
(first balls / direct play, 1v1, winning the ball back, security under pressure, set-piece threat).
A metric counts when the player is in the top 30% of CBs in his most recent league-season export.
Usage:  python3 data_standouts.py "Joe Wright" "Kaelan Casey" ...
"""
import os, re, sys, unicodedata
from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
# newest first: a player is judged on his most recent export
EXPORTS = [("L2 26/27", "data/CB_L2_2627.xlsx", 300), ("L1 25/26", "data/CB_L1_2526.xlsx", 500),
           ("L2 25/26", "data/CB_L2_2526.xlsx", 500),
           ("L1 24/25", "data/CB_L1_2425.xlsx", 500), ("L2 24/25", "data/CB_L2_2425.xlsx", 500)]

# (label, column titles to try, higher is better, helps our gaps, family - one stand-out per family)
METRICS = [  # (label, column titles to try, higher is better, family - one stand-out per family)
    ("Aerial Win%", ["Aerial Win%"], True, "aerial"),
    ("Aerial Wins", ["Aerial Wins"], True, "aerial"),
    ("Dribbles Stopped%", ["Dribbles Stopped%"], True, "1v1"),
    ("Low Dribbled Past", ["Dribbled Past"], False, "1v1"),
    ("PAdj Tack&Int", ["PAdj Tack&Int"], True, "ballwin"),
    ("PAdj Interceptions", ["PAdj Interceptions"], True, "ballwin"),
    ("PAdj Tackles", ["PAdj Tackles"], True, "ballwin"),
    ("Ball Recoveries", ["Ball Recoveries"], True, "recover"),
    ("Pressure Regains", ["Pressure Regains"], True, "press"),
    ("PAdj Clearances", ["PAdj Clearances"], True, "clear"),
    ("Pressured Pass%", ["Pr. Pass%"], True, "secure"),
    ("Low Errors", ["Errors"], False, "secure"),
    ("Low Turnovers", ["Turnovers"], False, "secure"),
    ("NP Goals", ["NP Goals", "Non Penalty Goals"], True, "setpiece"),
]
MIN_PCT = 70

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
        for label, cols, hi, fam in METRICS:
            col = next((c for c in cols if c in me), None)
            if col is None or not isinstance(me[col], (int, float)): continue
            vals = [r[col] for r in peers if isinstance(r.get(col), (int, float))]
            better = sum(1 for v in vals if (v < me[col] if hi else v > me[col]))
            equal = sum(1 for v in vals if v == me[col])
            pct = round(100 * (better + 0.5 * equal) / len(vals))
            scored.append((pct, label, fam))
        picks, fams = [], set()
        for pct, label, fam in sorted(scored, reverse=True):
            if pct < MIN_PCT or fam in fams: continue
            picks.append(label); fams.add(fam)
            if len(picks) == 3: break
        return ", ".join(picks) or "None in the top 30% for our gaps"
    return None

if __name__ == "__main__":
    for n in sys.argv[1:]:
        print(f"{n}: {standouts(n) or 'no CB data in the exports'}")
