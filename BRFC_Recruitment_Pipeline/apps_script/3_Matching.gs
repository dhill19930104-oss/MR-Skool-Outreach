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

