function stockQuoteApp() {
    // ECharts 实例不放入 Alpine 响应式对象，避免 Proxy 破坏其内部状态（如 dataZoom 更新）
    let chart = null;

    return {
        code: (window.__stockQuoteCtx?.code ?? '000001.SH'),
        timeframe: 'daily',
        years: 3,
        searchQuery: '',
        searchResults: [],
        searchOpen: false,
        loadingQuote: false,
        quoteError: '',
        quote: null,
        loadingFinancial: false,
        financial: [],
        loadingNews: false,
        news: [],
        loadingConsensus: false,
        consensus: [],

        init() {
            const params = new URLSearchParams(location.search);
            this.code = params.get('code') || '000001.SH';
            const tf = params.get('timeframe') || 'daily';
            this.timeframe = ['daily', 'weekly', 'monthly'].includes(tf) ? tf : 'daily';
            this.loadAll();
            window.addEventListener('resize', () => {
                if (chart) chart.resize();
            });
        },

        async loadAll() {
            this.loadingQuote = true;
            this.loadingFinancial = true;
            this.loadingNews = true;
            this.loadingConsensus = true;
            this.quoteError = '';

            await Promise.all([
                this.loadQuote(),
                this.loadFinancial(),
                this.loadNews(),
                this.loadConsensus(),
            ]);
        },

        async loadQuote() {
            this.loadingQuote = true;
            try {
                const qs = new URLSearchParams({ code: this.code, timeframe: this.timeframe, years: String(this.years) });
                const r = await App.get('/api/stock-quote/quote?' + qs.toString());
                if (r.ok) {
                    this.quote = r;
                    this.quoteError = '';
                    this.$nextTick(() => this.renderChart());
                } else {
                    this.quote = null;
                    this.quoteError = r.message || '加载行情失败';
                }
            } catch (e) {
                this.quote = null;
                this.quoteError = '加载行情失败: ' + e.message;
            } finally {
                this.loadingQuote = false;
            }
        },

        async loadFinancial() {
            this.loadingFinancial = true;
            try {
                const r = await App.get('/api/stock-quote/financial?code=' + encodeURIComponent(this.code));
                this.financial = (r.ok ? r.items : []);
            } catch (e) {
                this.financial = [];
            } finally {
                this.loadingFinancial = false;
            }
        },

        async loadNews() {
            this.loadingNews = true;
            try {
                const r = await App.get('/api/stock-quote/news?code=' + encodeURIComponent(this.code));
                this.news = (r.ok ? r.items : []);
            } catch (e) {
                this.news = [];
            } finally {
                this.loadingNews = false;
            }
        },

        async loadConsensus() {
            this.loadingConsensus = true;
            try {
                const r = await App.get('/api/stock-quote/consensus?code=' + encodeURIComponent(this.code));
                this.consensus = (r.ok ? r.items : []);
            } catch (e) {
                this.consensus = [];
            } finally {
                this.loadingConsensus = false;
            }
        },

        async onSearchInput() {
            const q = this.searchQuery.trim();
            if (!q) {
                this.searchResults = [];
                this.searchOpen = false;
                return;
            }
            try {
                const r = await App.get('/api/stock-quote/search?q=' + encodeURIComponent(q));
                this.searchResults = (r.ok ? r.results : []);
                this.searchOpen = true;
            } catch (e) {
                this.searchResults = [];
                this.searchOpen = false;
            }
        },

        selectFirst() {
            if (this.searchResults.length) {
                this.selectStock(this.searchResults[0]);
            }
        },

        selectStock(item) {
            if (!item || !item.code) return;
            this.code = item.code;
            this.searchQuery = '';
            this.searchResults = [];
            this.searchOpen = false;
            // 切股票时彻底释放旧图表实例，避免旧 K 线数据/尺寸状态残留
            this.quote = null;
            this.quoteError = '';
            if (chart) {
                chart.dispose();
                chart = null;
            }
            const url = '/stock-quote?code=' + encodeURIComponent(this.code) + '&timeframe=' + this.timeframe;
            history.replaceState(null, '', url);
            this.loadAll();
        },

        switchTimeframe(tf) {
            if (this.timeframe === tf) return;
            if (!['daily', 'weekly', 'monthly'].includes(tf)) return;
            this.timeframe = tf;
            history.replaceState(null, '', '/stock-quote?code=' + encodeURIComponent(this.code) + '&timeframe=' + tf);
            // 切周期时先清空图表，避免旧数据残留导致渲染异常
            if (chart) {
                chart.clear();
            }
            this.loadQuote();
        },

        sentimentClass(s) {
            if (s === 'positive') return 'bg-red-100 text-red-700';
            if (s === 'negative') return 'bg-green-100 text-green-700';
            return 'bg-gray-100 text-gray-600';
        },
        sentimentText(s) {
            if (s === 'positive') return '正面';
            if (s === 'negative') return '负面';
            return '中性';
        },

        renderChart(retry = 0) {
            const el = document.getElementById('stock-kline-chart');
            if (!el || !this.quote || !this.quote.dates) return;

            // 确保容器已有实际尺寸；CSS 或布局未就绪时短暂延迟重试，避免 canvas 宽高为 0
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) {
                if (retry < 10) {
                    setTimeout(() => this.renderChart(retry + 1), 80);
                }
                return;
            }

            // 复用 chart 实例，避免 dispose/init 导致切换周期时偶发空白
            if (!chart) {
                chart = echarts.init(el);
                // 自定义滚轮缩放：以右边界为锚点，放大时左边界左移，缩小时左边界右移
                chart.getZr().on('mousewheel', (e) => {
                    const event = e && e.event;
                    if (!event) return;
                    event.preventDefault && event.preventDefault();
                    event.stopPropagation && event.stopPropagation();
                    const delta = event.wheelDelta || -event.deltaY;
                    if (!delta) return;
                    const opt = chart.getOption();
                    const dz = opt.dataZoom && opt.dataZoom[0];
                    const xData = opt.xAxis && opt.xAxis[0] && opt.xAxis[0].data;
                    if (!dz || !xData || !xData.length) return;
                    let endValue = dz.endValue != null ? dz.endValue : xData.length - 1;
                    let startValue = dz.startValue != null ? dz.startValue : 0;
                    const currentCount = Math.max(1, endValue - startValue);
                    const factor = delta > 0 ? 0.9 : 1.1; // 向上滚轮放大，向下滚轮缩小
                    const newCount = Math.max(10, Math.min(Math.round(currentCount * factor), xData.length - 1));
                    const newStartValue = Math.max(0, endValue - newCount);
                    chart.dispatchAction({ type: 'dataZoom', startValue: newStartValue, endValue: endValue });
                });
            } else {
                chart.clear();
            }

            const dates = this.quote.dates;
            const ohlc = this.quote.ohlc || [];
            const volume = this.quote.volume || [];
            const amount = this.quote.amount || [];
            const turnoverRate = this.quote.turnover_rate || [];
            const macd = this.quote.macd || { dif: [], dea: [], hist: [] };
            const closes = ohlc.map(k => k ? k[1] : null);

            // 计算简单移动平均线
            const sma = (arr, n) => arr.map((_, i) => {
                if (i < n - 1) return null;
                let sum = 0, c = 0;
                for (let j = 0; j < n; j++) {
                    const v = arr[i - j];
                    if (v != null) { sum += v; c++; }
                }
                return c > 0 ? +(sum / c).toFixed(4) : null;
            });
            const ma5 = sma(closes, 5);
            const ma10 = sma(closes, 10);
            const ma20 = sma(closes, 20);

            // 成交量颜色与 K 线方向一致
            const volumeData = volume.map((v, i) => {
                const up = ohlc[i] && ohlc[i][1] >= ohlc[i][0];
                return { value: v, itemStyle: { color: up ? '#ef4444' : '#22c55e' } };
            });

            // MACD 柱状图颜色（与 K 线红涨绿跌保持一致）
            const histData = (macd.hist || []).map(v => {
                if (v == null) return { value: 0, itemStyle: { color: 'transparent' } };
                return { value: v, itemStyle: { color: v >= 0 ? '#ef4444' : '#22c55e' } };
            });

            // 根据周期设置默认显示区间；后端已返回全量数据，这里仅控制默认缩放
            let zoomStart = 0, zoomEnd = 100;
            if (this.timeframe === 'daily') {
                // 日线默认展示最近 120 根（约半年）
                zoomStart = Math.max(0, (1 - 120 / dates.length) * 100);
                zoomEnd = 100;
            } else if (this.timeframe === 'weekly') {
                // 周线默认展示最近 104 根（约 2 年）
                zoomStart = Math.max(0, (1 - 104 / dates.length) * 100);
                zoomEnd = 100;
            } else if (this.timeframe === 'monthly') {
                // 月线默认展示最近 60 根（约 5 年）
                zoomStart = Math.max(0, (1 - 60 / dates.length) * 100);
                zoomEnd = 100;
            }

            const option = {
                animation: false,
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'cross' },
                    backgroundColor: 'rgba(255,255,255,0.98)',
                    borderColor: '#e5e7eb',
                    borderWidth: 1,
                    padding: [8, 10],
                    transitionDuration: 0,
                    hideDelay: 0,
                    textStyle: { color: '#374151', fontSize: 11 },
                    formatter: (params) => {
                        if (!params || !params.length) return '';
                        const idx = params[0].dataIndex;
                        if (idx == null || idx < 0 || idx >= dates.length) return '';
                        const d = dates[idx];
                        const k = ohlc[idx];
                        let html = `<div class="font-mono text-xs"><div class="font-bold mb-1">${d || '-'}</div>`;
                        if (k && Array.isArray(k) && k[0] != null && k[1] != null && k[2] != null && k[3] != null) {
                            const up = k[1] >= k[0];
                            const color = up ? '#ef4444' : '#22c55e';
                            html += `<div>开: <span style="color:${color}">${k[0].toFixed(2)}</span> 收: <span style="color:${color}">${k[1].toFixed(2)}</span> 低: ${k[2].toFixed(2)} 高: ${k[3].toFixed(2)}</div>`;
                        }
                        html += `<div>成交量: ${App.fmtNum(volume[idx] || 0, 0)}</div>`;
                        const amt = amount[idx];
                        if (amt != null) html += `<div>成交额: ${App.fmtNum(amt, 0)}</div>`;
                        const tr = turnoverRate[idx];
                        if (tr != null) html += `<div>换手率: ${tr.toFixed(2)}%</div>`;
                        const maParts = [];
                        if (ma5[idx] != null) maParts.push(`MA5: ${ma5[idx].toFixed(2)}`);
                        if (ma10[idx] != null) maParts.push(`MA10: ${ma10[idx].toFixed(2)}`);
                        if (ma20[idx] != null) maParts.push(`MA20: ${ma20[idx].toFixed(2)}`);
                        if (maParts.length) html += `<div>${maParts.join(' ')}</div>`;
                        const dif = macd.dif[idx], dea = macd.dea[idx], hist = macd.hist[idx];
                        const macdParts = [];
                        if (dif != null) macdParts.push(`DIF: ${dif.toFixed(3)}`);
                        if (dea != null) macdParts.push(`DEA: ${dea.toFixed(3)}`);
                        if (hist != null) macdParts.push(`HIST: ${hist.toFixed(3)}`);
                        if (macdParts.length) html += `<div>MACD ${macdParts.join(' ')}</div>`;
                        html += '</div>';
                        return html;
                    }
                },
                axisPointer: {
                    link: [{ xAxisIndex: 'all' }],
                    label: { backgroundColor: '#777' }
                },
                // 进一步增加整体高度与 MACD 子图高度，使图表更方正、趋势更陡峭
                grid: [
                    { left: '10%', right: '4%', top: '4%', height: '44%' },
                    { left: '10%', right: '4%', top: '51%', height: '18%' },
                    { left: '10%', right: '4%', top: '68%', height: '20%' }
                ],
                xAxis: [
                    { type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#d1d5db' } }, axisLabel: { show: false }, splitLine: { show: false } },
                    { type: 'category', data: dates, gridIndex: 1, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#d1d5db' } }, axisLabel: { show: false }, splitLine: { show: false } },
                    { type: 'category', data: dates, gridIndex: 2, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#d1d5db' } }, axisLabel: { color: '#6b7280', fontSize: 10 }, splitLine: { show: false } }
                ],
                yAxis: [
                    { scale: true, splitArea: { show: true, areaStyle: { color: ['rgba(250,250,250,0.5)', 'rgba(245,247,250,0.5)'] } }, axisLine: { show: false }, axisLabel: { color: '#6b7280', fontSize: 10 }, splitLine: { lineStyle: { color: '#e5e7eb', type: 'dashed' } } },
                    { scale: true, gridIndex: 1, splitNumber: 2, axisLine: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
                    { scale: true, gridIndex: 2, splitNumber: 2, axisLine: { show: false }, axisLabel: { color: '#6b7280', fontSize: 10 }, splitLine: { lineStyle: { color: '#e5e7eb', type: 'dashed' } } }
                ],
                dataZoom: [
                    { type: 'inside', xAxisIndex: [0, 1, 2], start: zoomStart, end: zoomEnd, filterMode: 'filter', zoomOnMouseWheel: false, moveOnMouseMove: true, moveOnMouseWheel: false },
                    {
                        type: 'slider',
                        filterMode: 'filter',
                        xAxisIndex: [0, 1, 2],
                        start: zoomStart,
                        end: zoomEnd,
                        height: 22,
                        bottom: 32,
                        left: '10%',
                        right: '4%',
                        borderColor: '#e5e7eb',
                        fillerColor: 'rgba(79,70,229,0.18)',
                        handleStyle: { color: '#4f46e5', borderColor: '#4f46e5', borderWidth: 1 },
                        handleSize: '70%',
                        backgroundColor: '#f9fafb',
                        dataBackground: { lineStyle: { color: '#d1d5db', width: 1 }, areaStyle: { color: '#e5e7eb' } },
                        selectedDataBackground: { lineStyle: { color: '#4f46e5', width: 1 }, areaStyle: { color: '#c7d2fe' } },
                        textStyle: { color: '#6b7280', fontSize: 10 },
                        brushSelect: false,
                        showDetail: true
                    }
                ],
                series: [
                    {
                        name: 'K线',
                        type: 'candlestick',
                        data: ohlc,
                        // 控制单根 K 线宽度，避免数据量大时实体过宽压盖影线
                        barMaxWidth: 10,
                        barMinWidth: 2,
                        itemStyle: {
                            color: '#ef4444',
                            color0: '#22c55e',
                            borderColor: '#ef4444',
                            borderColor0: '#22c55e',
                            borderWidth: 1
                        }
                    },
                    { name: 'MA5', type: 'line', data: ma5, showSymbol: false, smooth: false, lineStyle: { width: 1, color: '#f59e0b' } },
                    { name: 'MA10', type: 'line', data: ma10, showSymbol: false, smooth: false, lineStyle: { width: 1, color: '#3b82f6' } },
                    { name: 'MA20', type: 'line', data: ma20, showSymbol: false, smooth: false, lineStyle: { width: 1, color: '#8b5cf6' } },
                    {
                        name: '成交量',
                        type: 'bar',
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        data: volumeData
                    },
                    {
                        name: 'MACD-HIST',
                        type: 'bar',
                        xAxisIndex: 2,
                        yAxisIndex: 2,
                        data: histData
                    },
                    {
                        name: 'DIF',
                        type: 'line',
                        xAxisIndex: 2,
                        yAxisIndex: 2,
                        data: macd.dif,
                        showSymbol: false,
                        lineStyle: { width: 1, color: '#3b82f6' }
                    },
                    {
                        name: 'DEA',
                        type: 'line',
                        xAxisIndex: 2,
                        yAxisIndex: 2,
                        data: macd.dea,
                        showSymbol: false,
                        lineStyle: { width: 1, color: '#f59e0b' }
                    }
                ]
            };

            chart.setOption(option, true);
            this.$nextTick(() => {
                if (chart) chart.resize();
            });
        },
    };
}
