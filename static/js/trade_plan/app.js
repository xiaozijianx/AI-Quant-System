// ECharts 实例不放入 Alpine 响应式对象, 避免 Proxy 破坏其内部状态
let klineChart = null;

function tradePlanApp() {
    return {
        code: (window.__tradePlanCtx?.code ?? ''),
        planType: (window.__tradePlanCtx?.plan_type ?? ''),
        tradeDate: (window.__tradePlanCtx?.trade_date ?? ''),
        markdown: '',
        metadata: {},
        parsed: {
            current_opinion: { conclusion: '', detail: '' },
            position_plan: { current: {}, target: {} },
            exit_plan: { take_profit: [], stop_loss: [] },
            add_position_conditions: [],
            entry_conditions: []
        },
        sections: {},
        exists: false,
        editing: false,
        saving: false,
        generating: false,
        watchList: [],
        planIndex: {},
        quote: {},
        klineData: null,
        totalCapital: 1000000,

        async init() {
            await this.loadWatchList();
            await this.loadPlanIndex();
            if (!this.code) return;
            await this.loadPlan();
            await this.loadQuote();
            await this.loadKline();
        },

        switchPlanType(pt) {
            if (pt === this.planType) return;
            // 切换后刷新 URL, 保持当前 code
            if (this.code) {
                window.location.href = '/trade-plan/' + encodeURIComponent(this.code) + '?plan_type=' + pt;
            } else {
                window.location.href = '/trade-plan?plan_type=' + pt;
            }
        },

        async loadPlan() {
            if (!this.code) {
                this.exists = false;
                return;
            }
            try {
                const r = await App.get('/api/trade-plan/' + encodeURIComponent(this.code)
                                        + '?plan_type=' + this.planType + '&trade_date=' + this.tradeDate);
                if (r && r.ok && r.exists) {
                    this.markdown = r.raw_markdown || '';
                    this.metadata = r.metadata || {};
                    this.parsed = r.parsed || this.parsed;
                    this.sections = (r.parsed && r.parsed.sections) || {};
                    this.exists = true;
                    this.editing = false;
                } else {
                    this.exists = false;
                    this.editing = false;
                    this.markdown = '';
                    this.metadata = {};
                    this.parsed = { current_opinion: { conclusion: '', detail: '' }, position_plan: { current: {}, target: {} }, exit_plan: { take_profit: [], stop_loss: [] }, add_position_conditions: [], entry_conditions: [] };
                    this.sections = {};
                }
            } catch (e) {
                console.error('loadPlan', e);
                App.toast('加载计划失败: ' + (e && e.message ? e.message : String(e)), 'warn');
                this.exists = false;
            }
        },

        async generatePlan(force = false) {
            this.generating = true;
            try {
                const r = await App.post('/api/trade-plan/' + encodeURIComponent(this.code)
                                         + '/generate?plan_type=' + this.planType + '&trade_date=' + this.tradeDate,
                                         force ? { force: true } : {});
                if (r && r.ok && r.exists) {
                    App.toast(force ? '已重新生成交易计划' : '已生成默认交易计划', 'success');
                    this.markdown = r.raw_markdown || '';
                    this.metadata = r.metadata || {};
                    this.parsed = r.parsed || this.parsed;
                    this.sections = (r.parsed && r.parsed.sections) || {};
                    this.exists = true;
                    this.editing = false;
                    await this.loadPlanIndex();
                } else {
                    App.toast('生成失败: ' + ((r && r.message) || '未知错误'), 'danger');
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            } finally {
                this.generating = false;
            }
        },

        isPlanComplete() {
            const required = ['当前操作建议', '仓位计划', '出场计划', '判断逻辑', '风控说明'];
            return required.every(s => this.sections[s] && this.sections[s].trim());
        },

        async savePlan() {
            this.saving = true;
            try {
                const r = await App.post('/api/trade-plan/' + encodeURIComponent(this.code)
                                         + '?plan_type=' + this.planType + '&trade_date=' + this.tradeDate, {
                    markdown: this.markdown
                });
                if (r && r.ok) {
                    App.toast('已保存', 'success');
                    this.metadata = (r.parsed && r.parsed.metadata) || this.metadata;
                    this.parsed = r.parsed || this.parsed;
                    this.sections = (r.parsed && r.parsed.sections) || {};
                    this.exists = true;
                    this.editing = false;
                    await this.loadPlanIndex();
                } else {
                    App.toast('保存失败: ' + ((r && r.message) || '未知错误'), 'danger');
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            } finally {
                this.saving = false;
            }
        },

        cancelEdit() {
            this.editing = false;
            // 重新加载, 丢弃未保存的编辑
            this.loadPlan();
        },

        /** 切换「生效」: 生效即自动执行, 后端联动打开 is_auto_trade */
        async onToggleActive(value) {
            await this.toggle('is_active', value);
        },

        async toggle(field, value) {
            try {
                const r = await App.post('/api/trade-plan/' + encodeURIComponent(this.code)
                                         + '/toggle?plan_type=' + this.planType + '&trade_date=' + this.tradeDate, {
                    field: field,
                    value: value
                });
                if (r && r.ok) {
                    App.toast('已更新', 'success');
                    this.metadata[field] = value;
                    await this.loadPlanIndex();
                } else {
                    App.toast('更新失败: ' + ((r && r.message) || '未知错误'), 'danger');
                    await this.loadPlan();
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'danger');
                await this.loadPlan();
            }
        },

        async loadWatchList() {
            try {
                // sim/real 独立: planType='live' 时读取实盘 watch_merge
                const url = this.planType === 'live' ? '/api/live/real/watch_merge?ui=' : '/api/live/watch_merge?ui=';
                const r = await App.get(url);
                let merged = (r && r.merged) || [];
                // 实盘: 监控列表 = 自选池 + 待入场 + QMT 实时持仓
                // (watch_merge 的持仓来自 live_state_real.json, 这里再并入 QMT 账户真实持仓;
                //   QMT 未连接时忽略, 不影响自选池/待入场的展示)
                if (this.planType === 'live') {
                    try {
                        const acct = await App.get('/api/live/real_account');
                        const posCodes = ((acct && acct.positions) || [])
                            .map(p => this.normCode(p.stock_code))
                            .filter(c => c);
                        merged = [...new Set([...merged, ...posCodes])];
                    } catch (e2) { /* QMT 不可用时忽略持仓并入 */ }
                }
                const names = await this.loadStockNames(merged);
                this.watchList = merged.map(c => ({ code: c, name: names[c] || '' }));
            } catch (e) {
                console.error('loadWatchList', e);
                this.watchList = [];
            }
        },

        async loadStockNames(codes) {
            if (!codes || codes.length === 0) return {};
            try {
                const r = await App.get('/api/live/stock_names?codes=' + encodeURIComponent(codes.join(',')));
                return (r && r.names) || {};
            } catch (e) {
                console.error('loadStockNames', e);
                return {};
            }
        },

        async loadQuote() {
            try {
                const r = await App.get('/api/live/watch_quotes?codes=' + encodeURIComponent(this.code));
                this.quote = (r && r.quotes && r.quotes[this.code]) || {};
            } catch (e) {
                console.error('loadQuote', e);
                this.quote = {};
            }
        },

        async loadKline() {
            if (!this.code) return;
            try {
                const qs = new URLSearchParams({ code: this.code, timeframe: 'daily', years: '1' });
                const r = await App.get('/api/stock-quote/quote?' + qs.toString());
                if (r && r.ok) {
                    this.klineData = r;
                    this.$nextTick(() => this.renderKline());
                } else {
                    this.klineData = null;
                }
            } catch (e) {
                console.error('loadKline', e);
                this.klineData = null;
            }
        },

        renderKline() {
            const el = document.getElementById('plan-kline-chart');
            if (!el || !this.klineData) return;
            const dates = this.klineData.dates || [];
            const ohlc = this.klineData.ohlc || [];
            if (!dates.length || !ohlc.length) return;

            if (!klineChart) {
                klineChart = echarts.init(el);
                // 自定义滚轮缩放: 以右边界为锚点, 放大时左边界左移, 缩小时左边界右移
                // (与个股详情页 K 线一致: 缩放时右侧时间不变, 左侧时间变化)
                klineChart.getZr().on('mousewheel', (e) => {
                    const event = e && e.event;
                    if (!event) return;
                    event.preventDefault && event.preventDefault();
                    event.stopPropagation && event.stopPropagation();
                    const delta = event.wheelDelta || -event.deltaY;
                    if (!delta) return;
                    const opt = klineChart.getOption();
                    const dz = opt.dataZoom && opt.dataZoom[0];
                    const xData = opt.xAxis && opt.xAxis[0] && opt.xAxis[0].data;
                    if (!dz || !xData || !xData.length) return;
                    let endValue = dz.endValue != null ? dz.endValue : xData.length - 1;
                    let startValue = dz.startValue != null ? dz.startValue : 0;
                    const currentCount = Math.max(1, endValue - startValue);
                    const factor = delta > 0 ? 0.9 : 1.1; // 向上滚轮放大, 向下滚轮缩小
                    const newCount = Math.max(10, Math.min(Math.round(currentCount * factor), xData.length - 1));
                    const newStartValue = Math.max(0, endValue - newCount);
                    klineChart.dispatchAction({ type: 'dataZoom', startValue: newStartValue, endValue: endValue });
                });
            }

            // 收盘价序列, 用于计算 MA
            const closes = ohlc.map(k => (k && k[1] != null) ? Number(k[1]) : null);
            const sma = (arr, n) => arr.map((_, i) => {
                if (i < n - 1) return null;
                let sum = 0, cnt = 0;
                for (let j = i - n + 1; j <= i; j++) {
                    if (arr[j] != null) { sum += arr[j]; cnt++; }
                }
                return cnt > 0 ? sum / cnt : null;
            });
            const ma20 = sma(closes, 20);
            const ma60 = sma(closes, 60);

            // 默认展示最近 120 根日线, 与个股行情页保持一致
            const total = dates.length;
            const zoomStart = total > 120 ? Math.max(0, (1 - 120 / total) * 100) : 0;

            // 收集触发价标注线
            const markLines = [];
            const addLine = (price, label, color) => {
                if (price > 0) {
                    markLines.push({
                        yAxis: price,
                        label: { formatter: label + ' ¥{c}', position: 'end', color: color, fontSize: 10 },
                        lineStyle: { color: color, type: 'dashed', width: 1.5 }
                    });
                }
            };
            (this.parsed.entry_conditions || []).forEach(c => addLine(c.trigger_price, '入场', '#059669'));
            (this.parsed.exit_plan?.take_profit || []).forEach(c => addLine(c.trigger_price, '止盈', '#16a34a'));
            (this.parsed.exit_plan?.stop_loss || []).forEach(c => addLine(c.trigger_price, '止损', '#dc2626'));
            (this.parsed.add_position_conditions || []).forEach(c => addLine(c.trigger_price, '加仓', '#4f46e5'));

            const option = {
                animation: false,
                grid: { left: '10%', right: '10%', bottom: '15%', top: '10%' },
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'cross' },
                    formatter: (params) => {
                        const idx = params[0].dataIndex;
                        const d = dates[idx];
                        const v = ohlc[idx];
                        let html = `<div class="font-mono text-xs"><div class="font-bold mb-1">${d || '-'}</div>`;
                        if (v && v[0] != null && v[1] != null && v[2] != null && v[3] != null) {
                            const up = v[1] >= v[0];
                            const color = up ? '#ef4444' : '#22c55e';
                            html += `<div>开: <span style="color:${color}">${Number(v[0]).toFixed(2)}</span> 收: <span style="color:${color}">${Number(v[1]).toFixed(2)}</span> 低: ${Number(v[2]).toFixed(2)} 高: ${Number(v[3]).toFixed(2)}</div>`;
                        }
                        const parts = [];
                        if (ma20[idx] != null) parts.push(`MA20: ${ma20[idx].toFixed(2)}`);
                        if (ma60[idx] != null) parts.push(`MA60: ${ma60[idx].toFixed(2)}`);
                        if (parts.length) html += `<div>${parts.join(' ')}</div>`;
                        html += '</div>';
                        return html;
                    }
                },
                xAxis: {
                    type: 'category',
                    data: dates,
                    axisLine: { lineStyle: { color: '#9ca3af' } },
                    axisLabel: { color: '#6b7280', fontSize: 10 }
                },
                yAxis: {
                    scale: true,
                    axisLine: { lineStyle: { color: '#9ca3af' } },
                    splitLine: { lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { color: '#6b7280', fontSize: 10 }
                },
                dataZoom: [
                    { type: 'inside', start: zoomStart, end: 100, zoomOnMouseWheel: false, moveOnMouseWheel: false },
                    { type: 'slider', start: zoomStart, end: 100, bottom: 10 }
                ],
                series: [
                    {
                        type: 'candlestick',
                        name: 'K线',
                        data: ohlc,
                        itemStyle: {
                            color: '#ef4444',
                            color0: '#22c55e',
                            borderColor: '#ef4444',
                            borderColor0: '#22c55e'
                        },
                        markLine: {
                            symbol: 'none',
                            data: markLines,
                            animation: false
                        }
                    },
                    {
                        type: 'line',
                        name: 'MA20',
                        data: ma20,
                        smooth: true,
                        showSymbol: false,
                        lineStyle: { color: '#f59e0b', width: 1 }
                    },
                    {
                        type: 'line',
                        name: 'MA60',
                        data: ma60,
                        smooth: true,
                        showSymbol: false,
                        lineStyle: { color: '#3b82f6', width: 1 }
                    }
                ]
            };
            klineChart.setOption(option, true);
        },

        currentCostText() {
            const cur = this.parsed.position_plan && this.parsed.position_plan.current;
            if (!cur || !cur.value || !cur.volume) return '—';
            return '¥' + (cur.value / cur.volume).toFixed(2);
        },

        nameForCode(code) {
            const item = this.watchList.find(x => x.code === code);
            return item ? item.name : '';
        },

        displayName() {
            const n = this.metadata.stock_name;
            if (n && n !== this.code) return n;
            const watchName = this.nameForCode(this.code);
            if (watchName && watchName !== this.code) return watchName;
            return '';
        },

        formatTriggerAndAction(cond) {
            if (!cond) return '';
            const side = cond.side || 'sell';
            const pct = cond.action_percent !== undefined ? Number(cond.action_percent) : 1.0;
            let actionText;
            if (side === 'buy') {
                actionText = pct >= 0.999 ? '市价全仓买入' : '市价买入 ' + (pct * 100).toFixed(0) + '%';
            } else {
                actionText = pct >= 0.999 ? '市价卖出 100%' : '市价卖出 ' + (pct * 100).toFixed(0) + '%';
            }
            let triggerText = '';
            if (cond.trigger_pct !== undefined && cond.trigger_pct !== 0) {
                triggerText = cond.trigger_pct > 0
                    ? '浮盈高于 ' + (cond.trigger_pct * 100).toFixed(1) + '%'
                    : '浮亏低于 ' + (Math.abs(cond.trigger_pct) * 100).toFixed(1) + '%';
            } else if (cond.trigger_price !== undefined && cond.trigger_price > 0) {
                triggerText = '触发价 ¥' + Number(cond.trigger_price).toFixed(2);
            } else {
                triggerText = '条件触发';
            }
            return triggerText + ' → ' + actionText;
        },

        conditionTriggerDesc(cond) {
            if (!cond) return '';
            const parts = [];
            if (cond.trigger_pct !== undefined && cond.trigger_pct !== 0) {
                parts.push((cond.trigger_pct > 0 ? '浮盈 +' : '浮亏 ') + (cond.trigger_pct * 100).toFixed(0) + '%');
            }
            if (cond.trigger_price !== undefined && cond.trigger_price > 0) {
                parts.push('触发价 ≈ ¥' + Number(cond.trigger_price).toFixed(2));
            }
            return parts.length ? parts.join(' · ') : '满足条件';
        },

        async loadPlanIndex() {
            try {
                const r = await App.get('/api/trade-plans?plan_type=' + this.planType);
                const idx = {};
                (r.items || []).forEach(p => { idx[p.stock_code] = p; });
                this.planIndex = idx;
            } catch (e) {
                console.error('loadPlanIndex', e);
                this.planIndex = {};
            }
        },

        formatCondition(cond) {
            const parts = [];
            if (cond.trigger_price !== undefined && cond.trigger_price > 0) {
                parts.push('触发价 ¥' + Number(cond.trigger_price).toFixed(2));
            }
            if (cond.trigger_pct !== undefined && cond.trigger_pct !== 0) {
                parts.push('触发比例 ' + (cond.trigger_pct > 0 ? '+' : '') + (cond.trigger_pct * 100).toFixed(1) + '%');
            }
            if (cond.action_percent !== undefined) {
                const pct = Number(cond.action_percent);
                const side = cond.side || 'sell';
                if (pct >= 0.999) {
                    parts.push(side === 'buy' ? '买入' : '清仓');
                } else {
                    parts.push((side === 'buy' ? '买入 ' : '卖出 ') + (pct * 100).toFixed(0) + '%');
                }
            }
            return parts.length ? parts.join(' · ') : '（未解析到数值）';
        },

        formatConditionDetail(cond) {
            if (!cond || !cond.raw) return '';
            return cond.raw;
        },

        normCode(code) {
            if (!code) return code;
            const c = String(code).trim();
            if (c.includes('.')) return c;
            if (/^\d{6}$/.test(c)) {
                const first = c.charAt(0);
                if (first === '6') return c + '.SH';
                if (first === '0' || first === '2' || first === '3') return c + '.SZ';
                if (first === '8' || first === '9') return c + '.BJ';
            }
            return c;
        }
    }
}
