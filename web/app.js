// A股蜡烛图形态筛选工具 —— 前端逻辑
// Author: HZQ
const API = {
  meta: '/api/meta',
  scan: '/api/scan',
  scanStatus: (id) => `/api/scan/status/${id}`,
  scanCancel: (id) => `/api/scan/cancel/${id}`,
  scanLast: '/api/scan/last',
  syncStatus: '/api/sync/status',
  history: '/api/history',
  historyItem: (id) => `/api/history/${id}`,
  kline: (code, tf) => `/api/kline/${code}?tf=${tf}`,
  import: '/api/import',
  selftest: '/api/selftest',
  export: '/api/export',
  board: (kind, date) => `/api/board/${kind}${date ? '?date=' + date : ''}`,
  ladder: (date) => `/api/ladder${date ? '?date=' + date : ''}`,
  ladderDown: () => '/api/ladder-down',
  unsealed: (dir) => `/api/unsealed/${dir}`,
  dragonTiger: (date) => `/api/dragon-tiger${date ? '?date=' + date : ''}`,
  dragonTigerSeats: (code, date) => `/api/dragon-tiger/${code}${date ? '?date=' + date : ''}`,
  dragonTigerHistory: (code) => `/api/dragon-tiger/history/${code}`,
  latestDate: '/api/latest-trade-date',
  hotspot: (date) => `/api/hotspot${date ? '?date=' + date : ''}`,
  news: '/api/news',
  weekendNews: '/api/news/weekend',
};

// A股配色：涨=红，跌=绿
const C_UP = '#f23645';
const C_DOWN = '#26a69a';
const C_ACCENT = '#4c8dff';
const C_RESONANCE = '#f5a623';
const C_TEXT = '#e6ebf2';
const C_DIM = '#8b96a8';

const state = {
  meta: null,
  results: [],
  scanStats: null,
  customCodes: [],       // 导入的自定义股票代码
  importNames: {},       // 导入代码的名称
  jobId: null,
  pollTimer: null,
  scanning: false,       // 是否正在扫描
  scanStartTime: null,   // 扫描开始时间戳（用于 ETA 估算）
  lastParams: null,      // 最近一次成功扫描的参数（用于「重新加载」）
  sortKey: 'strength',
  sortDesc: true,
  resonanceOnly: false,
  page: 1,
  pageSize: 50,
  klineChart: null,
  eventTab: null,        // 当前市场事件模块
  eventData: null,       // 当前模块数据
};

// ===================== 初始化 =====================
document.addEventListener('DOMContentLoaded', async () => {
  bindEvents();
  try {
    const r = await fetch(API.meta);
    state.meta = await r.json();
    renderTimeframes();
    renderMarkets();
    renderPatterns();
    initEventDate();
    restoreCachedResult();   // 恢复最近一次筛选结果（无需重新计算）
    initSyncStatus();        // 显示上次数据同步时间
    loadHistory();           // 加载历史筛选结果栏
  } catch (e) {
    console.error('加载元信息失败', e);
  }
});

function bindEvents() {
  document.getElementById('scanBtn').addEventListener('click', () => startScan());
  document.getElementById('stopBtn').addEventListener('click', stopScan);
  document.getElementById('reloadBtn').addEventListener('click', reloadScan);
  document.getElementById('exportBtn').addEventListener('click', exportCSV);
  document.getElementById('reportBtn').addEventListener('click', generateReport);
  document.getElementById('selftestBtn').addEventListener('click', runSelftest);
  document.getElementById('patternSelectAll').addEventListener('click', () => setAllPatterns(true));
  document.getElementById('patternClearAll').addEventListener('click', () => setAllPatterns(false));
  document.getElementById('resonanceOnly').addEventListener('change', (e) => {
    state.resonanceOnly = e.target.checked;
    state.page = 1;
    renderResults();
  });
  document.getElementById('sortBy').addEventListener('change', (e) => {
    state.sortKey = e.target.value;
    state.page = 1;
    renderResults();
  });
  document.querySelector('.sortable').addEventListener('click', () => {
    state.sortDesc = !state.sortDesc;
    renderResults();
  });
  // 分页
  document.getElementById('prevPage').addEventListener('click', () => { state.page--; renderResults(); });
  document.getElementById('nextPage').addEventListener('click', () => { state.page++; renderResults(); });
  document.getElementById('pageSize').addEventListener('change', (e) => {
    state.pageSize = parseInt(e.target.value, 10);
    state.page = 1;
    renderResults();
  });
  // 文件导入
  document.getElementById('importBtn').addEventListener('click', () => document.getElementById('importFile').click());
  document.getElementById('importFile').addEventListener('change', onImportFile);
  document.getElementById('clearImportBtn').addEventListener('click', clearImport);
  // 弹窗
  document.getElementById('closeModal').addEventListener('click', closeModal);
  document.getElementById('modalBackdrop').addEventListener('click', closeModal);
  document.getElementById('closeSelftest').addEventListener('click', closeSelftest);
  document.getElementById('selftestBackdrop').addEventListener('click', closeSelftest);
  document.getElementById('closeSeat').addEventListener('click', closeSeat);
  document.getElementById('seatBackdrop').addEventListener('click', closeSeat);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeModal(); closeSelftest(); closeSeat(); } });
  window.addEventListener('resize', () => { if (state.klineChart) state.klineChart.resize(); });
  // 顶层功能切换
  document.querySelectorAll('#mainTabs .tab').forEach((t) => {
    t.addEventListener('click', () => switchTab(t.dataset.tab));
  });
  document.getElementById('eventRefresh').addEventListener('click', () => loadEvent(state.eventTab));
  document.getElementById('eventDate').addEventListener('change', () => loadEvent(state.eventTab));
}

// ===================== 渲染筛选控件 =====================
function renderTimeframes() {
  const box = document.getElementById('timeframeChips');
  box.innerHTML = '';
  state.meta.timeframes.forEach((tf, i) => {
    const chip = document.createElement('div');
    chip.className = 'chip' + (i === 0 ? ' active' : '');
    chip.dataset.key = tf.key;
    chip.textContent = tf.zh;
    chip.addEventListener('click', () => chip.classList.toggle('active'));
    box.appendChild(chip);
  });
}

function renderMarkets() {
  const box = document.getElementById('marketChips');
  box.innerHTML = '';
  (state.meta.markets || []).forEach((m) => {
    const chip = document.createElement('div');
    chip.className = 'chip';   // 默认不选中 = 不限
    chip.dataset.key = m.key;
    chip.textContent = m.zh;
    chip.addEventListener('click', () => chip.classList.toggle('active'));
    box.appendChild(chip);
  });
}

function renderPatterns() {
  const box = document.getElementById('patternList');
  box.innerHTML = '';
  const groups = [
    { key: 'bullish', zh: '看涨形态' },
    { key: 'bearish', zh: '看跌形态' },
    { key: 'neutral', zh: '中性/双向' },
  ];
  groups.forEach((g) => {
    const patterns = state.meta.patterns.filter((p) => p.direction === g.key);
    if (!patterns.length) return;
    const gwrap = document.createElement('div');
    gwrap.className = 'pattern-group';
    gwrap.dataset.dir = g.key;
    const title = document.createElement('div');
    title.className = 'pattern-group-title';
    title.innerHTML = `<span>${g.zh}</span><span class="link group-toggle" data-group="${g.key}">全选/清空</span>`;
    gwrap.appendChild(title);
    patterns.forEach((p) => {
      const item = document.createElement('label');
      item.className = 'pattern-item';
      item.innerHTML = `
        <input type="checkbox" data-key="${p.key}" checked>
        <span class="pname">${p.name_zh} <span class="pdir" style="color:${C_DIM}">${p.name_en}</span></span>
        <span class="pdir dir-${p.direction}">${dirZh(p.direction)}</span>`;
      gwrap.appendChild(item);
    });
    box.appendChild(gwrap);
  });
  // 分组「全选/清空」切换
  box.querySelectorAll('.group-toggle').forEach((t) => {
    t.addEventListener('click', () => toggleGroup(t.dataset.group));
  });
}

function dirZh(d) { return d === 'bullish' ? '看涨' : (d === 'bearish' ? '看跌' : '中性'); }

function setAllPatterns(checked) {
  document.querySelectorAll('#patternList input[type=checkbox]').forEach((cb) => { cb.checked = checked; });
}

function toggleGroup(direction) {
  const gw = document.querySelector(`.pattern-group[data-dir="${direction}"]`);
  if (!gw) return;
  const cbs = [...gw.querySelectorAll('input[type=checkbox]')];
  if (!cbs.length) return;
  const allChecked = cbs.every((cb) => cb.checked);
  cbs.forEach((cb) => { cb.checked = !allChecked; });   // 全选→清空，否则→全选
}

// ===================== 文件导入 =====================
async function onImportFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  document.getElementById('importBtn').textContent = '解析中…';
  try {
    const r = await fetch(API.import, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await r.json();
    state.customCodes = data.valid_codes || [];
    state.importNames = data.names || {};
    showImportResult(data, file.name);
  } catch (err) {
    console.error(err);
    alert('导入失败');
  } finally {
    document.getElementById('importBtn').textContent = '📄 导入 TXT/CSV/EBK';
    e.target.value = '';
  }
}

function showImportResult(data, fname) {
  const box = document.getElementById('importResult');
  box.classList.remove('hidden');
  const dist = Object.entries(data.market_dist || {})
    .map(([k, v]) => `${marketZh(k)} ${v}`).join(' · ');
  const bad = (data.invalid_entries || []).join('、');
  box.innerHTML = `
    <div>文件「${fname}」：成功 <span class="ok">${data.valid_count}</span> 个，
      失败 <span class="bad">${data.invalid_count}</span> 个</div>
    ${dist ? `<div class="detail">分布：${dist}</div>` : ''}
    ${bad ? `<div class="detail">无效项：${bad}${data.invalid_count > 50 ? '…' : ''}</div>` : ''}
    <div class="detail" style="color:var(--accent)">已作为「自定义股票池」参与后续筛选</div>`;
}

function clearImport() {
  state.customCodes = [];
  state.importNames = {};
  document.getElementById('importResult').classList.add('hidden');
}

// ===================== 收集参数 =====================
function collectParams() {
  const timeframes = [...document.querySelectorAll('#timeframeChips .chip.active')].map((c) => c.dataset.key);
  const markets = [...document.querySelectorAll('#marketChips .chip.active')].map((c) => c.dataset.key);
  const patterns = [...document.querySelectorAll('#patternList input:checked')].map((cb) => cb.dataset.key);

  const num = (id) => { const v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };

  const params = {
    timeframes: timeframes.length ? timeframes : ['daily'],
    markets: markets.length ? markets : null,       // 空 = 不限
    patterns: patterns.length ? patterns : null,
    above_ma250: document.getElementById('aboveMa250').checked,
    sync: document.getElementById('syncData').checked,
    limit_up_count_min: num('limitUpCountMin'),
    volume_min: num('volumeMin'),
    price_min: num('priceMin'),
    price_max: num('priceMax'),
    change_min: num('changeMin'),
    change_max: num('changeMax'),
    exclude_st: document.getElementById('excludeSt').checked,
    custom_codes: state.customCodes.length ? state.customCodes : null,
    sort_by: state.sortKey,
  };
  return params;
}

// ===================== 扫描 =====================
function setScanning(scanning) {
  state.scanning = scanning;
  const sidebar = document.querySelector('.sidebar');
  sidebar.classList.toggle('scanning', scanning);
  document.getElementById('scanBtn').classList.toggle('hidden', scanning);
  document.getElementById('stopBtn').classList.toggle('hidden', !scanning);
}

function formatDuration(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m} 分 ${s} 秒` : `${m} 分钟`;
}

async function startScan(params) {
  // 仅当传入的是带 timeframes 数组的有效参数对象时复用，否则从界面重新收集
  // （防御：点击事件监听若误传 Event 对象，也会回退到 collectParams）
  const p = (params && Array.isArray(params.timeframes)) ? params : collectParams();
  if (!p.timeframes || !p.timeframes.length) { alert('请至少选择一个时间级别'); return; }
  if (state.scanning) return;   // 防止重复提交

  setScanning(true);
  state.scanStartTime = Date.now();
  state.lastParams = p;   // 记录本次参数，供「重新加载」复用
  showProgress(true, 0, '提交任务…');

  try {
    const r = await fetch(API.scan, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
    const data = await r.json();
    state.jobId = data.job_id;
    pollStatus();
  } catch (e) {
    console.error(e);
    setScanning(false);
    showProgress(false);
    alert('提交筛选任务失败');
  }
}

function stopScan() {
  if (!state.jobId) return;
  document.getElementById('stopBtn').disabled = true;
  document.getElementById('stopBtn').textContent = '停止中…';
  fetch(API.scanCancel(state.jobId), { method: 'POST' }).catch(() => {});
}

function pollStatus() {
  state.pollTimer = setInterval(async () => {
    try {
      const r = await fetch(API.scanStatus(state.jobId));
      const s = await r.json();
      // 进度 + 预估剩余时间
      let eta = '';
      if (s.progress > 0 && state.scanStartTime) {
        const elapsed = (Date.now() - state.scanStartTime) / 1000;
        const remaining = elapsed / s.progress * (100 - s.progress);
        eta = ` · 预计剩余 ${formatDuration(remaining)}`;
      }
      showProgress(true, s.progress, s.message + eta);

      if (s.status === 'done') {
        clearInterval(state.pollTimer);
        state.results = s.result.results || [];
        state.scanStats = s.result.stats || null;
        state.page = 1;
        finishScan(s.result);
      } else if (s.status === 'error') {
        clearInterval(state.pollTimer);
        finishScan(null, s.error || s.message, s.errlog);
      } else if (s.status === 'cancelled') {
        clearInterval(state.pollTimer);
        finishScan(null, '已停止筛选');
      }
    } catch (e) {
      clearInterval(state.pollTimer);
      finishScan(null, '轮询失败');
    }
  }, 800);
}

function finishScan(result, error, errlog) {
  setScanning(false);
  document.getElementById('stopBtn').disabled = false;
  document.getElementById('stopBtn').textContent = '⏹ 停止筛选';
  showProgress(false);
  if (error) {
    let msg = error;
    if (errlog) msg += `\n\n错误日志已保存：\n${errlog}`;
    alert(msg);
    return;
  }
  renderResults();
  const has = state.results.length > 0;
  document.getElementById('reloadBtn').disabled = !has;
  document.getElementById('exportBtn').disabled = !has;
  document.getElementById('reportBtn').disabled = !has;
  // 筛选完成后刷新同步时间与历史结果栏
  initSyncStatus();
  loadHistory();
}

function showProgress(show, pct, text) {
  document.getElementById('progressWrap').classList.toggle('hidden', !show);
  document.getElementById('progressFill').style.width = (pct || 0) + '%';
  document.getElementById('progressText').textContent = text || '';
}

// 用最近一次成功的参数重新执行筛选（主动刷新数据）
function reloadScan() {
  if (!state.lastParams) return;
  startScan(state.lastParams);
}

// 恢复最近一次成功结果（页面加载 / 切回时快速显示，无需重新计算）
async function restoreCachedResult() {
  try {
    const r = await fetch(API.scanLast);
    const d = await r.json();
    if (d.has_result && d.result) {
      state.results = d.result.results || [];
      state.scanStats = d.result.stats || null;
      state.lastParams = d.params || null;
      renderResults();
      const has = state.results.length > 0;
      document.getElementById('reloadBtn').disabled = !has;
      document.getElementById('exportBtn').disabled = !has;
      document.getElementById('reportBtn').disabled = !has;
    }
  } catch (e) { /* 忽略：无缓存或服务未就绪 */ }
}

// ===================== 数据同步状态 & 历史筛选结果 =====================
async function initSyncStatus() {
  try {
    const r = await fetch(API.syncStatus);
    const d = await r.json();
    const el = document.getElementById('syncStatus');
    if (d.last_sync) {
      el.textContent = `上次同步：${d.last_sync}（更新 ${d.synced_count} 项）`;
    } else {
      el.textContent = '上次同步：尚未同步';
    }
  } catch (e) { /* 忽略 */ }
}

async function loadHistory() {
  try {
    const r = await fetch(API.history);
    const d = await r.json();
    const list = d.history || [];
    const box = document.getElementById('historyList');
    const batchBox = document.getElementById('historyBatch');
    const checkAll = document.getElementById('historyCheckAll');

    if (!list.length) {
      box.innerHTML = '<span class="history-empty">暂无历史结果</span>';
      batchBox.style.display = 'none';
      checkAll.checked = false;
      return;
    }
    batchBox.style.display = 'flex';
    box.innerHTML = list.map((h) => {
      const tf = (h.timeframes || []).map(lvTf).join('/') || '—';
      const mk = (h.markets || []).map(marketZh).join('/') || '全部市场';
      return `<div class="history-item" data-id="${h.id}" title="点击加载该结果">
        <input type="checkbox" class="hi-check" data-id="${h.id}">
        <span class="hi-time">${h.ts}</span>
        <span class="hi-meta">${tf} · ${mk} · 命中 <b>${h.matched_rows}</b> 条</span>
        <span class="hi-del" data-del="${h.id}" title="删除">✕</span>
      </div>`;
    }).join('');

    // 点击加载历史结果（点 checkbox 或删除按钮时不触发）
    box.querySelectorAll('.history-item').forEach((el) => {
      el.addEventListener('click', (e) => {
        if (e.target.classList.contains('hi-check') || e.target.dataset.del) return;
        loadHistoryItem(el.dataset.id);
      });
    });
    // 单条删除
    box.querySelectorAll('.hi-del').forEach((el) => {
      el.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(API.historyItem(el.dataset.del), { method: 'DELETE' });
        loadHistory();
      });
    });
    // 全选
    checkAll.onchange = () => {
      box.querySelectorAll('.hi-check').forEach((cb) => { cb.checked = checkAll.checked; });
    };
    // 批量删除
    document.getElementById('historyBatchDel').onclick = async () => {
      const ids = [...box.querySelectorAll('.hi-check:checked')].map((cb) => cb.dataset.id);
      if (!ids.length) { alert('请先勾选要删除的记录'); return; }
      if (!confirm(`确定删除选中的 ${ids.length} 条历史结果吗？`)) return;
      await fetch(API.history + '/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      });
      checkAll.checked = false;
      loadHistory();
    };
  } catch (e) { /* 忽略 */ }
}

async function loadHistoryItem(id) {
  try {
    const r = await fetch(API.historyItem(id));
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    state.results = d.results || [];
    state.scanStats = d.stats || null;
    state.lastParams = d.params || null;
    state.page = 1;
    renderResults();
    const has = state.results.length > 0;
    document.getElementById('reloadBtn').disabled = !has;
    document.getElementById('exportBtn').disabled = !has;
    document.getElementById('reportBtn').disabled = !has;
    // 切回形态筛选页（若当前在其它 Tab）
    switchTab('screener');
  } catch (e) {
    alert('加载历史结果失败');
  }
}

// ===================== 结果渲染（含分页/统计） =====================
function renderResults() {
  let list = [...state.results];
  if (state.resonanceOnly) list = list.filter((r) => r.resonance);

  // 排序
  list.sort((a, b) => {
    let va, vb;
    if (state.sortKey === 'date') {
      va = a.date + a.code; vb = b.date + b.code;
    } else {
      va = a.strength; vb = b.strength;
      if (va === vb) { va = a.date; vb = b.date; }
    }
    if (typeof va === 'number') return state.sortDesc ? vb - va : va - vb;
    return state.sortDesc ? vb.localeCompare(va) : va.localeCompare(vb);
  });

  renderStats();

  // 分页
  const total = list.length;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > totalPages) state.page = totalPages;
  const start = (state.page - 1) * state.pageSize;
  const pageList = list.slice(start, start + state.pageSize);

  const tbody = document.getElementById('resultBody');
  if (!total) {
    tbody.innerHTML = '<tr class="empty"><td colspan="13">无符合条件的信号，请调整筛选条件</td></tr>';
    updatePagination(0, 1, 1);
    return;
  }

  tbody.innerHTML = pageList.map((r) => {
    const dirCls = r.direction === 'bullish' ? 'tag-up' : (r.direction === 'bearish' ? 'tag-down' : 'tag-tf');
    const chgCls = r.change_pct >= 0 ? 'num-up' : 'num-down';
    const resonanceTag = r.resonance
      ? `<span class="tag tag-resonance">共振·${r.resonance_levels.map(lvTf).join('/')}</span>`
      : '<span style="color:var(--text-faint)">—</span>';
    return `<tr data-code="${r.code}" data-tf="${r.timeframe}">
      <td class="cell-code">${r.code}</td>
      <td>${r.name}</td>
      <td><span class="tag tag-tf">${r.market_zh || '—'}</span></td>
      <td><span class="tag tag-tf">${r.timeframe_zh}</span></td>
      <td>${r.pattern_zh}</td>
      <td><span class="tag ${dirCls}">${r.direction_zh}</span></td>
      <td>${r.date}</td>
      <td class="strength-cell">${r.strength}</td>
      <td>${r.volume_ratio}×</td>
      <td>${r.close.toFixed(2)}</td>
      <td class="${chgCls}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct}%</td>
      <td>${r.limit_1y || 0}</td>
      <td>${resonanceTag}</td>
    </tr>`;
  }).join('');

  tbody.querySelectorAll('tr[data-code]').forEach((tr) => {
    tr.addEventListener('click', () => openKline(tr.dataset.code, tr.dataset.tf));
  });

  updatePagination(total, state.page, totalPages);
}

function renderStats() {
  const st = state.scanStats;
  if (!st) { document.getElementById('stats').innerHTML = '尚未扫描'; return; }
  const upCount = state.results.filter((r) => r.direction === 'bullish').length;
  const downCount = state.results.filter((r) => r.direction === 'bearish').length;
  const resonanceCount = state.results.filter((r) => r.resonance).length;

  const dist = Object.entries(st.market_dist || {})
    .map(([k, v]) => `${marketZh(k)}${v}`).join(' · ');

  let html = `总样本 <b>${st.total_samples}</b> 只 · 符合条件 <b>${st.matched_rows}</b> 条（<b>${st.matched_stocks}</b> 只）`;
  if (st.ma250_above != null) html += ` · 年线上 <b style="color:${C_DOWN}">${st.ma250_above}</b> 只`;
  html += ` · 看涨 ${upCount} / 看跌 ${downCount} · 共振 <b style="color:${C_RESONANCE}">${resonanceCount}</b>`;
  if (dist) html += `<br><span style="font-size:11px">样本分布：${dist}</span>`;
  document.getElementById('stats').innerHTML = html;
}

function updatePagination(total, page, totalPages) {
  document.getElementById('pageInfo').textContent = `共 ${total} 条 · 第 ${page}/${totalPages} 页`;
  document.getElementById('pageNum').textContent = page;
  document.getElementById('prevPage').disabled = page <= 1;
  document.getElementById('nextPage').disabled = page >= totalPages;
}

function marketZh(k) {
  const m = (state.meta?.markets || []).find((x) => x.key === k);
  return m ? m.zh : k;
}

function lvTf(k) {
  const m = { daily: '日', weekly: '周', monthly: '月' };
  return m[k] || k;
}

// ===================== 形态引擎自检 =====================
async function runSelftest() {
  document.getElementById('selftestBtn').textContent = '自检中…';
  try {
    const r = await fetch(API.selftest);
    const d = await r.json();
    renderSelftest(d);
  } catch (e) {
    console.error(e);
    alert('自检失败');
  } finally {
    document.getElementById('selftestBtn').textContent = '🧪 形态引擎自检';
  }
}

function renderSelftest(d) {
  const body = document.getElementById('selftestBody');
  const cases = (d.cases || []).map((c) => `
    <div class="selftest-case ${c.passed ? 'pass' : 'fail'}">
      <span class="icon">${c.passed ? '✓' : '✗'}</span>
      <span>${c.name}</span>
      <span class="actual">命中 ${c.actual.join('、') || '无'}</span>
    </div>`).join('');
  body.innerHTML = `
    <div class="selftest-summary">
      <div class="selftest-card"><div class="num">${d.total}</div><div class="lbl">用例总数</div></div>
      <div class="selftest-card pass"><div class="num">${d.passed}</div><div class="lbl">通过</div></div>
      <div class="selftest-card ${d.failed ? 'fail' : ''}"><div class="num">${d.failed}</div><div class="lbl">失败</div></div>
      <div class="selftest-card"><div class="num">${(d.patterns || []).length}</div><div class="lbl">形态库</div></div>
    </div>
    ${cases}`;
  document.getElementById('selftestModal').classList.remove('hidden');
}

function closeSelftest() {
  document.getElementById('selftestModal').classList.add('hidden');
}

// ===================== 顶层功能切换 & 市场事件 =====================
const EVENT_TITLES = { zt: '涨停板', dt: '跌停板', ladder: '连板天梯', lhb: '龙虎榜', hotspot: '题材热点', news: '周末热点新闻' };
const SUB_TABS = {
  zt: [{ key: 'board', zh: '封板涨停' }, { key: 'unsealed', zh: '未封板' }],
  dt: [{ key: 'board', zh: '封板跌停' }, { key: 'unsealed', zh: '未封板' }],
  ladder: [{ key: 'up', zh: '涨停连板' }, { key: 'down', zh: '跌停连板' }],
};

function switchTab(tab) {
  state.eventTab = tab;
  state.eventSub = null;
  document.querySelectorAll('#mainTabs .tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
  const isScreener = tab === 'screener';
  document.getElementById('panel-screener').classList.toggle('active', isScreener);
  document.getElementById('eventPanel').classList.toggle('hidden', isScreener);
  if (!isScreener) loadEvent(tab);
}

function renderSubTabs(tab) {
  const box = document.getElementById('eventSubTabs');
  const subs = SUB_TABS[tab];
  if (!subs) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.classList.remove('hidden');
  if (state.eventSub === null) state.eventSub = subs[0].key;
  box.innerHTML = subs.map((s) =>
    `<div class="tab ${state.eventSub === s.key ? 'active' : ''}" data-sub="${s.key}">${s.zh}</div>`).join('');
  box.querySelectorAll('.tab').forEach((t) => {
    t.addEventListener('click', () => { state.eventSub = t.dataset.sub; loadEvent(tab); });
  });
}

async function initEventDate() {
  try {
    const r = await fetch(API.latestDate);
    const d = await r.json();
    if (d.date) document.getElementById('eventDate').value = d.date;
  } catch (e) { /* 忽略 */ }
}

async function loadEvent(tab) {
  document.getElementById('eventTitle').textContent = EVENT_TITLES[tab] || '';
  renderSubTabs(tab);
  const date = document.getElementById('eventDate').value || '';
  document.getElementById('eventStats').textContent = '加载中…';
  document.getElementById('eventContent').innerHTML = '';
  const sub = state.eventSub;
  try {
    if (tab === 'zt') {
      if (sub === 'unsealed') renderUnsealed(await (await fetch(API.unsealed('up'))).json());
      else renderBoard('zt', await (await fetch(API.board('zt', date))).json());
    } else if (tab === 'dt') {
      if (sub === 'unsealed') renderUnsealed(await (await fetch(API.unsealed('down'))).json());
      else renderBoard('dt', await (await fetch(API.board('dt', date))).json());
    } else if (tab === 'ladder') {
      if (sub === 'down') renderLadder(await (await fetch(API.ladderDown())).json(), true);
      else renderLadder(await (await fetch(API.ladder(date))).json(), false);
    } else if (tab === 'lhb') {
      renderDragonTiger(await (await fetch(API.dragonTiger(date))).json());
    } else if (tab === 'hotspot') {
      renderHotspot(await (await fetch(API.hotspot(date))).json());
    } else if (tab === 'news') {
      renderWeekendNews(await (await fetch(API.weekendNews)).json());
    }
  } catch (e) {
    console.error(e);
    document.getElementById('eventStats').textContent = '加载失败，请检查网络';
  }
}

function renderBoard(kind, d) {
  document.getElementById('eventStats').innerHTML = `<b>${d.date}</b> · 共 <b>${d.count}</b> 只`;
  const isUp = kind === 'zt';
  const hasLimitCount = isUp;
  const rows = (d.stocks || []).map((s) => {
    const reason = s.reason ? `<td class="reason-cell">${s.reason}</td>` : '<td style="color:var(--text-faint)">—</td>';
    const boardTag = s.boards >= 2 ? `<span class="tag tag-up">${s.boards}连板</span>` : (s.boards === 1 ? '首板' : '—');
    const breakTag = s.break_count > 0 ? `<span style="color:var(--resonance)">${s.break_count}次</span>` : '0';
    const limitCols = hasLimitCount ? `<td>${s.limit_1y ?? '—'}</td><td>${s.limit_6m ?? '—'}</td><td>${s.limit_1m ?? '—'}</td>` : '';
    const chgCls = isUp ? 'num-up' : 'num-down';
    const chgSign = isUp ? '+' : '';
    return `<tr class="clickable" data-code="${s.code}">
      <td class="cell-code">${s.code}</td><td>${s.name}</td><td>${s.market_zh}</td>
      <td class="${chgCls}">${chgSign}${s.change_pct}%</td><td>${s.first_time}</td><td>${boardTag}</td>
      <td>${breakTag}</td><td>${s.fund}万</td><td>${s.turnover}%</td>${limitCols}
      <td>${s.industry || '—'}</td>${reason}</tr>`;
  }).join('');
  const limitHead = hasLimitCount ? '<th>年涨停</th><th>半年</th><th>月</th>' : '';
  const header = `<th>代码</th><th>名称</th><th>板块</th><th>涨跌幅</th><th>${isUp ? '首次封板' : '首次跌停'}</th><th>连板</th><th>炸板次数</th><th>封单额</th><th>换手</th>${limitHead}<th>行业</th><th>涨停原因</th>`;
  const colCount = hasLimitCount ? 14 : 11;
  const empty = `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-faint);padding:40px">当日无数据</td></tr>`;
  document.getElementById('eventContent').innerHTML =
    `<table class="event-table"><thead><tr>${header}</tr></thead><tbody>${rows || empty}</tbody></table>`;
  document.querySelectorAll('#eventContent tr[data-code]').forEach((tr) => {
    tr.addEventListener('click', () => openKline(tr.dataset.code, 'daily'));
  });
}

function renderUnsealed(d) {
  const isUp = d.direction === 'up';
  document.getElementById('eventStats').innerHTML = `<b>${d.date}</b> · ${isUp ? '涨停未封板' : '跌停未封板'} <b>${d.count}</b> 只`;
  const rows = (d.stocks || []).map((s) => {
    const chgCls = s.change_pct >= 0 ? 'num-up' : 'num-down';
    return `<tr class="clickable" data-code="${s.code}">
      <td class="cell-code">${s.code}</td><td>${s.name}</td><td>${s.market_zh}</td>
      <td class="${chgCls}">${s.change_pct >= 0 ? '+' : ''}${s.change_pct}%</td><td>${s.close}</td></tr>`;
  }).join('');
  const empty = '<tr><td colspan="5" style="text-align:center;color:var(--text-faint);padding:40px">当日无数据</td></tr>';
  document.getElementById('eventContent').innerHTML =
    `<table class="event-table"><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>涨跌幅</th><th>收盘价</th></tr></thead><tbody>${rows || empty}</tbody></table>`;
  document.querySelectorAll('#eventContent tr[data-code]').forEach((tr) => {
    tr.addEventListener('click', () => openKline(tr.dataset.code, 'daily'));
  });
}

function renderLadder(d, isDown = false) {
  const title = isDown ? '跌停连板' : '涨停连板';
  const color = isDown ? C_DOWN : C_UP;
  document.getElementById('eventStats').innerHTML =
    `<b>${d.date}</b> · ${title} <b>${d.total}</b> 只 · 最高 <b style="color:${color}">${d.height}连板</b>`;
  const html = (d.ladder || []).map((g) => {
    const cards = g.stocks.map((s) => `
      <div class="ladder-stock" data-code="${s.code}">
        <span class="ls-name">${s.name}</span>
        <span class="ls-sub">${s.code} · ${s.boards}板${s.theme ? ' · ' + s.theme : ''}</span>
      </div>`).join('');
    return `<div class="ladder-group">
      <div class="ladder-head"><span class="ladder-badge" style="color:${color};border-color:${color}">${g.label}</span><span style="color:var(--text-dim)">${g.stocks.length} 只</span></div>
      <div class="ladder-stocks">${cards}</div>
    </div>`;
  }).join('');
  document.getElementById('eventContent').innerHTML = html || '<div style="padding:40px;color:var(--text-faint);text-align:center">当日无数据</div>';
  document.querySelectorAll('#eventContent .ladder-stock[data-code]').forEach((el) => {
    el.addEventListener('click', () => openKline(el.dataset.code, 'daily'));
  });
}

function renderDragonTiger(d) {
  if (d.note) {
    document.getElementById('eventStats').textContent = d.note;
    document.getElementById('eventContent').innerHTML = '';
    return;
  }
  document.getElementById('eventStats').innerHTML = `<b>${d.date}</b> · 共 <b>${d.count}</b> 条上榜记录`;
  const rows = (d.stocks || []).map((s) => {
    const netCls = s.net_buy_wan >= 0 ? 'num-up' : 'num-down';
    return `<tr class="clickable" data-code="${s.code}">
      <td class="cell-code">${s.code}</td><td>${s.name}</td><td>${s.market_zh}</td>
      <td class="${s.change_pct >= 0 ? 'num-up' : 'num-down'}">${s.change_pct >= 0 ? '+' : ''}${s.change_pct}%</td>
      <td>${s.close.toFixed(2)}</td>
      <td class="${netCls}">${s.net_buy_wan >= 0 ? '+' : ''}${s.net_buy_wan}万</td>
      <td>${s.buy_wan}万</td><td>${s.sell_wan}万</td><td>${s.turnover_pct}%</td>
      <td class="reason-cell">${s.reason}</td></tr>`;
  }).join('');
  const empty = '<tr><td colspan="10" style="text-align:center;color:var(--text-faint);padding:40px">当日无数据</td></tr>';
  document.getElementById('eventContent').innerHTML =
    `<table class="event-table"><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>涨跌幅</th><th>收盘</th><th>净买额</th><th>买入</th><th>卖出</th><th>换手</th><th>上榜原因</th></tr></thead><tbody>${rows || empty}</tbody></table>`;
  document.querySelectorAll('#eventContent tr[data-code]').forEach((tr) => {
    tr.addEventListener('click', () => openSeat(tr.dataset.code));
  });
}

async function openSeat(code) {
  const date = document.getElementById('eventDate').value || '';
  document.getElementById('seatTitle').textContent = `${code} · 龙虎榜详情`;
  document.getElementById('seatBody').innerHTML = '<div style="padding:20px;color:var(--text-dim)">加载中…</div>';
  document.getElementById('seatModal').classList.remove('hidden');
  let historyAsc = false;
  try {
    const [d, h] = await Promise.all([
      (await fetch(API.dragonTigerSeats(code, date))).json(),
      (await fetch(API.dragonTigerHistory(code))).json(),
    ]);
    const seatRow = (s) => `<tr><td>${s.name}</td><td class="num-up">${s.buy_wan}万</td><td class="num-down">${s.sell_wan}万</td><td>${s.net_wan}万</td></tr>`;
    const buyRows = (d.buy_seats || []).map(seatRow).join('');
    const sellRows = (d.sell_seats || []).map(seatRow).join('');
    const inst = d.institution || {};

    const renderHistory = () => {
      const recs = [...(h.records || [])].sort((a, b) => historyAsc ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date));
      const recRows = recs.map((r) => {
        const netCls = r.net_buy_wan >= 0 ? 'num-up' : 'num-down';
        return `<tr><td>${r.date}</td><td class="${r.change_pct >= 0 ? 'num-up' : 'num-down'}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct}%</td><td class="${netCls}">${r.net_buy_wan >= 0 ? '+' : ''}${r.net_buy_wan}万</td><td>${r.turnover_pct}%</td><td class="reason-cell">${r.reason}</td></tr>`;
      }).join('');
      return recRows || '<tr><td colspan="5" style="color:var(--text-faint)">近一年无上榜记录</td></tr>';
    };

    document.getElementById('seatBody').innerHTML = `
      <div class="seat-section">
        <div class="inst-card">
          <span>机构净买入：<b class="${inst.net_wan >= 0 ? 'num-up' : 'num-down'}">${inst.net_wan >= 0 ? '+' : ''}${inst.net_wan}万</b></span>
          <span>机构买入 ${inst.buy_wan}万</span>
          <span>机构卖出 ${inst.sell_wan}万</span>
        </div>
      </div>
      <div class="seat-section"><h4>买入席位 TOP5</h4>
        <table class="seat-table"><thead><tr><th>营业部</th><th>买入</th><th>卖出</th><th>净额</th></tr></thead><tbody>${buyRows || '<tr><td colspan="4" style="color:var(--text-faint)">无数据</td></tr>'}</tbody></table>
      </div>
      <div class="seat-section"><h4>卖出席位 TOP5</h4>
        <table class="seat-table"><thead><tr><th>营业部</th><th>买入</th><th>卖出</th><th>净额</th></tr></thead><tbody>${sellRows || '<tr><td colspan="4" style="color:var(--text-faint)">无数据</td></tr>'}</tbody></table>
      </div>
      <div class="seat-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <h4 style="margin:0">近一年上榜明细（${h.count} 次）</h4>
          <button class="ghost-btn" id="historySortBtn">日期${historyAsc ? '升序 ↑' : '降序 ↓'}</button>
        </div>
        <table class="seat-table"><thead><tr><th>日期</th><th>涨跌幅</th><th>净买额</th><th>换手</th><th>上榜原因</th></tr></thead><tbody id="historyBody">${renderHistory()}</tbody></table>
      </div>`;
    document.getElementById('historySortBtn').addEventListener('click', () => {
      historyAsc = !historyAsc;
      document.getElementById('historySortBtn').textContent = `日期${historyAsc ? '升序 ↑' : '降序 ↓'}`;
      document.getElementById('historyBody').innerHTML = renderHistory();
    });
  } catch (e) {
    document.getElementById('seatBody').innerHTML = '<div style="padding:20px;color:var(--up)">加载失败</div>';
  }
}

function closeSeat() {
  document.getElementById('seatModal').classList.add('hidden');
}

// ===================== 题材热点 & 热点新闻 =====================
function renderHotspot(d) {
  document.getElementById('eventStats').innerHTML =
    `<b>${d.date}</b> · ${d.total} 只涨停 · 提取 <b>${d.themes.length}</b> 个题材`;
  const html = (d.themes || []).map((t, i) => {
    const chips = t.stocks.map((s) => `
      <span class="hot-stock" data-code="${s.code}" title="${s.first_time}封板">
        ${s.name}<em>${s.boards >= 2 ? s.boards + '板' : ''}</em>
      </span>`).join('');
    return `<div class="theme-group">
      <div class="theme-head">
        <span class="theme-rank">${i + 1}</span>
        <span class="theme-name">${t.name}</span>
        <span class="theme-count">${t.count} 只</span>
      </div>
      <div class="theme-stocks">${chips}</div>
    </div>`;
  }).join('');
  document.getElementById('eventContent').innerHTML =
    html || '<div style="padding:40px;color:var(--text-faint);text-align:center">当日无数据</div>';
  document.querySelectorAll('#eventContent .hot-stock[data-code]').forEach((el) => {
    el.addEventListener('click', () => openKline(el.dataset.code, 'daily'));
  });
}

function renderWeekendNews(d) {
  const news = d.news || [];
  document.getElementById('eventStats').innerHTML =
    `周末窗口 <b>${d.window_start}</b> ~ <b>${d.window_end}</b> · 共 <b>${d.count}</b> 条（★ 为重点）`;
  const html = news.map((n) => {
    const star = n.important ? '<span style="color:var(--resonance)">★</span>' : '<span style="color:var(--text-faint)">·</span>';
    const stockTags = (n.stocks || []).map((c) => `<span class="tag tag-tf news-stock" data-code="${c}">${c}</span>`).join('');
    return `<div class="news-item">
      <div class="news-time">${star} ${n.time}</div>
      <div class="news-body">
        <div class="news-title">${n.title}</div>
        ${n.summary ? `<div class="news-summary">${n.summary}</div>` : ''}
        ${stockTags ? `<div class="news-stocks">${stockTags}</div>` : ''}
      </div>
    </div>`;
  }).join('');
  document.getElementById('eventContent').innerHTML =
    html || '<div style="padding:40px;color:var(--text-faint);text-align:center">暂无周末快讯</div>';
  document.querySelectorAll('#eventContent .news-stock[data-code]').forEach((el) => {
    el.addEventListener('click', (e) => { e.stopPropagation(); openKline(el.dataset.code, 'daily'); });
  });
}

// ===================== 生成筛选报告 =====================
function generateReport() {
  if (!state.results.length) return;
  const st = state.scanStats || {};
  const results = [...state.results].sort((a, b) => b.strength - a.strength);
  const top = results.slice(0, 30);
  const resonanceStocks = [...new Set(state.results.filter((r) => r.resonance).map((r) => r.code + ' ' + r.name))];
  const upCount = state.results.filter((r) => r.direction === 'bullish').length;
  const downCount = state.results.filter((r) => r.direction === 'bearish').length;
  const now = new Date().toLocaleString('zh-CN');

  const rows = top.map((r) => `
    <tr>
      <td>${r.code}</td><td>${r.name}</td><td>${r.market_zh}</td><td>${r.timeframe_zh}</td>
      <td>${r.pattern_zh}</td><td style="color:${r.direction === 'bullish' ? '#f23645' : '#26a69a'}">${r.direction_zh}</td>
      <td>${r.date}</td><td>${r.strength}</td><td>${r.volume_ratio}×</td>
      <td>${r.change_pct}%</td><td>${r.resonance ? '✓' : ''}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
  <title>A股蜡烛图形态筛选报告</title>
  <style>
    body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:1000px;margin:0 auto;padding:24px;color:#1a1a1a;background:#fff}
    h1{font-size:22px;border-bottom:3px solid #f23645;padding-bottom:10px}
    .meta{color:#666;font-size:13px;margin-bottom:16px}
    .summary{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}
    .card{flex:1;min-width:130px;background:#f7f8fa;border:1px solid #e5e7eb;border-radius:8px;padding:14px;text-align:center}
    .card .num{font-size:24px;font-weight:700;color:#f23645}
    .card .lbl{font-size:12px;color:#666;margin-top:4px}
    table{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}
    th{background:#f7f8fa;text-align:left;padding:8px 10px;border-bottom:2px solid #e5e7eb}
    td{padding:7px 10px;border-bottom:1px solid #f0f1f3}
    h2{font-size:16px;margin-top:24px}
    .disclaimer{margin-top:24px;padding:12px;background:#fff8f0;border:1px solid #fde8c8;border-radius:6px;color:#8a6d3b;font-size:12px}
    .tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;background:#f0f1f3;margin:2px}
  </style></head><body>
  <h1>🕯 A股蜡烛图形态筛选报告</h1>
  <div class="meta">生成时间：${now}</div>
  <div class="summary">
    <div class="card"><div class="num">${st.total_samples ?? '—'}</div><div class="lbl">总样本数</div></div>
    <div class="card"><div class="num">${st.matched_stocks ?? state.results.length}</div><div class="lbl">命中股票</div></div>
    <div class="card"><div class="num">${state.results.length}</div><div class="lbl">信号总数</div></div>
    <div class="card"><div class="num">${resonanceStocks.length}</div><div class="lbl">共振股票</div></div>
    <div class="card"><div class="num" style="color:#f23645">${upCount}</div><div class="lbl">看涨信号</div></div>
    <div class="card"><div class="num" style="color:#26a69a">${downCount}</div><div class="lbl">看跌信号</div></div>
  </div>
  <h2>Top ${top.length} 信号（按强度排序）</h2>
  <table><thead><tr>
    <th>代码</th><th>名称</th><th>板块</th><th>级别</th><th>形态</th><th>方向</th><th>日期</th><th>强度</th><th>放量</th><th>涨跌</th><th>共振</th>
  </tr></thead><tbody>${rows}</tbody></table>
  ${resonanceStocks.length ? `<h2>跨级别共振股票（${resonanceStocks.length} 只）</h2><div>${resonanceStocks.map((s) => `<span class="tag">${s}</span>`).join('')}</div>` : ''}
  <div class="disclaimer">本报告由 A股量化分析工具自动生成，仅用于技术形态学习与研究，不构成任何投资建议。股市有风险，投资需谨慎。</div>
  </body></html>`;

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank');
  URL.revokeObjectURL(url);
}

// ===================== K线详情 =====================
async function openKline(code, tf) {
  const modal = document.getElementById('klineModal');
  modal.classList.remove('hidden');
  document.getElementById('modalTitle').textContent = `${code} · ${state.meta.timeframes.find(t => t.key === tf)?.zh || tf} 蜡烛图`;
  document.getElementById('modalLegend').innerHTML = '';
  document.getElementById('klineChart').innerHTML = '';

  try {
    const r = await fetch(API.kline(code, tf));
    const data = await r.json();
    if (data.error) { alert(data.error); closeModal(); return; }
    renderKline(data);
  } catch (e) {
    console.error(e);
  }
}

function closeModal() {
  document.getElementById('klineModal').classList.add('hidden');
  if (state.klineChart) { state.klineChart.dispose(); state.klineChart = null; }
}

function renderKline(data) {
  const candles = data.candles;
  const dates = candles.map((c) => c.dt);
  const ohlc = candles.map((c) => [c.open, c.close, c.low, c.high]);
  const vols = candles.map((c) => ({
    value: c.volume,
    itemStyle: { color: c.close >= c.open ? C_UP : C_DOWN, opacity: 0.75 },
  }));

  const ma = (k) => candles.map((c) => c[k]);

  // 形态高亮（markArea 阴影 + 图例）
  const marks = (data.matches || []).map((m) => {
    const idxs = m.candle_indexes || [m.index];
    const firstDt = dates[idxs[0]] ?? dates[dates.length - 1];
    const lastDt = dates[idxs[idxs.length - 1]] ?? firstDt;
    const color = m.direction === 'bearish' ? C_DOWN : (m.direction === 'bullish' ? C_UP : C_ACCENT);
    return {
      name: m.name_zh,
      coord: [{ xAxis: firstDt }, { xAxis: lastDt }],
      itemStyle: { color: hexToRgba(color, 0.18), borderColor: color, borderWidth: 1 },
      label: { show: true, position: 'insideTop', color, fontSize: 10, formatter: m.name_zh },
    };
  });

  const legendHtml = (data.matches || []).map((m) => {
    const color = m.direction === 'bearish' ? C_DOWN : (m.direction === 'bullish' ? C_UP : C_ACCENT);
    return `<span class="tag" style="color:${color};border:1px solid ${color}">${m.name_zh} ${m.date}</span>`;
  }).join('');
  document.getElementById('modalLegend').innerHTML = legendHtml || '<span style="color:var(--text-faint);font-size:12px">该级别近端未命中形态</span>';

  const chart = echarts.init(document.getElementById('klineChart'), 'dark');
  state.klineChart = chart;

  const option = {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: '#1c2330',
      borderColor: '#2a3444',
      textStyle: { color: C_TEXT },
    },
    legend: {
      data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60'],
      textStyle: { color: C_DIM },
      top: 4,
    },
    grid: [
      { left: 60, right: 20, top: 30, height: '58%' },
      { left: 60, right: 20, top: '74%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#2a3444' } }, axisLabel: { color: C_DIM }, splitLine: { show: false } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#2a3444' } }, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    yAxis: [
      { scale: true, axisLabel: { color: C_DIM }, splitLine: { lineStyle: { color: 'rgba(42,52,68,.5)' } } },
      { gridIndex: 1, scale: true, axisLabel: { color: C_DIM, show: false }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 0, height: 18, start: 60, end: 100 },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: ohlc,
        itemStyle: { color: C_UP, color0: C_DOWN, borderColor: C_UP, borderColor0: C_DOWN },
        markArea: { silent: true, data: marks },
      },
      { name: 'MA5', type: 'line', data: ma('ma5'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f5a623' } },
      { name: 'MA10', type: 'line', data: ma('ma10'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#4c8dff' } },
      { name: 'MA20', type: 'line', data: ma('ma20'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#b06ce0' } },
      { name: 'MA60', type: 'line', data: ma('ma60'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#26a69a' } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols },
    ],
  };
  chart.setOption(option);
}

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ===================== 导出 =====================
async function exportCSV() {
  if (!state.results.length) return;
  try {
    const r = await fetch(API.export, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results: state.results }),
    });
    if (!r.ok) { alert('导出失败'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const disp = r.headers.get('Content-Disposition') || '';
    let fname = 'scan_results.csv';
    const m1 = disp.match(/filename\*=UTF-8''([^;]+)/i);
    if (m1) { fname = decodeURIComponent(m1[1]); }
    else {
      const m2 = disp.match(/filename="?([^";]+)/i);
      if (m2) fname = m2[1];
    }
    a.href = url;
    a.download = fname;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
    alert('导出失败');
  }
}
