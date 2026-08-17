// A股蜡烛图形态筛选工具 —— 前端逻辑
// Author: HZQ
const API = {
  meta: '/api/meta',
  scan: '/api/scan',
  scanStatus: (id) => `/api/scan/status/${id}`,
  scanCancel: (id) => `/api/scan/cancel/${id}`,
  scanLast: '/api/scan/last',
  syncStatus: '/api/sync/status',
  sync: '/api/sync',
  cancelSync: '/api/cancel-sync',
  history: '/api/history',
  historyItem: (id) => `/api/history/${id}`,
  kline: (code, tf) => `/api/kline/${code}?tf=${tf}`,
  report: (code) => `/api/report/${code}`,
  reportSearch: (kw) => `/api/report/search?kw=${kw}`,
  import: '/api/import',
  selftest: '/api/selftest',
  export: '/api/export',
  exportEbk: '/api/export/ebk',
  board: (kind, date) => `/api/board/${kind}${date ? '?date=' + date : ''}`,
  ladder: (date) => `/api/ladder${date ? '?date=' + date : ''}`,
  ladderDown: () => '/api/ladder-down',
  dragonTiger: (date) => `/api/dragon-tiger${date ? '?date=' + date : ''}`,
  dragonTigerSeats: (code, date) => `/api/dragon-tiger/${code}${date ? '?date=' + date : ''}`,
  dragonTigerHistory: (code, days = 180) => `/api/dragon-tiger/history/${code}?days=${days}`,
  latestDate: '/api/latest-trade-date',
  hotspot: (date) => `/api/hotspot${date ? '?date=' + date : ''}`,
  news: '/api/news',
  dailyNews: '/api/news/daily',
  sealRate: (dir) => `/api/seal-rate/${dir}`,
  opened: (dir) => `/api/opened/${dir}`,
  marketOverview: '/api/market/overview',
  marketKline: (symbol, tf) => `/api/market/kline?symbol=${symbol}&tf=${tf}&count=160`,
};

// A股配色：涨=红，跌=绿

// fetch 带超时（默认 25s），避免接口异常时界面一直「加载中」
async function fetchTimeout(url, options = {}, ms = 25000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}
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
  scanElapsedMs: null,  // 本次筛选总耗时（毫秒）
  viewingHistory: null,  // 当前查看的历史记录 {id, ts}，null=非历史视图
  lockedParams: null,    // 锁定的历史筛选条件（基于历史记录继续筛选时锁定，只能追加）
  lockSource: null,      // 锁定来源描述（历史记录时间）
  showAllDims: false,    // 是否展开全部筛选维度（历史精简视图下默认收起未用维度）
  marketIdx: 'sh000001', // 市场分析：当前指数
  marketTf: 'day',       // 市场分析：日/周/月
  marketChart: null,     // 市场分析 K 线图实例
  customCodes: [],       // 导入的自定义股票代码
  importNames: {},       // 导入代码的名称
  dataSource: 'local',   // 数据来源：local(本地) / server(服务器) / upload(上传文件)
  serverHistory: [],     // 服务器地址历史记录
  serverSyncing: false,  // 服务器同步中
  jobId: null,
  pollTimer: null,
  scanning: false,       // 是否正在扫描
  scanStartTime: null,   // 扫描开始时间戳（用于 ETA 估算）
  lastParams: null,      // 最近一次成功扫描的参数（用于「重新加载」）
  sortKey: 'strength',   // 默认按信号强度排序
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
  initSidebarCollapse();
  try {
    const r = await fetch(API.meta);
    state.meta = await r.json();
    renderTimeframes();
    renderMarkets();
    renderPatterns();
    initEventDate();
    restoreCachedResult();   // 恢复最近一次筛选结果（无需重新计算）
    initSyncStatus();        // 显示上次数据同步时间
    initDataSource();        // 数据来源选择器（本地/服务器/上传）
    loadHistory();           // 加载历史筛选结果栏
  } catch (e) {
    console.error('加载元信息失败', e);
  }
});

function bindEvents() {
  document.getElementById('scanBtn').addEventListener('click', () => startScan());
  document.getElementById('stopBtn').addEventListener('click', stopScan);
  document.getElementById('scanBannerStop').addEventListener('click', stopScan);
  document.getElementById('reloadBtn').addEventListener('click', reloadScan);
  document.getElementById('clearResultBtn').addEventListener('click', clearResult);
  document.getElementById('exportBtn').addEventListener('click', exportCSV);
  document.getElementById('exportEbkBtn').addEventListener('click', exportEBK);
  document.getElementById('reportBtn').addEventListener('click', generateReport);
  document.getElementById('selftestBtn').addEventListener('click', runSelftest);
  document.getElementById('patternSelectAll').addEventListener('click', () => setAllPatterns(true));
  document.getElementById('patternClearAll').addEventListener('click', () => setAllPatterns(false));
  document.getElementById('resonanceOnly').addEventListener('change', (e) => {
    state.resonanceOnly = e.target.checked;
    state.page = 1;
    renderResults();
  });
  // 个股研报查询
  document.getElementById('reportQueryBtn').addEventListener('click', queryReport);
  document.getElementById('reportCode').addEventListener('keydown', (e) => { if (e.key === 'Enter') queryReport(); });
  // 输入时实时搜索名称候选（防抖 350ms；纯数字不触发，等回车按代码查）
  let reportSearchTimer = null;
  document.getElementById('reportCode').addEventListener('input', (e) => {
    clearTimeout(reportSearchTimer);
    const v = e.target.value.trim();
    if (!v || /^\d{1,6}$/.test(v)) { hideReportCand(); return; }
    reportSearchTimer = setTimeout(async () => {
      try {
        const r = await fetchTimeout(API.reportSearch(encodeURIComponent(v)), {}, 10000);
        const d = await r.json();
        const results = d.results || [];
        if (results.length > 1) showReportCand(results);
        else hideReportCand();
      } catch (err) { hideReportCand(); }
    }, 350);
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.report-search-wrap')) hideReportCand();
  });
  // 结果表所有列点击排序
  document.querySelectorAll('th.sortable').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDesc = !state.sortDesc;   // 同列点击切换升降序
      } else {
        state.sortKey = key;
        state.sortDesc = true;              // 新列默认降序
      }
      state.page = 1;
      renderResults();
    });
  });
  // 分页
  document.getElementById('prevPage').addEventListener('click', () => { state.page--; renderResults(); });
  document.getElementById('nextPage').addEventListener('click', () => { state.page++; renderResults(); });
  document.getElementById('pageSize').addEventListener('change', (e) => {
    state.pageSize = parseInt(e.target.value, 10);
    state.page = 1;
    renderResults();
  });
  // 数据来源切换
  document.getElementById('dataSource').addEventListener('change', onDataSourceChange);
  document.getElementById('serverConnect').addEventListener('click', onServerConnect);
  document.getElementById('serverCancel').addEventListener('click', onServerCancel);
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
  document.getElementById('sidebarToggle').addEventListener('click', toggleSidebar);
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
    chip.addEventListener('click', () => {
      if (chip.classList.contains('locked')) return;  // 锁定条件不可切换
      chip.classList.toggle('active');
    });
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
    chip.addEventListener('click', () => {
      if (chip.classList.contains('locked')) return;  // 锁定条件不可切换
      chip.classList.toggle('active');
    });
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
      const item = document.createElement('div');
      item.className = 'pattern-item';
      item.innerHTML = `
        <label class="pat-main">
          <input type="checkbox" data-key="${p.key}" checked>
          <span class="pname">${p.name_zh} <span class="pdir" style="color:${C_DIM}">${p.name_en}</span></span>
        </label>
        <label class="pat-verify" title="勾选后追加 1 天验证日，仅保留通过验证的形态">
          <input type="checkbox" class="verify-on" data-key="${p.key}"> 验证
        </label>`;
      gwrap.appendChild(item);
    });
    box.appendChild(gwrap);
  });
  // 分组「全选/清空」切换
  box.querySelectorAll('.group-toggle').forEach((t) => {
    t.addEventListener('click', () => toggleGroup(t.dataset.group));
  });
  // 看涨/看跌形态单选互斥
  setupPatternDirToggle();
}

function dirZh(d) { return d === 'bullish' ? '看涨' : (d === 'bearish' ? '看跌' : '中性'); }

// 看涨/看跌形态单选互斥：选一个方向自动隐藏另一个方向（中性组始终显示）
let _updateDirectionExclusion = null;
function setupPatternDirToggle() {
  const bullGroup = document.querySelector('.pattern-group[data-dir="bullish"]');
  const bearGroup = document.querySelector('.pattern-group[data-dir="bearish"]');

  const update = () => {
    const val = document.querySelector('input[name="patternDir"]:checked')?.value || 'bullish';
    if (val === 'bullish') {
      bullGroup && bullGroup.classList.remove('hidden-group');
      bearGroup && bearGroup.classList.add('hidden-group');
      // 清空隐藏组的勾选，避免被 collectParams 收集
      bearGroup && bearGroup.querySelectorAll('.pat-main input').forEach((cb) => { cb.checked = false; });
    } else {
      bearGroup && bearGroup.classList.remove('hidden-group');
      bullGroup && bullGroup.classList.add('hidden-group');
      bullGroup && bullGroup.querySelectorAll('.pat-main input').forEach((cb) => { cb.checked = false; });
    }
  };
  _updateDirectionExclusion = update;
  document.querySelectorAll('input[name="patternDir"]').forEach((r) => r.addEventListener('change', update));
}

function setAllPatterns(checked) {
  // 单选模式下只操作「当前显示方向组」的形态（隐藏组不参与）
  document.querySelectorAll('#patternList .pattern-group:not(.hidden-group) .pat-main input[type=checkbox]').forEach((cb) => { cb.checked = checked; });
}

function toggleGroup(direction) {
  const gw = document.querySelector(`.pattern-group[data-dir="${direction}"]`);
  if (!gw) return;
  const cbs = [...gw.querySelectorAll('.pat-main input[type=checkbox]')];
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
    const newCodes = data.valid_codes || [];
    const newNames = data.names || {};
    // 替换 / 合并当前筛选范围
    const mode = document.querySelector('input[name="uploadMode"]:checked')?.value || 'replace';
    if (mode === 'merge' && state.customCodes.length) {
      const merged = [...state.customCodes];
      const seen = new Set(merged);
      for (const c of newCodes) {
        if (!seen.has(c)) { merged.push(c); seen.add(c); }
      }
      state.customCodes = merged;
      state.importNames = { ...state.importNames, ...newNames };
    } else {
      state.customCodes = newCodes;
      state.importNames = newNames;
    }
    showImportResult(data, file.name, mode, newCodes.length);
    // 上传后仅在结果栏展示已上传股票列表（代码+名称两列），不自动筛选
    renderUploadedList();
  } catch (err) {
    console.error(err);
    alert('导入失败');
  } finally {
    document.getElementById('importBtn').textContent = '📄 选择股票列表文件';
    e.target.value = '';
  }
}

// 结果栏展示已上传的股票列表（仅「代码」「股票名」两列）
function renderUploadedList() {
  const codes = state.customCodes || [];
  const names = state.importNames || {};
  const table = document.getElementById('resultTable');
  const empty = document.getElementById('emptyState');
  const tbody = document.getElementById('resultBody');

  // 清空筛选结果状态，切换为「上传列表」视图
  state.results = [];
  state.scanStats = null;
  state.lastParams = null;
  state.viewingHistory = null;
  document.getElementById('stats').textContent =
    `📁 已上传 ${codes.length} 只股票（仅展示列表，请设置条件后点击「开始筛选」）`;

  // 上传列表视图：只显示「代码」「股票名」两列
  setTableColumns('upload');

  if (!codes.length) {
    empty.classList.remove('hidden');
    table.classList.add('hidden');
    updateResultButtons();
    return;
  }
  empty.classList.add('hidden');
  table.classList.remove('hidden');
  tbody.innerHTML = codes.map((c) => `
    <tr data-code="${c}">
      <td class="cell-code">${c}</td>
      <td>${names[c] || '—'}</td>
    </tr>`).join('');
  updateResultButtons();
}

// 切换结果表列显示：full=完整列，upload=仅「代码」「股票名」两列
function setTableColumns(mode) {
  document.querySelectorAll('#resultTable thead th[data-key]').forEach((th) => {
    const isKey = th.dataset.key === 'code' || th.dataset.key === 'name';
    th.classList.toggle('hidden', mode === 'upload' && !isKey);
  });
}

function showImportResult(data, fname, mode, addedCount) {
  const box = document.getElementById('importResult');
  box.classList.remove('hidden');
  const dist = Object.entries(data.market_dist || {})
    .map(([k, v]) => `${marketZh(k)} ${v}`).join(' · ');
  const bad = (data.invalid_entries || []).join('、');
  const modeText = mode === 'merge' ? `已合并 ${addedCount} 个（当前共 ${state.customCodes.length} 个）` : `已替换（共 ${state.customCodes.length} 个）`;
  box.innerHTML = `
    <div>文件「${fname}」：成功 <span class="ok">${data.valid_count}</span> 个，
      失败 <span class="bad">${data.invalid_count}</span> 个</div>
    ${dist ? `<div class="detail">分布：${dist}</div>` : ''}
    ${bad ? `<div class="detail">无效项：${bad}${data.invalid_count > 50 ? '…' : ''}</div>` : ''}
    <div class="detail" style="color:var(--accent)">${modeText}，结果栏已展示上传列表，请设置筛选条件后点击「开始筛选」</div>`;
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
  const patterns = [...document.querySelectorAll('#patternList .pat-main input:checked')].map((cb) => cb.dataset.key);
  const verifyPatterns = [...document.querySelectorAll('#patternList .verify-on:checked')].map((cb) => cb.dataset.key);

  const num = (id) => { const v = document.getElementById(id).value; return v === '' ? null : parseFloat(v); };

  const params = {
    timeframes: timeframes.length ? timeframes : ['daily'],
    markets: markets.length ? markets : null,       // 空 = 不限
    patterns: patterns.length ? patterns : null,
    verify_patterns: verifyPatterns.length ? verifyPatterns : null,   // 需要验证的形态
    above_ma250: document.getElementById('aboveMa250').checked,
    sync: false,   // 「同步服务器数据」选项已移除，筛选仅基于本地缓存（服务器同步由「数据来源→服务器」连接触发）
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
  // 筛选期间禁用结果栏交互，结束后恢复
  const content = document.querySelector('.content');
  if (content) content.classList.toggle('scanning', scanning);
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

function formatMs(ms) {
  if (ms == null) return '';
  if (ms < 1000) return `${ms} 毫秒`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)} 秒（${ms} 毫秒）`;
  return `${formatDuration(ms / 1000)}（${ms} 毫秒）`;
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
  state.viewingHistory = null;
  // 在统计栏显示本次筛选总耗时（精确到毫秒）
  const ms = (result && result.elapsed_ms != null) ? result.elapsed_ms : null;
  const statsEl = document.getElementById('stats');
  if (statsEl && ms != null) {
    const cur = statsEl.innerHTML;
    statsEl.innerHTML = `${cur}　·　⏱ 耗时 <b>${formatMs(ms)}</b>`;
  }
  updateResultButtons();
  // 筛选完成后刷新同步时间与历史结果栏
  initSyncStatus();
  loadHistory();
}

function showProgress(show, pct, text) {
  // 侧边栏进度条
  document.getElementById('progressWrap').classList.toggle('hidden', !show);
  document.getElementById('progressFill').style.width = (pct || 0) + '%';
  document.getElementById('progressText').textContent = text || '';
  // 结果区顶部醒目进度横幅
  const banner = document.getElementById('scanBanner');
  if (banner) {
    banner.classList.toggle('hidden', !show);
    document.getElementById('scanBannerFill').style.width = (pct || 0) + '%';
    document.getElementById('scanBannerPct').textContent = (pct || 0) + '%';
    document.getElementById('scanBannerMsg').textContent = text || '';
  }
}

// 用最近一次成功的参数重新执行筛选（主动刷新数据）
function reloadScan() {
  if (!state.lastParams) return;
  startScan(state.lastParams);
}

// 清空当前结果，回到「暂无结果」空状态（从历史视图返回，同时解除条件锁定）
function clearResult() {
  state.results = [];
  state.scanStats = null;
  state.viewingHistory = null;
  state.page = 1;
  if (state.lockedParams) unlockParams();  // 返回空状态即解除锁定
  setDataSourceVisible(true);  // 离开历史视图，恢复显示「数据来源」选择项
  document.querySelectorAll('.history-item.selected').forEach((el) => el.classList.remove('selected'));
  renderResults();
  updateResultButtons();
}

// 显示/隐藏「数据来源」面板（历史数据视图下隐藏，避免误操作）
function setDataSourceVisible(visible) {
  const panel = document.getElementById('dataSourcePanel');
  if (panel) panel.classList.toggle('hidden', !visible);
}

// 统一更新结果区按钮可用状态
function updateResultButtons() {
  const has = state.results.length > 0;
  document.getElementById('clearResultBtn').disabled = !has;
  document.getElementById('reloadBtn').disabled = !state.lastParams;
  document.getElementById('exportBtn').disabled = !has;
  document.getElementById('exportEbkBtn').disabled = !has;
  document.getElementById('reportBtn').disabled = !has;
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
      state.viewingHistory = null;
      renderResults();
      updateResultButtons();
    }
  } catch (e) { /* 忽略：无缓存或服务未就绪 */ }
}

// ===================== 数据同步状态 & 历史筛选结果 =====================
async function initSyncStatus() {
  // 「同步服务器数据」选项已移除，上次同步时间改由数据来源面板展示
  refreshLocalStatus();
}

// ===================== 数据来源选择器（本地 / 服务器 / 上传） =====================
function initDataSource() {
  refreshLocalStatus();   // 刷新上次同步时间 + 缓存空检测
  renderServerPresets();  // 渲染「数据服务器」下拉（来源/场景说明）
}

function renderServerPresets() {
  const sel = document.getElementById('serverPreset');
  const presets = (state.meta && state.meta.server_presets) || [];
  if (!sel || !presets.length) return;
  sel.innerHTML = presets.map((p) => `<option value="${p.key}">${p.zh}</option>`).join('');
  const def = (state.meta && state.meta.default_server_preset) || (presets[0] && presets[0].key);
  sel.value = def || presets[0].key;
  sel.addEventListener('change', onServerPresetChange);
  onServerPresetChange();   // 立即刷新说明与自定义地址行
}

function onServerPresetChange() {
  const sel = document.getElementById('serverPreset');
  const presets = (state.meta && state.meta.server_presets) || [];
  const cur = presets.find((p) => p.key === sel.value);
  const descEl = document.getElementById('serverPresetDesc');
  const addrRow = document.getElementById('serverAddrRow');
  if (descEl) descEl.textContent = cur ? `来源：${cur.source}。${cur.desc}` : '';
  if (addrRow) addrRow.classList.toggle('hidden', !(cur && cur.kind === 'custom'));
}

async function refreshLocalStatus() {
  try {
    const r = await fetch(API.syncStatus);
    const d = await r.json();
    const el = document.getElementById('srcSyncTime');
    if (el) {
      const files = d.cache_files ?? 0;
      el.textContent = d.last_sync
        ? `上次同步：${d.last_sync} · 本地缓存 ${files} 个文件`
        : `上次同步：尚未同步 · 本地缓存 ${files} 个文件`;
    }
    // 本地缓存为空 → 「本地数据」选项置灰禁用
    const localOpt = document.querySelector('#dataSource option[value="local"]');
    if (localOpt) localOpt.disabled = !(d.cache_files > 0);
  } catch (e) { /* 忽略 */ }
}

function onDataSourceChange() {
  const val = document.getElementById('dataSource').value;
  state.dataSource = val;
  document.getElementById('srcLocal').classList.toggle('hidden', val !== 'local');
  document.getElementById('srcServer').classList.toggle('hidden', val !== 'server');
  document.getElementById('srcUpload').classList.toggle('hidden', val !== 'upload');
  // 数据来源切换仅切换面板，不自动筛选（筛选统一由「开始筛选」按钮触发）
}

/**
 * 同步期间锁定/恢复相关控件：
 *  - 锁定：禁止「开始筛选」；禁止「数据来源」「数据服务器」下拉与自定义地址输入；
 *           显示「⏹ 中断」按钮（此时「连接」按钮保持禁用）。
 *  - 恢复：全部还原为可操作，隐藏中断按钮。
 */
function setSyncControls(locking) {
  const ids = ['scanBtn', 'dataSource', 'serverPreset', 'serverAddr'];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = locking;
  }
  const cancelBtn = document.getElementById('serverCancel');
  if (cancelBtn) {
    cancelBtn.classList.toggle('hidden', !locking);
    if (!locking) { cancelBtn.disabled = false; cancelBtn.textContent = '⏹ 中断'; }
  }
  const connectBtn = document.getElementById('serverConnect');
  if (connectBtn && !locking) connectBtn.disabled = false;
}

async function onServerConnect() {
  if (state.serverSyncing) return;
  // 数据服务器：预设键名；自定义选项填了地址则提交地址（host:port）
  const preset = document.getElementById('serverPreset').value;
  const addr = document.getElementById('serverAddr').value.trim();
  const server = (preset === 'custom' && addr) ? addr : preset;
  state.serverSyncing = true;
  setSyncControls(true);   // 锁定「开始筛选」+ 来源/服务器下拉，显示中断按钮
  const statusEl = document.getElementById('serverStatus');
  const progressEl = document.getElementById('serverProgress');
  const progressFill = document.getElementById('serverProgressFill');
  const progressText = document.getElementById('serverProgressText');
  const btn = document.getElementById('serverConnect');
  statusEl.textContent = '连接中…';
  statusEl.className = 'src-status';
  progressEl.classList.remove('hidden');
  progressFill.style.width = '0%';
  progressText.textContent = '连接服务器…';
  btn.disabled = true;

  try {
    // 同步级别：默认日/周/月全选（界面「同步级别」勾选可配置）；
    // 一个都没勾选时回退到默认三级别，保证本地数据完整。
    const tfs = [];
    for (const [key, id] of [['daily', 'syncLvDaily'], ['weekly', 'syncLvWeekly'], ['monthly', 'syncLvMonthly']]) {
      const el = document.getElementById(id);
      if (el && el.checked) tfs.push(key);
    }
    const timeframes = tfs.length ? tfs : ['daily', 'weekly', 'monthly'];
    const r = await fetchTimeout(API.sync, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server, timeframes }),
    }, 30000);
    const d = await r.json();
    if (d.error) {
      statusEl.textContent = `❌ 连接失败：${d.error}`;
      statusEl.className = 'src-status src-fail';
    } else {
      // 后端已改为后台同步：轮询 /api/sync/status 实时展示进度
      await pollSyncProgress(statusEl, progressFill, progressText);
    }
  } catch (e) {
    statusEl.textContent = e && e.name === 'AbortError' ? '❌ 连接超时，请检查网络' : '❌ 连接失败，请检查网络或稍后重试';
    statusEl.className = 'src-status src-fail';
  } finally {
    state.serverSyncing = false;
    setSyncControls(false);   // 恢复全部控件：筛选按钮可用、下拉可切换、隐藏中断按钮
    progressEl.classList.add('hidden');
  }
}

// 轮询同步进度（最长 10 分钟），完成后展示结果
async function pollSyncProgress(statusEl, progressFill, progressText) {
  for (let i = 0; i < 750; i++) {
    await new Promise((r) => setTimeout(r, 800));
    let s;
    try {
      s = await (await fetchTimeout(API.syncStatus, {}, 15000)).json();
    } catch (e) { continue; }
    const p = s.progress || {};
    if (p.total > 0 && p.done >= 0) {
      const pct = Math.min(100, Math.round((p.done / p.total) * 100));
      progressFill.style.width = pct + '%';
      progressText.textContent = `同步中 ${pct}%（${p.done}/${p.total}）${p.msg ? ' · ' + p.msg : ''}`;
    }
    if (!p.active) {
      if (p.error) {
        statusEl.textContent = `❌ 同步失败：${p.error}`;
        statusEl.className = 'src-status src-fail';
      } else if (p.cancelled) {
        statusEl.textContent = '⏹ 已中断同步，本地数据未更新';
        statusEl.className = 'src-status src-fail';
      } else {
        const { synced = 0, failed = 0, empty = 0 } = p;
        if (synced > 0) {
          statusEl.textContent = `✅ 同步完成：${synced} 项写入本地，请点击「开始筛选」`;
          statusEl.className = 'src-status src-ok';
        } else if (empty > 0) {
          statusEl.textContent = `⚠️ 同步完成，但 ${empty} 项未获取到数据（数据源无返回）。可切换「数据服务器」后重试`;
          statusEl.className = 'src-status src-fail';
        } else if (failed > 0) {
          statusEl.textContent = `⚠️ 同步完成：${failed} 项失败`;
          statusEl.className = 'src-status src-fail';
        } else {
          statusEl.textContent = 'ℹ️ 本地数据已是最新，无需更新';
          statusEl.className = 'src-status src-ok';
        }
      }
      // 同步完成后刷新同步时间，筛选由用户点击「开始筛选」触发
      await refreshLocalStatus();
      return;
    }
  }
  statusEl.textContent = '❌ 同步超时，请查看日志后重试';
  statusEl.className = 'src-status src-fail';
}

async function onServerCancel() {
  if (!state.serverSyncing) return;
  const cancelBtn = document.getElementById('serverCancel');
  if (cancelBtn) { cancelBtn.disabled = true; cancelBtn.textContent = '正在中断…'; }
  try {
    await fetch(API.cancelSync, { method: 'POST' });
  } catch (e) { /* 即使通知失败，同步接口也会因超时/网络自行结束 */ }
  // 不在此处复位状态：等待 onServerConnect 收到 cancelled 结果后统一恢复控件
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
      const cost = h.elapsed_ms != null ? `<span class="hi-cost">⏱ ${formatMs(h.elapsed_ms)}</span>` : '';
      const selected = (state.viewingHistory && state.viewingHistory.id === h.id) ? ' selected' : '';
      return `<div class="history-item${selected}" data-id="${h.id}" title="点击加载该结果">
        <input type="checkbox" class="hi-check" data-id="${h.id}">
        <span class="hi-time">${h.ts}</span>
        <span class="hi-meta">${tf} · ${mk} · 命中 <b>${h.matched_rows}</b> 条</span>
        ${cost}
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
    // 单条删除（先确认再删）
    box.querySelectorAll('.hi-del').forEach((el) => {
      el.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('确定要删除该记录吗？')) return;
        const r = await fetch(API.historyItem(el.dataset.del), { method: 'DELETE' });
        const d = await r.json().catch(() => ({}));
        if (d.deleted === false) { alert('删除失败，请重试'); }
        resetIfDeletedViewing([el.dataset.del]);   // 删除当前查看的记录则清空结果区
        loadHistory();
      });
    });
    // 全选
    checkAll.onchange = () => {
      box.querySelectorAll('.hi-check').forEach((cb) => { cb.checked = checkAll.checked; });
    };
    // 批量删除（先确认再删）
    document.getElementById('historyBatchDel').onclick = async () => {
      const ids = [...box.querySelectorAll('.hi-check:checked')].map((cb) => cb.dataset.id);
      if (!ids.length) { alert('请先勾选要删除的记录'); return; }
      if (!confirm(`确定要删除选中的 ${ids.length} 条记录吗？`)) return;
      const r = await fetch(API.history + '/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      });
      const d = await r.json().catch(() => ({}));
      if (d.deleted !== ids.length) { alert(`删除完成：${d.deleted}/${ids.length} 条`); }
      checkAll.checked = false;
      resetIfDeletedViewing(ids);   // 批量删除含当前查看记录则清空结果区
      loadHistory();
    };
  } catch (e) { /* 忽略 */ }
}

// 删除历史记录后，若删除了当前正在查看的记录，则清空结果区并恢复初始状态
function resetIfDeletedViewing(ids) {
  if (state.viewingHistory && ids.includes(state.viewingHistory.id)) {
    clearResult();
  }
}

async function loadHistoryItem(id) {
  try {
    const r = await fetch(API.historyItem(id));
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    state.results = d.results || [];
    state.scanStats = d.stats || null;
    state.lastParams = d.params || null;
    state.viewingHistory = { id, ts: d.ts };
    state.page = 1;
    // 历史数据视图：隐藏「数据来源」选择项，避免误操作
    setDataSourceVisible(false);
    // 高亮选中的历史记录项（标识当前操作对象）
    document.querySelectorAll('.history-item').forEach((el) => {
      el.classList.toggle('selected', el.dataset.id === id);
    });
    // 基于历史记录继续筛选：仅保留已用条件维度（回填原值可调整），隐藏未用维度
    applyLockedParams(d.params || {}, d.ts || '');
    renderResults();
    updateResultButtons();
    // 统计栏提示当前查看的是历史结果
    const statsEl = document.getElementById('stats');
    if (statsEl) {
      statsEl.innerHTML = `📜 已加载历史结果 <b>${d.ts || ''}</b> · 命中 <b>${state.results.length}</b> 条　<a href="#" id="backToEmpty" style="color:var(--accent)">返回</a>`;
      document.getElementById('backToEmpty').addEventListener('click', (e) => { e.preventDefault(); clearResult(); });
    }
    // 切回形态筛选页（若当前在其它 Tab）
    switchTab('screener');
  } catch (e) {
    alert('加载历史结果失败');
  }
}

// ===================== 筛选条件精简（基于历史记录继续筛选） =====================
// 原则：仅保留历史记录中「已使用」的条件维度（回填原值，可调整），
//       未使用过的维度隐藏（可展开），避免展示无关条件造成干扰。
function applyLockedParams(params, source) {
  state.lockedParams = params;
  state.lockSource = source;
  state.showAllDims = false;

  // 时间级别：已用则回填可调，未用则隐藏
  const tfUsed = (params.timeframes || []).length > 0;
  markDim('panelTimeframe', tfUsed);
  if (tfUsed) {
    const tfSel = new Set(params.timeframes || []);
    document.querySelectorAll('#timeframeChips .chip').forEach((chip) => {
      chip.classList.toggle('active', tfSel.has(chip.dataset.key));
      chip.classList.remove('locked');
    });
  }

  // 市场：已用则回填可调，未用则隐藏
  const mkUsed = (params.markets || []).length > 0;
  markDim('panelMarket', mkUsed);
  if (mkUsed) {
    const mkSel = new Set(params.markets || []);
    document.querySelectorAll('#marketChips .chip').forEach((chip) => {
      chip.classList.toggle('active', mkSel.has(chip.dataset.key));
      chip.classList.remove('locked');
    });
  }

  // 形态：已用则回填可调，未用则隐藏
  const patUsed = !!(params.patterns && params.patterns.length);
  markDim('panelPattern', patUsed);
  if (patUsed) {
    const patSel = new Set(params.patterns || []);
    document.querySelectorAll('#patternList .pat-main input[type=checkbox]').forEach((cb) => {
      cb.checked = patSel.has(cb.dataset.key);
      cb.disabled = false;
    });
    const verifySel = new Set(params.verify_patterns || []);
    document.querySelectorAll('#patternList .verify-on').forEach((cb) => {
      cb.checked = verifySel.has(cb.dataset.key);
      cb.disabled = false;
    });
    const pats = params.patterns || [];
    const hasBull = pats.some((k) => (state.meta.patterns.find((p) => p.key === k) || {}).direction === 'bullish');
    const hasBear = pats.some((k) => (state.meta.patterns.find((p) => p.key === k) || {}).direction === 'bearish');
    const dirRadio = document.querySelector(`input[name="patternDir"][value="${hasBear && !hasBull ? 'bearish' : 'bullish'}"]`);
    if (dirRadio) dirRadio.checked = true;
    if (_updateDirectionExclusion) _updateDirectionExclusion();
  }

  // 附加条件：逐个字段判断「已用/未用」，已用回填可调，未用隐藏
  const extraUsed = {
    above_ma250: !!params.above_ma250,
    limit_up_count_min: params.limit_up_count_min != null,
    volume_min: params.volume_min != null,
    price: (params.price_min != null || params.price_max != null),
    change: (params.change_min != null || params.change_max != null),
    exclude_st: params.exclude_st === false,   // 仅「主动取消剔除 ST」算已用
  };
  document.querySelectorAll('.extra-item[data-extra]').forEach((item) => {
    const used = !!extraUsed[item.dataset.extra];
    item.classList.toggle('hidden', !used);
    item.dataset.dimHidden = used ? 'false' : 'true';
  });
  // 回填附加条件值（可调整，不锁定）
  document.getElementById('aboveMa250').checked = !!params.above_ma250;
  document.getElementById('aboveMa250').disabled = false;
  const numBack = (id, v) => { const el = document.getElementById(id); if (el) { el.value = (v != null) ? v : ''; el.disabled = false; } };
  numBack('limitUpCountMin', params.limit_up_count_min);
  numBack('volumeMin', params.volume_min);
  numBack('priceMin', params.price_min);
  numBack('priceMax', params.price_max);
  numBack('changeMin', params.change_min);
  numBack('changeMax', params.change_max);
  document.getElementById('excludeSt').checked = params.exclude_st !== false;
  document.getElementById('excludeSt').disabled = false;

  // 「附加筛选条件」面板：所有子项都未用时隐藏整个面板
  const extraPanel = document.getElementById('panelExtra');
  const anyExtraVisible = [...extraPanel.querySelectorAll('.extra-item')].some((el) => !el.classList.contains('hidden'));
  extraPanel.classList.toggle('hidden', !anyExtraVisible);
  extraPanel.dataset.dimHidden = anyExtraVisible ? 'false' : 'true';

  showLockBar(source);
  renderLockBar();
}

// 标记某个维度面板是否「已用」：已用显示，未用隐藏（记 data-dim-hidden 供展开用）
function markDim(id, used) {
  const panel = document.getElementById(id);
  if (!panel) return;
  panel.classList.toggle('hidden', !used);
  panel.dataset.dimHidden = used ? 'false' : 'true';
}

// 展开/收起所有未用维度
function toggleAllDims() {
  state.showAllDims = !state.showAllDims;
  document.querySelectorAll('[data-dim-hidden="true"]').forEach((el) => {
    el.classList.toggle('hidden', !state.showAllDims);
  });
  renderLockBar();
}

// 渲染锁定提示条（含展开/解除入口）
function renderLockBar() {
  const bar = document.getElementById('lockBar');
  if (!bar) return;
  const expanded = state.showAllDims;
  bar.innerHTML = `📌 已按历史条件精简维度 <b>${state.lockSource}</b>（已用条件可调整）
    <a href="#" id="toggleAllDims">${expanded ? '收起条件' : '＋ 展开全部条件'}</a>
    <a href="#" id="unlockBtn">解除锁定</a>`;
  document.getElementById('toggleAllDims').addEventListener('click', (e) => { e.preventDefault(); toggleAllDims(); });
  document.getElementById('unlockBtn').addEventListener('click', (e) => { e.preventDefault(); unlockParams(); });
}

function unlockParams() {
  state.lockedParams = null;
  state.lockSource = null;
  state.showAllDims = false;
  // 恢复所有维度显示（移除 hidden 与 data-dim-hidden）
  document.querySelectorAll('[data-dim-hidden]').forEach((el) => {
    el.classList.remove('hidden');
    delete el.dataset.dimHidden;
  });
  document.querySelectorAll('.chip.locked').forEach((c) => c.classList.remove('locked'));
  document.querySelectorAll('#patternList input[type=checkbox]').forEach((cb) => { cb.disabled = false; });
  ['limitUpCountMin', 'volumeMin', 'priceMin', 'priceMax', 'changeMin', 'changeMax',
   'aboveMa250', 'excludeSt'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = false;
  });
  // 恢复单选按钮为「看涨」并重新应用隐藏逻辑
  const bullRadio = document.querySelector('input[name="patternDir"][value="bullish"]');
  if (bullRadio) bullRadio.checked = true;
  if (_updateDirectionExclusion) _updateDirectionExclusion();
  // 恢复「开始筛选」入口可用
  document.getElementById('scanBtn').disabled = false;
  hideLockBar();
}

function showLockBar(source) {
  // 仅负责创建锁定提示条元素，具体内容与绑定由 renderLockBar 统一处理
  let bar = document.getElementById('lockBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'lockBar';
    bar.className = 'lock-bar';
    const sidebar = document.querySelector('.sidebar');
    sidebar.insertBefore(bar, sidebar.firstChild);
  }
}

function hideLockBar() {
  const bar = document.getElementById('lockBar');
  if (bar) bar.remove();
}

// ===================== 结果渲染（含分页/统计） =====================
function renderResults() {
  setTableColumns('full');   // 筛选结果视图：恢复完整表头列
  let list = [...state.results];
  if (state.resonanceOnly) list = list.filter((r) => r.resonance);

  // 排序（所有列通用）
  const SORT_FIELD = {
    code: (r) => r.code,
    name: (r) => r.name,
    market: (r) => r.market_zh || '',
    timeframe: (r) => r.timeframe,
    pattern: (r) => r.pattern_zh,
    strength: (r) => r.strength,
    volume_ratio: (r) => r.volume_ratio,
    close: (r) => r.close,
    ytd_change: (r) => r.ytd_change || 0,
    limit_1y: (r) => r.limit_1y || 0,
    resonance: (r) => (r.resonance ? 1 : 0),
  };
  const get = SORT_FIELD[state.sortKey] || SORT_FIELD.strength;
  list.sort((a, b) => {
    const va = get(a), vb = get(b);
    if (typeof va === 'number' && typeof vb === 'number') {
      return state.sortDesc ? vb - va : va - vb;
    }
    const sa = String(va), sb = String(vb);
    return state.sortDesc ? sb.localeCompare(sa) : sa.localeCompare(sb);
  });
  // 更新表头排序箭头
  document.querySelectorAll('th.sortable').forEach((th) => {
    const arrow = th.querySelector('.sort-arrow');
    if (th.dataset.key === state.sortKey) {
      th.classList.add('sorted');
      if (arrow) arrow.textContent = state.sortDesc ? '▾' : '▴';
    } else {
      th.classList.remove('sorted');
      if (arrow) arrow.textContent = '';
    }
  });

  renderStats();

  // 分页
  const total = list.length;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > totalPages) state.page = totalPages;
  const start = (state.page - 1) * state.pageSize;
  const pageList = list.slice(start, start + state.pageSize);

  const tbody = document.getElementById('resultBody');
  const emptyState = document.getElementById('emptyState');
  const table = document.getElementById('resultTable');
  if (!total) {
    // 空结果状态：显示「暂无结果」提示界面，隐藏表格
    emptyState.classList.remove('hidden');
    table.classList.add('hidden');
    tbody.innerHTML = '';
    updatePagination(0, 1, 1);
    return;
  }

  emptyState.classList.add('hidden');
  table.classList.remove('hidden');

  tbody.innerHTML = pageList.map((r) => {
    const ytdCls = (r.ytd_change || 0) >= 0 ? 'num-up' : 'num-down';
    const ytd = r.ytd_change != null ? `${r.ytd_change >= 0 ? '+' : ''}${r.ytd_change}%` : '—';
    const resonanceTag = r.resonance
      ? `<span class="tag tag-resonance">共振·${r.resonance_levels.map(lvTf).join('/')}</span>`
      : '<span style="color:var(--text-faint)">—</span>';
    return `<tr data-code="${r.code}" data-tf="${r.timeframe}">
      <td class="cell-code">${r.code}</td>
      <td>${r.name}</td>
      <td><span class="tag tag-tf">${r.market_zh || '—'}</span></td>
      <td><span class="tag tag-tf">${r.timeframe_zh}</span></td>
      <td>${r.pattern_zh}</td>
      <td class="strength-cell">${r.strength}</td>
      <td>${r.volume_ratio}×</td>
      <td>${r.close.toFixed(2)}</td>
      <td class="${ytdCls}">${ytd}</td>
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
const EVENT_TITLES = { zt: '涨停板', dt: '跌停板', ladder: '连板天梯', lhb: '龙虎榜', hotspot: '题材热点', news: '每日新闻', market: '市场分析' };
const SUB_TABS = {
  zt: [
    { key: 'board', zh: '封板涨停' },
    { key: 'opened', zh: '涨停打开' },
  ],
  dt: [
    { key: 'board', zh: '封板跌停' },
    { key: 'opened', zh: '跌停打开' },
  ],
  ladder: [{ key: 'up', zh: '涨停连板' }, { key: 'down', zh: '跌停连板' }],
};

function switchTab(tab) {
  state.eventTab = tab;
  state.eventSub = null;
  document.querySelectorAll('#mainTabs .tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === tab));
  const isScreener = tab === 'screener';
  const isReport = tab === 'report';
  document.getElementById('panel-screener').classList.toggle('active', isScreener);
  document.getElementById('panel-report').classList.toggle('active', isReport);
  document.getElementById('eventPanel').classList.toggle('hidden', isScreener || isReport);
  if (isReport) {
    // 已有代码自动查询，否则聚焦输入框
    const inp = document.getElementById('reportCode');
    if (inp.value.trim()) queryReport();
    else inp.focus();
  } else if (!isScreener) {
    loadEvent(tab);
  }
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

function toggleSidebar() {
  const layout = document.querySelector('.layout');
  if (!layout) return;
  const collapsed = layout.classList.toggle('sidebar-collapsed');
  const btn = document.getElementById('sidebarToggle');
  if (btn) btn.textContent = collapsed ? '⏵ 展开筛选栏' : '⏴ 收起筛选栏';
  try { localStorage.setItem('candle_sidebar_collapsed', collapsed ? '1' : '0'); } catch (e) { /* 忽略 */ }
}

function initSidebarCollapse() {
  // 恢复上次折叠状态（折叠时侧栏隐藏，主体自适应占满）
  try {
    if (localStorage.getItem('candle_sidebar_collapsed') === '1') {
      document.querySelector('.layout').classList.add('sidebar-collapsed');
      const btn = document.getElementById('sidebarToggle');
      if (btn) btn.textContent = '⏵ 展开筛选栏';
    }
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
    // 涨停/跌停：标题旁内联展示今日/昨日封板率统计（随行情实时更新）
    if (tab === 'zt' || tab === 'dt') {
      const dir = tab === 'zt' ? 'up' : 'down';
      try {
        renderTitleSealRate(dir, await (await fetchTimeout(API.sealRate(dir))).json());
      } catch (e) { clearTitleSealRate(); }
    } else {
      clearTitleSealRate();
    }
    if (tab === 'zt') {
      if (sub === 'opened') renderOpened('up', await (await fetchTimeout(API.opened('up'))).json());
      else renderBoard('zt', await (await fetchTimeout(API.board('zt', date))).json());
    } else if (tab === 'dt') {
      if (sub === 'opened') renderOpened('down', await (await fetchTimeout(API.opened('down'))).json());
      else renderBoard('dt', await (await fetchTimeout(API.board('dt', date))).json());
    } else if (tab === 'ladder') {
      if (sub === 'down') renderLadder(await (await fetchTimeout(API.ladderDown())).json(), true);
      else renderLadder(await (await fetchTimeout(API.ladder(date))).json(), false);
    } else if (tab === 'lhb') {
      renderDragonTiger(await (await fetchTimeout(API.dragonTiger(date))).json());
    } else if (tab === 'hotspot') {
      renderHotspot(await (await fetchTimeout(API.hotspot(date))).json());
    } else if (tab === 'news') {
      renderDailyNews(await (await fetchTimeout(API.dailyNews)).json());
    } else if (tab === 'market') {
      renderMarket(await (await fetchTimeout(API.marketOverview)).json());
    }
  } catch (e) {
    console.error(e);
    // 明确错误/空状态，避免一直「加载中」
    const msg = (e && e.name === 'AbortError') ? '⏱ 加载超时，请稍后重试' : '⚠️ 加载失败，请检查网络';
    document.getElementById('eventStats').textContent = msg;
    document.getElementById('eventContent').innerHTML =
      `<div class="event-empty" style="padding:60px;text-align:center;color:var(--text-faint)">${msg}</div>`;
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
      (await fetch(API.dragonTigerHistory(code, 180))).json(),   // 最近 6 个月上榜明细
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
      return recRows || '<tr><td colspan="5" style="color:var(--text-faint)">近6个月无上榜记录</td></tr>';
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
          <h4 style="margin:0">近6个月上榜明细（${h.count} 次）</h4>
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

// ===================== 个股研报 =====================
async function queryReport() {
  const val = document.getElementById('reportCode').value.trim();
  if (!val) { alert('请输入股票名称或 6 位代码，如：贵州茅台 / 600519'); return; }
  const meta = document.getElementById('reportMeta');
  const list = document.getElementById('reportList');
  // 6 位纯数字 → 直接按代码查询
  if (/^\d{6}$/.test(val)) {
    hideReportCand();
    return queryReportByCode(val);
  }
  // 名称/模糊 → 先搜索匹配股票
  meta.textContent = `正在搜索「${val}」…`;
  list.innerHTML = '';
  try {
    const r = await fetchTimeout(API.reportSearch(encodeURIComponent(val)), {}, 15000);
    const d = await r.json();
    const results = d.results || [];
    if (!results.length) {
      meta.innerHTML = '<span style="color:var(--text-dim)">未找到与「' + val + '」匹配的股票，请检查名称或代码</span>';
      return;
    }
    if (results.length === 1) {
      document.getElementById('reportCode').value = results[0].code;
      hideReportCand();
      return queryReportByCode(results[0].code, results[0].name);
    }
    showReportCand(results);   // 多个匹配 → 候选列表供选择
    meta.textContent = `找到 ${results.length} 只匹配股票，请选择：`;
  } catch (e) {
    meta.textContent = '❌ 搜索失败，请检查网络后重试';
  }
}

async function queryReportByCode(code, name) {
  const meta = document.getElementById('reportMeta');
  const list = document.getElementById('reportList');
  meta.textContent = `正在查询 ${code} 的研报…`;
  list.innerHTML = '';
  try {
    const r = await fetchTimeout(API.report(code), {}, 30000);
    const d = await r.json();
    if (d.error) { meta.textContent = `❌ ${d.error}`; return; }
    meta.innerHTML = d.count > 0
      ? `📑 <b>${d.name || name || d.code}</b>（${d.code}）最近一年研报 <b>${d.count}</b> 篇，点击条目可展开详情`
      : `📑 <b>${d.name || name || d.code}</b>（${d.code}）最近一年暂无研报`;
    renderReportList(list, d.reports || []);
  } catch (e) {
    meta.textContent = (e && e.name === 'AbortError') ? '❌ 查询超时，请稍后重试' : '❌ 查询失败，请检查网络后重试';
  }
}

// 名称搜索候选：显示匹配股票列表
function showReportCand(results) {
  const box = document.getElementById('reportCand');
  if (!box) return;
  box.innerHTML = results.map((r) =>
    `<div class="report-cand" data-code="${r.code}">${r.code}　${r.name || ''}</div>`).join('');
  box.classList.remove('hidden');
  box.querySelectorAll('.report-cand').forEach((c) => {
    c.addEventListener('click', () => {
      document.getElementById('reportCode').value = c.dataset.code;
      hideReportCand();
      queryReportByCode(c.dataset.code);
    });
  });
}

function hideReportCand() {
  const box = document.getElementById('reportCand');
  if (box) { box.classList.add('hidden'); box.innerHTML = ''; }
}

function renderReportList(container, reports) {
  if (!reports.length) {
    container.innerHTML = '<div class="report-empty">📭 最近一年没有研报记录<br><span style="font-size:12px;color:var(--text-faint)">可尝试搜索其他股票</span></div>';
    return;
  }
  container.innerHTML = reports.map((r) => `
    <div class="report-item" title="点击展开详情">
      <div class="report-head">
        <span class="report-date">${r.date}</span>
        <span class="report-rating">${r.rating || '—'}${r.rating_change && r.rating_change !== '-' ? `<em class="rating-change">（${r.rating_change}）</em>` : ''}</span>
      </div>
      <div class="report-title">${r.title}</div>
      <div class="report-foot">
        <span>🏢 ${r.org || '—'}</span>
        ${r.author ? `<span>👤 ${r.author}</span>` : ''}
        ${r.industry ? `<span>📂 ${r.industry}</span>` : ''}
        ${r.pdf_url ? `<a href="${r.pdf_url}" target="_blank" rel="noopener" class="report-pdf">📄 查看 PDF</a>` : ''}
      </div>
      <div class="report-detail hidden">
        ${r.target_price != null
          ? `<div class="rd-row">🎯 目标价：<b class="num-up">${r.target_price}</b>${r.target_low != null ? `<span class="rd-sub">（区间 ${r.target_low} ~ ${r.target_price}）</span>` : ''}</div>` : ''}
        ${r.eps_this != null
          ? `<div class="rd-row">📈 EPS 预测：今年 <b>${r.eps_this}</b>${r.eps_next != null ? ` ／ 明年 <b>${r.eps_next}</b>` : ''}${r.eps_next2 != null ? ` ／ 后年 <b>${r.eps_next2}</b>` : ''}</div>` : ''}
        ${r.stock_name ? `<div class="rd-row">🏷 标的：${r.stock_name}</div>` : ''}
      </div>
    </div>`).join('');
  // 点击条目展开/收起详情
  container.querySelectorAll('.report-item').forEach((item) => {
    item.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      const dt = item.querySelector('.report-detail');
      if (dt) dt.classList.toggle('hidden');
    });
  });
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

function renderDailyNews(d) {
  const news = d.news || [];
  document.getElementById('eventStats').innerHTML =
    `每日新闻 <b>${d.date}</b>（全天 00:00~23:59）· 共 <b>${d.count}</b> 条（★ 为重点）`;

  // 按时间段归并：盘前 / 盘中 / 盘后
  const bucket = (time) => {
    const hm = (time || '').slice(11, 16);   // "HH:MM"
    if (hm < '09:30') return 'pre';          // 盘前
    if (hm <= '15:00') return 'intraday';    // 盘中（含午间）
    return 'post';                           // 盘后
  };
  const GROUPS = [
    { key: 'pre', zh: '盘前（00:00–09:29）' },
    { key: 'intraday', zh: '盘中（09:30–15:00）' },
    { key: 'post', zh: '盘后（15:00–23:59）' },
  ];
  const grouped = { pre: [], intraday: [], post: [] };
  news.forEach((n) => grouped[bucket(n.time)] && grouped[bucket(n.time)].push(n));

  const itemHtml = (n) => {
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
  };
  const html = GROUPS.map((g) => {
    const list = grouped[g.key] || [];
    if (!list.length) return '';
    return `<div class="news-group">
      <div class="news-group-head">${g.zh} · ${list.length} 条</div>
      ${list.map(itemHtml).join('')}
    </div>`;
  }).join('');

  document.getElementById('eventContent').innerHTML =
    html || '<div style="padding:40px;color:var(--text-faint);text-align:center">暂无当日新闻</div>';
  document.querySelectorAll('#eventContent .news-stock[data-code]').forEach((el) => {
    el.addEventListener('click', (e) => { e.stopPropagation(); openKline(el.dataset.code, 'daily'); });
  });
}

// ===================== 涨停/跌停 封板率（标题旁内联）/ 打开 =====================
function renderTitleSealRate(dir, d) {
  const el = document.getElementById('eventTitleStats');
  if (!el) return;
  const kw = dir === 'up' ? '涨停' : '跌停';
  const fmt = (s) => {
    const t = s || {};
    return `今日${kw}数${t.board_count ?? 0}，${kw}打开${t.opened_count ?? 0}，封板率${t.seal_rate != null ? t.seal_rate + '%' : '—'}`;
  };
  const today = d.today || {}, yesterday = d.yesterday || {};
  el.innerHTML =
    `<div class="ts-line">${fmt(today)}</div>`
    + `<div class="ts-line">昨日${kw}数${yesterday.board_count ?? 0}，${kw}打开${yesterday.opened_count ?? 0}，封板率${yesterday.seal_rate != null ? yesterday.seal_rate + '%' : '—'}</div>`
    + `<div class="ts-formula">封板率=封板${kw}数÷(封板${kw}数+${kw}打开数)，随行情实时更新</div>`;
}

function clearTitleSealRate() {
  const el = document.getElementById('eventTitleStats');
  if (el) el.innerHTML = '';
}

function renderOpened(dir, d) {
  const kw = dir === 'up' ? '涨停打开' : '跌停打开';
  const rowsOf = (s) => (s && s.stocks || []).map((r) => {
    const chgCls = r.change_pct >= 0 ? 'num-up' : 'num-down';
    return `<tr class="clickable" data-code="${r.code}">
      <td class="cell-code">${r.code}</td><td>${r.name}</td><td>${r.market_zh}</td>
      <td class="${chgCls}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct}%</td><td>${r.close}</td></tr>`;
  }).join('');
  const section = (label, s) => {
    const rows = rowsOf(s);
    const empty = '<tr><td colspan="5" style="text-align:center;color:var(--text-faint);padding:30px">当日无' + kw + '</td></tr>';
    return `<div class="opened-section">
      <div class="opened-head">${label}${kw} · <b>${s ? s.date : ''}</b>（${s ? s.count : 0} 只）</div>
      <table class="event-table"><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>涨跌幅</th><th>收盘价</th></tr></thead><tbody>${rows || empty}</tbody></table>
    </div>`;
  };
  document.getElementById('eventStats').innerHTML = `${kw} = 盘中触及${dir === 'up' ? '涨停' : '跌停'}但收盘未封住`;
  document.getElementById('eventContent').innerHTML =
    section('今日', d.today) + section('昨日', d.yesterday);
  document.querySelectorAll('#eventContent tr[data-code]').forEach((tr) => {
    tr.addEventListener('click', () => openKline(tr.dataset.code, 'daily'));
  });
}

// ===================== 市场分析 =====================
function renderMarket(d) {
  const fmtWan = (v) => (v == null ? '—' : (v >= 1e4 ? (v / 1e4).toFixed(2) + '亿' : v.toFixed(0) + '万'));
  const fmtHand = (v) => (v == null ? '—' : (v >= 1e4 ? (v / 1e4).toFixed(2) + '亿手' : v.toFixed(0) + '手'));
  const fmtYuan = (v) => (v == null ? '—' : (v >= 1e8 ? (v / 1e8).toFixed(2) + '亿' : (v / 1e4).toFixed(0) + '万'));
  const cards = (d.indices || []).map((ix) => {
    const up = ix.change_pct >= 0;
    const cls = up ? 'num-up' : 'num-down';
    const sign = up ? '+' : '';
    const volChg = (ix.volume_today != null && ix.volume_yesterday)
      ? ((ix.volume_today - ix.volume_yesterday) / ix.volume_yesterday * 100) : null;
    return `<div class="idx-card">
      <div class="idx-head"><span class="idx-name">${ix.name}</span><span class="idx-code">${ix.code}</span></div>
      <div class="idx-price ${cls}">${ix.price.toFixed(2)}</div>
      <div class="idx-chg ${cls}">${sign}${ix.change.toFixed(2)}　${sign}${ix.change_pct.toFixed(2)}%</div>
      <div class="idx-meta">
        <div><span>今开</span><b>${ix.open.toFixed(2)}</b></div>
        <div><span>最高</span><b>${ix.high.toFixed(2)}</b></div>
        <div><span>最低</span><b>${ix.low.toFixed(2)}</b></div>
        <div><span>昨收</span><b>${ix.pre_close.toFixed(2)}</b></div>
        <div><span>成交量(今)</span><b>${fmtHand(ix.volume_today)}</b></div>
        <div><span>成交量(昨)</span><b>${fmtHand(ix.volume_yesterday)}</b></div>
        <div><span>量比</span><b class="${volChg != null && volChg > 0 ? 'num-up' : 'num-down'}">${volChg != null ? (volChg > 0 ? '+' : '') + volChg.toFixed(1) + '%' : '—'}</b></div>
        <div><span>成交额</span><b>${fmtWan(ix.amount_today_wan)}</b></div>
      </div>
    </div>`;
  }).join('');
  const flowRows = (d.fund_flow || []).map((f) => {
    const netCls = (v) => (v >= 0 ? 'num-up' : 'num-down');
    return `<tr><td>${f.date}</td>
      <td class="${netCls(f.main_net)}">${fmtYuan(f.main_net)}</td>
      <td class="${netCls(f.super_net)}">${fmtYuan(f.super_net)}</td>
      <td class="${netCls(f.big_net)}">${fmtYuan(f.big_net)}</td>
      <td class="${netCls(f.medium_net)}">${fmtYuan(f.medium_net)}</td>
      <td class="${netCls(f.small_net)}">${fmtYuan(f.small_net)}</td>
      <td class="${netCls(f.main_net_pct)}">${f.main_net_pct.toFixed(2)}%</td></tr>`;
  }).join('');
  document.getElementById('eventStats').innerHTML = `更新于 ${d.updated || '—'}`;
  document.getElementById('eventContent').innerHTML = `
    <div class="market-kline">
      <div class="kline-toolbar">
        <div class="kline-idx-chips" id="klineIdxChips">
          ${INDEXES.map(([sym, nm]) =>
            `<span class="kline-chip ${sym === state.marketIdx ? 'active' : ''}" data-sym="${sym}">${nm}</span>`).join('')}
        </div>
        <div class="kline-tf-switch">
          ${['day', 'week', 'month'].map((tf) =>
            `<button class="tf-btn ${tf === state.marketTf ? 'active' : ''}" data-tf="${tf}">${{ day: '日K', week: '周K', month: '月K' }[tf]}</button>`).join('')}
        </div>
      </div>
      <div class="kline-chart" id="indexKlineChart">加载中…</div>
    </div>
    <div class="market-toolbar">
      <button class="ghost-btn" id="marketReportBtn">📄 生成市场分析报告</button>
    </div>
    <div class="idx-grid">${cards || '<div style="padding:40px;color:var(--text-faint);text-align:center">暂无指数数据</div>'}</div>
    <div class="flow-section">
      <div class="flow-head">上证指数 · 资金流向</div>
      <table class="event-table"><thead><tr><th>日期</th><th>主力净流入</th><th>超大单</th><th>大单</th><th>中单</th><th>小单</th><th>主力净占比</th></tr></thead><tbody>${flowRows || '<tr><td colspan="7" style="text-align:center;color:var(--text-faint);padding:30px">暂无资金流向数据</td></tr>'}</tbody></table>
    </div>`;
  const rb = document.getElementById('marketReportBtn');
  if (rb) rb.addEventListener('click', () => buildMarketReport(d));
  // K 线图：指数选择 + 级别切换 + 渲染
  bindKlineToolbar();
  renderIndexKline(state.marketIdx, state.marketTf);
}

// 关注指数（与后端 _INDICES 一致）
const INDEXES = [
  ['sh000001', '上证指数'], ['sz399001', '深证成指'], ['sz399006', '创业板指'],
  ['sh000688', '科创50'], ['bj899050', '北证50'], ['sh000300', '沪深300'],
  ['sh000016', '上证50'], ['sh000852', '中证1000'],
];

function bindKlineToolbar() {
  document.querySelectorAll('#klineIdxChips .kline-chip').forEach((c) => {
    c.addEventListener('click', () => {
      state.marketIdx = c.dataset.sym;
      document.querySelectorAll('#klineIdxChips .kline-chip').forEach((x) => x.classList.toggle('active', x === c));
      renderIndexKline(state.marketIdx, state.marketTf);
    });
  });
  document.querySelectorAll('.kline-tf-switch .tf-btn').forEach((b) => {
    b.addEventListener('click', () => {
      state.marketTf = b.dataset.tf;
      document.querySelectorAll('.kline-tf-switch .tf-btn').forEach((x) => x.classList.toggle('active', x === b));
      renderIndexKline(state.marketIdx, state.marketTf);
    });
  });
}

// 指数 K 线图（日/周/月 + 成交量）
async function renderIndexKline(symbol, tf) {
  const el = document.getElementById('indexKlineChart');
  if (!el) return;
  el.style.height = '440px';
  el.innerHTML = '<div class="kline-empty">加载中…</div>';
  try {
    const r = await fetchTimeout(API.marketKline(symbol, tf), {}, 20000);
    const d = await r.json();
    if (d.error || !d.kline || !d.kline.length) {
      const tfZh = { day: '日', week: '周', month: '月' }[tf] || '';
      el.innerHTML = `<div class="kline-empty">暂无 ${d.name || symbol} 的${tfZh}K 数据</div>`;
      return;
    }
    drawIndexKline(el, d);
  } catch (e) {
    el.innerHTML = '<div class="kline-empty">⏱ 加载失败或超时，请稍后重试</div>';
  }
}

function drawIndexKline(el, d) {
  if (!window.echarts) { el.innerHTML = '<div class="kline-empty">图表组件加载失败</div>'; return; }
  if (state.marketChart) { state.marketChart.dispose(); state.marketChart = null; }
  const chart = echarts.init(el);
  state.marketChart = chart;
  const dates = d.kline.map((k) => k[0]);
  const kdata = d.kline.map((k) => [k[1], k[2], k[3], k[4]]);   // [open, close, low, high]
  const vols = d.volume.map((v) => ({
    value: v[1],
    itemStyle: { color: v[2] >= 0 ? '#f23645' : '#26a69a' },   // 涨红跌绿（A股）
  }));
  chart.setOption({
    animation: false,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'cross' },
      backgroundColor: '#1f2430', borderColor: '#333', textStyle: { color: '#ddd', fontSize: 12 },
      formatter: (ps) => {
        const i = ps[0].dataIndex;
        const k = d.kline[i];
        const v = d.volume[i];
        const cls = (c) => (c >= 0 ? '#f23645' : '#26a69a');
        const chg = ((k[2] - k[1]) / k[1] * 100).toFixed(2);
        return `<b>${k[0]}</b><br/>开 ${k[1].toFixed(2)}　收 ${k[2].toFixed(2)}<br/>
          高 ${k[3].toFixed(2)}　低 ${k[4].toFixed(2)}<br/>
          涨跌 <span style="color:${cls(k[2] - k[1])}">${k[2] >= k[1] ? '+' : ''}${chg}%</span><br/>
          成交量 ${v ? (v[1] / 1e8).toFixed(2) + '亿手' : '—'}`;
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#777' } },
    grid: [
      { left: 64, right: 24, top: 24, height: '56%' },
      { left: 64, right: 24, top: '70%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
        axisLine: { lineStyle: { color: '#3a3f4b' } }, axisLabel: { color: '#999', fontSize: 11 } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#3a3f4b' } } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#262b36' } },
        axisLabel: { color: '#999', fontSize: 11 } },
      { gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 30, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], top: '90%', height: 14,
        start: 30, end: 100, borderColor: '#333', backgroundColor: '#1a1f2b',
        fillerColor: 'rgba(59,130,246,.15)', textStyle: { color: '#999', fontSize: 10 } },
    ],
    series: [
      {
        name: d.name, type: 'candlestick', data: kdata,
        itemStyle: { color: '#f23645', color0: '#26a69a', borderColor: '#f23645', borderColor0: '#26a69a' },
      },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, barWidth: '60%' },
    ],
  });
  const onResize = () => { if (state.marketChart) state.marketChart.resize(); };
  window.removeEventListener('resize', onResize);
  window.addEventListener('resize', onResize);
}

// ===================== 市场分析报告 =====================
function buildMarketReport(d) {
  const fmtWan = (v) => (v == null ? '—' : (v >= 1e4 ? (v / 1e4).toFixed(2) + '亿' : v.toFixed(0) + '万'));
  const fmtHand = (v) => (v == null ? '—' : (v >= 1e4 ? (v / 1e4).toFixed(2) + '亿手' : v.toFixed(0) + '手'));
  const fmtYuan = (v) => (v == null ? '—' : (v >= 1e8 ? (v / 1e8).toFixed(2) + '亿' : (v / 1e4).toFixed(0) + '万'));
  const up = (v) => (v >= 0 ? '+' : '');
  const chgCls = (v) => (v >= 0 ? '#f23645' : '#26a69a');   // 红涨绿跌（A股惯例）
  const now = new Date().toLocaleString('zh-CN');

  // 指数走势解读（含科创50 / 北证50 重点点评）
  const idxComment = (ix) => {
    const dir = ix.change_pct >= 0 ? '上涨' : '下跌';
    const volChg = (ix.volume_today != null && ix.volume_yesterday)
      ? ((ix.volume_today - ix.volume_yesterday) / ix.volume_yesterday * 100) : null;
    const volTxt = (volChg == null) ? '成交量较昨日持平（数据暂缺）'
      : (Math.abs(volChg) < 1 ? '成交量与昨日基本持平'
        : (volChg > 0 ? `放量 ${volChg.toFixed(1)}%` : `缩量 ${Math.abs(volChg).toFixed(1)}%`));
    return `收于 <b>${ix.price.toFixed(2)}</b>，${dir} <b style="color:${chgCls(ix.change_pct)}">${up(ix.change_pct)}${ix.change_pct.toFixed(2)}%</b>（${up(ix.change)}${ix.change.toFixed(2)} 点），${volTxt}，成交额 ${fmtWan(ix.amount_today_wan)}。`;
  };
  const find = (name) => (d.indices || []).find((i) => i.name === name);
  const kc = find('科创50'), bj = find('北证50'), sh = find('上证指数');
  const relative = (ix) => {
    if (!ix || !sh) return '';
    const gap = ix.change_pct - sh.change_pct;
    return `相对上证指数${gap >= 0 ? '强' : '弱'} ${Math.abs(gap).toFixed(2)} 个百分点`;
  };

  const tableRows = (d.indices || []).map((ix) => {
    const volChg = (ix.volume_today != null && ix.volume_yesterday)
      ? ((ix.volume_today - ix.volume_yesterday) / ix.volume_yesterday * 100) : null;
    return `<tr>
      <td>${ix.name}</td><td>${ix.code}</td><td>${ix.price.toFixed(2)}</td>
      <td style="color:${chgCls(ix.change_pct)}">${up(ix.change_pct)}${ix.change_pct.toFixed(2)}%</td>
      <td>${ix.open.toFixed(2)}</td><td>${ix.high.toFixed(2)}</td><td>${ix.low.toFixed(2)}</td><td>${ix.pre_close.toFixed(2)}</td>
      <td>${fmtHand(ix.volume_today)}</td><td>${fmtHand(ix.volume_yesterday)}</td>
      <td>${volChg != null ? up(volChg) + volChg.toFixed(1) + '%' : '—'}</td><td>${fmtWan(ix.amount_today_wan)}</td></tr>`;
  }).join('');

  const flowRows = (d.fund_flow || []).map((f) => `<tr>
    <td>${f.date}</td><td style="color:${chgCls(f.main_net)}">${up(f.main_net)}${fmtYuan(f.main_net)}</td>
    <td style="color:${chgCls(f.super_net)}">${up(f.super_net)}${fmtYuan(f.super_net)}</td>
    <td style="color:${chgCls(f.big_net)}">${up(f.big_net)}${fmtYuan(f.big_net)}</td>
    <td style="color:${chgCls(f.medium_net)}">${up(f.medium_net)}${fmtYuan(f.medium_net)}</td>
    <td style="color:${chgCls(f.small_net)}">${up(f.small_net)}${fmtYuan(f.small_net)}</td>
    <td style="color:${chgCls(f.main_net_pct)}">${up(f.main_net_pct)}${f.main_net_pct.toFixed(2)}%</td></tr>`).join('');
  const lastFlow = (d.fund_flow || [])[0];

  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
  <title>市场分析报告</title>
  <style>
    body{font-family:"Microsoft YaHei",Arial,sans-serif;max-width:920px;margin:0 auto;padding:24px;color:#2b3440;line-height:1.7;background:#f7f9fc}
    h1{font-size:22px} .meta{color:#8b96a8;font-size:13px;margin-bottom:16px}
    h2{font-size:16px;border-left:4px solid #3b82f6;padding-left:10px;margin-top:26px}
    table{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}
    th,td{border:1px solid #dde3ec;padding:7px 9px;text-align:left}
    th{background:#eef2f8}
    .comment{background:#f0f4fa;border:1px solid #d8e0ec;border-radius:8px;padding:12px 14px;margin:8px 0}
    .disclaimer{margin-top:28px;color:#8b96a8;font-size:12px;border-top:1px solid #dde3ec;padding-top:12px}
  </style></head><body>
  <h1>📊 市场分析报告</h1>
  <div class="meta">生成时间：${now} · 行情更新：${d.updated || '—'}</div>

  <h2>一、指数行情概览</h2>
  <table><thead><tr><th>指数</th><th>代码</th><th>最新</th><th>涨跌幅</th><th>今开</th><th>最高</th><th>最低</th><th>昨收</th><th>成交量(今)</th><th>成交量(昨)</th><th>量比</th><th>成交额</th></tr></thead><tbody>${tableRows || '<tr><td colspan="12">暂无数据</td></tr>'}</tbody></table>

  <h2>二、科创50 走势解读</h2>
  <div class="comment">${kc ? `科创50 ${idxComment(kc)}${relative(kc)}。` : '科创50 数据暂缺。'}</div>

  <h2>三、北证50 走势解读</h2>
  <div class="comment">${bj ? `北证50 ${idxComment(bj)}${relative(bj)}。` : '北证50 数据暂缺。'}</div>

  <h2>四、市场资金流向（上证指数）</h2>
  <table><thead><tr><th>日期</th><th>主力净流入</th><th>超大单</th><th>大单</th><th>中单</th><th>小单</th><th>主力净占比</th></tr></thead><tbody>${flowRows || '<tr><td colspan="7">暂无资金流向数据</td></tr>'}</tbody></table>
  <div class="comment">${lastFlow ? `主力资金${lastFlow.main_net >= 0 ? '净流入' : '净流出'} <b>${fmtYuan(lastFlow.main_net)}</b>（净占比 ${lastFlow.main_net_pct}%），超大单${lastFlow.super_net >= 0 ? '净流入' : '净流出'} ${fmtYuan(lastFlow.super_net)}，大单${lastFlow.big_net >= 0 ? '净流入' : '净流出'} ${fmtYuan(lastFlow.big_net)}，显示${lastFlow.main_net >= 0 ? '增量资金入场、做多情绪占优' : '资金离场、做多情绪偏谨慎'}。` : '资金流向数据暂缺。'}</div>

  <div class="disclaimer">本报告由 A股量化分析工具自动生成，数据来自公开行情源（腾讯财经 / 东方财富），仅供学习研究参考，不构成任何投资建议。股市有风险，投资需谨慎。</div>
  </body></html>`;

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank');
  URL.revokeObjectURL(url);
}

// ===================== 生成筛选报告 =====================
function generateReport() {
  if (!state.results.length) return;
  const st = state.scanStats || {};
  const results = [...state.results].sort((a, b) => b.strength - a.strength);
  const all = results;   // 展示全部筛选结果（不再截断前 30 条）
  const resonanceStocks = [...new Set(state.results.filter((r) => r.resonance).map((r) => r.code + ' ' + r.name))];
  const upCount = state.results.filter((r) => r.direction === 'bullish').length;
  const downCount = state.results.filter((r) => r.direction === 'bearish').length;
  const now = new Date().toLocaleString('zh-CN');

  const rows = all.map((r) => `
    <tr>
      <td>${r.code}</td><td>${r.name}</td><td>${r.market_zh}</td><td>${r.timeframe_zh}</td>
      <td>${r.pattern_zh}</td><td>${r.strength}</td><td>${r.volume_ratio}×</td>
      <td>${r.resonance ? '✓' : ''}</td>
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
  <h2>全部信号（${all.length} 条，按强度排序）</h2>
  <table><thead><tr>
    <th>代码</th><th>名称</th><th>板块</th><th>级别</th><th>形态</th><th>强度</th><th>放量</th><th>共振</th>
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
      data: ['K线', 'MA5', 'MA10', 'MA15', 'MA20', 'MA120', 'MA250'],
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
      { name: 'MA15', type: 'line', data: ma('ma15'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#ff7b4c' } },
      { name: 'MA20', type: 'line', data: ma('ma20'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#b06ce0' } },
      { name: 'MA120', type: 'line', data: ma('ma120'), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#26a69a' } },
      { name: 'MA250', type: 'line', data: ma('ma250'), smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#f23645' } },
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

// 导出 EBK（通达信自选股板块，去重保序）
async function exportEBK() {
  if (!state.results.length) return;
  try {
    const r = await fetch(API.exportEbk, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results: state.results }),
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); alert(d.error || '导出失败'); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const disp = r.headers.get('Content-Disposition') || '';
    let fname = 'scan_results.EBK';
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
    alert('导出 EBK 失败');
  }
}
