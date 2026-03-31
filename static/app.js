/* ═══════════════════════════════════════════════════════════
   MT Tennis Predictor — frontend logic
   ═══════════════════════════════════════════════════════════ */

const API = '';   // same origin

let selectedPlayer1 = null;
let selectedPlayer2 = null;
let selectedSurface = 'Hard';

/* ── Status polling ──────────────────────────────────────── */
async function pollStatus() {
  const badge = document.getElementById('status-badge');
  try {
    const r = await fetch(`${API}/api/status`);
    const data = await r.json();
    if (data.ready) {
      badge.textContent = `Gotowy — ${data.players_loaded.toLocaleString()} zawodników`;
      badge.className = 'badge badge-ready';
      return true;
    } else {
      badge.textContent = 'Ładowanie danych ATP…';
      badge.className = 'badge badge-loading';
      return false;
    }
  } catch {
    badge.textContent = 'Błąd połączenia';
    badge.className = 'badge badge-error';
    return false;
  }
}

async function waitUntilReady() {
  for (let i = 0; i < 120; i++) {
    const ok = await pollStatus();
    if (ok) return;
    await sleep(3000);
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ── Autocomplete ────────────────────────────────────────── */
function setupAutocomplete(inputId, listId, onSelect, getOther) {
  const input = document.getElementById(inputId);
  const list  = document.getElementById(listId);
  let debounce;

  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (q.length < 2) { list.classList.add('hidden'); return; }
    debounce = setTimeout(() => fetchSuggestions(q, list, input, onSelect, getOther), 200);
  });

  input.addEventListener('blur', () => {
    // If user typed exact match, accept it without clicking dropdown
    setTimeout(() => {
      const val = input.value.trim();
      if (val && !list.classList.contains('hidden')) {
        const first = list.querySelector('li');
        if (first) { onSelect(first.textContent); }
      }
      list.classList.add('hidden');
    }, 150);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { list.classList.add('hidden'); return; }
    if (e.key === 'Enter') {
      const first = list.querySelector('li');
      if (first) { onSelect(first.textContent); list.classList.add('hidden'); }
      else {
        // Try exact name match
        const val = input.value.trim();
        if (val) onSelect(val);
      }
    }
  });
}

async function fetchSuggestions(q, list, input, onSelect, getOther) {
  try {
    const r = await fetch(`${API}/api/players/search?q=${encodeURIComponent(q)}`);
    const data = await r.json();
    const players = data.players || [];

    list.innerHTML = '';
    if (players.length === 0) { list.classList.add('hidden'); return; }

    const other = getOther();
    players.filter(p => p !== other).slice(0, 15).forEach(name => {
      const li = document.createElement('li');
      li.textContent = name;
      li.addEventListener('mousedown', () => { onSelect(name); list.classList.add('hidden'); });
      list.appendChild(li);
    });
    list.classList.remove('hidden');
  } catch {}
}

function selectPlayer1(name) {
  selectedPlayer1 = name;
  document.getElementById('p1-input').value = name;
  const tag = document.getElementById('p1-tag');
  tag.textContent = name;
  tag.classList.remove('hidden');
  updatePredictBtn();
}

function selectPlayer2(name) {
  selectedPlayer2 = name;
  document.getElementById('p2-input').value = name;
  const tag = document.getElementById('p2-tag');
  tag.textContent = name;
  tag.classList.remove('hidden');
  updatePredictBtn();
}

function updatePredictBtn() {
  document.getElementById('predict-btn').disabled = !(selectedPlayer1 && selectedPlayer2);
}

/* ── Surface buttons ─────────────────────────────────────── */
document.querySelectorAll('.surface-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.surface-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedSurface = btn.dataset.surface;
  });
});

/* ── Predict ─────────────────────────────────────────────── */
document.getElementById('predict-btn').addEventListener('click', runPredict);

async function runPredict() {
  if (!selectedPlayer1 || !selectedPlayer2) return;

  document.getElementById('results').classList.add('hidden');
  document.getElementById('spinner').classList.remove('hidden');

  try {
    const r = await fetch(`${API}/api/predict`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player1: selectedPlayer1, player2: selectedPlayer2, surface: selectedSurface })
    });

    if (!r.ok) {
      const err = await r.json();
      alert(`Błąd: ${err.detail || r.statusText}`);
      return;
    }

    const data = await r.json();
    renderResults(data);
  } catch (e) {
    alert(`Błąd połączenia: ${e.message}`);
  } finally {
    document.getElementById('spinner').classList.add('hidden');
  }
}

/* ── Render results ──────────────────────────────────────── */
function renderResults(d) {
  const p1 = d.player1;
  const p2 = d.player2;

  /* probability bar */
  setNameWithFlag('prob-name1', p1.name, p1.ioc);
  setNameWithFlag('prob-name2', p2.name, p2.ioc);
  document.getElementById('prob-bar1').style.width = p1.win_pct + '%';
  document.getElementById('prob-bar2').style.width = p2.win_pct + '%';
  setText('prob-pct1', p1.win_pct + '%');
  setText('prob-pct2', p2.win_pct + '%');
  setText('surface-label', `Nawierzchnia: ${d.surface}`);

  /* player cards */
  setNameWithFlag('card-name1', p1.name, p1.ioc);
  setNameWithFlag('card-name2', p2.name, p2.ioc);
  setText('score1', p1.score);
  setText('score2', p2.score);

  fillStatsTable('stats1', p1, d.surface);
  fillStatsTable('stats2', p2, d.surface);

  /* form dots */
  setNameWithFlag('form-label1', p1.name.split(' ').pop(), p1.ioc);
  setNameWithFlag('form-label2', p2.name.split(' ').pop(), p2.ioc);
  renderFormDots('form-dots1', p1.form_last_10);
  renderFormDots('form-dots2', p2.form_last_10);

  /* H2H bar */
  setNameWithFlag('h2h-name1', p1.name.split(' ').pop(), p1.ioc);
  setNameWithFlag('h2h-name2', p2.name.split(' ').pop(), p2.ioc);
  const total = d.h2h_total;
  if (total === 0) {
    document.getElementById('h2h-bar1').style.width = '50%';
    document.getElementById('h2h-bar2').style.width = '50%';
  } else {
    document.getElementById('h2h-bar1').style.width = (p1.h2h_wins / total * 100) + '%';
    document.getElementById('h2h-bar2').style.width = (p2.h2h_wins / total * 100) + '%';
  }
  setText('h2h-count1', p1.h2h_wins);
  setText('h2h-total', `/ ${total} meczów`);
  setText('h2h-count2', p2.h2h_wins);
  const surfH2H = d.h2h_surface_total;
  if (surfH2H > 0) {
    setText('h2h-surface-info',
      `Na ${d.surface}: ${p1.h2h_wins_surface} – ${p2.h2h_wins_surface} (${surfH2H} meczów)`);
  } else {
    setText('h2h-surface-info', `Brak spotkań na ${d.surface}`);
  }

  /* surface win rates */
  renderSurfaceWR(p1, p2);

  /* serve stats */
  renderServe(p1, p2);

  /* radar chart */
  drawRadar(p1, p2, d.surface);

  /* method note */
  setText('method-note', `Metoda: ${d.method}`);

  document.getElementById('results').classList.remove('hidden');
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setNameWithFlag(id, name, ioc) {
  const el = document.getElementById(id);
  if (!el) return;
  const flag = iocToFlag(ioc);
  el.innerHTML = flag ? `${flag} ${name}` : name;
}

function fillStatsTable(tableId, p, surface) {
  const surf = surface.toLowerCase();
  const rows = [
    ['Ranking ATP', p.rank === 500 ? 'Brak' : `#${p.rank}`],
    ['Elo (overall)', p.elo.overall],
    [`Elo (${surface})`, p.elo[surf] || p.elo.hard],
    ['Forma (score)', p.form_score + '%'],
    [`WR ${surface}`, (p.surface_wr[surf] ?? '—') + '%'],
    ['WR Overall', p.surface_wr.overall + '%'],
    ['1st Serve %', pct(p.first_serve_in_pct)],
    ['1st Won %', pct(p.first_serve_won_pct)],
    ['2nd Won %', pct(p.second_serve_won_pct)],
    ['Ace %', pct(p.ace_pct)],
  ];
  const tb = document.getElementById(tableId);
  tb.innerHTML = rows.map(([l,v]) =>
    `<tr><td>${l}</td><td>${v}</td></tr>`
  ).join('');
}

function pct(v) { return v ? (v * 100).toFixed(1) + '%' : '—'; }

function renderFormDots(containerId, results) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = results.map(r =>
    `<span class="dot ${r ? 'dot-win' : 'dot-loss'}">${r ? 'W' : 'L'}</span>`
  ).join('');
}

function renderSurfaceWR(p1, p2) {
  const surfs = [
    { key: 'hard', label: 'Twarda' },
    { key: 'clay', label: 'Ceglasta' },
    { key: 'grass', label: 'Trawa' },
    { key: 'carpet', label: 'Dywan' },
  ];
  const grid = document.getElementById('surface-wr-grid');
  grid.innerHTML = surfs.map(s => {
    const v1 = p1.surface_wr[s.key] ?? 50;
    const v2 = p2.surface_wr[s.key] ?? 50;
    const diff = (v1 - v2).toFixed(1);
    const diffStr = diff > 0 ? `+${diff}` : `${diff}`;
    return `
      <div class="surface-wr-item">
        <div class="surf-name">${s.label}</div>
        <div class="wr-vals">
          <span class="wr-p1">${v1}%</span>
          <span class="wr-p2">${v2}%</span>
        </div>
        <div class="wr-diff">${diffStr}%</div>
      </div>`;
  }).join('');
}

function renderServe(p1, p2) {
  const items = [
    { key: 'first_serve_in_pct', label: '1st Serve In' },
    { key: 'first_serve_won_pct', label: '1st Won' },
    { key: 'second_serve_won_pct', label: '2nd Won' },
    { key: 'ace_pct', label: 'Ace %' },
    { key: 'df_pct', label: 'Double Fault %' },
  ];
  const grid = document.getElementById('serve-grid');
  grid.innerHTML = items.map(it => {
    const v1 = +(p1[it.key] * 100).toFixed(1);
    const v2 = +(p2[it.key] * 100).toFixed(1);
    const barWidth = v1 ? Math.round((v1 / Math.max(v1, v2, 0.1)) * 100) : 0;
    return `
      <div class="serve-item">
        <div class="serve-label">${it.label}</div>
        <div class="serve-vals">
          <span class="wr-p1">${v1 ? v1 + '%' : '—'}</span>
          <span class="wr-p2">${v2 ? v2 + '%' : '—'}</span>
        </div>
        <div class="serve-bar-wrap">
          <div class="serve-bar-p1" style="width:${barWidth}%"></div>
        </div>
      </div>`;
  }).join('');
}

/* ── Radar chart (canvas) ────────────────────────────────── */
function drawRadar(p1, p2, surface) {
  const canvas = document.getElementById('radar-canvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const surf = surface.toLowerCase();
  const labels = ['Elo', 'Forma', 'WR ' + surface, 'Serwis 1', 'Serwis 2'];

  function normalize(val, min, max) { return Math.max(0, Math.min(1, (val - min) / (max - min))); }

  const ELO_MID = 1500, ELO_RANGE = 400;
  const data1 = [
    normalize(p1.elo[surf] ?? p1.elo.overall, ELO_MID - ELO_RANGE, ELO_MID + ELO_RANGE),
    p1.form_score / 100,
    (p1.surface_wr[surf] ?? 50) / 100,
    p1.first_serve_won_pct,
    p1.second_serve_won_pct,
  ];
  const data2 = [
    normalize(p2.elo[surf] ?? p2.elo.overall, ELO_MID - ELO_RANGE, ELO_MID + ELO_RANGE),
    p2.form_score / 100,
    (p2.surface_wr[surf] ?? 50) / 100,
    p2.first_serve_won_pct,
    p2.second_serve_won_pct,
  ];

  const cx = W / 2, cy = H / 2, R = Math.min(cx, cy) - 36;
  const N = labels.length;
  const angleStep = (2 * Math.PI) / N;
  const startAngle = -Math.PI / 2;

  function point(i, r) {
    const a = startAngle + i * angleStep;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }

  // Grid rings
  ctx.strokeStyle = '#2a2d3e';
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1].forEach(scale => {
    ctx.beginPath();
    for (let i = 0; i < N; i++) {
      const [x, y] = point(i, R * scale);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
  });

  // Spokes
  for (let i = 0; i < N; i++) {
    const [x, y] = point(i, R);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  // Labels
  ctx.fillStyle = '#7c85a6';
  ctx.font = '11px Segoe UI,sans-serif';
  ctx.textAlign = 'center';
  for (let i = 0; i < N; i++) {
    const [x, y] = point(i, R + 20);
    ctx.fillText(labels[i], x, y + 4);
  }

  function drawPolygon(data, color) {
    ctx.beginPath();
    for (let i = 0; i < N; i++) {
      const [x, y] = point(i, R * data[i]);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = color + '33';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  drawPolygon(data1, '#4f8ef7');
  drawPolygon(data2, '#f7634f');

  // Legend
  ctx.fillStyle = '#4f8ef7';
  ctx.fillRect(20, H - 28, 12, 12);
  ctx.fillStyle = '#e8eaf6';
  ctx.font = '11px Segoe UI,sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(p1.name.split(' ').pop(), 36, H - 18);

  ctx.fillStyle = '#f7634f';
  ctx.fillRect(W / 2 + 10, H - 28, 12, 12);
  ctx.fillStyle = '#e8eaf6';
  ctx.fillText(p2.name.split(' ').pop(), W / 2 + 26, H - 18);
}

/* ── Sidebar: upcoming matches ───────────────────────────── */
const SURFACE_LABELS_PL = { Hard: 'Twarda', Clay: 'Ceglasta', Grass: 'Trawa', Carpet: 'Dywan' };

// Convert IOC 3-letter code to emoji flag via ISO 3166-1 alpha-2
const IOC_TO_ISO2 = {
  USA:'US', GBR:'GB', FRA:'FR', GER:'DE', ESP:'ES', ITA:'IT', AUS:'AU', AUT:'AT',
  SUI:'CH', SWE:'SE', NOR:'NO', DEN:'DK', FIN:'FI', NED:'NL', BEL:'BE', POR:'PT',
  CZE:'CZ', SVK:'SK', POL:'PL', HUN:'HU', ROU:'RO', BUL:'BG', GRE:'GR', TUR:'TR',
  CRO:'HR', SRB:'RS', SLO:'SI', UKR:'UA', BLR:'BY', RUS:'RU', KAZ:'KZ', UZB:'UZ',
  CAN:'CA', MEX:'MX', BRA:'BR', ARG:'AR', CHI:'CL', COL:'CO', PER:'PE', URU:'UY',
  VEN:'VE', ECU:'EC', PAR:'PY', BOL:'BO', JPN:'JP', CHN:'CN', KOR:'KR', TPE:'TW',
  IND:'IN', THA:'TH', RSA:'ZA', EGY:'EG', MAR:'MA', TUN:'TN', QAT:'QA', UAE:'AE',
  ISR:'IL', MON:'MC', LUX:'LU', GEO:'GE', ARM:'AM', AZE:'AZ', LAT:'LV', LTU:'LT',
  EST:'EE', NZL:'NZ', PHI:'PH', MAS:'MY', BAH:'BS', HAI:'HT', JAM:'JM',
};

function iocToFlag(ioc) {
  if (!ioc) return '';
  const iso2 = IOC_TO_ISO2[ioc.toUpperCase()];
  if (!iso2) return '';
  return `<img class="flag-img" src="https://flagcdn.com/16x12/${iso2.toLowerCase()}.png" alt="${ioc}" title="${ioc}">`;
}

// Tournament name → country flag (keyword matching)
const TOURNEY_FLAGS = [
  [['australian open', 'brisbane', 'sydney', 'adelaide', 'perth', 'melbourne'], 'AU'],
  [['roland garros', 'french open', 'paris', 'lyon', 'marseille', 'montpellier', 'metz', 'nice'], 'FR'],
  [['wimbledon', "queen's", 'queens', 'eastbourne', 'nottingham', 'london'], 'GB'],
  [['us open', 'indian wells', 'miami', 'cincinnati', 'washington', 'delray beach', 'newport', 'atlanta', 'los angeles', 'new york'], 'US'],
  [['madrid', 'barcelona', 'mallorca', 'valencia', 'marbella'], 'ES'],
  [['rome', 'italy', 'palermo', 'umag'], 'IT'],
  [['halle', 'hamburg', 'munich', 'stuttgart', 'cologne', 'metz', 'berlin', 'vienna', 'kitzbuhel', 'kitzbühel'], 'DE'],
  [['monte-carlo', 'monaco'], 'MC'],
  [['basel', 'gstaad', 'geneva'], 'CH'],
  [['toronto', 'montreal', 'canadian'], 'CA'],
  [['tokyo', 'japan'], 'JP'],
  [['shanghai', 'beijing', 'china'], 'CN'],
  [['doha', 'qatar'], 'QA'],
  [['dubai'], 'AE'],
  [['acapulco', 'los cabos', 'mexico'], 'MX'],
  [['buenos aires', 'cordoba', 'argentina'], 'AR'],
  [['rio', 'brazil', 'brasil'], 'BR'],
  [['santiago', 'chile'], 'CL'],
  [['moscow', 'russia', 'st. petersburg'], 'RU'],
  [['vienna', 'austria'], 'AT'],
  [['stockholm', 'bastad', 'sweden'], 'SE'],
  [['bucharest', 'romania', 'cluj'], 'RO'],
  [['sofia', 'bulgaria'], 'BG'],
  [['antwerp', 'belgium'], 'BE'],
  [['rotterdam', 'netherlands'], 'NL'],
  [['estoril', 'lisbon', 'portugal'], 'PT'],
  [['marrakech', 'casablanca', 'morocco'], 'MA'],
  [['zagreb', 'croatia'], 'HR'],
  [['prague', 'czech'], 'CZ'],
  [['auckland', 'new zealand'], 'NZ'],
  [['pune', 'chennai', 'india'], 'IN'],
  [['bogota', 'colombia'], 'CO'],
  [['umag', 'croatia'], 'HR'],
  [['winston-salem', 'memphis'], 'US'],
];

function tournamentFlag(name) {
  if (!name) return '';
  const lower = name.toLowerCase();
  for (const [keywords, iso2] of TOURNEY_FLAGS) {
    if (keywords.some(k => lower.includes(k))) {
      return `<img class="flag-img" src="https://flagcdn.com/16x12/${iso2.toLowerCase()}.png" alt="${iso2}">`;
    }
  }
  return '';
}

async function loadSidebarMatches() {
  const loadingEl = document.getElementById('sidebar-loading');
  const errorEl   = document.getElementById('sidebar-error');
  const listEl    = document.getElementById('match-list');

  loadingEl.classList.remove('hidden');
  errorEl.classList.add('hidden');
  listEl.innerHTML = '';

  try {
    const refresh = loadingEl.dataset.refresh === '1';
    loadingEl.dataset.refresh = '0';
    const r = await fetch(`${API}/api/matches/upcoming?limit=30${refresh ? '&refresh=true' : ''}`);
    if (!r.ok) throw new Error(r.statusText);
    const data = await r.json();
    const matches = data.matches || [];

    loadingEl.classList.add('hidden');

    if (matches.length === 0) {
      errorEl.textContent = 'Brak nadchodzących meczów';
      errorEl.classList.remove('hidden');
      return;
    }

    // Group by tournament
    const groups = {};
    for (const m of matches) {
      const key = m.tournament || 'ATP';
      if (!groups[key]) groups[key] = [];
      groups[key].push(m);
    }

    for (const [tourney, ms] of Object.entries(groups)) {
      // Collapsible group header
      const flag = tournamentFlag(tourney);
      const header = document.createElement('li');
      header.className = 'match-group-header';
      header.innerHTML = `<span class="group-flag">${flag}</span><span class="group-name">${tourney}</span><span class="group-chevron">▾</span>`;
      listEl.appendChild(header);

      // Container for match items
      const groupItems = document.createElement('ul');
      groupItems.className = 'match-group-items';
      for (const m of ms) {
        const li = renderMatchItem(m);
        groupItems.appendChild(li);
      }
      listEl.appendChild(groupItems);

      // Toggle collapse on click
      header.addEventListener('click', () => {
        const collapsed = groupItems.classList.toggle('collapsed');
        header.querySelector('.group-chevron').textContent = collapsed ? '▸' : '▾';
      });
    }
  } catch (e) {
    loadingEl.classList.add('hidden');
    errorEl.textContent = `Błąd: ${e.message}`;
    errorEl.classList.remove('hidden');
  }
}

function renderMatchItem(m) {
  const li = document.createElement('li');
  const hasData = m.both_resolved;
  li.className = 'match-item' + (hasData ? '' : ' no-data');
  li.dataset.match = JSON.stringify(m);

  const p1display = m.player1_resolved || m.player1_raw;
  const p2display = m.player2_resolved || m.player2_raw;
  const p1flag = iocToFlag(m.player1_ioc);
  const p2flag = iocToFlag(m.player2_ioc);
  const surfaceLabel = SURFACE_LABELS_PL[m.surface] || m.surface;

  // Status badge
  let statusBadge = '';
  if (m.live) {
    statusBadge = '<span class="match-live-badge">● LIVE</span>';
  } else if (!m.finished && m.time_display) {
    statusBadge = `<span class="match-time-badge">${m.time_display}</span>`;
  } else if (!m.finished) {
    statusBadge = `<span class="match-time-badge">${m.date_display || ''}</span>`;
  }

  // Score for finished/live
  const scoreStr = m.score ? `<span class="match-score">${m.score}</span>` : '';

  li.innerHTML = `
    <div class="match-tourney-row">
      ${statusBadge}
      <span class="match-date-small">${m.finished ? m.date_display : ''}</span>
    </div>
    <div class="match-players">
      <span class="p1">${p1flag ? `<span class="player-flag">${p1flag}</span>` : ''}${p1display}</span>
      ${scoreStr}
      <br>
      <span class="p2">${p2flag ? `<span class="player-flag">${p2flag}</span>` : ''}${p2display}</span>
    </div>
    <div class="match-meta">
      <span class="match-surface-pill pill-${m.surface}">${m.surface_icon} ${surfaceLabel}</span>
      ${!hasData ? '<span class="match-no-data-badge">brak w bazie</span>' : ''}
    </div>`;

  if (hasData) {
    li.addEventListener('click', () => applyMatchFromSidebar(m, li));
  }
  return li;
}

function applyMatchFromSidebar(m, liEl) {
  // Highlight active
  document.querySelectorAll('.match-item').forEach(el => el.classList.remove('active'));
  liEl.classList.add('active');

  // Set players
  selectPlayer1(m.player1_resolved);
  selectPlayer2(m.player2_resolved);

  // Set surface
  setSurface(m.surface);

  // Show tournament badge
  const badge = document.getElementById('tourney-badge');
  badge.textContent = `🏆 ${m.tournament}  ·  ${m.surface_icon} ${SURFACE_LABELS_PL[m.surface]}  ·  ${m.date_display || ''}`;
  badge.classList.remove('hidden');

  // Scroll main content to top
  document.querySelector('main').scrollTo({ top: 0, behavior: 'smooth' });
}

function setSurface(surface) {
  selectedSurface = surface;
  document.querySelectorAll('.surface-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.surface === surface);
  });
}

document.getElementById('sidebar-refresh').addEventListener('click', () => {
  document.getElementById('sidebar-loading').dataset.refresh = '1';
  loadSidebarMatches();
});

/* ── Init ────────────────────────────────────────────────── */
setupAutocomplete('p1-input', 'p1-list', selectPlayer1, () => selectedPlayer2);
setupAutocomplete('p2-input', 'p2-list', selectPlayer2, () => selectedPlayer1);

waitUntilReady();
loadSidebarMatches();
