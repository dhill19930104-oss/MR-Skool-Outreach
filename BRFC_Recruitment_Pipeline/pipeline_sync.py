#!/usr/bin/env python3
"""
BRFC Recruitment Pipeline <-> Monday.com sync.

Commands (run on your Mac, from the folder holding this script):

  python3 pipeline_sync.py inspect --board "Live Watchlist"
      Shows a board's groups and columns (use once to check names).

  python3 pipeline_sync.py pull --tab CB
      Pulls every candidate for a position from Monday (position board, OOC 2027 boards,
      loan boards, Data-Driven Watchlist; Unattainable groups skipped) into pull_CB.csv.
      Send that CSV to Claude to qualify against the profile.

  python3 pipeline_sync.py sync --file BRFC_Recruitment_Pipeline.xlsx           (dry run)
  python3 pipeline_sync.py sync --file BRFC_Recruitment_Pipeline.xlsx --apply   (writes)
      Progress (Y/N) = Y -> player moved into the Shortlist group of the tab's Monday board
                            (created there if he isn't on the board yet) AND added to the Live Watchlist.
      The workbook is only read. Re-runs are safe: players already in place are skipped.

Token: export MONDAY_API_KEY=...   (or put MONDAY_API_KEY=... in a .env file next to this script).
Never commit or share the token.
"""
import argparse, csv, json, os, re, ssl, sys, time, unicodedata, urllib.error, urllib.request
from datetime import date

BOARD_IDS = {
    "CB List": "1405453688", "LB List": "1405455920", "RB List": "1405459501", "CM - 6": "1630835327",
    "CM - 8": "1630854223", "CM - 10": "1630854673", "Winger List": "1405463991",
    "CF - Type A (Target)": "1630857074", "CF - Type B (Runner)": "1630857775", "GK Lists": "1405448899",
    "Data-Driven Watchlist": "1661120502", "Live Watchlist": "5092355536", "U21 List": "1600769912",
    "ECH - Out of Contract 2027": "2135192629", "L1 - Out Of Contract 2027": "2135167421",
    "L2 - Out Of Contract 2027": "2135161181", "SPL - Out Of Contract 2027": "2135154604",
    "ECH - Loans 2026/27": "2132745869", "L1 - Loans 2026/27": "2133606339", "L2 - Loans 2026/27": "2133737830",
    "SPL - Loans 2026/27": "2134661464", "VNL - Loans 2026/27": "2134439757",
}
OOC_BOARDS = [b for b in BOARD_IDS if "Out Of Contract" in b or "Out of Contract" in b]
LOAN_BOARDS = [b for b in BOARD_IDS if "Loans" in b]
ROLE_BOARDS = {
    "GK": ["GK Lists"], "RCB": ["CB List"], "LCB": ["CB List"], "MCB": ["CB List"],
    "LB": ["LB List"], "LWB": ["LB List"], "RB": ["RB List"], "RWB": ["RB List"],
    "6": ["CM - 6"], "8": ["CM - 8"], "10": ["CM - 10"], "RW": ["Winger List"], "LW": ["Winger List"],
    "CF-A": ["CF - Type A (Target)"], "CF-B": ["CF - Type B (Runner)"],
}
TAB_BOARDS = {
    "GK": ["GK Lists"], "CB": ["CB List"], "LB-LWB": ["LB List"], "RB-RWB": ["RB List"],
    "CM 6-8": ["CM - 6", "CM - 8"], "W-10": ["Winger List", "CM - 10"],
    "CF": ["CF - Type A (Target)", "CF - Type B (Runner)"],
}
# group-title keywords per tab on OOC / loan / Data-Driven boards (prefix/contains match, case-insensitive)
TAB_GROUP_WORDS = {
    "GK": ["gk", "goalkeeper"], "CB": ["centre half", "centre back", "cb"],
    "LB-LWB": ["full-back", "full back", "wing-back", "lb", "left back"], "RB-RWB": ["full-back", "full back", "wing-back", "rb", "right back"],
    "CM 6-8": ["cm", "midfield", "6", "8"], "W-10": ["winger", "10", "wide"], "CF": ["cf", "striker", "forward"],
}
SHORTLIST_WORD = "short"        # group whose title contains this = shortlist group
EXCLUDE_PREFIX = "unattainable"  # never touch / pull these groups
HEADER_ROW, FIRST_ROW = 14, 15
TABS = ["CB", "GK", "CM 6-8", "LB-LWB", "W-10", "RB-RWB", "CF"]

# ---------------------------------------------------------------- API
def _key():
    k = os.environ.get("MONDAY_API_KEY")
    if not k:
        env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env):
            for line in open(env):
                if line.strip().startswith("MONDAY_API_KEY="):
                    k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k: sys.exit("Set MONDAY_API_KEY (export it, or put it in .env next to this script).")
    return k

def _ctx():
    ctx = ssl.create_default_context()
    try:
        import certifi; ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return ctx

_last = [0.0]
def monday(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for wait in [0, 15, 30, 45, 60]:
        if wait: print(f"  rate limited - waiting {wait}s"); time.sleep(wait)
        gap = time.time() - _last[0]
        if gap < 0.35: time.sleep(0.35 - gap)
        req = urllib.request.Request("https://api.monday.com/v2", data=body, headers={
            "Authorization": _key(), "Content-Type": "application/json", "API-Version": "2024-10"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
                _last[0] = time.time(); payload = json.load(r)
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code == 429: continue
            raise
        if "errors" in payload:
            if any("complexity" in str(x).lower() or "rate" in str(x).lower() for x in payload["errors"]): continue
            raise RuntimeError(payload["errors"])
        return payload["data"]
    raise RuntimeError("Still rate limited after retries - run again in a few minutes (it resumes).")

_struct = {}
def board(name):
    if name not in _struct:
        d = monday("query($id:[ID!]){boards(ids:$id){id name groups{id title} columns{id title type}}}", {"id": [BOARD_IDS[name]]})
        _struct[name] = d["boards"][0]
    return _struct[name]

_items = {}
def items(name):
    if name not in _items:
        out, cur = [], None
        while True:
            d = monday("""query($id:[ID!],$c:String){boards(ids:$id){items_page(limit:200,cursor:$c){cursor
                       items{id name group{id title} column_values{id text}}}}}""", {"id": [BOARD_IDS[name]], "c": cur})
            pg = d["boards"][0]["items_page"]; out += pg["items"]; cur = pg["cursor"]
            if not cur: break
        _items[name] = out
    return _items[name]

def col_by_title(bname, *words):
    for c in board(bname)["columns"]:
        t = c["title"].lower()
        if any(w in t for w in words): return c
    return None

# ---------------------------------------------------------------- matching
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).split()

def find_player(bname, player, club=""):
    """Exact normalised name first; else unique surname + first-initial match. Returns (item, how)."""
    tgt = norm(player)
    if not tgt: return None, "no name"
    live = [i for i in items(bname) if not (i["group"]["title"] or "").lower().startswith(EXCLUDE_PREFIX)]
    exact = [i for i in live if norm(i["name"]) == tgt]
    if len(exact) >= 1:
        if len(exact) > 1 and club:
            cc = col_by_title(bname, "current club", "club", "team")
            if cc:
                byclub = [i for i in exact if norm(club)[:1] and norm(club)[0] in " ".join(norm(next((v["text"] for v in i["column_values"] if v["id"] == cc["id"]), "")))]
                if len(byclub) == 1: return byclub[0], "exact+club"
        return exact[0], "exact" if len(exact) == 1 else f"exact (first of {len(exact)} rows)"
    loose = [i for i in live if norm(i["name"]) and norm(i["name"])[-1] == tgt[-1] and norm(i["name"])[0][:1] == tgt[0][:1]]
    if len(loose) == 1: return loose[0], f"loose ({loose[0]['name']})"
    return None, "not on board"

def in_unattainable(boards, player):
    tgt = norm(player)
    for b in boards:
        for i in items(b):
            if (i["group"]["title"] or "").lower().startswith(EXCLUDE_PREFIX):
                n = norm(i["name"])
                if n == tgt or (n and tgt and n[-1] == tgt[-1] and n[0][:1] == tgt[0][:1]): return True
    return False

def group_with(bname, word):
    for g in board(bname)["groups"]:
        if word in g["title"].lower(): return g
    return None

# ---------------------------------------------------------------- pull
def cmd_pull(tab, out):
    words = TAB_GROUP_WORDS[tab]
    rows, titles = [], set()
    def take(bname, group_ok):
        b = board(bname); idmap = {c["id"]: c["title"] for c in b["columns"]}
        n = 0
        for it in items(bname):
            g = it["group"]["title"] or ""
            if g.lower().startswith(EXCLUDE_PREFIX) or not group_ok(g): continue
            rec = {"Player": it["name"], "Source board": bname, "Group": g, "Monday item id": it["id"]}
            for v in it["column_values"]:
                t = idmap.get(v["id"], v["id"])
                if v["text"]: rec[t] = v["text"]; titles.add(t)
            rows.append(rec); n += 1
        print(f"  {bname}: {n}")
    gmatch = lambda g: any(w == g.lower().strip() or g.lower().startswith(w) or f" {w}" in f" {g.lower()}" for w in words)
    print(f"Pulling {tab} candidates...")
    for bname in TAB_BOARDS[tab]: take(bname, lambda g: True)
    for bname in OOC_BOARDS + LOAN_BOARDS + ["Data-Driven Watchlist"]: take(bname, gmatch)
    base = ["Player", "Source board", "Group", "Monday item id"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=base + sorted(titles - set(base)), extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {out}  (duplicates across boards kept on purpose: source board tells you OOC / loan / list)")

# ---------------------------------------------------------------- sync
SHEET_BOARD = {"CB": "CB List", "GK": "GK Lists", "CM 6": "CM - 6", "LB": "LB List", "Winger": "Winger List",
               "CM 8": "CM - 8", "CM 10": "CM - 10", "RB": "RB List", "CF Target": "CF - Type A (Target)",
               "CF Runner": "CF - Type B (Runner)"}

def cmd_sync(path, apply):
    """Progress (Y/N) = Y  ->  shortlist group on the tab's Monday board  +  Live Watchlist.
    Read-only on the workbook; idempotent by checking Monday state."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    plan = []
    for tab, bname in SHEET_BOARD.items():
        if tab not in wb.sheetnames: continue
        rows = list(wb[tab].iter_rows(values_only=True))
        hr = next((i for i, r in enumerate(rows) if r and str(r[0] or "").strip() == "Name"), None)
        if hr is None: continue
        for r in rows[hr + 1:]:
            name, club, prog = (r[0], r[1], r[4]) if len(r) >= 5 else (None, None, None)
            if name and str(prog or "").strip().upper() == "Y": plan.append((tab, bname, str(name).strip(), str(club or "").strip()))
    if not plan: print("Nothing to sync - no Progress = Y rows."); return
    print(f"{len(plan)} player(s) with Progress = Y{'' if apply else ' (DRY RUN - add --apply to write)'}:")
    for tab, bname, name, club in plan:
        try:
            g = group_with(bname, SHORTLIST_WORD)
            if not g: raise RuntimeError(f"no group containing '{SHORTLIST_WORD}' on {bname}")
            it, how = find_player(bname, name, club)
            if it and it["group"]["id"] == g["id"]:
                print(f"  {name}: already in {bname} / {g['title']}")
            elif it:
                print(f"  {name}: MOVE on {bname} {it['group']['title']} -> {g['title']} [{how}]")
                if apply: monday("mutation($i:ID!,$g:String!){move_item_to_group(item_id:$i,group_id:$g){id}}", {"i": it["id"], "g": g["id"]})
            elif in_unattainable([bname], name):
                print(f"  {name}: SKIPPED - in Unattainable on {bname}, move by hand if that has changed"); continue
            else:
                print(f"  {name}: CREATE in {bname} / {g['title']}")
                if apply:
                    new = monday("mutation($b:ID!,$g:String!,$n:String!){create_item(board_id:$b,group_id:$g,item_name:$n){id}}",
                                 {"b": BOARD_IDS[bname], "g": g["id"], "n": name})["create_item"]["id"]
                    cc = col_by_title(bname, "current club")
                    if cc and club:
                        monday("mutation($b:ID!,$i:ID!,$c:String!,$v:String!){change_simple_column_value(board_id:$b,item_id:$i,column_id:$c,value:$v){id}}",
                               {"b": BOARD_IDS[bname], "i": new, "c": cc["id"], "v": club})
            lw, _ = find_player("Live Watchlist", name, club)
            if lw:
                print(f"  {name}: already on Live Watchlist")
            else:
                lg = board("Live Watchlist")["groups"][0]  # ⚠ confirm target group in discover
                print(f"  {name}: ADD to Live Watchlist / {lg['title']}")
                if apply:
                    new = monday("mutation($b:ID!,$g:String!,$n:String!){create_item(board_id:$b,group_id:$g,item_name:$n){id}}",
                                 {"b": BOARD_IDS["Live Watchlist"], "g": lg["id"], "n": name})["create_item"]["id"]
                    for words, val in [(("current club", "club", "team"), club), (("position",), tab)]:
                        c = col_by_title("Live Watchlist", *words)
                        if c and val and c["type"] in ("text", "long_text", "status", "dropdown"):
                            try: monday("mutation($b:ID!,$i:ID!,$c:String!,$v:String!){change_simple_column_value(board_id:$b,item_id:$i,column_id:$c,value:$v){id}}",
                                        {"b": BOARD_IDS["Live Watchlist"], "i": new, "c": c["id"], "v": val})
                            except Exception as ex: print(f"    ({c['title']} not set: {ex})")
        except Exception as ex:
            print(f"  SKIPPED {name}: {ex}")

def cmd_inspect(name):
    b = board(name)
    print(f"{b['name']} ({b['id']})\nGroups: " + " | ".join(g["title"] for g in b["groups"]))
    for c in b["columns"]: print(f"  {c['title']:<35} {c['type']:<12} {c['id']}")
    print(f"Items: {len(items(name))}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("pull"); a.add_argument("--tab", required=True, choices=TABS); a.add_argument("--out")
    b = sp.add_parser("sync"); b.add_argument("--file", default="BRFC_Recruitment_Pipeline.xlsx"); b.add_argument("--apply", action="store_true")
    c = sp.add_parser("inspect"); c.add_argument("--board", required=True, choices=list(BOARD_IDS))
    x = ap.parse_args()
    if x.cmd == "pull": cmd_pull(x.tab, x.out or f"pull_{x.tab.replace(' ', '_')}.csv")
    elif x.cmd == "sync": cmd_sync(x.file, x.apply)
    else: cmd_inspect(x.board)
