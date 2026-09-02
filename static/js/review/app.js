function reviewApp() {
    // 默认日期: 2026-04-01 至今 (跟模拟盘 SIM_HISTORY_START_DATE 保持一致)
    const today = new Date();
    const fmtDate = (d) => d.toISOString().slice(0, 10);

    return {
        showHelp: false,
        subTab: 'brinson',
        // ---- 交割单 CSV 文件列表 (交割单面板 + Brinson csv 数据源 共享) ----
        csvFiles: [],                     // [{name, path, label}, ...] 由 GET /trade_csv_files 填充
        csvPath:  '',                     // 当前选中的 CSV 绝对路径
        // ---- 交割单 / 历史成交 (跟随 brSource 自动推导, csv 或 sim 模式才有流水) ----
        trReport: null,                   // {ok, source, source_label, real_cost, rows, summary}
        trError: '',
        trRunning: false,
        trAutoLoaded: false,              // 第一次展开时自动加载, 避免空状态
        trOpen:    false,                 // details 折叠当前是否展开 (toggle 同步)
        // ---- Brinson 数据 + 控制 ----
        brSource: 'sim',                  // 'sim' | 'real' | 'csv' | 'demo' -- 默认模拟盘快照
        brStart: '2026-04-01',
        brEnd:   fmtDate(today),
        brinson: null,                    // 归因核心结果 (扁平: portfolio_return / by_industry / ...)
        brinsonReal: null,                // 真实数据完整 response (含 positions_detail / industry_map / params)
        brinsonError: '',
        brinsonRunning: false,
        indMapBusy: false,
        // ---- Walk-Forward 过拟合检测 ----
        wfCode:    '600519.SH',
        wfCount:   800,
        wfTrain:   120,
        wfTest:    60,
        wfReport:  null,
        wfError:   '',
        wfRunning: false,
        // 标的快捷预设 (覆盖大盘蓝筹 / 成长 / 周期 / 银行, 方便快速切换)
        wfPresets: [
            { code: '600519.SH', label: '茅台 600519' },
            { code: '601318.SH', label: '中国平安 601318' },
            { code: '300750.SZ', label: '宁德时代 300750' },
            { code: '600036.SH', label: '招行 600036' },
            { code: '000858.SZ', label: '五粮液 000858' },
        ],
        // 策略列表 (从 /api/review/wf_strategies 拉取, 含 key/label/description/param_text_hint/defaults_text)
        wfStrategies: [],
        wfStrategiesLoaded: false,
        wfStrategy: 'double_ma',
        // 当前策略的参数候选 textarea 内容 (策略切换时自动用 defaults_text 重置)
        wfParamGridText: '',
        // 是否展开"高级"区域 (参数候选编辑); 默认收起, 用默认 6 组够用 80% 场景
        wfShowAdvanced: false,
        // ---- 策略生命周期 ----
        registry: null,
        lifecycleLog: '',
        // ---- 生命周期 真实数据 (sim / real) ----
        lcSim: null,
        lcSimSource: 'sim',           // 'sim' | 'real'
        lcSimFromStage: 'paper',
        lcSimRunning: false,
        snapBusy: false,

        /** Alpine 生命周期 init -- 读 URL hash 决定初始 tab + 监听切换同步 hash
         *
         * 设计:
         *   - hash 形如 #brinson / #walkforward / #lifecycle, F5 后 / 直接打开 URL 都能定位到指定 tab
         *   - subTab 变化 -> 自动写 hash, 同时按 tab 跑数据加载副作用 (ensureWfStrategiesLoaded / loadRegistry)
         *     这样按钮 @click 即使不写副作用也会自动加载, 是兜底; 现有按钮的副作用调用是冗余但幂等, 保留
         *   - 监听 hashchange -> 浏览器前进 / 后退按钮也能切 tab
         */
        init() {
            const validTabs = ['brinson', 'walkforward', 'lifecycle'];
            const applyTabSideEffects = () => {
                if (this.subTab === 'walkforward') this.ensureWfStrategiesLoaded();
                else if (this.subTab === 'lifecycle') this.loadRegistry();
            };
            // 1) 从 hash 读初始 tab (无效 hash 走默认 brinson)
            const initial = (location.hash || '').replace(/^#/, '');
            if (validTabs.includes(initial)) {
                this.subTab = initial;
            }
            // 2) subTab 变化 -> 同步写 hash + 加载数据
            this.$watch('subTab', (v) => {
                const cur = (location.hash || '').replace(/^#/, '');
                if (cur !== v) {
                    // 用 replaceState 避免污染浏览器历史 (每点一次 tab 不应是一个独立的"后退点")
                    history.replaceState(null, '', '#' + v);
                }
                applyTabSideEffects();
            });
            // 3) 浏览器前进 / 后退 -> 同步切 subTab
            window.addEventListener('hashchange', () => {
                const h = (location.hash || '').replace(/^#/, '');
                if (validTabs.includes(h) && h !== this.subTab) {
                    this.subTab = h;
                }
            });
            // 4) 初次进入也跑一次副作用 (默认 brinson 时无副作用; walkforward / lifecycle 时要拉数据)
            applyTabSideEffects();
            // 5) 原有: 拉 CSV 文件清单
            this.loadCsvFiles();
        },

        /** 进 review 页时拉一次 CSV 文件清单 (data/ 下 历史成交_*.csv) */
        async loadCsvFiles() {
            try {
                const r = await App.get('/api/review/trade_csv_files');
                if (r && r.ok && Array.isArray(r.files) && r.files.length > 0) {
                    this.csvFiles = r.files;
                    if (!this.csvPath) {
                        this.csvPath = r.default || r.files[0].path;
                    }
                }
            } catch (e) { /* 静默失败, 后端默认走 DEFAULT_CSV_PATH */ }
        },

        /** 加载交割单 -- source 从 brSource 推导 (csv / sim 才有流水, real / demo 跳过) */
        async runTradeRecord() {
            if (this.trRunning) return;
            if (this.brSource !== 'csv' && this.brSource !== 'sim') {
                this.trReport = null;
                return;
            }
            this.trError = '';
            this.trRunning = true;
            try {
                const body = { source: this.brSource };
                if (this.brSource === 'csv' && this.csvPath) body.csv_path = this.csvPath;
                const r = await App.post('/api/review/trade_record', body);
                if (r && r.ok) {
                    this.trReport = r;
                } else {
                    this.trReport = null;
                    this.trError = (r && r.message) || '加载失败';
                }
            } catch (e) {
                this.trReport = null;
                this.trError = String(e);
            } finally {
                this.trRunning = false;
            }
        },

        /** details 第一次展开时自动加载一次, 避免学员看到空面板 */
        onTradeRecordToggle(ev) {
            this.trOpen = !!ev?.target?.open;
            if (this.trOpen && !this.trAutoLoaded && !this.trReport) {
                this.trAutoLoaded = true;
                this.runTradeRecord();
            }
        },

        /** CSV 文件下拉切换: 同步刷新流水 + Brinson 区间 */
        async onCsvPathChange() {
            // 流水面板若已展开过, 重新拉一次
            if (this.trAutoLoaded || this.trReport) {
                await this.runTradeRecord();
            }
            // Brinson csv 数据源也要刷新区间到新 CSV 的实际范围
            if (this.brSource === 'csv') {
                await this.onBrSourceChange();
            }
        },

        /** 一个统一入口: 根据 brSource 调对应接口, 把结果统一回填到 this.brinson */
        async runBrinsonSwitch() {
            if (this.brinsonRunning) return;
            this.brinsonError = '';
            this.brinsonRunning = true;
            try {
                if (this.brSource === 'demo') {
                    this.brinson = await App.post('/api/review/brinson', {});
                    this.brinsonReal = null;
                } else {
                    // sim / real / csv: 同一个端点, 数据源不同
                    const body = {
                        source: this.brSource,
                        benchmark: '沪深300',
                        start: this.brStart,
                        end:   this.brEnd,
                    };
                    if (this.brSource === 'csv' && this.csvPath) body.csv_path = this.csvPath;
                    const r = await App.post('/api/review/brinson_real', body);
                    if (!r || !r.ok) {
                        this.brinson = null;
                        this.brinsonReal = null;
                        this.brinsonError = (r && r.message) || '归因失败';
                        App.toast(this.brinsonError, 'danger');
                    } else {
                        this.brinsonReal = r;
                        this.brinson = r.result;
                        const tag = this.brSource === 'real' ? '实盘'
                                  : this.brSource === 'csv'  ? 'CSV 交割单'
                                  : '模拟盘';
                        App.toast(`${tag}真实数据归因完成 (${r.params.elapsed_sec}s)`, 'success');
                    }
                }
            } catch (e) {
                this.brinsonError = String(e);
                App.toast('归因失败: ' + e, 'danger');
            } finally {
                this.brinsonRunning = false;
            }
            // 流水卡若已展开, 顺带刷新一次保持跟主结果同步 (csv / sim 模式才有流水)
            if (this.trOpen && (this.brSource === 'csv' || this.brSource === 'sim')) {
                this.runTradeRecord();
            }
        },

        /** 数据源切换 -- csv 模式自动按交割单实际日期范围调区间; 同时让流水卡跟上 */
        async onBrSourceChange() {
            // real / demo 模式: 流水状态清空
            if (this.brSource !== 'csv' && this.brSource !== 'sim') {
                this.trReport = null;
                this.trError = '';
                this.trAutoLoaded = false;
                return;
            }
            // 切到 csv: 自动按 CSV 实际范围调区间
            if (this.brSource === 'csv') {
                try {
                    const body = { source: 'csv' };
                    if (this.csvPath) body.csv_path = this.csvPath;
                    const r = await App.post('/api/review/trade_record', body);
                    if (r && r.ok && Array.isArray(r.rows) && r.rows.length > 0) {
                        const dates = r.rows.map(x => String(x.trade_date)).sort();
                        this.brStart = dates[0];
                        this.brEnd   = dates[dates.length - 1];
                        // 流水卡若已展开过, 同步用这次结果填充, 不用再发一次请求
                        if (this.trAutoLoaded || this.trReport) {
                            this.trReport = r;
                            this.trError = '';
                        }
                        App.toast(`已按 CSV 数据范围调整区间: ${this.brStart} ~ ${this.brEnd}`, 'info');
                    }
                } catch (e) {
                    // 静默失败 -- 用户仍能手动调日期再点运行
                }
                return;
            }
            // 切到 sim: 流水卡已展开过就重拉一次
            if (this.brSource === 'sim' && (this.trAutoLoaded || this.trReport)) {
                await this.runTradeRecord();
            }
        },

        /** 老接口 (demo) -- 保留兼容, 暂时未在 UI 暴露 */
        async runBrinson() {
            this.brinsonRunning = true;
            try {
                this.brinson = await App.post('/api/review/brinson', {});
            } catch (e) {
                App.toast('归因失败: ' + e, 'danger');
            }
            this.brinsonRunning = false;
        },

        /** 行业明细按 |total| 降序 (一眼看到贡献最大 / 最拖后腿的行业) */
        brinsonByIndustrySorted() {
            const arr = (this.brinson && this.brinson.by_industry) || [];
            return [...arr].sort((x, y) => Math.abs(y.total || 0) - Math.abs(x.total || 0));
        },

        /** 一眼读懂: 把三因子分布翻译成定性结论 (这才是 Brinson 的真正价值) */
        brinsonHeadline() {
            if (!this.brinson) return '';
            const a = Number(this.brinson.allocation_effect || 0);
            const s = Number(this.brinson.selection_effect || 0);
            const i = Number(this.brinson.interaction_effect || 0);
            const ex = Number(this.brinson.excess_return || 0);
            const fmt = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
            const head = `本期超额 ${fmt(ex)} -- `;
            if (ex < 0) {
                return head + '区间内跑输基准, 看下方各行业明细找拖累项';
            }
            const aa = Math.abs(a), as = Math.abs(s), ai = Math.abs(i);
            const total = aa + as + ai || 1e-9;
            const maxv = Math.max(aa, as, ai);
            const allPositive = (a > 0 && s > 0 && i > 0);
            // 三个因子都正向, 且最大那个 < 50% 的总贡献 -> 算均衡
            if (allPositive && (maxv / total) < 0.5) {
                return head + '三因子均衡正向, 配置/选股/交互都在贡献 -- 真 Alpha 信号 (可复制能力)';
            }
            if (ai >= aa && ai >= as) {
                return head + '主要来自交互效应 (重仓 + 选对的叠加) -- 大概率是运气, 不可复制, 警惕过拟合';
            }
            if (aa >= as) {
                return head + '主要来自配置效应 -- 赌对了赛道, 注意行业 beta 风险, 板块退潮就会打回原形';
            }
            return head + '主要来自选股效应 -- 真 Alpha (在选定行业里挑出了强势股)';
        },

        /** banner 配色 */
        brinsonHeadlineClass() {
            if (!this.brinson) return '';
            const ex = Number(this.brinson.excess_return || 0);
            if (ex < 0) return 'bg-rose-50 border border-rose-200 text-rose-800';
            const a = Number(this.brinson.allocation_effect || 0);
            const s = Number(this.brinson.selection_effect || 0);
            const i = Number(this.brinson.interaction_effect || 0);
            const aa = Math.abs(a), as = Math.abs(s), ai = Math.abs(i);
            const total = aa + as + ai || 1e-9;
            const maxv = Math.max(aa, as, ai);
            const allPositive = (a > 0 && s > 0 && i > 0);
            if (allPositive && (maxv / total) < 0.5) return 'bg-emerald-50 border border-emerald-200 text-emerald-800';
            if (ai >= aa && ai >= as)                 return 'bg-amber-50 border border-amber-200 text-amber-800';
            if (aa >= as)                              return 'bg-sky-50 border border-sky-200 text-sky-800';
            return 'bg-emerald-50 border border-emerald-200 text-emerald-800';
        },

        /** 强制重建申万一级行业字典 cache */
        async refreshIndustryMap() {
            if (this.indMapBusy) return;
            this.indMapBusy = true;
            try {
                const r = await App.post('/api/review/industry_map_refresh', {});
                if (r && r.ok) {
                    App.toast(r.message || '字典已刷新', 'success');
                } else {
                    App.toast((r && r.message) || '刷新失败', 'danger');
                }
            } catch (e) {
                App.toast('刷新失败: ' + e, 'danger');
            } finally {
                this.indMapBusy = false;
            }
        },
        /** 取当前选中策略的 meta (含 description / param_text_hint / defaults_text) */
        wfStrategyMeta() {
            return (this.wfStrategies || []).find(s => s.key === this.wfStrategy) || null;
        },

        /** 第一次进入 Walk-Forward 子 Tab 时拉策略列表 (只拉一次, 失败给提示) */
        async ensureWfStrategiesLoaded() {
            if (this.wfStrategiesLoaded) return;
            try {
                const r = await App.get('/api/review/wf_strategies');
                if (r && r.ok && Array.isArray(r.strategies) && r.strategies.length > 0) {
                    this.wfStrategies = r.strategies;
                    if (!r.strategies.find(s => s.key === this.wfStrategy)) {
                        this.wfStrategy = r.strategies[0].key;
                    }
                    if (!this.wfParamGridText) {
                        this.wfParamGridText = this.wfStrategyMeta()?.defaults_text || '';
                    }
                    this.wfStrategiesLoaded = true;
                } else {
                    this.wfError = '加载策略列表失败';
                }
            } catch (e) {
                this.wfError = '加载策略列表失败: ' + e;
            }
        },

        /** 用户切换策略时, 把 textarea 重置为该策略的默认参数候选 */
        onWfStrategyChange() {
            this.wfParamGridText = this.wfStrategyMeta()?.defaults_text || '';
            this.wfReport = null;
            this.wfError = '';
        },

        /** Walk-Forward 跑一次, 把结果回填 wfReport
         *  param_grid 以 textarea 文本送给后端, 后端按 strategy.param_cols 顺序解析每行.
         */
        async runWalkForward() {
            if (this.wfRunning) return;
            this.wfError = '';
            this.wfRunning = true;
            try {
                const r = await App.post('/api/review/walk_forward', {
                    code:       (this.wfCode || '600519.SH').trim(),
                    count:      this.wfCount,
                    train:      this.wfTrain,
                    test:       this.wfTest,
                    strategy:   this.wfStrategy,
                    param_grid: (this.wfParamGridText || '').trim(),
                });
                this.wfReport = r;
                if (r && r.ok) {
                    const tag = r.verdict === 'ok' ? 'success'
                              : (r.verdict === 'warn' ? 'warning' : 'danger');
                    App.toast('Walk-Forward 完成: ' + r.verdict_text, tag);
                } else {
                    this.wfError = (r && r.message) || '运行失败';
                    App.toast(this.wfError, 'danger');
                }
            } catch (e) {
                this.wfError = String(e);
                App.toast('运行失败: ' + e, 'danger');
            } finally {
                this.wfRunning = false;
            }
        },

        async loadRegistry() {
            this.registry = await App.get('/api/review/registry');
        },
        async evalLifecycle() {
            const r = await App.post('/api/review/lifecycle_eval', {});
            this.lifecycleLog = r.log;
            await this.loadRegistry();
            App.toast(r.summary, 'info');
        },

        /** 用真实数据 (sim 或 real) 跑生命周期评估 */
        async evalLifecycleSim() {
            if (this.lcSimRunning) return;
            this.lcSimRunning = true;
            try {
                const r = await App.post('/api/review/lifecycle_sim_eval', {
                    from_stage: this.lcSimFromStage,
                    source:     this.lcSimSource,
                });
                this.lcSim = r;
                if (r && r.ok) {
                    if (r.stage_changed) {
                        App.toast('触发迁移: ' + r.from_stage + ' -> ' + r.next_stage, 'success');
                    } else {
                        App.toast('未触发迁移 -- 维持 ' + r.from_stage, 'info');
                    }
                } else {
                    App.toast((r && r.message) || '评估失败', 'danger');
                }
            } catch (e) {
                App.toast('评估失败: ' + e, 'danger');
            } finally {
                this.lcSimRunning = false;
            }
        },

        /** 实盘 NAV 快照: 拉一次 total_asset 写入 real_pnl_history.json */
        async recordRealSnapshot(force) {
            if (this.snapBusy) return;
            this.snapBusy = true;
            try {
                const r = await App.post('/api/review/real_pnl_snapshot', {force: !!force});
                if (r && r.ok) {
                    App.toast(r.message || '快照已记录', 'success');
                } else {
                    App.toast((r && r.message) || '快照失败', 'danger');
                }
            } catch (e) {
                App.toast('快照失败: ' + e, 'danger');
            } finally {
                this.snapBusy = false;
            }
        },

        /** 占位: 提示信息里的 "最近 N 个交易日" 数字, 进 tab 时若已加载 brinsonReal 则用它的, 否则给空 */
        equityPointCount() {
            return null;
        },
    }
}
