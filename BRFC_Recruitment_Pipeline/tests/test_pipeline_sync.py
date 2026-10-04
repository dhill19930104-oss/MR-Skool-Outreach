"""Offline tests for pipeline_sync.py - Monday is replaced by an in-memory fake, no network."""
import hashlib, io, json, os, sys, urllib.error
from datetime import date

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline_sync as ps

TODAY = date(2026, 10, 4)
CB = ps.BOARD_IDS["CB List"]
GROUPS = [{"id": "g_target", "title": "Left Centre Back - Target List"}, {"id": "g_short", "title": "Short List"},
          {"id": "g_long", "title": "Long List"}, {"id": "g_un", "title": "Unattainable"},
          {"id": "g_nfu", "title": "Not For Us Currently"}]
COLUMNS = [{"id": "name", "title": "Name", "type": "name"}, {"id": "current_club", "title": "Current Club", "type": "text"},
           {"id": "parent_club9", "title": "Parent Club", "type": "text"}]


class FakeMonday:
    """Answers the handful of GraphQL operations the script sends, and records every write."""

    def __init__(self, players, profiles=None, fail_on_write=None):
        self.items = []
        for n, (name, club, gid) in enumerate(players):
            self.items.append({"id": str(100 + n), "name": name, "group": self._g(gid),
                               "column_values": [{"id": "current_club", "text": club}]})
        self.profiles = profiles or {}
        self.writes, self.fail_on_write, self.next_id = [], fail_on_write, 900

    def _g(self, gid):
        return dict(next(g for g in GROUPS if g["id"] == gid))

    def __call__(self, query, variables=None):
        v = variables or {}
        if query.lstrip().startswith("mutation"):
            if self.fail_on_write is not None and len(self.writes) == self.fail_on_write:
                raise RuntimeError("killed")
            self.writes.append((query.split("(")[1].split("{")[1] if "{" in query else query, v))
            if "move_item_to_group" in query:
                next(i for i in self.items if i["id"] == v["i"])["group"] = self._g(v["g"])
                return {"move_item_to_group": {"id": v["i"]}}
            if "create_item" in query:
                self.next_id += 1
                self.items.append({"id": str(self.next_id), "name": v["n"], "group": self._g(v["g"]), "column_values": []})
                return {"create_item": {"id": str(self.next_id)}}
            if "change_simple_column_value" in query:
                it = next(i for i in self.items if i["id"] == v["i"])
                it["column_values"] = [c for c in it["column_values"] if c["id"] != v["c"]] + [{"id": v["c"], "text": v["v"]}]
                return {"change_simple_column_value": {"id": v["i"]}}
        if "items_page" in query:
            return {"boards": [{"items_page": {"cursor": None, "items": json.loads(json.dumps(self.items))}}]}
        if "groups{id title}" in query:
            return {"boards": [{"id": CB, "name": "CB List", "groups": GROUPS, "columns": COLUMNS}]}
        if "items(ids" in query:
            return {"items": [self.profiles.get(v["i"][0], {"updates": [], "subitems": []})]}
        raise AssertionError(f"unexpected query: {query[:80]}")


def fresh(fake, monkeypatch):
    ps._struct.clear(); ps._items.clear()
    monkeypatch.setattr(ps, "monday", fake)
    return fake


def workbook(tmp_path, tabs):
    """tabs: {tab: (trait_lines, rows)} - rows are (name, club, mins, notes, progress)."""
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    for tab, (traits, rows) in tabs.items():
        ws = wb.create_sheet(tab)
        ws.append([f"{tab} - WHAT WE NEED"])
        for t in range(traits): ws.append([f"•  trait {t}"])
        ws.append(["Players are added only after Dhillon agrees."]); ws.append([])
        ws.append(["Name", "Club", "Mins 26/27", "Notes", "Progress (Y/N)"])
        for r in rows: ws.append(list(r))
    p = tmp_path / "BRFC_Recruitment_Pipeline.xlsx"; wb.save(p)
    return str(p)


def sync(path, apply=True):
    ps._struct.clear(); ps._items.clear()
    return ps.cmd_sync(path, apply, today=TODAY)


# ---------------------------------------------------------------- workbook
def test_header_row_found_by_name_text_with_different_trait_lengths(tmp_path):
    path = workbook(tmp_path, {"CB": (6, [("A One", "X", 1, "", "Y")]), "GK": (2, [("B Two", "Y", 1, "", "Y")]),
                               "RB": (11, [("C Three", "Z", 1, "", "Y")])})
    assert [(t, n) for t, _, n, _ in ps.read_rows(path)] == [("CB", "A One"), ("GK", "B Two"), ("RB", "C Three")]


def test_only_progress_y_rows_sync(tmp_path):
    path = workbook(tmp_path, {"CB": (3, [("Yes Man", "A", 1, "", "Y"), ("Lower Case", "A", 1, "", "y"),
                                         ("No Man", "A", 1, "", "N"), ("Blank Man", "A", 1, "", None)])})
    assert [n for _, _, n, _ in ps.read_rows(path)] == ["Yes Man", "Lower Case"]


def test_refuses_when_excel_has_workbook_open(tmp_path):
    path = workbook(tmp_path, {"CB": (3, [("A One", "X", 1, "", "Y")])})
    (tmp_path / "~$BRFC_Recruitment_Pipeline.xlsx").write_text("lock")
    with pytest.raises(SystemExit, match="open in Excel"):
        ps.read_rows(path)


# ---------------------------------------------------------------- matcher
@pytest.mark.parametrize("players,name,club,status,detail", [
    ([("Jack Tucker", "Burton Albion", "g_long")], "Jack Tucker", "Burton", "found", "exact"),
    ([("Ryan Johnson", "Oxford United", "g_long")], "Ryan Anthony Johnson", "Oxford Utd", "found", "loose"),
    ([("Will Smith", "Morecombe", "g_long"), ("Will Smith", "Barnet", "g_long")], "Will Smith", "Morecambe", "found", "exact+club"),
    ([("Will Smith", "Morecombe", "g_long"), ("Will Smith", "Morecombe", "g_nfu")], "Will Smith", "Morecambe", "ambiguous", "2 rows"),
    ([("Ryan Johnson", "Barnet", "g_long")], "Ryan Anthony Johnson", "Oxford Utd", "ambiguous", "loose"),
    ([("Eoin Toal", "Bolton", "g_un")], "Eoin Toal", "Bolton", "unattainable", "Unattainable"),
    ([("Someone Else", "Bolton", "g_long")], "New Player", "Bolton", "missing", "not on board"),
])
def test_matcher(monkeypatch, players, name, club, status, detail):
    fresh(FakeMonday(players), monkeypatch)
    got, _, why = ps.match_player("CB List", name, club)
    assert got == status and detail in why


def test_club_aliases():
    assert ps.same_club("MK Dons", "Milton Keynes Dons")
    assert ps.same_club("Sheff Wed", "Sheffield Wednesday FC")
    assert ps.same_club("Cambridge Utd", "Cambridge United")
    assert ps.same_club("Dag & Red", "Dagenham & Redbridge")
    assert not ps.same_club("Bristol City", "Bristol Rovers")


# ---------------------------------------------------------------- sync behaviour
PLAYERS = [("Jack Tucker", "Burton Albion", "g_short"), ("Shane Blaney", "Livingston FC", "g_long"),
           ("Eoin Toal", "Bolton Wanderers", "g_un"), ("Will Smith", "Barnet", "g_long"), ("Will Smith", "Barnet", "g_nfu")]
ROWS = [("Jack Tucker", "Burton", 900, "", "Y"), ("Shane Blaney", "Livingston", 800, "", "Y"),
        ("Eoin Toal", "Bolton", 0, "", "Y"), ("Brand New", "Nowhere FC", 10, "", "Y"),
        ("Will Smith", "Barnet", 50, "", "Y"), ("Not Ready", "Somewhere", 10, "", "N")]


def test_actions_and_dry_run_makes_no_writes(tmp_path, monkeypatch):
    fake = fresh(FakeMonday(PLAYERS), monkeypatch)
    res = sync(workbook(tmp_path, {"CB": (4, ROWS)}), apply=False)
    assert {r["name"]: r["action"] for r in res} == {"Jack Tucker": "none", "Shane Blaney": "move", "Eoin Toal": "skip",
                                                    "Brand New": "create", "Will Smith": "skip"}
    assert fake.writes == []


def test_apply_twice_second_run_makes_no_writes(tmp_path, monkeypatch):
    fake = fresh(FakeMonday(PLAYERS), monkeypatch)
    path = workbook(tmp_path, {"CB": (4, ROWS)})
    sync(path)
    assert len(fake.writes) == 3  # move Blaney, create Brand New, set his club
    new = next(i for i in fake.items if i["name"] == "Brand New")
    assert new["group"]["id"] == "g_short" and new["column_values"] == [{"id": "current_club", "text": "Nowhere FC"}]
    assert next(i for i in fake.items if i["name"] == "Shane Blaney")["group"]["id"] == "g_short"
    assert next(i for i in fake.items if i["name"] == "Eoin Toal")["group"]["id"] == "g_un"
    before = len(fake.writes)
    res = sync(path)
    assert len(fake.writes) == before
    assert {r["name"]: r["action"] for r in res}["Brand New"] == "none"


def test_run_killed_halfway_resumes_from_monday_state(tmp_path, monkeypatch):
    fake = fresh(FakeMonday(PLAYERS, fail_on_write=1), monkeypatch)
    path = workbook(tmp_path, {"CB": (4, ROWS)})
    sync(path)  # move succeeds, create is killed
    assert len(fake.writes) == 1
    fake.fail_on_write = None
    sync(path)
    assert [i["name"] for i in fake.items].count("Brand New") == 1
    assert next(i for i in fake.items if i["name"] == "Brand New")["group"]["id"] == "g_short"
    before = len(fake.writes)
    sync(path)
    assert len(fake.writes) == before


def test_workbook_unchanged_after_run(tmp_path, monkeypatch):
    fresh(FakeMonday(PLAYERS), monkeypatch)
    path = workbook(tmp_path, {"CB": (4, ROWS)})
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    sync(path)
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest


def test_no_shortlist_group_stops_that_board(tmp_path, monkeypatch):
    fake = fresh(FakeMonday(PLAYERS), monkeypatch)
    monkeypatch.setattr(ps, "SHORTLIST_WORD", "nonexistent")
    res = sync(workbook(tmp_path, {"CB": (4, ROWS)}))
    assert {r["action"] for r in res} == {"error"} and fake.writes == []


# ---------------------------------------------------------------- profile check
def sub(name, when, kind="Video", has_file=True):
    return {"name": name, "created_at": f"{when}T10:00:00Z", "assets": [{"id": "1"}] if has_file else [],
            "column_values": [{"id": "status", "type": "status", "text": kind}, {"id": "date0", "type": "date", "text": when},
                              {"id": "files_x", "type": "file", "text": "https://x/f.pdf" if has_file else ""}]}


def test_profile_check_bullets_and_report_age(monkeypatch):
    profiles = {
        "1": {"updates": [{"created_at": "2026-02-01T00:00:00Z", "body": '<ul><li>Strong in the air</li><li>Left footed</li></ul>'},
                          {"created_at": "2026-01-01T00:00:00Z", "body": "<p>Moved on loan</p>"}],
              "subitems": [sub("Wyscout Clips Report", "2025-11-01"), sub("Old Report", "2024-01-01")]},
        "2": {"updates": [{"created_at": "2025-09-01T00:00:00Z", "body": "<p>﻿Watched live</p><p>* Tall</p><p>- Quick</p>"}],
              "subitems": [sub("Wyscout Report", "2025-10-03"), sub("No file", "2026-09-01", has_file=False)]},
        "3": {"updates": [{"created_at": "2025-09-01T00:00:00Z", "body": "<p>Spoke to agent - wants to move</p>"}], "subitems": []},
    }
    fresh(FakeMonday([], profiles), monkeypatch)
    p1, p2, p3 = (ps.profile_check(i, TODAY) for i in "123")
    assert p1["bullets"] == ["2026-02-01"] and [r[1] for r in p1["recent_reports"]] == ["Wyscout Clips Report"]
    assert p2["bullets"] == ["2025-09-01"] and p2["recent_reports"] == [] and p2["reports"][0][1] == "Wyscout Report"
    assert p3["bullets"] == [] and p3["reports"] == []  # a dash inside a sentence is not a bullet
    assert "NONE (last was Wyscout Report 2025-10-03)" in ps.describe_profile(p2)


# ---------------------------------------------------------------- rate limit
def test_429_html_page_triggers_backoff(monkeypatch):
    calls, sleeps = [], []
    ok = io.BytesIO(json.dumps({"data": {"me": {"id": "1"}}}).encode())

    class Resp:
        def __enter__(self): return ok
        def __exit__(self, *a): return False

    def urlopen(req, timeout=None, context=None):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"<html>blocked</html>"))
        return Resp()

    monkeypatch.setenv("MONDAY_API_KEY", "test")
    monkeypatch.setattr(ps.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ps.time, "sleep", sleeps.append)
    assert ps.monday("{me{id}}") == {"me": {"id": "1"}}
    assert 15 in sleeps and len(calls) == 2
