// AI 量化交易系统 -- 通用前端工具 (Stage 0 升级为全站公共层)
// =============================================================
// 提供:  请求封装 / 数字格式化 / 时间格式化 / 通知
//        SSE 流式封装 App.sse / Plotly 图表封装 App.chart / 页面状态 App.state
// 文件仍命名为 main.js (base.html 引用路径不变), 后续阶段拆分时再更名 common.js

window.App = (function () {
  'use strict';

  /** REST 请求 (GET) */
  async function request(url, opts = {}) {
    opts.headers = Object.assign(
      { 'Content-Type': 'application/json' },
      opts.headers || {}
    );
    if (opts.body && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
    }
    const r = await fetch(url, opts);
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      return await r.json();
    }
    return await r.text();
  }

  const get = (url) => request(url, { method: 'GET' });

  /**
   * POST：HTTP 非 2xx 时统一成 { ok: false, message }，避免业务里 typeof r === 'object' && r.ok 误判
   */
  async function post(url, body) {
    const opts = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: typeof body === 'string' ? body : JSON.stringify(body),
    };
    const r = await fetch(url, opts);
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const data = await r.json();
      if (!r.ok) {
        let msg = 'HTTP ' + r.status;
        if (data && data.detail !== undefined) {
          msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
        } else if (data && data.message) {
          msg = data.message;
        }
        return { ok: false, message: msg };
      }
      return data;
    }
    const text = await r.text();
    if (!r.ok) {
      return {
        ok: false,
        message: 'HTTP ' + r.status + (text ? ': ' + text.slice(0, 160) : ''),
      };
    }
    return text;
  }

  // ====== SSE 统一封装 ======
  // 统一各页面的两种 EventSource 写法 (data_collection/morning 等)。
  // 用法:
  //   const es = App.sse('/api/xxx/stream', {
  //     onEvent(name, data, raw),   // name: 事件名; data: JSON 解析结果(失败时为原文); raw: 原文本
  //     onDone(),                   // 服务端 done 事件或连接关闭
  //     onError(err),               // 连接错误
  //   });
  //   es.close();  // 主动断开
  // 约定: 后端 SSE 的终止事件名为 done (各流式路由现状一致)。
  function sse(url, handlers = {}) {
    const { onEvent, onDone, onError } = handlers;
    const es = new EventSource(url);

    // SSE 默认 message 事件 + 自定义命名事件都接住
    es.onmessage = (ev) => {
      dispatch('message', ev);
    };
    // 常见自定义事件名集合 (后端 data_collection/morning/factor 挖掘流已使用)
    ['start', 'log', 'progress', 'step', 'success', 'error', 'restart',
     'heartbeat', 'result', 'candidates', 'finish', 'warn'].forEach((name) => {
      es.addEventListener(name, (ev) => dispatch(name, ev));
    });
    es.onerror = (err) => {
      // EventSource 自动重连; done 后服务端关闭也会走这里, 由 closed 标志区分
      if (es._closed) return;
      if (onError) onError(err);
    };

    function dispatch(name, ev) {
      const raw = typeof ev.data === 'string' ? ev.data : '';
      let data = raw;
      if (raw) {
        try { data = JSON.parse(raw); } catch (e) { /* 保留原文 */ }
      }
      if (name === 'done') {
        close();
        if (onDone) onDone(data, raw);
        return;
      }
      if (onEvent) onEvent(name, data, raw);
      // success/finish 事件视为流结束 (各路由口径: 事件名不同但语义一致)
      if (name === 'success' || name === 'finish') {
        close();
        if (onDone) onDone(data, raw);
      }
    }

    function close() {
      es._closed = true;
      es.close();
    }

    return { close, raw: es };
  }

  // ====== Plotly 图表统一封装 ======
  // 统一各页内联的 layout 主题 (字号/配色/margin 基线), 版本由 base.html 的
  // plotly block 统一为 2.35.2。各页传入差异部分 (title/xaxis/yaxis 等)。
  function chartPlotly(el, data, layout, config) {
    if (typeof Plotly === 'undefined' || !el) return;
    const baseLayout = {
      margin: { l: 56, r: 24, t: 40, b: 36 },
      font: { family: 'system-ui, sans-serif', size: 12 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      showlegend: true,
      legend: { orientation: 'h', y: 1.08 },
      xaxis: { gridcolor: 'rgba(0,0,0,0.06)' },
      yaxis: { gridcolor: 'rgba(0,0,0,0.06)' },
    };
    const merged = Object.assign({}, baseLayout, layout || {});
    // 深合并一层的 xaxis/yaxis/legend/margin (调用方可覆盖基线)
    ['xaxis', 'yaxis', 'legend', 'margin'].forEach((k) => {
      if (layout && layout[k]) {
        merged[k] = Object.assign({}, baseLayout[k] || {}, layout[k]);
      }
    });
    const cfg = Object.assign(
      { responsive: true, displayModeBar: 'hover', modeBarButtonsToRemove: ['lasso2d', 'select2d'] },
      config || {}
    );
    return Plotly.react(el, data, merged, cfg);
  }

  // ====== 页面状态持久化封装 (后端 /api/page-settings/{namespace}) ======
  // 统一 factor/quantgp 页的裸 fetch 写法 与 morning/sector 等页的 App.get 写法。
  // 用法:
  //   const st = App.state('my_page');
  //   const saved = await st.load();          // 返回后端存储对象 (空时返回 {})
  //   await st.save({ a: 1 });               // 整体保存 (后端为全量替换语义)
  //   await st.patch({ b: 2 });               // 读-改-写合并保存
  const state = (namespace) => {
    const base = '/api/page-settings/' + encodeURIComponent(namespace);
    async function load() {
      try {
        const r = await request(base, { method: 'GET' });
        if (r && typeof r === 'object' && r.ok === false) return {};
        return (r && typeof r === 'object' && r.settings) ? r.settings : (r && typeof r === 'object' ? r : {});
      } catch (e) {
        return {};
      }
    }
    async function save(obj) {
      try {
        return await post(base, obj);
      } catch (e) {
        return { ok: false, message: String(e) };
      }
    }
    async function patch(obj) {
      const cur = await load();
      return save(Object.assign({}, cur, obj));
    }
    return { load, save, patch, namespace };
  };

  /** 数字格式化 */
  function fmtNum(v, digits = 2) {
    if (v === null || v === undefined || isNaN(v)) return '-';
    return Number(v).toLocaleString('zh-CN', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }
  function fmtPct(v, digits = 2) {
    if (v === null || v === undefined || isNaN(v)) return '-';
    return (Number(v) * 100).toFixed(digits) + '%';
  }
  function fmtSign(v, digits = 2, suffix = '') {
    if (v === null || v === undefined || isNaN(v)) return '-';
    const n = Number(v);
    const sign = n > 0 ? '+' : '';
    return sign + n.toFixed(digits) + suffix;
  }
  function pnlClass(v) {
    if (v === null || v === undefined || isNaN(v)) return '';
    return Number(v) > 0 ? 'pos' : (Number(v) < 0 ? 'neg' : '');
  }

  /** 信号 / 订单时间戳格式化:
   *  ISO 输入 (YYYY-MM-DDTHH:MM:SS) -> 短显示
   *  - 同一年: '04-15 15:00'
   *  - 缺失: '-'
   */
  function fmtSignalTs(ts) {
    if (!ts || typeof ts !== 'string') return '-';
    // 兼容 ISO 与 'YYYY-MM-DD HH:MM:SS'
    const m = ts.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::\d{2})?/);
    if (!m) return ts;
    return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  }

  /** 简单 toast */
  function toast(msg, kind = 'info') {
    const el = document.createElement('div');
    const colors = {
      info:    'bg-indigo-600',
      success: 'bg-green-600',
      warn:    'bg-yellow-600',
      danger:  'bg-red-600',
      // 兼容各页误传的 error (修复前静默降级为 info 的问题)
      error:   'bg-red-600',
    };
    el.className =
      'fixed top-4 right-4 z-[200] max-w-md px-4 py-3 rounded-lg text-white shadow-2xl text-sm font-medium leading-snug ring-2 ring-white/20 whitespace-pre-line ' +
      (colors[kind] || colors.info);
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }

  // 事件流 / 告警 -- 把 events 数组里的元素映射成 {level, time, msg, badge_class}
  // 兼容两种来源:
  //   1) 主循环 loop_cycle 事件: {ts, type:"loop_cycle", signal_count, duration_ms}
  //   2) 控制/告警事件: {ts, level: "INFO|WARN|CRITICAL|FATAL", title, message?, source?}
  // 友好化: 事件流面向用户, 不显示原始 type/字段名, 翻译成中文
  const _LEVEL_TEXT = {
    INFO:     '提示',
    WARN:     '警告',
    CRITICAL: '严重',
    FATAL:    '致命',
    TICK:     '心跳',
  };
  function alertLevelText(e) {
    if (!e) return '';
    const lv = (e.level || (e.type === 'loop_cycle' ? 'TICK' : 'INFO')).toUpperCase();
    return _LEVEL_TEXT[lv] || lv;
  }
  function alertBadgeClass(e) {
    if (!e) return 'badge-gray';
    const lv = (e.level || (e.type === 'loop_cycle' ? 'TICK' : 'INFO')).toUpperCase();
    const map = {
      INFO:     'badge-info',
      WARN:     'badge-warning',
      CRITICAL: 'badge-danger',
      FATAL:    'badge-danger',
      TICK:     'badge-gray',
    };
    return map[lv] || 'badge-gray';
  }
  function alertTimeText(e) {
    if (!e || !e.ts) return '';
    const m = String(e.ts).match(/(\d{2}):(\d{2}):(\d{2})/);
    return m ? `${m[1]}:${m[2]}:${m[3]}` : String(e.ts).slice(-8);
  }
  function alertMsgText(e) {
    if (!e) return '';
    if (e.type === 'loop_cycle') {
      const sc = e.signal_count != null ? e.signal_count : 0;
      const ms = e.duration_ms != null ? e.duration_ms : 0;
      const tail = sc === 0 ? '本轮无新信号' : `本轮触发 ${sc} 个信号`;
      return `策略巡检 · ${tail} · 耗时 ${ms}ms`;
    }
    const head = e.title || e.message || '';
    const src  = e.source ? ` (来自 ${e.source})` : '';
    return head + src;
  }

  // ====== 三栏布局: 左侧导航折叠 + 右侧 AI 侧栏拖拽/收起 ======

  /** 折叠/展开左侧导航栏 */
  function toggleRail() {
    const rail = document.getElementById('app-rail');
    if (!rail) return;
    rail.classList.toggle('collapsed');
    try {
      localStorage.setItem('app_rail_collapsed', rail.classList.contains('collapsed') ? '1' : '0');
    } catch(e) {}
  }

  /** 初始化三栏布局交互: 左栏折叠记忆 + 右侧 AI 侧栏拖拽宽度/收起展开 */
  function initLayout() {
    // 左侧导航折叠记忆
    const rail = document.getElementById('app-rail');
    const railBtn = document.getElementById('rail-collapse-btn');
    if (rail && railBtn) {
      try {
        if (localStorage.getItem('app_rail_collapsed') === '1') rail.classList.add('collapsed');
      } catch(e) {}
      railBtn.addEventListener('click', toggleRail);
    }

    const sidebar = document.getElementById('ai-sidebar');
    const resizer = document.getElementById('ai-sidebar-resizer');
    const closeBtn = document.getElementById('ai-sidebar-close');
    const expandBtn = document.getElementById('ai-sidebar-expand-btn');

    if (!sidebar) return;

    // 恢复宽度记忆
    try {
      const w = localStorage.getItem('ai_sidebar_w');
      if (w) sidebar.style.width = w + 'px';
    } catch(e) {}
    // 恢复收起记忆
    try {
      if (localStorage.getItem('ai_sidebar_collapsed') === '1') {
        sidebar.classList.add('collapsed');
        if (expandBtn) expandBtn.classList.add('show');
      }
    } catch(e) {}

    // 拖拽调宽度 (侧栏在右侧, 鼠标左移 = 宽度增加)
    if (resizer) {
      let dragging = false, startX = 0, startW = 0;
      resizer.addEventListener('mousedown', (e) => {
        dragging = true;
        startX = e.clientX;
        startW = sidebar.offsetWidth;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
      });
      document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const delta = startX - e.clientX;
        let w = startW + delta;
        w = Math.max(320, Math.min(720, w));
        sidebar.style.width = w + 'px';
      });
      document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        try { localStorage.setItem('ai_sidebar_w', sidebar.offsetWidth); } catch(e) {}
      });
    }

    // 收起侧栏
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        sidebar.classList.add('collapsed');
        if (expandBtn) expandBtn.classList.add('show');
        try { localStorage.setItem('ai_sidebar_collapsed', '1'); } catch(e) {}
      });
    }
    // 展开侧栏
    if (expandBtn) {
      expandBtn.addEventListener('click', () => {
        sidebar.classList.remove('collapsed');
        expandBtn.classList.remove('show');
        try { localStorage.setItem('ai_sidebar_collapsed', '0'); } catch(e) {}
      });
    }
  }

  // defer 脚本执行时 DOM 已就绪, 初始化布局
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLayout);
  } else {
    initLayout();
  }

  return {
    get, post, request,
    sse, chart: { plotly: chartPlotly }, state,
    fmtNum, fmtPct, fmtSign, pnlClass, fmtSignalTs, toast,
    alertLevelText, alertBadgeClass, alertTimeText, alertMsgText,
    initLayout, toggleRail,
  };
})();
