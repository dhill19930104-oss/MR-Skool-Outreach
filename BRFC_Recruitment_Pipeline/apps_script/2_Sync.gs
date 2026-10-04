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

