function backtestApp() {
    // 默认日期: 最近 1 年
    const today = new Date();
    const oneYearAgo = new Date();
    oneYearAgo.setFullYear(today.getFullYear() - 1);
    const fmt = (d) => d.toISOString().slice(0, 10);

    return {
        showHelp: false,
        ping: null,
        strategies: [],
        form: {
            code: '600519.SH',
            start: fmt(oneYearAgo),
            end:   fmt(today),
            strategy: 'macd_1d',
        },
        busy: false,
        recBusy: false,
        applyBusy: false,
        errMsg: '',
        result: null,
        recommendation: null,
        cmpSort: { key: 'annual_return', dir: 'desc' },  // 对比表当前排序键 (默认年化降序)

        async init() {
            // 拉策略列表 + ping 数据源
            try {
                const sres = await App.get('/api/backtest/strategies');
                this.strategies = (sres && sres.list) ? sres.list : [];
                if (this.strategies.length > 0
                        && !this.strategies.find(s => s.name === this.form.strategy)) {
                    this.form.strategy = this.strategies[0].name;
                }
            } catch (e) { console.error('strategies', e); }
            try { this.ping = await App.get('/api/backtest/ping'); } catch (e) { console.error('ping', e); }
        },

        metricCls(v) {
            if (v === null || v === undefined || isNaN(v)) return '';
            return Number(v) > 0 ? 'pos' : (Number(v) < 0 ? 'neg' : '');
        },

        async runOnce() {
            if (this.busy) return;
            this.errMsg = '';
            this.busy = true;
            this.result = null;
            try {
                const r = await App.post('/api/backtest/run', {
                    code:     (this.form.code || '').trim(),
                    strategy: this.form.strategy,
                    start:    this.form.start,
                    end:      this.form.end,
                });
                if (r && r.ok) {
                    this.result = r;
                    this.$nextTick(() => {
                        this.renderKlineChart();
                        this.renderNavChart();
                    });
                } else {
                    this.errMsg = (r && r.message) || '回测失败';
                }
            } catch (e) {
                this.errMsg = String(e);
            } finally {
                this.busy = false;
            }
        },

        async recommend() {
            if (this.recBusy) return;
            this.errMsg = '';
            this.recBusy = true;
            this.recommendation = null;
            try {
                const r = await App.post('/api/backtest/recommend', {
                    code:  (this.form.code || '').trim(),
                    start: this.form.start,
                    end:   this.form.end,
                });
                if (r && r.ok) {
                    this.recommendation = r;
                    const n = (r.summaries || []).length;
                    const f = (r.failed || []).length;
                    App.toast('对比完成: 成功 ' + n + ' / 失败 ' + f, n > 0 ? 'success' : 'warn');
                    this.$nextTick(() => {
                        this.renderCompareNavChart();
                        this.renderCompareBarChart();
                    });
                } else {
                    this.errMsg = (r && r.message) || '对比失败';
                }
            } catch (e) {
                this.errMsg = String(e);
            } finally {
                this.recBusy = false;
            }
        },

        // ---------- 策略对比报告 辅助方法 ----------
        /** 表头点击切换排序; 同 key 再点反向, 不同 key 默认 desc */
        sortCompareBy(key) {
            if (this.cmpSort.key === key) {
                this.cmpSort.dir = this.cmpSort.dir === 'desc' ? 'asc' : 'desc';
            } else {
                this.cmpSort.key = key;
                this.cmpSort.dir = 'desc';
            }
        },
        /** 按当前 cmpSort 对 summaries 排序; 失败列表不在这里 */
        sortedCompare() {
            const arr = ((this.recommendation || {}).summaries || []).slice();
            const k = this.cmpSort.key;
            const dir = this.cmpSort.dir === 'asc' ? 1 : -1;
            arr.sort((a, b) => {
                const va = Number(a[k]) || 0;
                const vb = Number(b[k]) || 0;
                if (va === vb) return 0;
                return va > vb ? dir : -dir;
            });
            return arr;
        },
        /** 找最大回撤最小的策略 (max_drawdown 是正数, 越小越好) */
        lowestDrawdown(rec) {
            const arr = ((rec || {}).summaries || []).filter(s => (s.trades || 0) > 0);
            if (!arr.length) return null;
            return arr.reduce((min, s) => (s.max_drawdown < min.max_drawdown ? s : min), arr[0]);
        },
        /** 找 Sharpe 最高的策略 */
        highestSharpe(rec) {
            const arr = ((rec || {}).summaries || []).filter(s => (s.trades || 0) > 0);
            if (!arr.length) return null;
            return arr.reduce((max, s) => (s.sharpe > max.sharpe ? s : max), arr[0]);
        },

        /** 净值曲线对比图: 所有策略 + 买入持有 同框
         *  数据来自 recommendation.nav_series (每只策略一条) + recommendation.buy_hold (基准) */
        renderCompareNavChart() {
            if (!window.Plotly) return;
            const el = document.getElementById('bt-compare-nav-chart');
            if (!el) return;
            const rec = this.recommendation;
            if (!rec) return;
            const nav_series = rec.nav_series || {};
            const bh = rec.buy_hold || [];
            const labelMap = {};
            (rec.summaries || []).forEach(s => { labelMap[s.strategy] = s.label || s.strategy; });

            // Plotly 默认色板; 让线条颜色稳定区分
            const palette = ['#4f46e5', '#dc2626', '#059669', '#d97706', '#0891b2',
                             '#7c3aed', '#db2777', '#65a30d', '#e11d48', '#0ea5e9'];
            const traces = [];
            let i = 0;
            Object.keys(nav_series).forEach(name => {
                const arr = nav_series[name] || [];
                if (!arr.length) return;
                traces.push({
                    type: 'scatter', mode: 'lines',
                    x: arr.map(p => p.date),
                    y: arr.map(p => p.nav),
                    line: { color: palette[i % palette.length], width: 1.5 },
                    name: labelMap[name] || name,
                    hovertemplate: '%{x}<br>' + (labelMap[name] || name) + ' %{y:.4f}<extra></extra>',
                });
                i += 1;
            });
            if (bh.length > 0) {
                traces.push({
                    type: 'scatter', mode: 'lines',
                    x: bh.map(p => p.date),
                    y: bh.map(p => p.nav),
                    line: { color: '#9ca3af', width: 2, dash: 'dash' },
                    name: '买入持有',
                    hovertemplate: '%{x}<br>买入持有 %{y:.4f}<extra></extra>',
                });
            }

            const layout = {
                margin: { l: 50, r: 16, t: 8, b: 36 },
                xaxis: { type: 'category', tickfont: { size: 10 }, nticks: 8 },
                yaxis: { tickfont: { size: 10 }, title: { text: '净值 (起点 1.0)', font: { size: 11 } } },
                shapes: [
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 1, y1: 1,
                      line: { color: '#9ca3af', width: 1, dash: 'dot' } },
                ],
                showlegend: true, legend: { x: 0.01, y: 0.99, font: { size: 10 } },
                plot_bgcolor: '#fff',
            };
            Plotly.react('bt-compare-nav-chart', traces, layout, { displayModeBar: false });
        },

        /** 关键指标柱状图: 3 组并排 (总收益 / 最大回撤 / Sharpe), 横轴 = 策略
         *  最大回撤取绝对值方便和总收益对比 (柱越高表示亏越多, 不是好事) */
        renderCompareBarChart() {
            if (!window.Plotly) return;
            const el = document.getElementById('bt-compare-bar-chart');
            if (!el) return;
            const rec = this.recommendation;
            if (!rec) return;
            const arr = (rec.summaries || []).slice();
            if (!arr.length) return;
            // 按当前表排序保持一致, 让用户对得上
            const sorted = this.sortedCompare();
            const names = sorted.map(s => s.label || s.strategy);
            const totalReturn = sorted.map(s => Number((s.total_return * 100).toFixed(2)));
            const drawdown    = sorted.map(s => Number((s.max_drawdown * 100).toFixed(2)));
            const sharpe      = sorted.map(s => Number((s.sharpe).toFixed(2)));

            const data = [
                { type: 'bar', x: names, y: totalReturn,
                  marker: { color: '#10b981' },
                  name: '总收益 %',
                  hovertemplate: '%{x}<br>总收益 %{y:.2f}%<extra></extra>' },
                { type: 'bar', x: names, y: drawdown,
                  marker: { color: '#ef4444' },
                  name: '最大回撤 % (越低越好)',
                  hovertemplate: '%{x}<br>最大回撤 %{y:.2f}%<extra></extra>' },
                { type: 'bar', x: names, y: sharpe,
                  marker: { color: '#6366f1' },
                  name: 'Sharpe (右轴)',
                  yaxis: 'y2',
                  hovertemplate: '%{x}<br>Sharpe %{y:.2f}<extra></extra>' },
            ];
            const layout = {
                margin: { l: 50, r: 50, t: 8, b: 80 },
                barmode: 'group',
                xaxis: { tickfont: { size: 10 }, tickangle: -25 },
                yaxis: { tickfont: { size: 10 }, title: { text: '收益 / 回撤 %', font: { size: 11 } },
                         ticksuffix: '%' },
                yaxis2: { tickfont: { size: 10 }, title: { text: 'Sharpe', font: { size: 11 } },
                          overlaying: 'y', side: 'right' },
                showlegend: true, legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.12, font: { size: 10 } },
                plot_bgcolor: '#fff',
            };
            Plotly.react('bt-compare-bar-chart', data, layout, { displayModeBar: false });
        },

        async applySingle() {
            if (!this.result || !this.result.ok) return;
            await this._applyTo(this.result.stock_code, this.result.strategy);
        },

        async applyRecommended(strategy) {
            const code = (this.form.code || '').trim();
            if (!code || !strategy) return;
            await this._applyTo(code, strategy);
        },

        async _applyTo(code, strategy) {
            if (this.applyBusy) return;
            this.applyBusy = true;
            try {
                const r = await App.post('/api/backtest/recommend_apply',
                                          { code, strategy });
                if (r && r.ok) {
                    App.toast(r.message || '已应用', 'success');
                } else {
                    App.toast((r && r.message) || '应用失败', 'danger');
                }
            } finally {
                this.applyBusy = false;
            }
        },

        // ============ 图表 ============

        renderKlineChart() {
            const k = (this.result && this.result.kline) || [];
            if (!k.length || !window.Plotly) return;
            const x = k.map(b => b.date);
            const candle = {
                type:   'candlestick',
                x:      x,
                open:   k.map(b => b.open),
                high:   k.map(b => b.high),
                low:    k.map(b => b.low),
                close:  k.map(b => b.close),
                increasing: { line: { color: '#ef4444' } },
                decreasing: { line: { color: '#10b981' } },
                name:   'K 线',
                showlegend: false,
            };
            const trades = (this.result && this.result.trades) || [];
            const buys  = trades.filter(t => t.side === 'buy');
            const sells = trades.filter(t => t.side === 'sell');
            const buyMarker = {
                type: 'scatter', mode: 'markers',
                x: buys.map(t => t.date),
                y: buys.map(t => t.price),
                marker: { color: '#dc2626', size: 12, symbol: 'triangle-up' },
                name: '买',
                hovertemplate: '%{x}<br>买 %{y:.2f}<extra></extra>',
            };
            const sellMarker = {
                type: 'scatter', mode: 'markers',
                x: sells.map(t => t.date),
                y: sells.map(t => t.price),
                marker: { color: '#059669', size: 12, symbol: 'triangle-down' },
                name: '卖',
                hovertemplate: '%{x}<br>卖 %{y:.2f}<extra></extra>',
            };
            const layout = {
                margin: { l: 50, r: 16, t: 8, b: 36 },
                xaxis: {
                    type: 'category', tickfont: { size: 10 },
                    rangeslider: { visible: false },
                    nticks: 8,
                },
                yaxis: { tickfont: { size: 10 }, title: { text: '价格', font: { size: 11 } } },
                showlegend: true,
                legend: { x: 0.01, y: 0.99, font: { size: 10 } },
                plot_bgcolor: '#fff',
            };
            Plotly.react('bt-kline-chart', [candle, buyMarker, sellMarker], layout,
                         { displayModeBar: false });
        },

        renderNavChart() {
            const navs = (this.result && this.result.navs) || [];
            const k = (this.result && this.result.kline) || [];
            if (!navs.length || !window.Plotly) return;
            const initial = (this.result.metrics && this.result.metrics.initial_cash) || 1;
            const x = navs.map(p => p.date);
            const stratNav = navs.map(p => p.nav / initial);
            // 同期买入持有: 用 K 线第一根开盘做基准
            let bhSeries = [];
            if (k.length > 0) {
                const baseOpen = k[0].open || 1;
                const closeMap = new Map(k.map(b => [b.date, b.close]));
                bhSeries = x.map(d => {
                    const c = closeMap.get(d);
                    return c ? c / baseOpen : null;
                });
            }
            const data = [
                { type: 'scatter', mode: 'lines', x: x, y: stratNav,
                  line: { color: '#4f46e5', width: 2 }, name: '策略净值',
                  hovertemplate: '%{x}<br>策略 %{y:.4f}<extra></extra>' },
                { type: 'scatter', mode: 'lines', x: x, y: bhSeries,
                  line: { color: '#9ca3af', width: 1.5 }, name: '买入持有',
                  hovertemplate: '%{x}<br>基准 %{y:.4f}<extra></extra>' },
            ];
            const layout = {
                margin: { l: 50, r: 16, t: 8, b: 36 },
                xaxis: { type: 'category', tickfont: { size: 10 }, nticks: 8 },
                yaxis: { tickfont: { size: 10 }, title: { text: '净值 (起点 1.0)', font: { size: 11 } } },
                shapes: [
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 1, y1: 1,
                      line: { color: '#9ca3af', width: 1, dash: 'dot' } },
                ],
                showlegend: true, legend: { x: 0.01, y: 0.99, font: { size: 10 } },
                plot_bgcolor: '#fff',
            };
            Plotly.react('bt-nav-chart', data, layout, { displayModeBar: false });
        },
    };
}
