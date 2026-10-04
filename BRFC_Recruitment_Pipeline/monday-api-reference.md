# Bristol Rovers Monday.com — API reference

Everything needed to read and write the recruitment boards from code.
Verified live on 4 October 2026.

Account: **Bristolrovers** (id `20690230`, region `euc1`) · workspace **Recruitment** · 50 active boards.

---

## 1. Connecting

| | |
|---|---|
| Endpoint | `https://api.monday.com/v2` (POST, GraphQL) |
| Auth | `Authorization: <token>` header — **no** `Bearer` prefix |
| Version | `API-Version: 2024-10` |
| Token | A personal API token from Monday → avatar → Developers → My access tokens |

**Never commit the token.** Keep it in `.env` / an environment variable and read it at
runtime. The token grants full read/write to every board in the account.

```python
import json, os, ssl, urllib.request

def monday(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        "https://api.monday.com/v2",
        data=body,
        headers={
            "Authorization": os.environ["MONDAY_API_KEY"],
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]
```

**macOS / python.org builds**: `urlopen` fails with `CERTIFICATE_VERIFY_FAILED` because
those builds ship no CA bundle. Pass a context built from `certifi`:

```python
ctx = ssl.create_default_context()
ctx.load_verify_locations(__import__("certifi").where())
# ... urlopen(req, context=ctx)
```

### Rate limits — the part that bites

- Pace writes at **~0.35 s between calls**. Several hundred back-to-back writes will trip
  the limit even so.
- A 429 may come back as an **HTML block page, not JSON** — an edge throttle rather than
  the documented per-minute complexity limit. Detect on HTTP status, not response body.
- Back off **15 s, 30 s, 45 s, 60 s**. Two-second retries do not clear it. A tripped limit
  can take several minutes.
- Design writes to be **idempotent and resumable**: write one cell per call, and make a
  re-run skip cells that already hold the right value. A run killed halfway can then just
  be run again. (This exact situation has happened — 179 writes died partway, and the
  re-run picked up only the 52 that were missing.)

---

## 2. Core queries

### Board structure (columns are the thing you need)

```graphql
query($id: [ID!]) {
  boards(ids: $id) {
    id name items_count
    groups { id title }
    columns { id title type }
  }
}
```

### Items, paginated

`items_page` caps at 500; loop on the cursor until it comes back null.

```graphql
query($id: [ID!], $ids: [String!], $c: String) {
  boards(ids: $id) {
    items_page(limit: 200, cursor: $c) {
      cursor
      items {
        id name
        group { title }
        column_values(ids: $ids) { id text }
      }
    }
  }
}
```

### Writing one cell

`change_simple_column_value` takes a bare string for both `numbers` and `text` columns,
which avoids the JSON-in-JSON escaping that `change_column_value` needs.

```graphql
mutation($b: ID!, $i: ID!, $c: String!, $v: String!) {
  change_simple_column_value(board_id: $b, item_id: $i, column_id: $c, value: $v) { id }
}
```

---

## 3. Gotchas that cost real time

1. **Column ids are not stable across boards.** "26/27 Minutes" is `minutes__1` on CB List,
   `numeric_mkvapjx8` on LB List, `data_score_mkn2ebe1` on RB List. **Always resolve
   columns by title at runtime**, never hardcode an id.
2. **The same column title can be a different type.** "26/27 Minutes" is `numbers` on most
   boards but `text` on RB List and the Data-Driven Watchlist. Carry the type through.
3. **`items_count` includes subitems.** ECH - Out of Contract reports 107 but has 92
   top-level items. Count what `items_page` returns, not `items_count`.
4. **Subitem boards appear in `boards(...)`** as "Subitems of X" with their own ids. Filter
   them out unless you want them.
5. **Group titles differ per board for the same concept.** The excluded group is
   `Unattainable` on the position lists but `Unattainable List` on the Data-Driven
   Watchlist. Match on prefix, not equality — an exact match silently includes 273 players
   that should have been left alone.
6. **A player can legitimately appear on several rows** of one board (the Data-Driven
   Watchlist lists people under each position group they fit), and boards also contain
   genuine duplicate rows. Decide deliberately whether to write all matches or stop.
7. Board data is **user-entered and inconsistent**: club names are abbreviated (`MK Dons`,
   `Sheff Wed`, `FGR`, `Dag & Red`, `Cambridge Utd`) and frequently misspelled
   (`Gatestead`, `Morecombe`, `Carisle`, `Shewsbury`, `Barsnley`, `QRP`). Anything matching
   on club needs normalisation and an alias table.

---

## 4. Board inventory

### Watchlists — position lists
Column titled **`26/27 Minutes`**. Groups are target/short/long lists plus `Unattainable`.
`Current Club` + `Parent Club` both present.

| Board | id | Items | Minutes column | type |
|---|---|---|---|---|
| CB List | `1405453688` | 217 | `minutes__1` | numbers |
| LB List | `1405455920` | 101 | `numeric_mkvapjx8` | numbers |
| RB List | `1405459501` | 119 | `data_score_mkn2ebe1` | **text** |
| CM - 6 | `1630835327` | 135 | `numeric_mkvbhs33` | numbers |
| CM - 8 | `1630854223` | 155 | `numeric_mkvbsz2y` | numbers |
| CM - 10 | `1630854673` | 87 | `numeric_mkvb1ywz` | numbers |
| Winger List | `1405463991` | 202 | `numeric_mkvbmk46` | numbers |
| CF - Type A (Target) | `1630857074` | 69 | `numeric_mkvbmx3` | numbers |
| CF - Type B (Runner) | `1630857775` | 126 | `numeric_mkvbajjq` | numbers |
| Data-Driven Watchlist | `1661120502` | 665 | `text6__1` | **text** |

Current Club column id varies: `current_club` (CB, LB, Winger), `current_club9` (RB),
`text_2__1` (CM boards, CF boards, Data-Driven).

### Out-of-contract boards
Column titled **`Minutes`**. Groups are positions (GK, Centre Half, Full-Back / Wing-Back,
CM (6 / 8), Winger / 10, CF) — **no Unattainable group**, every row is in scope.
`Current Club` only, no Parent Club. Each board covers a single division.

| Board | id | Items | Minutes column | Current Club |
|---|---|---|---|---|
| ECH - Out of Contract 2027 | `2135192629` | 92 | `minutes3__1` | `club__1` |
| L1 - Out Of Contract 2027 | `2135167421` | 182 | `minutes__1` | `club__1` |
| L2 - Out Of Contract 2027 | `2135161181` | 243 | `minutes__1` | `team__1` |
| SPL - Out Of Contract 2027 | `2135154604` | 88 | `minutes__1` | `team__1` |

### Loan boards
Column titled **`Minutes`** (`minutes__1` on all four). Position groups, no Unattainable.
Both `Current Club` (the loan club) and `Parent Club` are populated — **Current Club is
where the minutes come from**; Parent Club only helps confirm identity.

| Board | id | Items | Current Club | Parent Club |
|---|---|---|---|---|
| ECH - Loans 2026/27 | `2132745869` | 60 | `current_club__1` | `parent_club__1` |
| L1 - Loans 2026/27 | `2133606339` | 86 | `loan_club__1` | `parent_club__1` |
| L2 - Loans 2026/27 | `2133737830` | 101 | `current_club__1` | `parent_club__1` |
| SPL - Loans 2026/27 | `2134661464` | 34 | `current_club__1` | `parent_club__1` |
| VNL - Loans 2026/27 | `2134439757` | 64 | `current_club__1` | `parent_club__1` |

### Boards with no minutes column
`GK Lists` `1405448899` (94) · `U21 List` `1600769912` (72) ·
`Department Watchlist` `1829760419` (610) · `International Watchlist` `1426508977` ·
`BRFC Signed` `1627473501` (54) · `Live Watchlist` `5092355536` (10) ·
`League Rankings / Data Score` `1734369298` (69).
A numbers column would have to be created before any minutes sync could touch them.

Other boards: `Domestic U19 Most Mins Played` `2135144844` (80) has a `Minutes` column
(`numeric_mkvhrc00`, numbers) but no club column.

---

## 5. The weekly minutes export (context)

A zip of seven `.xlsx` files, one per league, one **sheet per club** inside each plus an
`_Overview` sheet to skip. Sheet columns:

```
player_name | team_name | player_season_minutes | country_id | primary_position
```

- Minutes are **floats** (`119.7797833`) — round to whole minutes.
- Player names are **full legal names** (`Ryan Anthony Johnson`, `Isaac Tanitoluwaloba
  Aduraoluwatimileyin Olaofe`) while boards use known names (`Ryan Johnson`, `Tanto
  Olaofe`).
- Only players who have **actually played** appear — there are no zero-minute rows. An
  absence therefore means no minutes, *provided* the board and the file cover the same
  ground.
- Leagues covered: Championship, League One, League Two, National League, National League
  N/S, Scottish Premiership, Scottish Championship. Anything else (Premier League, U21/PL2,
  Ireland, Scotland L1, abroad) is simply absent.
- **Check the file actually refreshed before trusting it.** One delivery had only Celtic
  and Rangers updated in the Scottish Premiership file and four clubs in the Championship,
  everything else frozen. Compare row counts and max minutes against the previous export,
  per league.

---

## 6. Existing tooling

A working sync lives at `~/Documents/monday-minutes` (own git repo, 55 tests). It resolves
columns by title, matches players by name with club disambiguation, never writes an
uncertain match, and reports what it skipped. See its `README.md` before rebuilding any of
this from scratch.
