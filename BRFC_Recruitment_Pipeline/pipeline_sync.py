#!/usr/bin/env python3
"""
BRFC Recruitment Pipeline <-> Monday.com sync.

Commands (run on your Mac, from the folder holding this script):

  python3 pipeline_sync.py discover
      Read-only. Groups, columns and item counts for the 10 position boards + Live Watchlist
      -> discovery_report.md.

  python3 pipeline_sync.py inspect --board "Live Watchlist"
      Shows a board's groups and columns (use once to check names).

  python3 pipeline_sync.py pull --tab CB
      Pulls every candidate for a position from Monday (position board, OOC 2027 boards,
      loan boards, Data-Driven Watchlist; Unattainable groups skipped) into pull_CB.csv.
      Send that CSV to Claude to qualify against the profile.

  python3 pipeline_sync.py sync --file BRFC_Recruitment_Pipeline.xlsx           (dry run)
  python3 pipeline_sync.py sync --file BRFC_Recruitment_Pipeline.xlsx --apply   (writes)
      Progress (Y/N) = Y -> player moved into the Short List group of the tab's Monday board
                            (created there if he isn't on the board yet). Live Watchlist is done by hand.
      Each player also gets a profile check: bullet-point comments on Monday, and a report
      (subitem with a file) dated within the last 12 months.
      The workbook is only read. Re-runs are safe: players already in place are skipped.

Token: export MONDAY_API_KEY=...   (or put MONDAY_API_KEY=... in a .env file next to this script).
Never commit or share the token.
"""
import argparse, csv, html, json, os, re, ssl, sys, time, unicodedata, urllib.error, urllib.request
from datetime import date, timedelta

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

# board club names are abbreviated / misspelt - map to one form before comparing
CLUB_ALIASES = {
    "mk dons": "milton keynes dons", "sheff wed": "sheffield wednesday", "sheff utd": "sheffield united",
    "fgr": "forest green rovers", "forest green": "forest green rovers", "dag red": "dagenham redbridge",
    "dag and red": "dagenham redbridge", "dagenham and redbridge": "dagenham redbridge",
    "gatestead": "gateshead", "morecombe": "morecambe", "carisle": "carlisle", "carisle united": "carlisle united",
    "shewsbury": "shrewsbury", "shewsbury town": "shrewsbury town", "barsnley": "barnsley",
    "qrp": "queens park rangers", "qpr": "queens park rangers", "wolves": "wolverhampton wanderers",
    "brighton": "brighton and hove albion", "west brom": "west bromwich albion", "wba": "west bromwich albion",
    "spurs": "tottenham hotspur", "man city": "manchester city", "man utd": "manchester united",
    "notts forest": "nottingham forest", "nottm forest": "nottingham forest",
}
_CLUB_DROP = {"fc", "afc", "the", "and"}

def club_key(s):
    t = " ".join(norm(str(s or "").replace("&", " and ")))
    t = CLUB_ALIASES.get(t, t)
    t = t.replace("utd", "united")
    return [w for w in CLUB_ALIASES.get(t, t).split() if w not in _CLUB_DROP]

def same_club(a, b):
    """True if two club names refer to the same club, allowing 'Cambridge' vs 'Cambridge United'."""
    ka, kb = club_key(a), club_key(b)
    if not ka or not kb: return False
    if ka == kb: return True
    short, long_ = (ka, kb) if len(ka) < len(kb) else (kb, ka)
    return short[0] == long_[0] and set(short) <= set(long_)

def _club_of(bname, it):
    cc = col_by_title(bname, "current club")
    return next((v["text"] for v in it["column_values"] if cc and v["id"] == cc["id"]), "") or ""

def _name_hits(pool, player):
    tgt = norm(player)
    exact = [i for i in pool if norm(i["name"]) == tgt]
    if exact: return exact, "exact"
    # known name vs full legal name: same surname + same first initial
    loose = [i for i in pool if norm(i["name"]) and norm(i["name"])[-1] == tgt[-1] and norm(i["name"])[0][0] == tgt[0][0]]
    return loose, "loose"

def match_player(bname, player, club=""):
    """Returns (status, item, detail). status: found | ambiguous | unattainable | missing.
    Never guesses: several candidates, or a loose name match whose club disagrees, is 'ambiguous'."""
    if not norm(player): return "ambiguous", None, "no name"
    excluded = lambda i: (i["group"]["title"] or "").lower().startswith(EXCLUDE_PREFIX)
    live = [i for i in items(bname) if not excluded(i)]
    hits, how = _name_hits(live, player)
    if hits:
        if len(hits) > 1 and club:
            byclub = [i for i in hits if same_club(club, _club_of(bname, i))]
            if len(byclub) == 1: return "found", byclub[0], f"{how}+club"
        if len(hits) > 1:
            short = [i for i in hits if SHORTLIST_WORD in (i["group"]["title"] or "").lower()]
            names = ", ".join(f"{i['name']} ({_club_of(bname, i) or '?'}, {i['group']['title']})" for i in hits)
            if len(short) == 1 and how == "exact": return "found", short[0], f"exact, already shortlisted (other rows: {names})"
            return "ambiguous", None, f"{len(hits)} rows match: {names}"
        it = hits[0]
        if how == "loose":
            bclub = _club_of(bname, it)
            if not (club and bclub and same_club(club, bclub)):
                return "ambiguous", None, f"only a loose name match: '{it['name']}' ({bclub or 'no club'}) - check by hand"
            return "found", it, f"loose ({it['name']}, same club)"
        return "found", it, how
    if _name_hits([i for i in items(bname) if excluded(i)], player)[0]:
        return "unattainable", None, "only in Unattainable"
    return "missing", None, "not on board"

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
REPORT_DAYS = 365
_BULLET = re.compile(r"^\s*([•\-\*·–▪◦●]|\d+[.)])\s+\S", re.M)

def _plain(body):
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", body or "")
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).replace("﻿", "").replace("\xa0", " ")

def profile_check(item_id, today=None):
    """What's already on the player's Monday profile: bulleted comments, and a report (subitem with a file)
    dated within the last REPORT_DAYS days. Read-only."""
    today = today or date.today()
    d = monday("""query($i:[ID!]){items(ids:$i){updates(limit:100){created_at body}
               subitems{name created_at assets{id} column_values{id type text}}}}""", {"i": [item_id]})["items"][0]
    bullets = [u["created_at"][:10] for u in d["updates"] if _BULLET.search(_plain(u["body"]))]
    reports = []
    for s in d.get("subitems") or []:
        has_file = bool(s.get("assets")) or any(v["type"] == "file" and v["text"] for v in s["column_values"])
        if not has_file: continue
        when = next((v["text"][:10] for v in s["column_values"] if v["type"] == "date" and v["text"]), s["created_at"][:10])
        kind = next((v["text"] for v in s["column_values"] if v["id"] == "status" and v["text"]), "")
        reports.append((when, s["name"], kind))
    reports.sort(reverse=True)
    cutoff = (today - timedelta(days=REPORT_DAYS)).isoformat()
    recent = [r for r in reports if r[0] >= cutoff]
    return {"bullets": sorted(bullets, reverse=True), "reports": reports, "recent_reports": recent, "comments": len(d["updates"])}

def describe_profile(p):
    b = f"bullet comments: {len(p['bullets'])} (latest {p['bullets'][0]})" if p["bullets"] else "bullet comments: NONE"
    if p["recent_reports"]:
        w, n, k = p["recent_reports"][0]; r = f"report <1yr: yes - {n}{f' ({k})' if k else ''} {w}"
    elif p["reports"]:
        w, n, k = p["reports"][0]; r = f"report <1yr: NONE (last was {n} {w})"
    else:
        r = "report <1yr: NONE (no reports at all)"
    return f"{b} | {r}"

def read_rows(path):
    """Progress = Y rows from every position tab. The header row is the one whose column A says 'Name'."""
    lock = os.path.join(os.path.dirname(os.path.abspath(path)), "~$" + os.path.basename(path))
    if os.path.exists(lock):
        sys.exit(f"{os.path.basename(path)} is open in Excel ({os.path.basename(lock)} exists). Save and close it, then run again.")
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    out = []
    try:
        for tab, bname in SHEET_BOARD.items():
            if tab not in wb.sheetnames: continue
            rows = list(wb[tab].iter_rows(values_only=True))
            hr = next((i for i, r in enumerate(rows) if r and str(r[0] or "").strip().lower() == "name"), None)
            if hr is None: print(f"  ! tab {tab}: no 'Name' header row - skipped"); continue
            for r in rows[hr + 1:]:
                r = list(r) + [None] * (5 - len(r))
                if r[0] and str(r[4] or "").strip().upper() == "Y":
                    out.append((tab, bname, str(r[0]).strip(), str(r[1] or "").strip()))
    finally:
        wb.close()
    return out

def cmd_sync(path, apply, today=None):
    """Progress (Y/N) = Y  ->  Short List group on the tab's Monday board, plus a profile check.
    Read-only on the workbook; idempotent because every decision is made from live Monday state."""
    plan = read_rows(path)
    if not plan: print("Nothing to sync - no Progress = Y rows."); return []
    print(f"{len(plan)} player(s) with Progress = Y{'' if apply else '  (DRY RUN - add --apply to write)'}:\n")
    results = []
    for tab, bname, name, club in plan:
        try:
            g = group_with(bname, SHORTLIST_WORD)
            if not g: raise RuntimeError(f"no group containing '{SHORTLIST_WORD}' on {bname} - not creating one")
            status, it, detail = match_player(bname, name, club)
            if status == "found" and it["group"]["id"] == g["id"]:
                action, msg = "none", f"already in {g['title']} [{detail}]"
            elif status == "found":
                action, msg = "move", f"MOVE {it['group']['title']} -> {g['title']} [{detail}]"
                if apply:
                    monday("mutation($i:ID!,$g:String!){move_item_to_group(item_id:$i,group_id:$g){id}}", {"i": it["id"], "g": g["id"]})
                    it["group"] = {"id": g["id"], "title": g["title"]}
            elif status == "missing":
                action, msg = "create", f"CREATE in {g['title']} (not on board - check for duplicates afterwards)"
                if apply:
                    new = monday("mutation($b:ID!,$g:String!,$n:String!){create_item(board_id:$b,group_id:$g,item_name:$n){id}}",
                                 {"b": BOARD_IDS[bname], "g": g["id"], "n": name})["create_item"]["id"]
                    cc = col_by_title(bname, "current club")
                    cvals = []
                    if cc and club:
                        monday("mutation($b:ID!,$i:ID!,$c:String!,$v:String!){change_simple_column_value(board_id:$b,item_id:$i,column_id:$c,value:$v){id}}",
                               {"b": BOARD_IDS[bname], "i": new, "c": cc["id"], "v": club})
                        cvals = [{"id": cc["id"], "text": club}]
                    items(bname).append({"id": new, "name": name, "group": {"id": g["id"], "title": g["title"]}, "column_values": cvals})
            else:
                action, msg = "skip", f"SKIPPED - {detail}" + (" (move by hand if that has changed)" if status == "unattainable" else "")
            prof = profile_check(it["id"], today) if it else None
            print(f"  [{tab}] {name} ({club or 'no club'}) on {bname}: {msg}")
            if it: print(f"        {describe_profile(prof)}")
            elif action == "create": print("        new item - no comments or reports yet")
            results.append({"tab": tab, "name": name, "action": action, "profile": prof})
        except Exception as ex:
            print(f"  [{tab}] {name}: SKIPPED - {ex}")
            results.append({"tab": tab, "name": name, "action": "error", "profile": None})
    n = {k: sum(r["action"] == k for r in results) for k in ("move", "create", "none", "skip", "error")}
    verb = "done" if apply else "planned"
    print(f"\n{verb}: {n['move']} move, {n['create']} create, {n['none']} already shortlisted, {n['skip']} skipped, {n['error']} errors")
    return results

def cmd_discover(out):
    """Read-only. Groups, columns and top-level item counts for the 10 position boards + Live Watchlist."""
    lines = [f"# Discovery report — {date.today().isoformat()}", "",
             "Read-only snapshot. Confirm the **shortlist group** on each board and the **Live Watchlist** mapping before any `sync --apply`.", ""]
    summary = ["| Tab | Board | Top-level items | Shortlist group (title contains 'short') | Unattainable group(s) |", "|---|---|---|---|---|"]
    detail = []
    for tab, bname in list(SHEET_BOARD.items()) + [("—", "Live Watchlist")]:
        b = board(bname); its = items(bname)
        counts = {}
        for i in its: counts[i["group"]["title"]] = counts.get(i["group"]["title"], 0) + 1
        short = [g["title"] for g in b["groups"] if SHORTLIST_WORD in g["title"].lower()]
        unatt = [g["title"] for g in b["groups"] if g["title"].lower().startswith(EXCLUDE_PREFIX)]
        flag = " ⚠ none" if not short else (" ⚠ several" if len(short) > 1 else "")
        summary.append(f"| {tab} | {b['name']} (`{b['id']}`) | {len(its)} | {', '.join(short) or '—'}{flag} | {', '.join(unatt) or '—'} |")
        detail += [f"## {b['name']} (`{b['id']}`) — tab `{tab}`", "", "**Groups**", "", "| Group | id | Items |", "|---|---|---|"]
        detail += [f"| {g['title']} | `{g['id']}` | {counts.get(g['title'], 0)} |" for g in b["groups"]]
        detail += ["", "**Columns**", "", "| Title | Type | id |", "|---|---|---|"]
        detail += [f"| {c['title']} | {c['type']} | `{c['id']}` |" for c in b["columns"]]
        if bname == "Live Watchlist":
            detail += ["", "**Current items**", ""] + [f"- {i['name']} — {i['group']['title']}" for i in its]
        detail.append("")
        print(f"  {b['name']}: {len(its)} items, shortlist = {', '.join(short) or 'NONE'}")
    with open(out, "w") as f: f.write("\n".join(lines + summary + [""] + detail))
    print(f"Wrote {out}")

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
    sp.add_parser("discover");
    c = sp.add_parser("inspect"); c.add_argument("--board", required=True, choices=list(BOARD_IDS))
    x = ap.parse_args()
    if x.cmd == "pull": cmd_pull(x.tab, x.out or f"pull_{x.tab.replace(' ', '_')}.csv")
    elif x.cmd == "sync": cmd_sync(x.file, x.apply)
    elif x.cmd == "discover": cmd_discover("discovery_report.md")
    else: cmd_inspect(x.board)
