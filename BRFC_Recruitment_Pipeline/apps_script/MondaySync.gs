/**
 * BRFC Recruitment Pipeline -> Monday.com
 *
 * Put "Y" in Progress (column E) on any position tab and the player is moved into the
 * Short List group on that tab's Monday board (created there if he isn't on the board).
 * The result is written as a note on the Progress cell.
 *
 * Setup (once): see README.md in this folder.
 */

var TAB_BOARDS = {
  'CB': '1405453688', 'GK': '1405448899', 'CM 6': '1630835327', 'LB': '1405455920',
  'Winger': '1405463991', 'CM 8': '1630854223', 'CM 10': '1630854673', 'RB': '1405459501',
  'CF Target': '1630857074', 'CF Runner': '1630857775'
};
var PROGRESS_COL = 5;            // E
var SHORTLIST_WORD = 'short';    // group whose title contains this = shortlist group
var EXCLUDE_PREFIX = 'unattainable';
var WRITE_GAP_MS = 350;
var BACKOFF_S = [15, 30, 45, 60];

// ------------------------------------------------------------------ triggers

/** Run once from the Apps Script editor: installs the edit trigger and a 15-minute safety sweep. */
function setup() {
  var ss = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('onProgressEdit').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('syncAll').timeBased().everyMinutes(15).create();
  apiKey_();  // fails loudly now if the token is missing
  SpreadsheetApp.getUi().alert('Monday sync is on. Put Y in Progress to move a player to Short List.');
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Monday')
    .addItem('Sync all Y rows now', 'syncAll')
    .addItem('Dry run (no changes)', 'dryRunAll')
    .addToUi();
}

/** Installable onEdit: reacts to Y typed or pasted into Progress on a position tab. */
function onProgressEdit(e) {
  var sh = e.range.getSheet(), tab = sh.getName();
  if (!TAB_BOARDS[tab]) return;
  if (e.range.getColumn() > PROGRESS_COL || e.range.getLastColumn() < PROGRESS_COL) return;
  var header = headerRow_(sh);
  if (!header) return;
  var rows = [];
  for (var r = Math.max(e.range.getRow(), header + 1); r <= e.range.getLastRow(); r++) rows.push(r);
  withLock_(function () { syncRows_(sh, rows, true); });
}

function syncAll() { withLock_(function () { eachTab_(true); }); }
function dryRunAll() { withLock_(function () { eachTab_(false); }); }

function eachTab_(apply) {
  var ss = SpreadsheetApp.getActive();
  Object.keys(TAB_BOARDS).forEach(function (tab) {
    var sh = ss.getSheetByName(tab);
    if (!sh) return;
    var header = headerRow_(sh);
    if (!header || sh.getLastRow() <= header) return;
    var rows = [];
    for (var r = header + 1; r <= sh.getLastRow(); r++) rows.push(r);
    syncRows_(sh, rows, apply);
  });
}

// ------------------------------------------------------------------ sync

function syncRows_(sh, rows, apply) {
  var tab = sh.getName(), boardId = TAB_BOARDS[tab], board = null;
  rows.forEach(function (r) {
    var vals = sh.getRange(r, 1, 1, PROGRESS_COL).getValues()[0];
    var name = String(vals[0] || '').trim(), club = String(vals[1] || '').trim();
    var progress = String(vals[PROGRESS_COL - 1] || '').trim().toUpperCase();
    if (!name || progress !== 'Y') return;
    var cell = sh.getRange(r, PROGRESS_COL), msg;
    try {
      board = board || loadBoard_(boardId);
      msg = syncPlayer_(board, name, club, apply);
    } catch (err) {
      msg = 'ERROR - ' + err.message;
    }
    var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd MMM HH:mm');
    var line = 'Monday ' + (apply ? '' : '(dry run) ') + stamp + ': ' + msg;
    // the 15-minute sweep re-checks every Y row; only touch the note when the outcome changes
    var note = cell.getNote();
    var keep = note.slice(-msg.length) === msg || (/^already in/.test(msg) && /: (moved|created|already in)/.test(note));
    if (apply && !keep) cell.setNote(line);
    if (!apply) SpreadsheetApp.getActive().toast(name + ': ' + msg, 'Dry run', 8);
    console.log(tab + ' | ' + line);
  });
}

/** Decides from live Monday state, so re-running never repeats a change. */
function syncPlayer_(board, name, club, apply) {
  var shortlist = board.groups.filter(function (g) { return g.title.toLowerCase().indexOf(SHORTLIST_WORD) >= 0; })[0];
  if (!shortlist) throw new Error('no Short List group on ' + board.name + ' - not creating one');
  var m = matchPlayer_(board, name, club);
  if (m.status === 'found' && m.item.group.id === shortlist.id) return 'already in ' + shortlist.title;
  if (m.status === 'found') {
    if (apply) {
      monday_('mutation($i:ID!,$g:String!){move_item_to_group(item_id:$i,group_id:$g){id}}', { i: m.item.id, g: shortlist.id });
      var from = m.item.group.title;
      m.item.group = { id: shortlist.id, title: shortlist.title };
      return 'moved ' + from + ' -> ' + shortlist.title + ' (' + m.detail + ')';
    }
    return 'would move ' + m.item.group.title + ' -> ' + shortlist.title + ' (' + m.detail + ')';
  }
  if (m.status === 'missing') {
    if (!apply) return 'would create in ' + shortlist.title + ' (not on board)';
    var id = monday_('mutation($b:ID!,$g:String!,$n:String!){create_item(board_id:$b,group_id:$g,item_name:$n){id}}',
                     { b: board.id, g: shortlist.id, n: name }).create_item.id;
    var item = { id: id, name: name, group: { id: shortlist.id, title: shortlist.title }, club: club };
    if (board.clubCol && club) {
      monday_('mutation($b:ID!,$i:ID!,$c:String!,$v:String!){change_simple_column_value(board_id:$b,item_id:$i,column_id:$c,value:$v){id}}',
              { b: board.id, i: id, c: board.clubCol, v: club });
    }
    board.items.push(item);
    return 'created in ' + shortlist.title + ' (was not on board - check for duplicates)';
  }
  if (m.status === 'unattainable') return 'SKIPPED - only in Unattainable, move by hand if that has changed';
  return 'SKIPPED - ' + m.detail;
}

// ------------------------------------------------------------------ matching

function norm_(s) {
  return String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/-/g, ' ').replace(/[^a-z ]/g, '').split(/\s+/).filter(String);
}

var CLUB_ALIASES = {
  'mk dons': 'milton keynes dons', 'sheff wed': 'sheffield wednesday', 'sheff utd': 'sheffield united',
  'fgr': 'forest green rovers', 'forest green': 'forest green rovers', 'dag red': 'dagenham redbridge',
  'dag and red': 'dagenham redbridge', 'dagenham and redbridge': 'dagenham redbridge',
  'gatestead': 'gateshead', 'morecombe': 'morecambe', 'carisle': 'carlisle', 'carisle united': 'carlisle united',
  'shewsbury': 'shrewsbury', 'shewsbury town': 'shrewsbury town', 'barsnley': 'barnsley',
  'qrp': 'queens park rangers', 'qpr': 'queens park rangers', 'wolves': 'wolverhampton wanderers',
  'brighton': 'brighton and hove albion', 'west brom': 'west bromwich albion', 'wba': 'west bromwich albion',
  'spurs': 'tottenham hotspur', 'man city': 'manchester city', 'man utd': 'manchester united',
  'notts forest': 'nottingham forest', 'nottm forest': 'nottingham forest'
};

function clubKey_(s) {
  var t = norm_(String(s || '').replace(/&/g, ' and ')).join(' ');
  t = CLUB_ALIASES[t] || t;
  t = t.replace(/utd/g, 'united');
  t = CLUB_ALIASES[t] || t;
  return t.split(' ').filter(function (w) { return w && ['fc', 'afc', 'the', 'and'].indexOf(w) < 0; });
}

function sameClub_(a, b) {
  var ka = clubKey_(a), kb = clubKey_(b);
  if (!ka.length || !kb.length) return false;
  if (ka.join(' ') === kb.join(' ')) return true;
  var s = ka.length < kb.length ? ka : kb, l = ka.length < kb.length ? kb : ka;
  return s[0] === l[0] && s.every(function (w) { return l.indexOf(w) >= 0; });
}

function nameHits_(pool, player) {
  var t = norm_(player);
  var exact = pool.filter(function (i) { return norm_(i.name).join(' ') === t.join(' '); });
  if (exact.length) return { hits: exact, how: 'exact' };
  var loose = pool.filter(function (i) {
    var n = norm_(i.name);
    return n.length && n[n.length - 1] === t[t.length - 1] && n[0][0] === t[0][0];
  });
  return { hits: loose, how: 'loose' };
}

/** found | ambiguous | unattainable | missing - never guesses between several candidates. */
function matchPlayer_(board, player, club) {
  if (!norm_(player).length) return { status: 'ambiguous', detail: 'no name' };
  var excluded = function (i) { return i.group.title.toLowerCase().indexOf(EXCLUDE_PREFIX) === 0; };
  var live = board.items.filter(function (i) { return !excluded(i); });
  var h = nameHits_(live, player);
  if (h.hits.length) {
    if (h.hits.length > 1 && club) {
      var byClub = h.hits.filter(function (i) { return sameClub_(club, i.club); });
      if (byClub.length === 1) return { status: 'found', item: byClub[0], detail: h.how + ' name + club' };
    }
    if (h.hits.length > 1) {
      var short = h.hits.filter(function (i) { return i.group.title.toLowerCase().indexOf(SHORTLIST_WORD) >= 0; });
      if (short.length === 1 && h.how === 'exact') return { status: 'found', item: short[0], detail: 'exact name' };
      return { status: 'ambiguous', detail: h.hits.length + ' rows match (' + h.hits.map(function (i) {
        return i.name + ', ' + (i.club || '?') + ', ' + i.group.title; }).join('; ') + ') - check by hand' };
    }
    var it = h.hits[0];
    if (h.how === 'loose' && !(club && it.club && sameClub_(club, it.club))) {
      return { status: 'ambiguous', detail: "only a loose name match: '" + it.name + "' (" + (it.club || 'no club') + ') - check by hand' };
    }
    return { status: 'found', item: it, detail: h.how === 'exact' ? 'exact name' : 'loose name + same club' };
  }
  if (nameHits_(board.items.filter(excluded), player).hits.length) return { status: 'unattainable' };
  return { status: 'missing' };
}

// ------------------------------------------------------------------ Monday API

function loadBoard_(boardId) {
  var b = monday_('query($id:[ID!]){boards(ids:$id){id name groups{id title} columns{id title type}}}', { id: [boardId] }).boards[0];
  var clubCol = (b.columns.filter(function (c) { return c.title.toLowerCase().indexOf('current club') >= 0; })[0] || {}).id || null;
  var items = [], cursor = null;
  do {
    var page = monday_('query($id:[ID!],$c:String,$cols:[String!]){boards(ids:$id){items_page(limit:200,cursor:$c){cursor items{id name group{id title} column_values(ids:$cols){id text}}}}}',
                       { id: [boardId], c: cursor, cols: clubCol ? [clubCol] : [] }).boards[0].items_page;
    page.items.forEach(function (i) {
      items.push({ id: i.id, name: i.name, group: i.group, club: (i.column_values[0] || {}).text || '' });
    });
    cursor = page.cursor;
  } while (cursor);
  return { id: b.id, name: b.name, groups: b.groups, clubCol: clubCol, items: items };
}

var lastCall_ = 0;
function monday_(query, variables) {
  for (var attempt = 0; attempt <= BACKOFF_S.length; attempt++) {
    if (attempt) Utilities.sleep(BACKOFF_S[attempt - 1] * 1000);
    var gap = Date.now() - lastCall_;
    if (gap < WRITE_GAP_MS) Utilities.sleep(WRITE_GAP_MS - gap);
    var res = UrlFetchApp.fetch('https://api.monday.com/v2', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: { Authorization: apiKey_(), 'API-Version': '2024-10' },
      payload: JSON.stringify({ query: query, variables: variables || {} })
    });
    lastCall_ = Date.now();
    var code = res.getResponseCode();
    if (code === 429) continue;  // may be an HTML block page - go by status, not body
    if (code !== 200) throw new Error('Monday HTTP ' + code);
    var body = JSON.parse(res.getContentText());
    if (body.errors) {
      if (/complexity|rate/i.test(JSON.stringify(body.errors))) continue;
      throw new Error(JSON.stringify(body.errors).slice(0, 200));
    }
    return body.data;
  }
  throw new Error('Monday still rate limited - put Y again in a few minutes (it resumes safely)');
}

function apiKey_() {
  var k = PropertiesService.getScriptProperties().getProperty('MONDAY_API_KEY');
  if (!k) throw new Error('Set MONDAY_API_KEY in Project Settings > Script properties');
  return k;
}

// ------------------------------------------------------------------ helpers

function headerRow_(sh) {
  var a = sh.getRange(1, 1, Math.min(sh.getLastRow(), 40) || 1, 1).getValues();
  for (var i = 0; i < a.length; i++) if (String(a[i][0]).trim().toLowerCase() === 'name') return i + 1;
  return null;
}

function withLock_(fn) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try { fn(); } finally { lock.releaseLock(); }
}
