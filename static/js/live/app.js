function liveApp() {
    return {
        showHelp: false,
        showEmergency: false,   // 应急干预 默认折叠
        showEvents: false,      // 事件流 默认折叠
        realHelpOpen: false,    // /live/real "为什么没连上" 折叠提示
        dragon: {               // 龙头战法面板 (CASE-C)
            show: false, loading: false, binding: false,
            // sourceMode: 'auto' (默认) / 'mysql' / 'xtdata' / 'mock'
            sourceMode: 'auto',
            source: '', tradeDate: '', warning: '', items: [],
        },
        viewMode: (window.__liveViewMode || 'sim'),  // 由 /live/sim 或 /live/real URL 决定
        realAccount: {          // 实盘视图: 来自 miniQMT 的真实账户 (5 秒缓存, 后端 /api/live/real_account)
            connected: false, error: null, asset: {}, positions: [], orders: [], cached_age_sec: -1,
        },
        approvals: [],          // 实盘视图: AI 信号待授权列表 (后端 /api/live/approvals)
        approvalBusyId: '',     // 正在处理的信号 id (用于按钮 disabled, 防重复点)
        cancelBusyId: 0,        // 正在撤单的 order_id (按钮 disabled, 防重复)
        showRealOrders: false,  // 实盘委托弹窗 (从「实盘账户」头部点开)
        simTrialBusy: false,    // 模拟盘试算 loading
        realTrialBusy: false,   // 实盘试算 loading
        trialBusy: false,       // 兼容旧代码
        trialResult: null,      // 试算结果 {summary, diagnoses}, 非 null 时弹窗显示
        chartMode: 'all',       // all (默认: 4-1 至今) / today (仅今天分时)
        showStratHelp: false,

        // ---- 模拟盘独立状态 ----
        simState: {},
        sim: { running: false, cycle_count: 0, last_cycle_at: null, last_error: null, dry_run: true },
        simWatch: '',
        simWatchDebounceTimer: null,
        mergedList: [],          // sim 合并监控列表
        simMergedList: [],
        bindingSource: {},       // {code: 'sim'|'real'}, 决定模拟盘「待入场」是否显示该 code
        executionModes: {},      // {code: 'plan'|'strategy'} 执行方式模式 (共用)
        tradingCodes: [],        // sim 已纳入「实时持仓/待入场」的代码
        simTradingCodes: [],
        stockNames: {},          // {code: name} 股票名称缓存 (共用)
        watchQuotes: {},         // sim 自选池行情缓存
        simWatchQuotes: {},
        watchPoolText: '',
        simWatchPoolText: '',
        watchAddMode: false,
        watchAddCode: '',
        watchBatchMode: false,
        simWatchAddMode: false,
        simWatchAddCode: '',
        simWatchBatchMode: false,
        planIndex: {},           // {code: plan_row} 当日交易计划索引 (共用)
        expandedPlan: '',        // 当前展开计划摘要的股票代码 (共用)
        planDetailCache: {},     // {code: parsed_plan} 展开时缓存解析结果 (共用)
        dryRun: true,
        lastUpdate: '-',
        opLog: '',
        chart: null,

        // ---- 实盘独立状态 ----
        realState: {},
        real: { running: false, cycle_count: 0, last_cycle_at: null, last_error: null, dry_run: false },
        realWatch: '',
        realMergedList: [],
        realBindingSource: {},
        realTradingCodes: [],
        realWatchQuotes: {},
        realPendingQuotes: {},   // 实盘待入场股票行情
        realWatchPoolText: '',
        realWatchAddMode: false,
        realWatchAddCode: '',
        realWatchBatchMode: false,
        // 实盘策略配置
        realStrategyConfig: { default: 'macd_5min', per_stock: {} },

        // ---- 资金面板 (派生自 state, 不查后端) ----
        // capital = 可用现金 (动态变化: 买入时减少, 卖出时增加)
        // 持仓市值 = positions[].market_value 之和
        // 总资产 = 可用现金 + 持仓市值
        totalAssets() {
            const cap = Number(this.simState && this.simState.capital) || 0;
            return cap + this.holdingsValue();
        },
        holdingsValue() {
            const ps = (this.simState && this.simState.positions) || [];
            return ps.reduce((s, p) => s + (Number(p.market_value) || 0), 0);
        },
        cashAvailable() {
            return Math.max(0, this.totalAssets() - this.holdingsValue());
        },
        holdingsRatio() {
            const t = this.totalAssets();
            return t > 0 ? this.holdingsValue() / t : 0;
        },
        cashRatio() {
            const t = this.totalAssets();
            return t > 0 ? this.cashAvailable() / t : 0;
        },

        // ---- 策略路由 ----
        strategyGroups: [],     // [{name: '技术指标', items: [{name, label, description}, ...]}, ...]
        strategyFlat: [],       // [{name, label, group, description}, ...] (供 <select> 用)
        strategiesLoadError: '', // API 失败时显示, 避免一直「加载中」
        strategyConfig: { default: 'macd_5min', per_stock: {} },
        // 持仓表「执行策略」点击后弹窗
        strategyDetailForPos: {
            show: false,
            code: '',
            label: '',
            scenario: '',
            rules: '',
            example: '',
            desc: '',
            switchTo: '',
        },
        // 添加股票并绑定策略; source 决定写到模拟盘自选池还是实盘绑定 (默认 sim)
        stockBind: { show: false, code: '', strategy: '', source: 'sim' },

        openStockBind() {
            // 勿整体替换 stockBind，否则弹窗内 select 的 x-model 可能丢绑定，确定时 strategy 为空导致绑定失败
            this.stockBind.show = true;
            this.stockBind.code = '';
            this.stockBind.strategy = '';
            this.stockBind.source = (this.viewMode === 'real') ? 'real' : 'sim';
        },

        async confirmStockBind() {
            const code = (this.stockBind.code || '').trim();
            const strategy = (this.stockBind.strategy || '').trim();
            const source = (this.stockBind.source === 'real') ? 'real' : 'sim';
            if (!code) {
                App.toast('请填写股票代码', 'warn');
                return;
            }
            if (!strategy) {
                App.toast('请选择策略', 'warn');
                return;
            }
            try {
                const r = await App.post('/api/live/stock/bind', { code, strategy, source });
                if (r && typeof r === 'object' && r.ok) {
                    this.opLog = r.message || '';
                    App.toast(r.message || '已绑定', 'success');
                    this.stockBind.show = false;
                    // sim/real 独立更新策略配置和监控列表
                    if (source === 'real') {
                        if (r.per_stock && typeof r.per_stock === 'object') {
                            this.realStrategyConfig.per_stock = { ...r.per_stock };
                        }
                        if (r.default) this.realStrategyConfig.default = r.default;
                        await this.loadRealWatchPool();
                        await this.refreshRealMergedWatch();
                    } else {
                        if (r.per_stock && typeof r.per_stock === 'object') {
                            this.strategyConfig.per_stock = { ...r.per_stock };
                        }
                        if (r.default) this.strategyConfig.default = r.default;
                        await this.loadWatchPool();
                        await this.refreshMergedWatch();
                    }
                } else {
                    let detail = (r && typeof r === 'object' && r.message)
                        ? r.message
                        : (typeof r === 'string' ? r : JSON.stringify(r || {}));
                    const ds = String(detail);
                    if (ds === 'Not Found' || /^HTTP 404/i.test(ds)) {
                        detail = '接口 404：当前后端可能未加载 stock/bind。请重启 python app.py，并访问 ' + window.location.origin + '/api/live/ping 应看到 ok:true';
                    }
                    App.toast('绑定失败: ' + detail, 'danger');
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'warn');
            }
        },

        /** 将裸代码补全为带交易所后缀的标准代码 */
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
        },

        async init() {
            await this.loadStrategies();
            await this.loadExecutionModes();
            await this.loadWatchPool();
            await this.loadStockNames(this.watchPoolCodes());
            await this.loadWatchQuotes();
            await this.loadPlanIndex();
            await this.refreshMergedWatch();
            // 实盘视图: 额外加载实盘自选池和合并列表
            if (this.viewMode === 'real') {
                await this.loadRealWatchPool();
                await this.loadRealWatchQuotes();
                await this.refreshRealMergedWatch();
                await this.loadRealPendingQuotes();
            }
            await this.refresh();
            // 5 秒自动轮询
            setInterval(() => this.refresh(), 5000);
        },

        async refresh() {
            try {
                // 模拟盘状态
                this.simState = await App.get('/api/live/sim/state');
                this.sim      = await App.get('/api/live/sim/status');
                // 实盘状态 (无论当前视图, 都拉取以便切换 tab 时数据已就绪)
                this.realState = await App.get('/api/live/real/state');
                this.real      = await App.get('/api/live/real/status');
                this.lastUpdate = new Date().toLocaleTimeString('zh-CN');
                this.renderChart();
                // 为持仓/待入场股票加载名称 (防止后端 name 字段为空时显示空白)
                const simPosCodes = (this.simState.positions || []).map(p => p.code).filter(Boolean);
                const realPosCodes = (this.realState.positions || []).map(p => p.stock_code || p.code).filter(Boolean);
                await this.loadStockNames([...simPosCodes, ...realPosCodes]);
                await this.loadExecutionModes();
                await this.refreshMergedWatch();
                await this.loadPlanIndex();
                await this.loadWatchQuotes();
                // 仅当用户处在「实盘」视图时才轮询 miniQMT + 待授权信号
                if (this.viewMode === 'real') {
                    await this.refreshRealAccount();
                    await this.refreshApprovals();
                    await this.loadRealWatchQuotes();
                    await this.refreshRealMergedWatch();
                    await this.loadRealPendingQuotes();
                }
            } catch (e) {
                console.error(e);
            }
        },

        /** 拉 miniQMT 真实账户 + 持仓 (后端 5 秒缓存, 频繁调用安全)
         *  force=true 时仍走同一接口, 后端缓存到期后会重连查询 */
        async refreshRealAccount(force) {
            try {
                const r = await App.get('/api/live/real_account');
                if (r && typeof r === 'object') {
                    const positions = (Array.isArray(r.positions) ? r.positions : []).map(p => ({
                        ...p,
                        stock_code: this.normCode(p.stock_code || p.code),
                    }));
                    this.realAccount = {
                        connected: !!r.connected,
                        error:     r.error || null,
                        asset:     r.asset || {},
                        positions: positions,
                        orders:    Array.isArray(r.orders) ? r.orders : [],
                        cached_age_sec: typeof r.cached_age_sec === 'number' ? r.cached_age_sec : -1,
                    };
                    if (force) {
                        App.toast(r.connected ? 'miniQMT 数据已刷新' : ('miniQMT 未连接: ' + (r.error || '未知')),
                                  r.connected ? 'success' : 'warn');
                    }
                }
            } catch (e) {
                console.error('refreshRealAccount', e);
                this.realAccount.connected = false;
                this.realAccount.error = String(e && e.message || e);
            }
        },

        /** 拉 AI 信号待授权列表 (实盘视图专用); 后端汇总最近 30 条 buy/sell 信号 + approval 状态 */
        async refreshApprovals(toastOnDone) {
            try {
                const r = await App.get('/api/live/approvals');
                this.approvals = (r && Array.isArray(r.items)) ? r.items : [];
                if (toastOnDone) App.toast('已刷新 ' + this.approvals.length + ' 条信号', 'info');
            } catch (e) {
                console.error('refreshApprovals', e);
                if (toastOnDone) App.toast('刷新失败: ' + (e && e.message ? e.message : e), 'warn');
            }
        },

        pendingApprovals() {
            return (this.approvals || []).filter(it => it.status === 'pending');
        },
        processedApprovals() {
            return (this.approvals || []).filter(it => it.status !== 'pending');
        },
        approvalStats() {
            const s = { pending: 0, approved: 0, rejected: 0, expired: 0 };
            (this.approvals || []).forEach(it => { if (s[it.status] !== undefined) s[it.status] += 1; });
            return s;
        },

        async approveSignal(it) {
            if (!it || !it.id) return;
            const tip = '确认走 miniQMT 真实下单?\n\n'
                      + (it.side === 'buy' ? '买入' : '卖出') + ' ' + it.code + ' '
                      + it.suggested_quantity + ' 股 @ '
                      + (it.suggested_price > 0 ? it.suggested_price.toFixed(2) : '市价');
            if (!window.confirm(tip)) return;
            this.approvalBusyId = it.id;
            try {
                const r = await App.post('/api/live/approvals/approve', { id: it.id });
                App.toast(r.message || (r.ok ? '已下单' : '下单失败'), r.ok ? 'success' : 'danger');
                await this.refreshApprovals();
                if (r.ok) await this.refreshRealAccount(false);
            } catch (e) {
                App.toast('请求失败: ' + (e && e.message ? e.message : e), 'danger');
            } finally {
                this.approvalBusyId = '';
            }
        },

        async rejectSignal(it) {
            if (!it || !it.id) return;
            this.approvalBusyId = it.id;
            try {
                const r = await App.post('/api/live/approvals/reject', { id: it.id });
                App.toast(r.message || '已拒绝', r.ok ? 'info' : 'warn');
                await this.refreshApprovals();
            } catch (e) {
                App.toast('请求失败: ' + (e && e.message ? e.message : e), 'danger');
            } finally {
                this.approvalBusyId = '';
            }
        },

        /** 拿策略中文标签 (用 strategyFlat 已加载好的; 没找到就回原 name) */
        strategyLabel(name) {
            if (!name) return '';
            const hit = (this.strategyFlat || []).find(s => s.name === name);
            return hit ? hit.label : name;
        },

        /** 信号对应的订单结果: 成交/被阻断原因 → 中文标签 */
        orderStatusLabel(st) {
            if (st === 'dry_run' || st === 'submitted') return '成交';
            if (st === 'rejected_t1') return 'T+1限制';
            if (st === 'rejected') return '资金不足';
            if (st === 'skipped_no_position') return '无持仓';
            if (st === 'paused_by_ceo') return '暂停';
            if (st === 'pending_manual') return '待确认';
            if (st === 'failed') return '失败';
            if (st === 'exception') return '异常';
            return '—';
        },

        /** 从服务端读自选池到文本框 (仅 init 调用, 避免覆盖用户未保存编辑) */
        async loadWatchPool() {
            try {
                const d = await App.get('/api/live/watch_pool');
                const arr = d && Array.isArray(d.codes) ? d.codes : [];
                this.watchPoolText = arr.join(',');
            } catch (e) {
                console.error('loadWatchPool', e);
            }
        },

        /** 加载执行方式模式表 (sim/real 独立) */
        async loadExecutionModes() {
            try {
                const url = this.viewMode === 'real' ? '/api/live/real/execution_mode' : '/api/live/sim/execution_mode';
                const r = await App.get(url);
                this.executionModes = (r && r.modes) || {};
            } catch (e) {
                console.error('loadExecutionModes', e);
                this.executionModes = {};
            }
        },

        /** 设置某只股票的执行方式模式 (plan / strategy / null) -- sim/real 独立 */
        async setExecutionMode(code, mode) {
            if (!code) return;
            try {
                const url = this.viewMode === 'real' ? '/api/live/real/execution_mode' : '/api/live/sim/execution_mode';
                const r = await App.post(url, { code, mode });
                if (r && r.ok) {
                    this.executionModes = r.modes || this.executionModes;
                    App.toast(r.message, 'success');
                    // sim/real 独立刷新
                    if (this.viewMode === 'real') {
                        await this.refreshRealMergedWatch();
                    } else {
                        await this.refreshMergedWatch();
                    }
                } else {
                    App.toast('设置失败: ' + ((r && r.message) || '未知错误'), 'warn');
                }
            } catch (e) {
                console.error('setExecutionMode', e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'warn');
            }
        },

        /** 持仓状态下取消交易计划执行方式: 清除 plan 模式, 该股变为纯持仓(无执行方式), 不再产生信号
         *  想恢复交易需重新绑定策略或交易计划 */
        async cancelPlanInPosition(code) {
            if (!code) return;
            if (!confirm('取消 ' + code + ' 的交易计划执行方式: 该股变为纯持仓, 不再产生信号。\n\n继续吗?')) return;
            await this.setExecutionMode(code, '');
        },

        /** 批量查询股票名称 */
        async loadStockNames(codes) {
            if (!codes || codes.length === 0) return;
            const missing = codes.filter(c => c && !this.stockNames[c]);
            if (missing.length === 0) return;
            try {
                const r = await App.get('/api/live/stock_names?codes=' + encodeURIComponent(missing.join(',')));
                const names = (r && r.names) || {};
                Object.assign(this.stockNames, names);
            } catch (e) {
                console.error('loadStockNames', e);
            }
        },

        /** 拉取自选池最新行情 (close / 前收 / 涨跌幅) */
        async loadWatchQuotes() {
            try {
                const codes = this.watchPoolCodes().map(c => this.normCode(c)).filter(Boolean);
                const url = codes.length
                    ? '/api/live/watch_quotes?codes=' + encodeURIComponent(codes.join(','))
                    : '/api/live/watch_quotes';
                const r = await App.get(url);
                const qs = (r && r.quotes) || {};
                Object.assign(this.watchQuotes, qs);
            } catch (e) {
                console.error('loadWatchQuotes', e);
            }
        },

        /** 加载实盘自选池行情 (最高价/最新价/涨跌幅) */
        async loadRealWatchQuotes() {
            const codes = this.realWatchPoolCodes();
            if (!codes.length) return;
            try {
                const r = await App.get('/api/live/real/watch_quotes?codes=' + encodeURIComponent(codes.join(',')));
                const qs = (r && r.quotes) || {};
                Object.assign(this.realWatchQuotes, qs);
            } catch (e) {
                console.error('loadRealWatchQuotes', e);
            }
        },

        /** 加载实盘待入场股票行情 (供待入场表格使用) */
        async loadRealPendingQuotes() {
            const codes = this.realTradingCodes || [];
            if (!codes.length) return;
            try {
                const r = await App.get('/api/live/real/watch_quotes?codes=' + encodeURIComponent(codes.join(',')));
                const qs = (r && r.quotes) || {};
                Object.assign(this.realPendingQuotes, qs);
            } catch (e) {
                console.error('loadRealPendingQuotes', e);
            }
        },

        /** 加载当日交易计划索引, 用于持仓表判断某只股票是否有计划 */
        async loadPlanIndex() {
            try {
                // viewMode 为 'real' 时对应数据库 plan_type='live'
                const planType = this.viewMode === 'real' ? 'live' : 'sim';
                const r = await App.get('/api/trade-plans?plan_type=' + planType);
                const idx = {};
                (r.items || []).forEach(p => { idx[p.stock_code] = p; });
                this.planIndex = idx;
            } catch (e) {
                console.error('loadPlanIndex', e);
                this.planIndex = {};
            }
        },

        hasPlan(code) {
            return !!(code && this.planIndex[code]);
        },

        /** 计划已生效 (planIndex 里有该代码且 is_active=true) */
        planActive(code) {
            const p = this.planIndex[code];
            return !!(p && p.is_active);
        },

        /** 某代码是否处于「交易计划模式」(只看显式设置的 execution mode) */
        isPlanMode(code) {
            if (!code) return false;
            // 只看显式设置的 execution mode，不被 hasPlan 覆盖
            // hasPlan 只影响 plan 模式下是否显示详细信息
            return this.executionModes[code] === 'plan';
        },

        /** 某代码是否处于「策略模式」(已绑策略 且 不是 plan 模式) */
        isStrategyMode(code) {
            if (!code) return false;
            if (this.isPlanMode(code)) return false;
            return this.hasBinding(code);
        },

        /** 返回计划摘要对象; 未加载过则异步加载并缓存。
         * 优先匹配当前视图(sim/live), 找不到则尝试另一类型, 避免跨类型计划无法显示。
         *
         * 使用 /overview 端点: 直接读取数据库中解析好的结构化条件,
         * 不再实时解析 Markdown 文件, 保证监控页看到的执行节点与数据库一致。
         */
        async ensurePlanDetail(code) {
            if (!code) return null;
            if (this.planDetailCache[code]) return this.planDetailCache[code];
            const planType = this.viewMode === 'real' ? 'live' : 'sim';
            const otherType = planType === 'live' ? 'sim' : 'live';
            for (const pt of [planType, otherType]) {
                try {
                    const r = await App.get('/api/trade-plan/' + encodeURIComponent(code)
                                            + '/overview?plan_type=' + pt);
                    if (r && r.ok) {
                        this.planDetailCache[code] = r.parsed || {};
                        return this.planDetailCache[code];
                    }
                } catch (e) {
                    console.error('ensurePlanDetail', pt, e);
                }
            }
            this.planDetailCache[code] = {};
            return this.planDetailCache[code];
        },

        /** 计划条件当前触发距离 (基于最新价): 再涨/再跌 X% 触发, 或已触发
         *
         * 触发方向推断:
         *   - 止盈 / 获利了结: 向上触发 (当前价 >= 触发价)
         *   - 止损 / 跌破 / 成本下跌: 向下触发 (当前价 <= 触发价)
         *   - 加仓 / 买入 / 回踩: 向下触发 (当前价 <= 触发价)
         */
        conditionDistanceText(cond, currentPrice) {
            if (!cond || !currentPrice || currentPrice <= 0) return '';
            const title = (cond.title || '').toLowerCase();
            const isUpward = title.includes('止盈') || title.includes('获利');
            const isDownward = title.includes('止损') || title.includes('跌破') || title.includes('下跌')
                              || title.includes('加仓') || title.includes('买入') || title.includes('回踩')
                              || title.includes('入场');
            const tp = cond.trigger_price;
            if (tp && tp > 0) {
                let triggered = false;
                if (isUpward) {
                    triggered = currentPrice >= tp;
                } else if (isDownward) {
                    triggered = currentPrice <= tp;
                } else {
                    // 默认按 side 推断: buy 向下, sell 向上
                    triggered = cond.side === 'buy' ? currentPrice <= tp : currentPrice >= tp;
                }
                if (triggered) return '已触发';
                if (tp > currentPrice) {
                    return '再涨 ' + ((tp - currentPrice) / currentPrice * 100).toFixed(1) + '% 触发';
                } else {
                    return '再跌 ' + ((currentPrice - tp) / currentPrice * 100).toFixed(1) + '% 触发';
                }
            }
            const pct = cond.trigger_pct;
            if (pct && pct !== 0) {
                return (pct > 0 ? '浮盈 +' : '浮亏 ') + (Math.abs(pct) * 100).toFixed(0) + '% 触发';
            }
            return '条件触发';
        },

        /** 计划条件操作文字 */
        conditionActionText(cond) {
            if (!cond) return '';
            const pct = cond.action_percent;
            const side = cond.side || 'sell';
            if (pct === undefined || pct === null) return side === 'buy' ? '买入' : '清仓';
            if (Math.abs(pct - 1.0) < 0.001) return side === 'buy' ? '全仓买入' : '清仓';
            return (side === 'buy' ? '买入 ' : '卖出 ') + (pct * 100).toFixed(0) + '%';
        },

        /** 计划条件操作 + 触发价 (概览卡片用): 清仓 @ ¥415.56 */
        conditionActionPrice(cond) {
            if (!cond) return '';
            const action = this.conditionActionText(cond);
            if (cond.trigger_price && cond.trigger_price > 0) {
                return action + ' @ ¥' + Number(cond.trigger_price).toFixed(2);
            }
            return action;
        },

        /** 计划条件触发价/描述 */
        conditionTriggerText(cond) {
            if (!cond) return '';
            const side = cond.side || 'sell';
            if (cond.trigger_price && cond.trigger_price > 0) {
                return '触发价 ≈ ¥' + Number(cond.trigger_price).toFixed(2);
            }
            if (cond.trigger_pct !== undefined && cond.trigger_pct !== 0) {
                const pct = cond.trigger_pct;
                if (side === 'buy') {
                    return pct > 0 ? '浮盈高于 ' + (pct * 100).toFixed(0) + '%' : '回踩低于 ' + (Math.abs(pct) * 100).toFixed(0) + '%';
                }
                return pct > 0 ? '浮盈高于 ' + (pct * 100).toFixed(0) + '%' : '浮亏低于 ' + (Math.abs(pct) * 100).toFixed(0) + '%';
            }
            return '条件触发';
        },

        /** 触发条件一句话描述 (不含动作) */
        conditionTriggerDesc(cond) {
            if (!cond) return '';
            const side = cond.side || 'sell';
            if (cond.trigger_price !== undefined && cond.trigger_price > 0) {
                return '触发价 ≈ ¥' + Number(cond.trigger_price).toFixed(2);
            }
            if (cond.trigger_pct !== undefined && cond.trigger_pct !== 0) {
                const pct = cond.trigger_pct;
                if (side === 'buy') {
                    return pct > 0 ? '浮盈高于 ' + (pct * 100).toFixed(0) + '%' : '回踩低于 ' + (Math.abs(pct) * 100).toFixed(0) + '%';
                }
                return pct > 0 ? '浮盈高于 ' + (pct * 100).toFixed(0) + '%' : '浮亏低于 ' + (Math.abs(pct) * 100).toFixed(0) + '%';
            }
            return '满足条件';
        },

        /** 触发 + 操作 组合 (卡片第二层) */
        conditionSummary(cond) {
            return this.conditionTriggerDesc(cond) + ' → ' + this.conditionActionText(cond);
        },

        async togglePlanExpand(code) {
            const norm = this.normCode(code);
            if (this.expandedPlan === norm) {
                this.expandedPlan = '';
                return;
            }
            this.expandedPlan = norm;
            if (!this.planDetailCache[norm]) {
                await this.ensurePlanDetail(norm);
            }
        },

        async saveWatchPool() {
            const raw = (this.watchPoolText || '').replace(/\r?\n/g, ',').replace(/，/g, ',');
            try {
                const r = await App.post('/api/live/watch_pool', { codes: raw });
                if (!r || typeof r !== 'object') {
                    App.toast('保存失败: 服务返回异常', 'warn');
                    return;
                }
                this.opLog = r.message || '';
                App.toast(r.ok ? (r.message || '已保存') : (r.message || '保存失败'), r.ok ? 'success' : 'warn');
                if (r.ok) await this.refreshMergedWatch();
            } catch (e) {
                console.error(e);
                App.toast('保存失败: ' + (e && e.message ? e.message : String(e)), 'warn');
            }
        },

        /** 解析 watchPoolText 为代码数组 (自动标准化为带后缀格式) */
        watchPoolCodes() {
            return (this.watchPoolText || '')
                .split(/[,，\r\n]+/)
                .map(c => this.normCode(c.trim()))
                .filter(c => c.length > 0)
                .filter((c, i, arr) => arr.indexOf(c) === i);
        },

        showWatchAdd() {
            this.watchAddMode = true;
            this.watchAddCode = '';
        },

        cancelWatchAdd() {
            this.watchAddMode = false;
            this.watchAddCode = '';
        },

        async confirmWatchAdd() {
            const code = this.normCode((this.watchAddCode || '').trim());
            if (!code) {
                App.toast('请填写股票代码', 'warn');
                return;
            }
            const codes = this.watchPoolCodes();
            if (codes.includes(code)) {
                App.toast(code + ' 已在自选池中', 'info');
                this.watchAddMode = false;
                this.watchAddCode = '';
                return;
            }
            codes.push(code);
            this.watchPoolText = codes.join(',');
            this.watchAddMode = false;
            this.watchAddCode = '';
            await this.saveWatchPool();
        },

        async removeWatchCode(code) {
            if (!code) return;
            const norm = this.normCode(code);
            const codes = this.watchPoolCodes().filter(c => c !== norm);
            this.watchPoolText = codes.join(',');
            await this.saveWatchPool();
        },

        /** 自选池候选列表: watch_pool 中尚未绑定策略/计划的代码, 附带行情 */
        watchListItems() {
            const trading = new Set(this.tradingCodes || []);
            return this.watchPoolCodes()
                .map(c => this.normCode(c))
                .filter((c, i, arr) => arr.indexOf(c) === i)
                .filter(c => !trading.has(c))
                .map(c => ({
                    code: c,
                    name: this.stockNames[c] || '',
                    quote: this.watchQuotes[c] || null,
                }));
        },

        /** 从弹窗添加代码到 watch_pool */
        async addToWatchList() {
            const code = this.normCode((this.watchAddCode || '').trim());
            if (!code) {
                App.toast('请填写股票代码', 'warn');
                return;
            }
            const codes = this.watchPoolCodes();
            if (codes.includes(code)) {
                App.toast(code + ' 已在自选池中', 'info');
                this.watchAddMode = false;
                this.watchAddCode = '';
                return;
            }
            codes.push(code);
            this.watchPoolText = codes.join(',');
            this.watchAddMode = false;
            this.watchAddCode = '';
            await this.saveWatchPool();
        },

        /** 从 watch_pool 删除某只候选 */
        async removeFromWatchList(code) {
            if (!code) return;
            const norm = this.normCode(code);
            if (!confirm('确认从自选监控池删除 ' + norm + '?')) return;
            await this.removeWatchCode(norm);
        },

        /** 自选池里点击「选择策略」 */
        bindStrategyForWatch(code) {
            if (!code) return;
            this.stockBind.show = true;
            this.stockBind.code = code;
            this.stockBind.strategy = '';
            this.stockBind.source = (this.viewMode === 'real') ? 'real' : 'sim';
        },

        /** 自选池里点击「+ 交易计划」: 设为 plan 模式, 自动进入待入场 */
        async addPlanForWatch(code) {
            if (!code) return;
            await this.setExecutionMode(code, 'plan');
        },

        /** 实盘自选池里点击「选择策略」: 复用现有策略绑定流程 */
        bindStrategyForRealWatch(code) {
            if (!code) return;
            this.bindStrategyForWatch(code);
        },

        /** 实盘自选池里点击「+ 交易计划」: 设为 plan 模式, 自动刷新实盘监控列表 */
        async addPlanForRealWatch(code) {
            if (!code) return;
            // setExecutionMode 内部会根据 viewMode === 'real' 自动调用 refreshRealMergedWatch()
            await this.setExecutionMode(code, 'plan');
        },

        /** 从实盘自选池删除代码 */
        async removeFromRealWatchList(code) {
            const norm = this.normCode(code);
            if (!confirm('确认从实盘自选池删除 ' + norm + '?')) return;
            const codes = this.realWatchPoolCodes();
            const idx = codes.indexOf(norm);
            if (idx >= 0) {
                codes.splice(idx, 1);
                this.realWatchPoolText = codes.join(',');
                await this.saveRealWatchPool();
            }
        },

        /** 与后端 merge_watch_codes 一致: 额外监控 + 持仓 + 自选 + 路由键 */
        async refreshMergedWatch() {
            try {
                const ui = encodeURIComponent(this.simWatch || '');
                const res = await App.get('/api/live/watch_merge?ui=' + ui);
                this.mergedList = Array.isArray(res.merged) ? res.merged : [];
                this.bindingSource = (res && res.binding_source) ? res.binding_source : {};
                this.tradingCodes = Array.isArray(res.trading_codes) ? res.trading_codes : [];
                await this.loadStockNames(this.mergedList);
            } catch (e) {
                console.error('refreshMergedWatch', e);
                this.mergedList = [];
                this.bindingSource = {};
            }
        },

        /** 临时代码输入防抖, 减少手动点「刷新列表」 */
        onSimWatchDebounced() {
            clearTimeout(this.simWatchDebounceTimer);
            this.simWatchDebounceTimer = setTimeout(() => {
                this.refreshMergedWatch();
            }, 450);
        },

        async loadStrategies() {
            this.strategiesLoadError = '';
            try {
                const reg = await App.get('/api/live/strategies/registry');
                if (!reg || typeof reg !== 'object' || !Array.isArray(reg.flat)) {
                    this.strategiesLoadError = '策略接口返回异常 (请确认已重启到新版 app, 且访问端口与后端一致)';
                    return;
                }
                // 把 {group: [items]} 转成数组, 保持原始注册顺序
                this.strategyGroups = Object.entries(reg.groups || {}).map(
                    ([name, items]) => ({ name, items })
                );
                this.strategyFlat = reg.flat;
                // 加载模拟盘策略配置
                const cfg = await App.get('/api/live/strategies/config');
                if (!cfg || typeof cfg !== 'object') {
                    this.strategiesLoadError = '路由配置接口返回异常';
                    return;
                }
                this.strategyConfig = {
                    default:   cfg.default || 'macd_5min',
                    per_stock: cfg.per_stock || {},
                };
                // 加载实盘策略配置
                try {
                    const realCfg = await App.get('/api/live/real/strategies/config');
                    if (realCfg && typeof realCfg === 'object') {
                        this.realStrategyConfig = {
                            default:   realCfg.default || 'macd_5min',
                            per_stock: realCfg.per_stock || {},
                        };
                    }
                } catch (e) {
                    console.warn('加载实盘策略配置失败, 使用默认:', e);
                }
            } catch (e) {
                console.error('loadStrategies failed', e);
                this.strategiesLoadError = '加载策略失败: ' + (e && e.message ? e.message : String(e))
                    + ' (检查网络与 /api/live/strategies/registry 是否可访问)';
            }
        },

        watchCodes() {
            return (this.simWatch || '')
                .split(',')
                .map(c => c.trim())
                .filter(c => c.length > 0);
        },

        /** 当前路由下该代码对应的策略 id (per_stock 优先, 否则 default)
         *  根据 viewMode 自动选择 sim 或 real 配置 */
        resolvedExecStrategy(code) {
            const isReal = this.viewMode === 'real';
            const cfg = isReal ? this.realStrategyConfig : this.strategyConfig;
            const ps = cfg.per_stock || {};
            return ps[code] || cfg.default || 'macd_5min';
        },

        /** 持仓表「执行策略」列: 显示中文 label */
        resolvedExecStrategyLabel(code) {
            const name = this.resolvedExecStrategy(code);
            const m = (this.strategyFlat || []).find(s => s.name === name);
            return m ? m.label : name;
        },

        openPositionStrategyModal(code) {
            const name = this.resolvedExecStrategy(code);
            const meta = (this.strategyFlat || []).find(s => s.name === name);
            // 整体替换 strategyDetailForPos 是 OK 的: 内层 select x-model="strategyDetailForPos.switchTo"
            // 走属性访问, Alpine 在 modal 显示瞬间会重新求值, 不存在 stockBind 那种 select 跑空的问题.
            this.strategyDetailForPos = {
                show: true,
                code: code || '',
                label: meta ? meta.label : name,
                scenario: meta && meta.scenario ? meta.scenario : '',
                rules: meta && meta.rules ? meta.rules : '',
                example: meta && meta.example ? meta.example : '',
                desc: meta ? meta.description : '（暂无说明, 请检查策略是否已加载）',
                switchTo: name,
            };
        },

        /** 弹窗里点「保存」:
         *  - target 为空 -> 走 /stock/unbind 解绑 (从 per_stock + watch_pool 移除)
         *  - target 非空 -> 改 per_stock[code], 调 /strategies/config 热加载
         *  根据 viewMode 自动选择 sim 或 real 端点
         */
        async confirmSwitchStrategy() {
            const code = (this.strategyDetailForPos.code || '').trim();
            const target = (this.strategyDetailForPos.switchTo || '').trim();
            if (!code) return;
            if (!target) {
                await this.confirmUnbindStrategy();
                return;
            }
            const isReal = this.viewMode === 'real';
            const cfg = isReal ? this.realStrategyConfig : this.strategyConfig;
            const ps = { ...(cfg.per_stock || {}) };
            ps[code] = target;
            const payload = { default: cfg.default, per_stock: ps };
            const url = isReal ? '/api/live/real/strategies/apply' : '/api/live/strategies/config';
            try {
                const r = await App.post(url, payload);
                if (r && r.ok) {
                    if (isReal) {
                        this.realStrategyConfig.per_stock = ps;
                    } else {
                        this.strategyConfig.per_stock = ps;
                    }
                    this.opLog = r.message || '';
                    App.toast(code + ' 已切换为: ' + (this.resolvedExecStrategyLabel(code)), 'success');
                    this.strategyDetailForPos.show = false;
                } else {
                    App.toast('切换失败: ' + ((r && r.message) || '未知错误'), 'danger');
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            }
        },

        /** 实盘持仓: 现价 = 市值 / 持仓 (miniQMT positions 字段没单独的现价, 用市值反算)
         *  返回 0 表示没法算 (volume 为 0 等异常) */
        realPosCurPrice(p) {
            const v = Number(p && p.volume) || 0;
            const mv = Number(p && p.market_value) || 0;
            if (v <= 0 || mv <= 0) return 0;
            return mv / v;
        },
        /** 浮盈 = (现价 - 成本) * 持仓; 算不出返回 null */
        realPosPnl(p) {
            const cur = this.realPosCurPrice(p);
            const cost = Number(p && p.open_price) || 0;
            const v = Number(p && p.volume) || 0;
            if (cur <= 0 || cost <= 0 || v <= 0) return null;
            return (cur - cost) * v;
        },
        /** 盈亏% = (现价 - 成本) / 成本; 返回小数 (0.05 = 5%), 前端 App.fmtPct 内部会 *100 */
        realPosPnlPct(p) {
            const cur = this.realPosCurPrice(p);
            const cost = Number(p && p.open_price) || 0;
            if (cur <= 0 || cost <= 0) return null;
            return (cur - cost) / cost;
        },
        /** 未结委托 (可撤单) -- 用于卡片标题统计 */
        pendingRealOrders() {
            return (this.realAccount.orders || []).filter(o => o && o.cancelable);
        },

        /** 实盘账户总浮盈 (元) = 各持仓 realPosPnl 之和; 任意一只算不出就跳过该只
         *  全部持仓都算不出 (eg 缺现价) -> 返回 null, 前端显示"待 miniQMT 推送现价" */
        realPosTotalPnl() {
            const ps = (this.realAccount.positions || []);
            let sum = 0, valid = 0;
            ps.forEach(p => {
                const v = this.realPosPnl(p);
                if (v !== null) { sum += v; valid += 1; }
            });
            return valid > 0 ? sum : null;
        },
        /** 总浮盈% = 总浮盈 / 总成本 (sum(volume*open_price))
         *  返回小数 (0.05 = 5%), App.fmtPct 内部会 *100 -- 不要在这里再乘 */
        realPosTotalPnlPct() {
            const ps = (this.realAccount.positions || []);
            let costSum = 0, pnlSum = 0, valid = 0;
            ps.forEach(p => {
                const cost = Number(p.open_price) || 0;
                const vol = Number(p.volume) || 0;
                const pnl = this.realPosPnl(p);
                if (pnl !== null && cost > 0 && vol > 0) {
                    costSum += cost * vol;
                    pnlSum += pnl;
                    valid += 1;
                }
            });
            if (valid === 0 || costSum <= 0) return null;
            return pnlSum / costSum;
        },
        /** 实盘持仓策略覆盖率 {bound, total}; bound = 当前持仓里在 realStrategyConfig 里有绑的 */
        realStratCoverage() {
            const ps = (this.realAccount.positions || []);
            const total = ps.length;
            let bound = 0;
            ps.forEach(p => { if (this.hasBinding(p.stock_code)) bound += 1; });
            return { bound, total };
        },
        /** 今日已成交委托 (traded_volume > 0); 用于状态条统计 */
        realFilledOrders() {
            return (this.realAccount.orders || []).filter(o => Number(o && o.traded_volume) > 0);
        },

        /** 「策略信号」表的"授权状态"列文案: 用 _signal_id 和 approvals 联表
         *  signal id = ts|code|side, approvals 由 /api/live/approvals 维护 */
        _signalKey(s) {
            return (s.ts || '') + '|' + (s.code || '') + '|' + (s.side || '');
        },
        signalApprovalText(s) {
            const k = this._signalKey(s);
            const hit = (this.approvals || []).find(a => a.id === k);
            if (!hit) return '—';
            return hit.status === 'pending'  ? '待授权'
                 : hit.status === 'approved' ? '已下单'
                 : hit.status === 'rejected' ? '已拒绝'
                 : hit.status === 'expired'  ? '已过期'
                 : hit.status;
        },
        signalApprovalBadgeCls(s) {
            const k = this._signalKey(s);
            const hit = (this.approvals || []).find(a => a.id === k);
            if (!hit) return 'text-gray-400';
            return hit.status === 'pending'  ? 'text-yellow-700 font-semibold'
                 : hit.status === 'approved' ? 'text-green-700 font-semibold'
                 : hit.status === 'rejected' ? 'text-gray-600'
                 : 'text-gray-400';
        },

        /** 撤单: 调 /real_order/cancel, 成功后立刻刷新一次 (后端会让 cache 过期) */
        async cancelRealOrder(o) {
            if (!o || !o.order_id) return;
            if (!window.confirm('确认撤销委托 #' + o.order_id + ' (' + o.stock_code + ' '
                                + (o.side === 'buy' ? '买入' : '卖出') + ' '
                                + o.order_volume + '股) ?')) return;
            this.cancelBusyId = o.order_id;
            try {
                const r = await App.post('/api/live/real_order/cancel', { order_id: o.order_id });
                App.toast(r.message || (r.ok ? '撤单已提交' : '撤单失败'), r.ok ? 'success' : 'danger');
                if (r.ok) await this.refreshRealAccount(false);
            } catch (e) {
                App.toast('请求失败: ' + (e && e.message ? e.message : e), 'danger');
            } finally {
                this.cancelBusyId = 0;
            }
        },

        /** 实盘表里某只「未绑定」的票, 点击 → 复用「添加股票」弹窗 (code 预填好) */
        openBindFromReal(code) {
            this.stockBind.show = true;
            this.stockBind.code = code || '';
            this.stockBind.strategy = '';
            this.stockBind.source = 'real';   // 实盘绑定: 不污染模拟盘的「待入场」
        },

        /** 该 code 是否有显式策略绑定 (per_stock 里有该代码)
         *  注意: 仅以「策略绑定表 per_stock」为准, 不把「在监控列表里」误判为有绑定;
         *  显示应正向由「绑定/执行方式/持仓」推导, 而非反向由列表推断
         *  根据 viewMode 自动选择 sim 或 real 配置 */
        hasBinding(code) {
            if (!code) return false;
            const isReal = this.viewMode === 'real';
            const cfg = isReal ? this.realStrategyConfig : this.strategyConfig;
            const ps = cfg.per_stock || {};
            return !!ps[code];
        },

        /** 弹窗里点「解除绑定」: 调 /stock/unbind 移除 per_stock + watch_pool, 引擎热加载后不再出信号
         *  根据 viewMode 自动选择 sim 或 real 端点 */
        async confirmUnbindStrategy() {
            const code = (this.strategyDetailForPos.code || '').trim();
            if (!code) return;
            if (!window.confirm(
                code + ' 解除绑定后, 引擎不再对它算 buy/sell 信号.\n\n确定?'
            )) return;
            try {
                const isReal = this.viewMode === 'real';
                const url = isReal ? '/api/live/real/stock/unbind' : '/api/live/stock/unbind';
                const r = await App.post(url, { code });
                if (r && r.ok) {
                    if (isReal) {
                        if (r.per_stock) this.realStrategyConfig.per_stock = r.per_stock;
                        if (r.default) this.realStrategyConfig.default = r.default;
                        await this.refreshRealMergedWatch();
                    } else {
                        if (r.per_stock) this.strategyConfig.per_stock = r.per_stock;
                        if (r.default) this.strategyConfig.default = r.default;
                        await this.refreshMergedWatch();
                    }
                    this.opLog = r.message || '';
                    App.toast(r.message || (code + ' 已解绑'), 'success');
                    this.strategyDetailForPos.show = false;
                } else {
                    App.toast('解绑失败: ' + ((r && r.message) || '未知错误'), 'danger');
                }
            } catch (e) {
                console.error(e);
                App.toast('请求失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            }
        },

        /** 持仓表 + 已纳入交易但尚未持仓的票 (volume = 0) 合并; 让用户加完即看到"已纳入交易" */
        zeroPositionRows() {
            // 模拟盘的「待入场」: 交易代码(tradingCodes) - 已持仓代码 - 仅在「实盘」绑定的代码 (source=real)
            // tradingCodes = 持仓 + 已绑策略 + 显式 plan 模式; 这样自选池里仅 watch_pool 的候选不会出现在这里
            const positionsCodes = new Set((this.simState.positions || []).map(p => p.code));
            const src = this.bindingSource || {};
            const trading = new Set(this.tradingCodes || []);
            return Array.from(trading)
                .filter(c => !positionsCodes.has(c))
                .filter(c => src[c] !== 'real')
                .map(c => ({ code: c, _zero: true, name: this.stockNames[c] || '' }));
        },
        displayPositions() {
            const positions = (this.simState.positions || []).map(p => ({
                ...p,
                code: this.normCode(p.code),
            }));
            return [...positions, ...this.zeroPositionRows()];
        },

        /** 拼装当前模拟盘持仓摘要文本, 供 AI 助手分析用 */
        buildPositionSummary() {
            const s = this.simState || {};
            const lines = [];
            lines.push('请分析我当前的模拟盘持仓状态：');
            lines.push('');
            lines.push('【账户概览】');
            lines.push('- 运行状态: ' + (s.trading_status || '未知'));
            lines.push('- 总资产: ' + App.fmtNum(this.totalAssets(), 0) + ' 元');
            lines.push('- 今日盈亏: ' + App.fmtSign(s.today_pnl || 0, 0) + ' (' + App.fmtPct(s.today_pnl_pct || 0, 2) + ')');
            lines.push('- 初始资金: ' + App.fmtNum(s.initial_capital || 0, 0) + ' 元');
            lines.push('- 持仓市值: ' + App.fmtNum(this.holdingsValue(), 0) + ' 元');
            lines.push('- 可用现金: ' + App.fmtNum(this.cashAvailable(), 0) + ' 元');
            lines.push('');
            lines.push('【持仓明细】');
            const positions = this.displayPositions() || [];
            if (positions.length === 0) {
                lines.push('（暂无持仓）');
            } else {
                positions.forEach((p, i) => {
                    const name = p.name || this.stockNames[p.code] || '—';
                    const strat = this.resolvedExecStrategyLabel(p.code) || '默认';
                    if (p._zero) {
                        lines.push((i + 1) + '. ' + p.code + ' ' + name + ' | 待入场 | 策略: ' + strat);
                    } else {
                        lines.push((i + 1) + '. ' + p.code + ' ' + name
                            + ' | 持仓 ' + App.fmtNum(p.volume, 0) + '股 成本 ' + App.fmtNum(p.cost, 2)
                            + ' | 盈亏 ' + App.fmtSign(p.pnl || 0, 0) + ' (' + App.fmtPct(p.pnl_pct || 0, 2) + ')'
                            + ' | 策略: ' + strat);
                    }
                });
            }
            lines.push('');
            lines.push('请基于以上持仓, 分析各持仓的健康度、策略适配性、风险敞口, 并给出调仓建议。');
            return lines.join('\n');
        },

        /** 一键将持仓摘要填入右侧 AI 助手 (不自动发送, 等用户确认) */
        analyzeByAI() {
            const summary = this.buildPositionSummary();
            if (typeof AI_CHAT !== 'undefined' && AI_CHAT.preload) {
                AI_CHAT.preload(summary);
                App.toast('持仓信息已填入 AI 助手, 确认后点击发送', 'success');
            } else {
                App.toast('AI 助手未加载, 请刷新页面重试', 'warn');
            }
        },

        /** 实盘待入场: realTradingCodes 里不在 realAccount.positions 中的股票 */
        realPendingRows() {
            const posCodes = new Set((this.realAccount.positions || []).map(p => this.normCode(p.stock_code)));
            return (this.realTradingCodes || [])
                .filter(c => c && !posCodes.has(c))
                .map(c => ({ code: c, name: this.stockNames[c] || '' }));
        },

        async applyStrategies() {
            // 只保留合并监控列表里出现过的票, 避免历史脏数据残留
            const codes = new Set(this.mergedList || []);
            const cleaned = {};
            for (const [code, name] of Object.entries(this.strategyConfig.per_stock || {})) {
                if (codes.has(code) && name) cleaned[code] = name;
            }
            const payload = { default: this.strategyConfig.default, per_stock: cleaned };
            const r = await App.post('/api/live/strategies/config', payload);
            this.opLog = r.message;
            App.toast(r.ok ? '策略配置已应用' : r.message, r.ok ? 'success' : 'warn');
            if (r.ok) {
                this.strategyConfig.per_stock = cleaned;
            }
        },

        _todayPrefix() {
            return new Date().toISOString().slice(0, 10);   // YYYY-MM-DD
        },
        // 信号: 直接按 ts 倒序, 最多展示 30 条
        // (历史回放 + 盘中实时信号都在 simState.signals / realState.signals 里, 不再做 today/all 切换)
        filteredSignals() {
            const all = ((this.viewMode === 'real' ? this.realState.signals : this.simState.signals) || []).slice();
            all.sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
            return all.slice(0, 30);
        },
        // 成交流水: 同样按 ts 倒序, 最多 20 条 (右侧紧凑展示)
        // 只显示实际执行的订单 (dry_run / submitted), 过滤 skipped_no_position / rejected / paused_by_ceo
        recentOrders() {
            const all = (this.simState.orders || []).filter(o =>
                o.status === 'dry_run' || o.status === 'submitted'
            );
            all.sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
            return all.slice(0, 20);
        },

        renderChart() {
            // 实盘视图没有 #pnl-chart 元素 (资金曲线只放在 sim 视图), 直接 return 避免 plotly 报错
            if (!document.getElementById('pnl-chart')) return;
            const h = this.simState.pnl_history || [];
            const mode = this.chartMode || 'today';

            // 数据过滤: all = 全部历史; today = 仅今天分时
            const now = new Date();
            const todayStr = now.toISOString().slice(0, 10);
            let filtered = h;
            if (mode === 'today') {
                filtered = h.filter(p => (p.ts || '').slice(0, 10) === todayStr);
            }

            const ts  = filtered.map(p => p.ts);
            const pct = filtered.map(p => (p.pnl_pct || 0) * 100);
            const lastVal = pct.length > 0 ? pct[pct.length - 1] : 0;
            const lineColor = lastVal >= 0 ? '#10b981' : '#ef4444';   // 涨绿跌红

            const data = filtered.length === 0
                ? [{ x: [], y: [], type: 'scatter' }]
                : [{
                    x: ts, y: pct, type: 'scatter', mode: 'lines',
                    line: { color: lineColor, width: 2, shape: 'spline' },
                    fill: 'tozeroy',
                    fillcolor: lastVal >= 0 ? 'rgba(16,185,129,0.10)' : 'rgba(239,68,68,0.10)',
                    hovertemplate: '%{x}<br>累计盈亏: %{y:.2f}%<extra></extra>',
                  }];

            // X 轴: today = 9:30-15:00 跳午休; all = 跨日, 跳周末/夜间/午休让线连贯
            let xaxis;
            if (mode === 'today') {
                xaxis = {
                    type: 'date',
                    range: [`${todayStr} 09:30:00`, `${todayStr} 15:00:00`],
                    tickformat: '%H:%M',
                    tickfont: { size: 10 },
                    rangebreaks: [
                        { bounds: [11.5, 13], pattern: 'hour' },
                    ],
                };
            } else {
                // all 视图: 历史日点每天 1 个 (14:59:00) + 今天分时(9:30-15:00),
                // 只跳周末就够了; 跳小时反而会把历史 14:59 点和今天分时点压挤变形
                xaxis = {
                    type: 'date',
                    tickformat: '%m-%d',
                    tickfont: { size: 10 },
                    rangebreaks: [
                        { bounds: ['sat', 'mon'], pattern: 'day of week' },
                    ],
                };
            }

            const layout = {
                margin: { l: 44, r: 16, t: 8, b: 30 },
                xaxis: xaxis,
                yaxis: {
                    tickfont: { size: 10 },
                    title: { text: '累计盈亏 %', font: { size: 11 } },
                    zerolinecolor: '#9ca3af', zerolinewidth: 1,
                    ticksuffix: '%',
                },
                showlegend: false,
                plot_bgcolor: '#fff',
                shapes: [
                    { type: 'line', xref: 'paper', x0: 0, x1: 1,
                      yref: 'y', y0: 0, y1: 0,
                      line: { color: '#9ca3af', width: 1, dash: 'dot' } },
                ],
            };
            Plotly.react('pnl-chart', data, layout, { displayModeBar: false });
        },

        setRealMode() {
            // 切换到实盘模式 -- 强二次确认
            const ok = confirm(
                '【高风险确认】\n\n' +
                '切换到实盘模式后, 启动循环时会连真实 miniQMT, 真实下单到你的券商账户!\n\n' +
                '请确认:\n' +
                '  1. .env 里 QMT_PATH 和 ACCOUNT_ID 已正确配置\n' +
                '  2. miniQMT 客户端已登录\n' +
                '  3. 你愿意承担信号触发后真实买卖的盈亏\n\n' +
                '继续切换吗?'
            );
            if (ok) {
                this.dryRun = false;
                App.toast('已切换到实盘模式 (慎用!)', 'danger');
            }
        },

        async simStart() {
            // 实盘模式启动前再次二次确认
            if (!this.dryRun) {
                if (!confirm('确认用【实盘模式】启动? 真实下单不可撤销!')) return;
            }
            const r = await App.post('/api/live/sim/start',
                { watch_stocks: this.simWatch, dry_run: this.dryRun });
            this.opLog = r.message;
            App.toast(r.ok ? '已启动' : r.message, r.ok ? 'success' : 'warn');
            await this.refresh();
        },

        async simStop() {
            const r = await App.post('/api/live/sim/stop', {});
            this.opLog = r.message;
            App.toast(r.message, 'info');
            await this.refresh();
        },

        async realStart() {
            if (!confirm('确认启动实盘引擎? 实盘信号需要手动授权才会下单。')) return;
            const r = await App.post('/api/live/real/start',
                { watch_stocks: this.realWatch || '', dry_run: false });
            this.opLog = r.message;
            App.toast(r.ok ? '实盘引擎已启动' : r.message, r.ok ? 'success' : 'warn');
            await this.refresh();
        },

        async realStop() {
            const r = await App.post('/api/live/real/stop', {});
            this.opLog = r.message;
            App.toast(r.message, 'info');
            await this.refresh();
        },

        /** 实盘试算: 按最近一根 K 线让引擎各策略跑一次 */
        async realTrialRunNow() {
            if (this.realTrialBusy) return;
            if (!confirm('实盘试算: 将按最新行情生成信号，但不会实际下单。\n\n继续吗?')) return;
            this.realTrialBusy = true;
            this.trialResult = null;
            try {
                const r = await App.post('/api/live/real/trial_run', {});
                if (r && r.ok) {
                    App.toast(r.message || '实盘试算已完成', 'success');
                    this.trialResult = {
                        summary:   r.summary   || {},
                        diagnoses: r.diagnoses || [],
                        message:   r.message   || '',
                    };
                } else {
                    App.toast((r && r.message) || '试算失败 (引擎可能未启动)', 'danger');
                }
                await this.refresh();
            } finally {
                this.realTrialBusy = false;
            }
        },

        /** 加载实盘自选池 */
        async loadRealWatchPool() {
            try {
                const d = await App.get('/api/live/real/watch_pool');
                const arr = d && Array.isArray(d.codes) ? d.codes : [];
                this.realWatchPoolText = arr.join(',');
            } catch (e) {
                console.error('loadRealWatchPool', e);
            }
        },

        /** 保存实盘自选池 */
        async saveRealWatchPool() {
            const raw = (this.realWatchPoolText || '').replace(/\r?\n/g, ',').replace(/，/g, ',');
            try {
                const r = await App.post('/api/live/real/watch_pool', { codes: raw });
                if (!r || typeof r !== 'object') {
                    App.toast('保存失败: 服务返回异常', 'warn');
                    return;
                }
                App.toast(r.ok ? (r.message || '已保存') : (r.message || '保存失败'), r.ok ? 'success' : 'warn');
                if (r.ok) await this.refreshRealMergedWatch();
            } catch (e) {
                console.error(e);
                App.toast('保存失败: ' + (e && e.message ? e.message : String(e)), 'warn');
            }
        },

        /** 实盘合并监控列表 */
        async refreshRealMergedWatch() {
            try {
                const ui = encodeURIComponent(this.realWatch || '');
                const res = await App.get('/api/live/real/watch_merge?ui=' + ui);
                this.realMergedList = Array.isArray(res.merged) ? res.merged : [];
                this.realBindingSource = (res && res.binding_source) ? res.binding_source : {};
                this.realTradingCodes = Array.isArray(res.trading_codes) ? res.trading_codes : [];
                // 同时为 mergedList 和 tradingCodes 加载股票名称 (待入场需要名称)
                const allCodes = [...new Set([...this.realMergedList, ...this.realTradingCodes])];
                await this.loadStockNames(allCodes);
                await this.loadRealPendingQuotes();
            } catch (e) {
                console.error('refreshRealMergedWatch', e);
                this.realMergedList = [];
                this.realBindingSource = {};
            }
        },

        /** 实盘自选池代码列表 */
        realWatchPoolCodes() {
            return (this.realWatchPoolText || '')
                .split(/[,，\r\n]+/)
                .map(c => this.normCode(c.trim()))
                .filter(c => c.length > 0)
                .filter((c, i, arr) => arr.indexOf(c) === i);
        },

        /** 实盘自选池候选列表: 过滤掉已纳入交易的代码, 附带行情 */
        realWatchListItems() {
            const trading = new Set(this.realTradingCodes || []);
            return this.realWatchPoolCodes()
                .map(c => this.normCode(c))
                .filter((c, i, arr) => arr.indexOf(c) === i)
                .filter(c => !trading.has(c))
                .map(c => ({
                    code: c,
                    name: this.stockNames[c] || '',
                    quote: this.realWatchQuotes[c] || null,
                }));
        },

        /** 实盘强制卖出 */
        async realForceSell(code) {
            if (!code) return;
            if (!confirm('强制卖出 ' + code + ': 下一轮主循环会清仓该票 (真实 miniQMT)。\n\n继续吗?')) return;
            try {
                const r = await App.post('/api/live/real/force_sell', { code: code });
                this.opLog = r.message || '';
                App.toast(r.message || '已提交', r.ok ? 'success' : 'danger');
                await this.refresh();
            } catch (e) {
                App.toast('强制卖出失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            }
        },

        /** 实盘自选池添加代码 */
        async confirmRealWatchAdd() {
            const code = this.normCode((this.realWatchAddCode || '').trim());
            if (!code) {
                App.toast('请填写股票代码', 'warn');
                return;
            }
            const codes = this.realWatchPoolCodes();
            if (codes.includes(code)) {
                App.toast(code + ' 已在实盘自选池中', 'info');
                this.realWatchAddMode = false;
                this.realWatchAddCode = '';
                return;
            }
            codes.push(code);
            this.realWatchPoolText = codes.join(',');
            this.realWatchAddMode = false;
            this.realWatchAddCode = '';
            await this.saveRealWatchPool();
        },

        async resetPositions() {
            if (!confirm('确认重置模拟盘?\n1. 按 config/mock_positions.yaml 覆盖持仓\n2. 清空自选监控池\n现有持仓与自选池都会被重置!')) return;
            const r = await App.post('/api/live/sim/reset_positions', {});
            this.opLog = r.message;
            App.toast(r.message, 'success');
            await this.refresh();
        },

        async clearHistory() {
            if (!confirm('确认清空 信号 / 订单 / 盈亏曲线 / 事件流 ?\n持仓不会被清掉。')) return;
            const r = await App.post('/api/live/sim/clear_history', {});
            this.opLog = r.message;
            App.toast(r.message, 'success');
            await this.refresh();
        },

        /** 实盘清空历史: 清掉信号/事件流 (不影响真实 miniQMT 持仓) */
        async realClearHistory() {
            if (!confirm('确认清空实盘信号 / 订单 / 事件流 ?\n真实 miniQMT 持仓不会被清掉。')) return;
            const r = await App.post('/api/live/real/clear_history', {});
            this.opLog = r.message;
            App.toast(r.message, 'success');
            await this.refresh();
        },

        /** 立即试算一轮: 不等盘中, 按最近一根 K 线让所有已绑策略各跑一次
         *  - buy/sell 信号会写到信号表 (走完整 loop 含风控+撮合)
         *  - hold 不写表, 但通过 diagnoses 在弹窗里展示, 答"为什么没有信号" */
        async trialRunNow() {
            if (this.trialBusy) return;
            const ctrl = (this.simState && this.simState.control) || {};
            const pendingSell = ctrl.force_clear_all || (ctrl.force_sell_codes && ctrl.force_sell_codes.length > 0);
            let tip = '立即试算一轮: 将按最新行情生成信号并模拟撮合成交。';
            if (pendingSell) {
                tip += '\n\n⚠️ 当前有强制卖出在队列中, 试算将立即执行这些卖出!';
            }
            tip += '\n\n继续吗?';
            if (!confirm(tip)) return;

            this.trialBusy = true;
            this.trialResult = null;
            try {
                const r = await App.post('/api/live/sim/trial_run', {});
                if (r && r.ok) {
                    App.toast(r.message || '已试算 1 轮', 'success');
                    this.trialResult = {
                        summary:   r.summary   || {},
                        diagnoses: r.diagnoses || [],
                        message:   r.message   || '',
                    };
                } else {
                    App.toast((r && r.message) || '试算失败 (引擎可能未启动)', 'danger');
                }
                await this.refresh();
            } finally {
                this.trialBusy = false;
            }
        },

        async ctrl(field, value) {
            const r = await App.post('/api/live/control', { field, value });
            this.opLog = r.message;
            App.toast(r.message, 'success');
            await this.refresh();
        },

        async setStatus(status) {
            const r = await App.post('/api/live/status', { status });
            this.opLog = r.message;
            App.toast(r.message, 'success');
            await this.refresh();
        },

        // 龙头战法 -- 拉候选名单
        // 数据源: auto (默认 = mysql -> xtdata -> mock 自动降级) / mysql / xtdata / mock
        async loadDragonCandidates() {
            this.dragon.loading = true;
            try {
                const params = new URLSearchParams({ source: this.dragon.sourceMode || 'auto' });
                const r = await App.get('/api/dragon/candidates?' + params.toString());
                this.dragon.items = (r && r.items) || [];
                this.dragon.source = (r && r.source) || '';
                this.dragon.tradeDate = (r && r.trade_date) || '';
                this.dragon.warning = (r && r.warning) || '';
                if (!this.dragon.items.length) App.toast('当前条件下无龙头候选', 'warn');
            } catch (e) {
                App.toast('拉龙头候选失败: ' + e, 'danger');
            } finally {
                this.dragon.loading = false;
            }
        },

        // 一键把候选写入 watch_pool 并绑 dragon_picker (热加载)
        async bindDragonAll() {
            const codes = this.dragon.items.map((x) => x.code);
            if (codes.length === 0) return;
            if (!confirm('把 ' + codes.length + ' 只龙头候选加入监控并绑定 dragon_picker?')) return;
            this.dragon.binding = true;
            try {
                const r = await App.post('/api/dragon/bind', { codes });
                this.opLog = r.message || '';
                App.toast(r.message || '完成', r.ok ? 'success' : 'danger');
                await this.refresh();
            } catch (e) {
                App.toast('绑定失败: ' + e, 'danger');
            } finally {
                this.dragon.binding = false;
            }
        },

        // 危险操作二次确认: action ∈ {'force_clear_all', 'HALTED'}
        async confirmDanger(action) {
            const labels = {
                force_clear_all: { tip: '一键清仓: 下一轮主循环会平掉全部持仓\n\n继续吗?',
                                   call: () => this.ctrl('force_clear_all', true) },
                HALTED:          { tip: '强制熔断: 立刻进入 HALTED 状态, 必须人工解除\n\n继续吗?',
                                   call: () => this.setStatus('HALTED') },
            };
            const item = labels[action];
            if (!item) return;
            if (!confirm(item.tip)) return;
            await item.call();
        },

        // 单票强制卖出二次确认
        async confirmForceSell(code) {
            if (!code) return;
            if (!confirm('强制卖出 ' + code + ': 下一轮主循环会忽略策略/交易计划, 直接清仓该票。\n\n继续吗?')) return;
            try {
                const r = await App.post('/api/live/force_sell', { code: code });
                this.opLog = r.message || '';
                App.toast(r.message || '已提交', r.ok ? 'success' : 'danger');
                await this.refresh();
            } catch (e) {
                App.toast('强制卖出失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            }
        },

        /** 取消待入场: 清除执行方式(plan/strategy), 解绑策略, 退回自选监控池 */
        async cancelEntry(code) {
            if (!code) return;
            if (!confirm('取消 ' + code + ' 的待入场: 清除执行方式, 退回自选监控池。\n\n继续吗?')) return;
            try {
                const isStrategy = this.isStrategyMode(code);
                // 清除执行模式 (plan 或 strategy) -- sim
                await App.post('/api/live/sim/execution_mode', { code, mode: '' });
                // 有策略绑定则解绑 (unbind 会从 watch_pool.yaml 移除该股)
                if (isStrategy) {
                    const unbindR = await App.post('/api/live/stock/unbind', { code });
                    this.opLog = (unbindR && unbindR.message) || '';
                }
                // 无论策略/计划模式, 取消待入场后一律退回自选监控池:
                // 重新拉取后端最新 watch_pool, 缺失则补回
                const d = await App.get('/api/live/watch_pool');
                const codes = Array.isArray(d && d.codes) ? d.codes : [];
                if (!codes.includes(code)) {
                    codes.push(code);
                    this.watchPoolText = codes.join(',');
                    await this.saveWatchPool();
                } else {
                    this.watchPoolText = codes.join(',');
                }
                App.toast(code + ' 已取消待入场, 退回自选监控池', 'success');
                await this.refreshMergedWatch();
                await this.refresh();
            } catch (e) {
                App.toast('取消失败: ' + (e && e.message ? e.message : String(e)), 'danger');
            }
        },

        /** 取消实盘待入场: 清除执行方式, 解绑策略, 退回实盘自选池 */
        async cancelRealEntry(code) {
            if (!code) return;
            if (!confirm('取消 ' + code + ' 的待入场: 清除执行方式, 退回实盘自选池。\n\n继续吗?')) return;
            try {
                // 清除执行模式 (plan 或 strategy) -- real
                await App.post('/api/live/real/execution_mode', { code, mode: '' });

                // 解绑实盘策略 (从 strategies_real.yaml 移除)
                const r = await App.post('/api/live/real/stock/unbind', { code });
                this.opLog = r.message || '';
                if (r && r.ok) {
                    if (r.per_stock) this.realStrategyConfig.per_stock = { ...r.per_stock };
                    if (r.default) this.realStrategyConfig.default = r.default;
                }

                // 将代码加回实盘自选池 (unbind 会从 watch_pool_real.yaml 移除, 需恢复)
                const codes = this.realWatchPoolCodes();
                if (!codes.includes(code)) {
                    codes.push(code);
                    this.realWatchPoolText = codes.join(',');
                    await this.saveRealWatchPool();
                }

                App.toast(code + ' 已取消待入场, 退回实盘自选池', 'success');
                await this.refreshRealMergedWatch();
                await this.refresh();
            } catch (e) {
                App.toast('取消失败: ' + (e && e.message ? e.message : String(e)), 'warn');
            }
        },
    }
}
