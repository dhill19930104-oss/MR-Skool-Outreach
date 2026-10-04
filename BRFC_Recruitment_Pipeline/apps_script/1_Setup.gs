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

