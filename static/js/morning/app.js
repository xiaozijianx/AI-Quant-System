function morningApp() {
    return {
        showHelp: false,
        running: false,
        elapsed: 0,
        status: '',
        industries: [],
        concepts: [],
        industryPicked: [],
        conceptPicked: [],
        messages: [],
        selectedStock: null,
        stockDetail: null,
        stockDetailLoading: false,
        detailTab: 'industry',
        params: {
            top_industries: 3,
            top_concepts: 3,
            top_stocks: 5,
            sample_per_industry: 15,
            lookback: 90,
            package_id: '',
        },
        factorPackages: [],
        timerId: null,

        get activePerspective() {
            if (!this.stockDetail) return {};
            // 优先使用当前 tab 对应的视角；不存在则自动切换到另一视角
            if (this.detailTab === 'concept' && this.stockDetail.concept_perspective) {
                return this.stockDetail.concept_perspective;
            }
            if (this.detailTab === 'industry' && this.stockDetail.industry_perspective) {
                return this.stockDetail.industry_perspective;
            }
            if (this.stockDetail.concept_perspective) {
                return this.stockDetail.concept_perspective;
            }
            if (this.stockDetail.industry_perspective) {
                return this.stockDetail.industry_perspective;
            }
            return {};
        },

        get factorGroups() {
            if (!this.stockDetail || !this.stockDetail.factor_group_map) return [];
            const raw = this.activePerspective.raw_factors || {};
            return Object.entries(this.stockDetail.factor_group_map)
                .map(([name, factors]) => ({
                    name,
                    factors: factors.filter(f => f in raw)
                }))
                .filter(g => g.factors.length);
        },

        // 当前选中的因子包对象（基于下拉值匹配），用于展示包信息与选股方式
        get selectedPackage() {
            return this.factorPackages.find(p => p.package_id === this.params.package_id) || null;
        },

        // 当前选股方式的展示文案：使用因子包时显示包名，否则默认等权
        get scoringDesc() {
            return this.selectedPackage
                ? '因子包: ' + this.selectedPackage.name
                : '多因子等权打分';
        },

        // 因子包合成方式中文名（与因子库多因子分析页一致）
        methodLabel(m) {
            const map = {
                equal: '等权', ic_weighted: 'IC加权(walk-forward)', rank_score: '排名打分',
                sharpe: '夏普加权', lasso: 'Lasso回归', markowitz: 'Markowitz最大夏普',
                optuna: 'Optuna权重优化', pca: 'PCA主成分',
                ml_reg: '机器学习-回归(预测收益)', ml_cls: '机器学习-分类(涨跌概率)',
            };
            return map[m] || m;
        },

        init() {
            // 启动时先从后端恢复已保存的分析参数 (多实例共享, 前后端解耦)
            this._restoreState().then(() => {
                // 恢复完成后才加载最近缓存与因子包列表
                this.loadCache(true);
                this.loadFactorPackages();
            });
        },

        // 从后端恢复晨会分析参数 (换端口/刷新后仍保留用户上次配置)
        _restoreState() {
            return App.get('/api/page-settings/morning').then(res => {
                const s = (res && res.data) || {};
                if (s.params && typeof s.params === 'object') {
                    // 仅覆盖合法的数值/字符串参数, 保证旧数据/脏数据不会挤进前端
                    const allowed = ['top_industries', 'top_concepts', 'top_stocks',
                                    'sample_per_industry', 'lookback', 'package_id'];
                    for (const key of allowed) {
                        if (s.params[key] !== undefined && s.params[key] !== null) {
                            this.params[key] = s.params[key];
                        }
                    }
                }
                // deep watch: 用户改动任一参数即自动保存到后端
                this.$watch('params', () => this._saveState(), { deep: true });
            }).catch(e => {
                console.warn('恢复晨会参数失败:', e);
                this.$watch('params', () => this._saveState(), { deep: true });
            });
        },

        // 保存晨会分析参数到后端 (多实例共享, 前端不保存数据)
        _saveState() {
            App.post('/api/page-settings/morning', {
                params: { ...this.params },
            }).catch(e => {
                console.warn('保存晨会参数失败:', e);
            });
        },

        async loadFactorPackages() {
            try {
                const r = await App.get('/api/factor/packages');
                this.factorPackages = r.packages || [];
            } catch (e) {
                // 因子包列表加载失败不阻塞晨会
            }
        },

        formatRawFactor(key, val) {
            if (val === null || val === undefined || isNaN(val)) return '-';
            const pctFactors = ['MOM_1M', 'MOM_3M', 'MOM_6M', 'REV_5D', 'NetProfit_YoY'];
            if (pctFactors.includes(key)) return (val * 100).toFixed(2) + '%';
            if (['ROE', 'GrossMargin', 'NegDebtRatio'].includes(key)) return val.toFixed(2) + '%';
            if (['VOL_20', 'VOL_60'].includes(key)) return (val * 100).toFixed(2) + '%';
            return val.toFixed(3);
        },

        factorZColor(z) {
            if (z === null || z === undefined || isNaN(z)) return 'text-gray-300';
            if (z > 0) return 'text-red-600';
            if (z < 0) return 'text-green-600';
            return 'text-gray-400';
        },

        formatZScore(z) {
            if (z === null || z === undefined || isNaN(z)) return '-';
            return (z > 0 ? '+' : '') + Number(z).toFixed(2);
        },

        selectStock(p) {
            this.selectedStock = p;
            // 优先使用选股阶段已预计算的详情数据，避免点击后重新计算
            const hasPerspective = p.detail && (
                p.detail.industry_perspective || p.detail.concept_perspective
            );
            if (hasPerspective) {
                this.stockDetail = p.detail;
                this.detailTab = p.perspective || 'industry';
                this.stockDetailLoading = false;
                return;
            }
            // 兼容旧缓存或异常缺失：回退到 API
            console.warn('选股结果中缺少预计算 detail，回退 API:', p.code);
            this.fetchStockDetailFallback(p);
        },

        async fetchStockDetailFallback(p) {
            this.stockDetail = null;
            this.stockDetailLoading = true;
            this.detailTab = 'industry';
            try {
                const qs = new URLSearchParams({
                    code: p.code,
                    top_industries: this.params.top_industries,
                    top_concepts: this.params.top_concepts,
                    sample_per_industry: this.params.sample_per_industry,
                    lookback: this.params.lookback,
                });
                const r = await App.get('/api/morning/stock-detail?' + qs.toString());
                if (r.ok) {
                    this.stockDetail = r;
                    if (!r.industry_perspective && r.concept_perspective) {
                        this.detailTab = 'concept';
                    }
                } else {
                    App.toast(r.error || '加载详情失败', 'warn');
                }
            } catch (e) {
                console.error('加载股票详情失败:', e);
                App.toast('加载详情失败', 'danger');
            } finally {
                this.stockDetailLoading = false;
            }
        },

        async loadCache(silent = false) {
            const r = await App.get('/api/morning/cache');
            if (r.error) {
                if (!silent) App.toast(r.error, 'warn');
                return;
            }
            this.industries = r.industry_rank || [];
            this.concepts = r.concept_industry_rank || [];
            this.industryPicked = r.industry_picked_stocks || [];
            this.conceptPicked = r.concept_picked_stocks || [];
            this.messages = r.messages || [];
            this.status = r.saved_at
                ? `<div class="text-xs text-gray-500">缓存数据 (保存于 ${r.saved_at})</div>`
                : '';
            this.elapsed = 0;
        },

        async trigger() {
            this.running = true;
            this.industries = [];
            this.concepts = [];
            this.industryPicked = [];
            this.conceptPicked = [];
            this.messages = [];
            this.status = `<span class="qa-loader">准备启动 6 节点工作流（板块 + 概念并行）<span class="qa-loader-dots"><i></i><i></i><i></i></span></span>`;
            this.elapsed = 0;

            const t0 = Date.now();
            this.timerId = setInterval(() => {
                this.elapsed = ((Date.now() - t0) / 1000).toFixed(1);
            }, 250);

            // SSE 流式
            const url = '/api/morning/stream?'
                + new URLSearchParams(this.params).toString();
            const es = new EventSource(url);

            es.addEventListener('progress', (e) => {
                const d = JSON.parse(e.data);
                this.status = `<div class="text-sm text-gray-600">当前节点: <b>${d.current_node}</b> (${d.estimate || ''})</div>`
                    + `<div class="mt-2"><span class="qa-loader">${d.message}<span class="qa-loader-dots"><i></i><i></i><i></i></span></span></div>`;
            });

            es.addEventListener('node_done', (e) => {
                const d = JSON.parse(e.data);
                this.industries = d.industry_rank || [];
                this.concepts = d.concept_industry_rank || [];
                this.industryPicked = d.industry_picked_stocks || [];
                this.conceptPicked = d.concept_picked_stocks || [];
                this.messages = d.messages || [];
                this.status = `<div class="text-sm text-green-700">完成: <b>${d.node_label}</b></div>`;
            });

            es.addEventListener('done', (e) => {
                const d = JSON.parse(e.data);
                this.industries = d.industry_rank || [];
                this.concepts = d.concept_industry_rank || [];
                this.industryPicked = d.industry_picked_stocks || [];
                this.conceptPicked = d.concept_picked_stocks || [];
                this.messages = d.messages || [];
                this.status = `<div class="text-sm text-green-700"><b>全部完成</b> -- Top ${this.industries.length} 板块, Top ${this.concepts.length} 概念, 选出 ${this.industryPicked.length + this.conceptPicked.length} 只标的</div>`;
                this.running = false;
                if (this.timerId) clearInterval(this.timerId);
                es.close();
            });

            es.addEventListener('error_event', (e) => {
                const d = JSON.parse(e.data);
                this.status = `<div class="text-sm text-red-700">[ERROR] ${d.error}</div>`;
                this.running = false;
                if (this.timerId) clearInterval(this.timerId);
                es.close();
            });

            es.onerror = (e) => {
                if (this.running) {
                    this.status = `<div class="text-sm text-red-700">[连接断开]</div>`;
                    this.running = false;
                    if (this.timerId) clearInterval(this.timerId);
                }
                es.close();
            };
        },
    }
}
