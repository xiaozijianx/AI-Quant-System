function dragonReviewApp() {
    return {
        loading: false,
        detailLoading: false,
        days: 5,
        endDate: '',
        hasMore: false,
        rows: [],
        hasData: false,
        statusText: '暂无数据',
        selected: null,
        selectedType: '',
        selectedName: '',
        selectedDate: '',
        sectorDetail: {},
        conceptDetail: {},
        stockDetail: {},
        sectorHistory: [],
        conceptHistory: [],
        params: {
            volume_ma: 20,
            volume_ratio_ma: 1.2,
            volume_ratio_ring: 1.05,
            max_limit_down: 10,
            min_up_down_ratio: 3.0,
            min_rise_ratio: 0.5,
            sector_short_lookback: 10,
            sector_short_return_pct: 15,
            sector_long_lookback: 30,
            sector_long_return_pct: 30,
            sector_max_board_level: 3,
            concept_short_lookback: 10,
            concept_short_return_pct: 8,
            concept_long_lookback: 30,
            concept_long_return_pct: 20,
            concept_max_board_level: 3,
            stock_gain_days: 10,
            stock_gain_limit: 20,
            concept_similarity_threshold: 0.4,
            // 板块打分权重 [涨停率, 涨停数量, 平均涨幅, 人均成交额, 成交额环比]
            sector_weights: [0.30, 0.25, 0.25, 0.10, 0.10],
            // 概念打分权重 [涨停率, 涨停数量, 平均涨幅, 人均成交额, 成交额环比]
            concept_weights: [0.30, 0.25, 0.25, 0.10, 0.10],
            concept_min_limit_up: 2,
            concept_min_stock_count: 10,
            // 龙头股前 4 维权重 [涨停强度, 量能强度, 换手健康, 位置安全]，与相关性权重一起归一化
            leader_weights: [0.45, 0.30, 0.15, 0.10],
            // 量能分内部：成交量分权重，放量分权重 = 1 - amount_weight
            amount_weight: 0.6,
            // 龙头股相关性权重（板块/概念联动程度）
            sector_relevance_weight: 0.10,
            concept_relevance_weight: 0.10,
        },

        _restoreState() {
            // 参数统一存后端 (多实例共享, 前后端解耦), 前端不再保存数据
            return App.get('/api/page-settings/dragon_review').then(res => {
                const state = (res && res.data) || {};
                if (state.days && [5, 10, 15].includes(Number(state.days))) {
                    this.days = Number(state.days);
                }
                if (state.endDate) this.endDate = state.endDate;
                if (state.params && typeof state.params === 'object') {
                    this.params = { ...this.params, ...state.params };
                }
            }).catch(e => {
                console.warn('恢复龙头复盘状态失败:', e);
            });
        },

        _saveState() {
            // 参数统一保存到后端, 多实例共享 (前端不再持有数据)
            App.post('/api/page-settings/dragon_review', {
                days: this.days,
                endDate: this.endDate,
                params: this.params,
            }).catch(e => {
                console.warn('保存龙头复盘状态失败:', e);
            });
        },

        async init() {
            await this._restoreState();
            this.$watch('days', () => this._saveState());
            this.$watch('endDate', () => this._saveState());
            this.$watch('params', () => this._saveState(), { deep: true });
            if (!this.endDate) {
                this.endDate = new Date().toISOString().split('T')[0];
            }
            await this.loadMatrix();
            // 支持 URL 参数 ?stock=CODE&date=DATE 自动打开个股详情
            this._applyUrlParams();
        },

        _applyUrlParams() {
            try {
                const params = new URLSearchParams(window.location.search);
                const stockCode = params.get('stock');
                const stockDate = params.get('date');
                if (stockCode && stockDate) {
                    // 异步加载个股信息以获取名称
                    this._loadStockNameAndSelect(stockCode, stockDate);
                }
            } catch (e) {
                console.warn('解析 URL 参数失败:', e);
            }
        },

        async _loadStockNameAndSelect(code, date) {
            try {
                const res = await App.get(`/api/dragon-review/stock-detail?code=${encodeURIComponent(code)}&date=${date}`);
                const name = res.ok && res.info ? (res.info.name || code) : code;
                this.selectStock(code, name, date);
            } catch (e) {
                console.warn('根据 URL 参数加载个股详情失败:', e);
                this.selectStock(code, code, date);
            }
        },

        async loadMatrix() {
            this.loading = true;
            try {
                const p = this.params;
                const endParam = this.endDate ? `&end_date=${this.endDate}` : '';
                const res = await App.get(
                    `/api/dragon-review/matrix?days=${this.days}${endParam}` +
                    `&ma_days=${p.volume_ma}` +
                    `&volume_ratio_ma=${p.volume_ratio_ma}` +
                    `&volume_ratio_ring=${p.volume_ratio_ring}` +
                    `&max_limit_down=${p.max_limit_down}` +
                    `&min_up_down_ratio=${p.min_up_down_ratio}` +
                    `&min_rise_ratio=${p.min_rise_ratio}` +
                    `&sector_short_lookback=${p.sector_short_lookback}` +
                    `&sector_short_return_pct=${p.sector_short_return_pct}` +
                    `&sector_long_lookback=${p.sector_long_lookback}` +
                    `&sector_long_return_pct=${p.sector_long_return_pct}` +
                    `&sector_max_board_level=${p.sector_max_board_level}` +
                    `&concept_short_lookback=${p.concept_short_lookback}` +
                    `&concept_short_return_pct=${p.concept_short_return_pct}` +
                    `&concept_long_lookback=${p.concept_long_lookback}` +
                    `&concept_long_return_pct=${p.concept_long_return_pct}` +
                    `&concept_max_board_level=${p.concept_max_board_level}` +
                    `&stock_gain_days=${p.stock_gain_days}` +
                    `&stock_gain_limit=${p.stock_gain_limit}` +
                    `&concept_similarity_threshold=${p.concept_similarity_threshold}` +
                    `&sector_weights=${p.sector_weights.join(',')}` +
                    `&concept_weights=${p.concept_weights.join(',')}` +
                    `&concept_min_limit_up=${p.concept_min_limit_up}` +
                    `&concept_min_stock_count=${p.concept_min_stock_count}` +
                    `&leader_weights=${p.leader_weights.join(',')}` +
                    `&amount_weight=${p.amount_weight}` +
                    `&sector_relevance_weight=${p.sector_relevance_weight}` +
                    `&concept_relevance_weight=${p.concept_relevance_weight}`
                );
                if (!res.ok) {
                    this.statusText = res.message || '加载失败';
                    this.hasData = false;
                    return;
                }
                this.rows = res.rows || [];
                this.hasMore = res.has_more || false;
                this.hasData = this.rows.length > 0;
                this.statusText = this.rangeText;
            } catch (e) {
                console.error('加载矩阵失败:', e);
                this.statusText = '加载失败';
                this.hasData = false;
            } finally {
                this.loading = false;
            }
        },

        get rangeText() {
            if (!this.rows.length) return `${this.endDate || '最新'} 往前 ${this.days} 个交易日`;
            const start = this.rows[this.rows.length - 1].date;
            const end = this.rows[0].date;
            return `${start} ~ ${end} 共 ${this.rows.length} 个交易日`;
        },

        setDays(n) {
            this.days = n;
            this.loadMatrix();
        },

        get detailSubtitle() {
            if (!this.selected) return '点击左侧板块、概念或个股查看详情';
            return `${this.selectedName} @ ${this.selectedDate}`;
        },

        selectSector(name, date) {
            this.selected = { type: 'sector', name, date };
            this.selectedType = 'sector';
            this.selectedName = name;
            this.selectedDate = date;
            this.loadSectorDetail(name, date);
        },

        async loadSectorDetail(name, date) {
            this.detailLoading = true;
            try {
                const [detailRes, indexRes] = await Promise.all([
                    App.get(`/api/sector-rotation/detail?sector=${encodeURIComponent(name)}&date=${date}`),
                    App.get(`/api/sector-rotation/sector-index?sector=${encodeURIComponent(name)}&years=2`),
                ]);
                this.sectorDetail = detailRes.ok ? detailRes.detail : {};
                this.sectorHistory = detailRes.ok ? (detailRes.history || []) : [];
                this.$nextTick(() => {
                    this.drawRankChart('sectorRankChart', this.sectorHistory, 'rank', 'composite_rank');
                    this.drawLineChart(indexRes.ok ? indexRes : null, 'sectorPriceChart', '板块指数');
                    // 延迟 resize，确保容器已完成布局
                    setTimeout(() => {
                        this.resizeChart('sectorRankChart');
                        this.resizeChart('sectorPriceChart');
                    }, 100);
                });
            } catch (e) {
                console.error('加载板块详情失败:', e);
                App.toast('加载板块详情失败', 'warn');
            } finally {
                this.detailLoading = false;
            }
        },

        selectConcept(name, code, date) {
            if (!code) {
                App.toast('该概念暂无编码，无法查看详情', 'warn');
                return;
            }
            this.selected = { type: 'concept', name, code, date };
            this.selectedType = 'concept';
            this.selectedName = name;
            this.selectedDate = date;
            this.loadConceptDetail(name, code, date);
        },

        async loadConceptDetail(name, code, date) {
            this.detailLoading = true;
            try {
                const [detailRes, indexRes] = await Promise.all([
                    App.get(`/api/concept-rotation/detail?concept_code=${encodeURIComponent(code)}&date=${date}`),
                    App.get(`/api/concept-rotation/concept-index?concept_code=${encodeURIComponent(code)}&years=1`),
                ]);
                this.conceptDetail = detailRes.ok ? detailRes.detail : {};
                this.conceptHistory = detailRes.ok ? (detailRes.history || []) : [];
                this.$nextTick(() => {
                    this.drawRankChart('conceptRankChart', this.conceptHistory, 'rank', 'composite_rank');
                    this.drawLineChart(indexRes.ok ? indexRes : null, 'conceptPriceChart', '概念指数');
                    setTimeout(() => {
                        this.resizeChart('conceptRankChart');
                        this.resizeChart('conceptPriceChart');
                    }, 100);
                });
            } catch (e) {
                console.error('加载概念详情失败:', e);
                App.toast('加载概念详情失败', 'warn');
            } finally {
                this.detailLoading = false;
            }
        },

        selectStock(code, name, date) {
            this.selected = { type: 'stock', code, name, date };
            this.selectedType = 'stock';
            this.selectedName = name;
            this.selectedDate = date;
            this.loadStockDetail(code, date);
        },

        // 将研报分析 prompt 注入右侧 AI 输入框（对标模拟盘 AI 分析按钮的 preload 用法）
        preloadResearchReport() {
            const code = this.stockDetail.code || this.selected?.code;
            const name = this.stockDetail.info?.name || this.selectedName || this.selected?.name;
            if (!code) {
                App.toast('未获取到股票代码，无法生成研报分析', 'warn');
                return;
            }
            const prompt = `请帮我完成${name}(${code})的研报分析。`;
            if (typeof AI_CHAT !== 'undefined' && AI_CHAT.preload) {
                AI_CHAT.preload(prompt);
                App.toast('研报分析 prompt 已填入 AI 助手输入框', 'success');
            } else {
                App.toast('AI 助手未加载，请刷新页面后重试', 'warn');
            }
        },

        async loadStockDetail(code, date) {
            this.detailLoading = true;
            try {
                const res = await App.get(`/api/dragon-review/stock-detail?code=${encodeURIComponent(code)}&date=${date}`);
                if (!res.ok) {
                    App.toast(res.message || '加载个股详情失败', 'warn');
                    return;
                }
                this.stockDetail = res;
                this.$nextTick(() => {
                    this.drawStockKline(res.quote);
                    setTimeout(() => {
                        this.resizeChart('priceChart');
                    }, 100);
                });
            } catch (e) {
                console.error('加载个股详情失败:', e);
                App.toast('加载个股详情失败', 'warn');
            } finally {
                this.detailLoading = false;
            }
        },

        drawRankChart(elementId, history, rankField, compositeField) {
            if (!history || !history.length) {
                Plotly.purge(elementId);
                return;
            }
            const dates = history.map(h => h.date);
            const ranks = history.map(h => h[rankField]);
            const compositeRanks = history.map(h => h[compositeField]);
            Plotly.newPlot(elementId, [
                {
                    x: dates, y: ranks, mode: 'lines+markers', name: '强度排名',
                    line: { color: '#dc2626', width: 2 }, marker: { size: 4 }, yaxis: 'y'
                },
                {
                    x: dates, y: compositeRanks, mode: 'lines+markers', name: '综合排名',
                    line: { color: '#2563eb', width: 2, dash: 'dot' }, marker: { size: 4 }, yaxis: 'y'
                }
            ], {
                autosize: true,
                margin: { t: 10, r: 10, b: 30, l: 30 },
                xaxis: { tickangle: -30, tickfont: { size: 10 } },
                yaxis: { autorange: 'reversed', tickfont: { size: 10 } },
                legend: { orientation: 'h', y: 1.12, x: 0.5, xanchor: 'center' },
                paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)'
            }, { responsive: true, displayModeBar: false });
        },

        drawLineChart(data, elementId, name) {
            if (!data || !data.dates || !data.dates.length) {
                Plotly.purge(elementId);
                return;
            }
            const closeKey = data.close !== undefined ? 'close' : 'close_idx';
            const closes = data[closeKey] || [];
            Plotly.newPlot(elementId, [{
                x: data.dates, y: closes, mode: 'lines', name: name,
                line: { color: '#059669', width: 2 }, fill: 'tozeroy', fillcolor: 'rgba(5,150,105,0.08)'
            }], {
                autosize: true,
                margin: { t: 10, r: 10, b: 30, l: 50 },
                xaxis: { tickangle: -30, tickfont: { size: 10 }, rangeslider: { visible: false } },
                yaxis: { tickfont: { size: 10 } },
                paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)'
            }, { responsive: true, displayModeBar: false });
        },

        drawStockKline(quote) {
            if (!quote || !quote.ok || !quote.dates || !quote.dates.length) {
                Plotly.purge('priceChart');
                return;
            }
            // 取最近 60 根
            const n = quote.dates.length;
            const start = Math.max(0, n - 60);
            const dates = quote.dates.slice(start);
            const ohlc = quote.ohlc.slice(start);
            const opens = ohlc.map(x => x[0]);
            const closes = ohlc.map(x => x[1]);
            const lows = ohlc.map(x => x[2]);
            const highs = ohlc.map(x => x[3]);
            const volumes = (quote.volume || []).slice(start);

            // 均线计算，不足周期返回 null
            const ma = (arr, len) => arr.map((_, i) => {
                if (i < len - 1) return null;
                let s = 0;
                for (let j = i - len + 1; j <= i; j++) s += arr[j];
                return Math.round(s / len * 100) / 100;
            });
            const ma5 = ma(closes, 5);
            const ma10 = ma(closes, 10);

            // 日期刻度只保留首、中、尾三个，显示为 YYYY-MM，避免拥挤
            const fmtMonth = (d) => d ? d.slice(0, 7) : d;
            const tickVals = dates.length > 2
                ? [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]]
                : dates;
            const tickText = tickVals.map(fmtMonth);
            // 类别轴，每根 K 线等距排列，消除非交易日的日历空隙
            const xaxisConfig = {
                type: 'category',
                tickvals: tickVals,
                ticktext: tickText,
                tickangle: 0, tickfont: { size: 9 },
                rangeslider: { visible: false },
                showgrid: false
            };

            // 主图：K 线 + MA5/MA10 趋势线
            const traces = [
                {
                    x: dates, open: opens, high: highs, low: lows, close: closes,
                    type: 'candlestick', name: 'K线',
                    increasing: { line: { color: '#ef4444', width: 1 }, fillcolor: '#fecaca' },
                    decreasing: { line: { color: '#22c55e', width: 1 }, fillcolor: '#bbf7d0' },
                    xaxis: 'x2', yaxis: 'y'
                },
                {
                    x: dates, y: ma5, type: 'scatter', mode: 'lines',
                    name: 'MA5', line: { color: '#f59e0b', width: 1.2 }, xaxis: 'x2', yaxis: 'y'
                },
                {
                    x: dates, y: ma10, type: 'scatter', mode: 'lines',
                    name: 'MA10', line: { color: '#3b82f6', width: 1.2 }, xaxis: 'x2', yaxis: 'y'
                }
            ];

            // 底部成交量柱（数据完整时追加）
            if (volumes && volumes.length === dates.length) {
                traces.push({
                    x: dates, y: volumes, type: 'bar', name: '成交量',
                    marker: { color: volumes.map((v, i) =>
                        closes[i] >= opens[i] ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)') },
                    xaxis: 'x', yaxis: 'y2'
                });
            }

            Plotly.newPlot('priceChart', traces, {
                autosize: true,
                margin: { t: 22, r: 24, b: 30, l: 28 },
                xaxis: { ...xaxisConfig, anchor: 'y2', domain: [0, 1] },
                xaxis2: { ...xaxisConfig, anchor: 'y', domain: [0, 1] },
                yaxis: { domain: [0.28, 1], tickfont: { size: 10 }, showgrid: true, gridcolor: 'rgba(0,0,0,0.06)' },
                yaxis2: { domain: [0, 0.22], tickfont: { size: 9 }, showgrid: false },
                legend: { orientation: 'h', y: 1.09, yref: 'paper', x: 0, xanchor: 'left',
                           font: { size: 6 }, itemwidth: 12, traceorder: 'normal', tracegroupgap: 0 },
                paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)'
            }, { responsive: true, displayModeBar: false });
        },

        resizeChart(elementId) {
            const el = document.getElementById(elementId);
            if (!el) return;
            try {
                Plotly.Plots.resize(el);
            } catch (e) {
                // 元素尚未初始化或已被 purge，忽略
            }
        },

        formatAmount(v) {
            if (v === null || v === undefined || isNaN(v)) return '-';
            const n = Number(v);
            if (n >= 1e12) return (n / 1e12).toFixed(2) + '万亿';
            if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿';
            if (n >= 1e4) return (n / 1e4).toFixed(2) + '万';
            return n.toFixed(0);
        },

        formatAmountSmall(v) {
            if (v === null || v === undefined || isNaN(v)) return '-';
            const n = Number(v);
            if (n >= 1e8) return (n / 1e8).toFixed(1) + '亿';
            if (n >= 1e4) return (n / 1e4).toFixed(1) + '万';
            return n.toFixed(0);
        },

        formatDate(dateStr) {
            const d = new Date(dateStr);
            return `${d.getMonth() + 1}/${d.getDate()}`;
        },

        fmt(v, digits = 2) {
            if (v === null || v === undefined || isNaN(v)) return '-';
            return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
        },

        fmtSign(v, digits = 2, suffix = '') {
            if (v === null || v === undefined || isNaN(v)) return '-';
            const n = Number(v);
            const sign = n > 0 ? '+' : '';
            return sign + n.toFixed(digits) + suffix;
        },

        pnlClass(v) {
            if (v === null || v === undefined || isNaN(v)) return '';
            return Number(v) > 0 ? 'pos' : (Number(v) < 0 ? 'neg' : '');
        },

        fieldName(field) {
            const map = {
                score: '强度得分', composite_score: '综合得分', rank: '排名',
                composite_rank: '综合排名', phase_desc: '轮动象限', member_count: '成份股数'
            };
            return map[field] || field;
        }
    };
}
