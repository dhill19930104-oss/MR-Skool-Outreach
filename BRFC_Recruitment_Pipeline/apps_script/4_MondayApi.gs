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
