// 轮动页面统一前端逻辑 (板块/概念共用)
// =============================================================
// 合并自 sector_rotation.html 与 concept_rotation.html 的两个内联组件。
// 维度差异全部收敛到 ROTATION_DIMS 配置 (API 前缀/字段名/文案/page-settings namespace)。
// alert() 已统一替换为 App.toast (Stage 1 去重计划项)。

(function () {
  'use strict';

  // 维度配置: 由页面 DOM 上的 data-dimension 属性选择
  const ROTATION_DIMS = {
    sector: {
      key: 'sector',
      label: '板块',
      api: '/api/sector-rotation',
      indexEndpoint: 'sector-index',
      indexParam: 'sector',           // detail/index 的查询参数名
      years: 2,
      settingsNamespace: 'sector_rotation',
      // cells 字段: sector 单标签
      cellLabelField: 'sector',
      detailParamField: null,          // selectCell 取 c.sector
      detailFields: [
        'score', 'composite_score', 'rank', 'composite_rank',
        'mom21_z', 'rs60_z', 'vol_ratio_z',
        'roc_20', 'ma20_slope', 'ma20_accel',
        'macd_hist', 'hist_delta', 'member_count',
      ],
    },
    concept: {
      key: 'concept',
      label: '概念',
      api: '/api/concept-rotation',
      indexEndpoint: 'concept-index',
      indexParam: 'concept_code',
      years: 1,
      settingsNamespace: 'concept_rotation',
      // cells 字段: concept 名称 + 来源前缀双行
      cellLabelField: 'concept_name',
      cellSubLabelField: 'source_prefix',
      detailParamField: 'concept_code',
      detailFields: [
        'score', 'composite_score', 'rank', 'composite_rank',
        'mom10_z', 'rs20_z', 'vol_ratio_z',
        'roc_20', 'ma20_slope', 'ma20_accel',
        'macd_hist', 'hist_delta', 'member_count',
        'concept_code', 'concept_name', 'source_prefix',
      ],
    },
  };

  window.rotationApp = function () {
    return {
      // ---- 状态 (两侧原样保留) ----
      loading: false,
      taskRunning: false,
      taskMessage: '',
      taskProgress: 0,
      taskTotal: 0,
      dates: [],
      ranks: [],
      cells: [],
      hasData: false,
      selected: null,
      detail: null,
      notes: {},
      history: [],
      itemIndex: null,
      relevantStocks: [],
      polling: null,
      statusText: '暂无数据',
      days: 20,
      endDate: '',
      dim: null,

      init() {
        // 从页面 DOM 读取维度 (data-dimension 属性)
        const host = document.querySelector('[x-data="rotationApp()"]');
        const key = (host && host.getAttribute('data-dimension')) || 'sector';
        this.dim = ROTATION_DIMS[key] || ROTATION_DIMS.sector;
        this._initAsync();
      },

      async _initAsync() {
        await this._restoreState();
        this.$watch('days', () => this._saveState());
        this.$watch('endDate', () => this._saveState());
        if (!this.endDate) {
          this.endDate = new Date().toISOString().split('T')[0];
        }
        await this.loadStatus();
        if (this.taskRunning) {
          // 如果后台正在计算, 先显示状态条, 等任务完成后再加载矩阵
          this.startPolling();
        } else {
          await this.loadMatrix();
        }
      },

      _restoreState() {
        // 参数统一存后端 (多实例共享, 前后端解耦), 前端不再保存数据
        const ns = this.dim.settingsNamespace;
        return App.get('/api/page-settings/' + ns).then(res => {
          const state = (res && res.data) || {};
          if (state.days && [5, 10, 20].includes(Number(state.days))) {
            this.days = Number(state.days);
          }
          if (state.endDate) this.endDate = state.endDate;
        }).catch(e => {
          console.warn('恢复' + this.dim.label + '轮动状态失败:', e);
        });
      },

      _saveState() {
        // 参数统一保存到后端, 多实例共享 (前端不再持有数据)
        const ns = this.dim.settingsNamespace;
        App.post('/api/page-settings/' + ns, {
          days: this.days,
          endDate: this.endDate,
        }).catch(e => {
          console.warn('保存' + this.dim.label + '轮动状态失败:', e);
        });
      },

      get taskProgressPct() {
        if (!this.taskTotal) return 0;
        return Math.round((this.taskProgress / this.taskTotal) * 100);
      },

      startPolling() {
        if (this.polling) return;
        this.polling = setInterval(() => this.loadStatus(), 2000);
      },

      stopPolling() {
        if (this.polling) {
          clearInterval(this.polling);
          this.polling = null;
        }
      },

      async loadStatus() {
        try {
          const s = await App.get(this.dim.api + '/status');
          const wasRunning = this.taskRunning;
          this.taskRunning = s.running;
          this.taskMessage = s.message || '';
          this.taskProgress = s.progress || 0;
          this.taskTotal = s.total || 0;
          this.statusText = s.message || '就绪';

          if (s.running) {
            this.startPolling();
          } else {
            this.stopPolling();
            // 任务从运行变为结束时, 刷新矩阵
            if (wasRunning || this.taskMessage && /(完成|失败|停止)/.test(this.taskMessage)) {
              await this.loadMatrix();
            }
          }
        } catch (e) {
          console.error('加载状态失败:', e);
        }
      },

      async loadMatrix() {
        this.loading = true;
        try {
          const endParam = this.endDate ? `&end_date=${this.endDate}` : '';
          const res = await App.get(`${this.dim.api}/matrix?days=${this.days}&top_n=15${endParam}`);
          this.dates = res.dates || [];
          this.ranks = res.ranks || [];
          this.cells = res.cells || [];
          this.hasData = res.has_data;
          // 只有没有任务消息时才显示默认提示, 避免覆盖错误信息
          if (!this.hasData && !this.taskRunning && !this.taskMessage) {
            this.statusText = '所选时间段暂无轮动数据，请点击「重建选中区间」生成';
          } else if (this.hasData) {
            const start = this.dates[0];
            const end = this.dates[this.dates.length - 1];
            this.statusText = `${start} ~ ${end} 共 ${this.dates.length} 个交易日`;
          }
        } catch (e) {
          console.error('加载矩阵失败:', e);
          if (!this.taskMessage) {
            this.statusText = '加载矩阵失败';
          }
        } finally {
          this.loading = false;
        }
      },

      setDays(n) {
        this.days = n;
        this.loadMatrix();
      },

      cellIndex(date, rank) {
        return this.cells.findIndex(c => c.date === date && c.rank === rank);
      },

      cell(date, rank) {
        const idx = this.cellIndex(date, rank);
        return idx >= 0 ? this.cells[idx] : null;
      },

      cellLabel(date, rank) {
        const c = this.cell(date, rank);
        return c ? (c[this.dim.cellLabelField] || '') : '';
      },

      cellSubLabel(date, rank) {
        if (!this.dim.cellSubLabelField) return '';
        const c = this.cell(date, rank);
        return c ? (c[this.dim.cellSubLabelField] || '') : '';
      },

      isSelected(date, rank) {
        return this.selected && this.selected.date === date && this.selected.rank === rank;
      },

      cellStyle(date, rank) {
        const c = this.cell(date, rank);
        if (!c) return '';
        const score = c.composite_score !== null ? c.composite_score : c.score;
        const color = this.scoreColor(score);
        return `background-color: ${color};`;
      },

      scoreColor(score) {
        if (score === null || score === undefined || isNaN(score)) return '#ffffff';
        // 计算当前所有单元格的 min/max
        const scores = this.cells
          .map(c => c.composite_score !== null ? c.composite_score : c.score)
          .filter(v => v !== null && v !== undefined && !isNaN(v));
        if (!scores.length) return '#ffffff';
        const min = Math.min(...scores);
        const max = Math.max(...scores);
        if (max === min) return '#ffffff';
        const ratio = Math.max(0, Math.min(1, (score - min) / (max - min)));
        // 从白色到深红
        const r = 255;
        const g = Math.round(255 - 200 * ratio);
        const b = Math.round(255 - 200 * ratio);
        return `rgb(${r}, ${g}, ${b})`;
      },

      async selectCell(date, rank) {
        const c = this.cell(date, rank);
        if (!c) return;
        // selected 结构: sector 版 {date, rank, sector}; concept 版含三字段
        this.selected = { date, rank, ...this._selectedExtra(c) };
        try {
          const param = this.dim.detailParamField || 'sector';
          const paramVal = c[this.dim.detailParamField] || c.sector;
          const res = await App.get(`${this.dim.api}/detail?${param}=${encodeURIComponent(paramVal)}&date=${date}`);
          if (!res.ok) {
            this.detail = null;
            return;
          }
          this.detail = res.detail;
          this.notes = res.notes || {};
          this.history = res.history || [];
          this.relevantStocks = res.relevant_stocks || [];
          // 加载指数数据
          this.itemIndex = null;
          const idxRes = await App.get(`${this.dim.api}/${this.dim.indexEndpoint}?${param}=${encodeURIComponent(paramVal)}&years=${this.dim.years}`);
          if (idxRes.ok) {
            this.itemIndex = idxRes;
          }
          this.$nextTick(() => {
            this.drawChart();
            this.drawIndexChart();
          });
        } catch (e) {
          console.error('加载明细失败:', e);
        }
      },

      _selectedExtra(c) {
        if (this.dim.key === 'concept') {
          return { concept_code: c.concept_code, concept_name: c.concept_name, source_prefix: c.source_prefix };
        }
        return { sector: c.sector };
      },

      get detailSubtitle() {
        if (!this.selected) return '点击左侧格子查看详情';
        if (this.dim.key === 'concept') {
          const prefix = this.selected.source_prefix ? `[${this.selected.source_prefix}] ` : '';
          return `${prefix}${this.selected.concept_name} (${this.selected.concept_code}) @ ${this.selected.date}`;
        }
        return `${this.selected.sector} @ ${this.selected.date}`;
      },

      get detailFields() {
        if (!this.detail) return [];
        return this.dim.detailFields.filter(f => this.detail[f] !== undefined);
      },

      fmt(v) {
        if (v === null || v === undefined || isNaN(v)) return '-';
        return Number(v).toLocaleString('zh-CN', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
      },

      formatDate(dateStr) {
        const d = new Date(dateStr);
        return `${d.getMonth() + 1}/${d.getDate()}`;
      },

      phaseClass(phase) {
        const map = {
          'accel_up': 'badge-success',
          'decel_up': 'badge-warning',
          'accel_down': 'badge-danger',
          'decel_down': 'badge-info',
          'neutral': 'badge-secondary',
        };
        return map[phase] || 'badge-secondary';
      },

      drawChart() {
        if (!this.history.length) return;
        const dates = this.history.map(h => h.date);
        const ranks = this.history.map(h => h.rank);
        const compositeRanks = this.history.map(h => h.composite_rank);

        Plotly.newPlot('rankChart', [
          {
            x: dates,
            y: ranks,
            mode: 'lines+markers',
            name: '强度排名',
            line: { color: '#dc2626', width: 2 },
            marker: { size: 4 },
            yaxis: 'y',
          },
          {
            x: dates,
            y: compositeRanks,
            mode: 'lines+markers',
            name: '综合排名',
            line: { color: '#2563eb', width: 2, dash: 'dot' },
            marker: { size: 4 },
            yaxis: 'y',
          }
        ], {
          margin: { t: 10, r: 10, b: 30, l: 30 },
          xaxis: { tickangle: -30, tickfont: { size: 10 } },
          yaxis: {
            title: '',
            autorange: 'reversed',
            tickfont: { size: 10 },
          },
          legend: { orientation: 'h', y: 1.1, x: 0.5, xanchor: 'center' },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
        }, {
          responsive: true,
          displayModeBar: false,
        });
      },

      drawIndexChart() {
        if (!this.itemIndex || !this.itemIndex.dates.length) return;
        const dates = this.itemIndex.dates;
        const closes = this.itemIndex.close;

        Plotly.newPlot('indexChart', [
          {
            x: dates,
            y: closes,
            mode: 'lines',
            name: this.dim.label + '指数',
            line: { color: '#059669', width: 2 },
            fill: 'tozeroy',
            fillcolor: 'rgba(5, 150, 105, 0.08)',
          }
        ], {
          margin: { t: 10, r: 10, b: 30, l: 50 },
          xaxis: {
            tickangle: -30,
            tickfont: { size: 10 },
            rangeslider: { visible: true, thickness: 0.05 },
          },
          yaxis: {
            title: '',
            tickfont: { size: 10 },
          },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
        }, {
          responsive: true,
          displayModeBar: false,
        });
      },

      async refreshToday() {
        try {
          const res = await App.post(this.dim.api + '/refresh');
          if (!res.ok) {
            App.toast(res.error || res.message || '刷新失败', 'warn');
            return;
          }
          this.startPolling();
          await this.loadStatus();
        } catch (e) {
          App.toast('刷新失败: ' + e.message, 'danger');
        }
      },

      async rebuildSelected() {
        if (!confirm(`确定要重建 ${this.endDate} 往前 ${this.days} 个交易日的${this.dim.label}轮动数据吗？`)) return;
        try {
          const endParam = this.endDate ? `&end_date=${this.endDate}` : '';
          const res = await App.post(`${this.dim.api}/rebuild?days=${this.days}${endParam}`);
          if (!res.ok) {
            App.toast(res.error || res.message || '重建失败', 'warn');
            return;
          }
          this.startPolling();
          await this.loadStatus();
        } catch (e) {
          App.toast('重建失败: ' + e.message, 'danger');
        }
      },

      openStockDetail(code, name, date) {
        const url = `/stock-quote?code=${encodeURIComponent(code)}`;
        window.open(url, '_blank');
      },

      async stopTask() {
        try {
          await App.post(this.dim.api + '/stop');
          this.stopPolling();
          await this.loadStatus();
        } catch (e) {
          App.toast('停止失败: ' + e.message, 'danger');
        }
      },
    };
  };
})();
