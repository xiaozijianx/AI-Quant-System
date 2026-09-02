/* Agent 设置抽屉 — P1-2 ~ P1-7
 *
 * 对接后端已有的设置类 API 端点：
 *   - Provider:       GET/PUT/DELETE /api/chat/providers
 *   - Mode:           GET/POST /api/chat/mode
 *   - Approval memory: GET/DELETE /api/chat/approval_memory
 *   - Rules toggles:  GET/PUT /api/chat/sessions/{id}/rule_toggles
 *   - MCP servers:    GET /api/chat/mcp/servers, POST /api/chat/mcp/reload
 *   - Checkpoints:    GET /api/chat/checkpoints, POST /api/chat/rollback
 */
const AI_SETTINGS = {
    currentTab: 'provider',
    isOpen: false,

    open() {
        document.getElementById('settings-drawer').classList.add('open');
        document.getElementById('settings-overlay').classList.add('show');
        this.isOpen = true;
        this.switchTab(this.currentTab);
    },

    close() {
        document.getElementById('settings-drawer').classList.remove('open');
        document.getElementById('settings-overlay').classList.remove('show');
        this.isOpen = false;
    },

    switchTab(tab) {
        this.currentTab = tab;
        document.querySelectorAll('.settings-tab').forEach(el => {
            el.classList.toggle('active', el.dataset.tab === tab);
        });
        const body = document.getElementById('settings-body');
        body.innerHTML = '<div class="settings-loading">加载中...</div>';
        const loaders = {
            provider: () => this._loadProviderTab(),
            mode: () => this._loadModeTab(),
            approval: () => this._loadApprovalTab(),
            rules: () => this._loadRulesTab(),
            mcp: () => this._loadMcpTab(),
            checkpoint: () => this._loadCheckpointTab(),
            file_checkpoint: () => this._loadFileCheckpointTab(),
            cron: () => this._loadCronTab(),
            pending: () => this._loadPendingTab(),
        };
        (loaders[tab] || loaders.provider)();
    },

    esc(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[c]);
    },

    // 获取当前会话 ID，兼容 AI_CHAT 可能未初始化的情况
    _getSessionId() {
        return (typeof AI_CHAT !== 'undefined' && AI_CHAT.currentConvId) || '';
    },

    toast(msg) {
        if (typeof AI_CHAT !== 'undefined' && AI_CHAT._showToast) {
            AI_CHAT._showToast(msg);
        } else {
            console.log('[settings]', msg);
        }
    },

    async apiGet(url) {
        const resp = await fetch(url);
        return resp.json();
    },

    async apiSend(url, method, body) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const resp = await fetch(url, opts);
        return resp.json();
    },

    // ============ Provider Tab ============
    async _loadProviderTab() {
        const body = document.getElementById('settings-body');
        try {
            const data = await this.apiGet('/api/chat/providers');
            if (data.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(data.message || '加载失败')}</div>`;
                return;
            }
            const providers = data.providers || [];
            const builtin = data.builtin || [];
            const active = data.active_provider || {};
            const activeAlias = active.alias || '';
            const isActiveConfigured = providers.some(p => p.alias === activeAlias);

            const sourceMap = {
                env_default: '环境变量默认值',
                env_override: '环境变量覆盖',
                configured: '已手动配置',
            };
            const sourceClass = {
                env_default: 'provider-source-default',
                env_override: 'provider-source-override',
                configured: 'provider-source-configured',
            };
            const sourceText = sourceMap[active.source] || active.source || '未知';
            const sourceCls = sourceClass[active.source] || 'provider-source-default';
            const apiKeyConfigured = !!(active.api_key_masked && active.env_key);
            const apiKeySourceText = active.api_key_source === 'configured' ? '文件配置' : (active.api_key_source === 'env' ? '环境变量' : '未配置');
            const apiKeyStatusText = apiKeyConfigured ? `已配置 (${apiKeySourceText})` : '未配置';
            const apiKeyStatusCls = apiKeyConfigured ? 'provider-key-on' : 'provider-key-off';

            let html = `
                <div class="settings-section">
                    <div class="section-title">当前生效 Provider</div>
                    <div class="section-desc">当前 Agent 实际使用的 Provider 配置。api_key 可在此页面配置并保存到 providers.yaml，也可通过环境变量配置。</div>
                    <div class="provider-card active-provider-card">
                        <div class="provider-header">
                            <span class="provider-id">${this.esc(active.alias || active.provider_id || '-')}</span>
                            <span class="provider-source ${sourceCls}">${this.esc(sourceText)}</span>
                            <span class="provider-key-status ${apiKeyStatusCls}">${this.esc(apiKeyStatusText)}</span>
                            ${isActiveConfigured
                                ? `<button class="btn-small" onclick="AI_SETTINGS._editProvider('${this.esc(active.alias)}')">编辑</button>`
                                : `<button class="btn-small" onclick="AI_SETTINGS._editActiveProvider()">编辑/保存为配置</button>`}
                        </div>
                        <div class="provider-fields">
                            <div><span class="field-label">provider_id:</span> <span class="field-value">${this.esc(active.provider_id || '-')}</span></div>
                            <div><span class="field-label">model_id:</span> <span class="field-value">${this.esc(active.model_id || '-')}</span></div>
                            <div><span class="field-label">base_url:</span> <span class="field-value">${this.esc(active.base_url || '-')}</span></div>
                            <div><span class="field-label">temperature:</span> <span class="field-value">${this.esc(active.temperature ?? '-')}</span></div>
                            <div><span class="field-label">max_tokens:</span> <span class="field-value">${this.esc(active.max_tokens ?? '-')}</span></div>
                            <div><span class="field-label">API Key 环境变量:</span> <span class="field-value">${this.esc(active.env_key || '-')}</span></div>
                            <div><span class="field-label">API Key:</span> <span class="field-value">${this.esc(active.api_key_masked || '-')}</span></div>
                        </div>
                    </div>
                </div>
                <div class="settings-section">
                    <div class="section-title">已配置 Provider</div>
                    <div class="section-desc">每条配置以“别名(alias)”为唯一标识，可拥有相同的 provider_id 但不同的 model_id。点击编辑可修改 provider_id / model_id / base_url / api_key / temperature / max_tokens。</div>
                    <div id="providers-list">`;
            if (providers.length === 0) {
                html += '<div class="empty-hint">暂无已配置 Provider，使用环境变量默认值</div>';
            } else {
                for (const p of providers) {
                    const title = p.model_id || p.alias;
                    const sub = p.model_id ? `${p.provider_id} · ${p.alias}` : p.provider_id;
                    html += `
                        <div class="provider-card">
                            <div class="provider-header">
                                <span class="provider-id">${this.esc(title)}</span>
                                <span class="provider-sub">${this.esc(sub)}</span>
                                <button class="btn-small" onclick="AI_SETTINGS._editProvider('${this.esc(p.alias)}')">编辑</button>
                                <button class="btn-small btn-danger" onclick="AI_SETTINGS._deleteProvider('${this.esc(p.alias)}')">删除</button>
                            </div>
                            <div class="provider-fields">
                                <div><span class="field-label">provider_id:</span> <span class="field-value">${this.esc(p.provider_id || '-')}</span></div>
                                <div><span class="field-label">model_id:</span> <span class="field-value">${this.esc(p.model_id || '-')}</span></div>
                                <div><span class="field-label">base_url:</span> <span class="field-value">${this.esc(p.base_url || '-')}</span></div>
                                <div><span class="field-label">temperature:</span> <span class="field-value">${this.esc(p.temperature ?? '-')}</span></div>
                                <div><span class="field-label">max_tokens:</span> <span class="field-value">${this.esc(p.max_tokens ?? '-')}</span></div>
                                <div><span class="field-label">env_key:</span> <span class="field-value">${this.esc(p.env_key || '-')}</span></div>
                                <div><span class="field-label">api_key:</span> <span class="field-value">${this.esc(p.api_key_masked || '-')}</span></div>
                            </div>
                        </div>`;
                }
            }
            html += `</div></div>
                <div class="settings-section">
                    <div class="section-title">添加 Provider</div>
                    <div class="section-desc">从内置 Provider 类型中选择添加。可多次添加同一类型，通过 model_id 区分不同模型（如 qwen-flash / qwen-max / deepseek-r1）。</div>
                    <div class="builtin-list">`;
            for (const id of builtin) {
                html += `<button class="btn-small" onclick="AI_SETTINGS._addProvider('${this.esc(id)}')">+ ${this.esc(id)}</button>`;
            }
            html += '</div></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    /** 编辑当前生效的 Provider 并保存为配置 */
    _editActiveProvider() {
        const body = document.getElementById('settings-body');
        this.apiGet('/api/chat/providers').then(data => {
            if (data.status !== 'ok' || !data.active_provider) return;
            const active = data.active_provider;
            const alias = active.alias || active.provider_id;
            body.innerHTML = `
                <div class="settings-section">
                    <div class="section-title">编辑 Provider: ${this.esc(alias)}</div>
                    <div class="section-desc">保存后该 Provider 的配置将写入 providers.yaml。</div>
                    <div class="form-row"><label>provider_id</label><input id="pf-pid" type="text" readonly value="${this.esc(active.provider_id)}"></div>
                    <div class="form-row"><label>model_id</label><input id="pf-model" type="text" placeholder="如 qwen-plus"></div>
                    <div class="form-row"><label>base_url</label><input id="pf-baseurl" type="text" placeholder="https://..."></div>
                    <div class="form-row"><label>api_key</label><input id="pf-apikey" type="password" placeholder="留空保留现有配置；输入后保存到 providers.yaml"></div>
                    <div class="form-row"><label>temperature</label><input id="pf-temp" type="number" step="0.1" placeholder="0.1"></div>
                    <div class="form-row"><label>max_tokens</label><input id="pf-maxtok" type="number" placeholder="8192"></div>
                    <div class="form-actions">
                        <button class="btn-primary" onclick="AI_SETTINGS._saveProvider('${this.esc(alias)}')">保存</button>
                        <button class="btn-small" onclick="AI_SETTINGS._loadProviderTab()">取消</button>
                    </div>
                </div>`;
            document.getElementById('pf-model').value = active.model_id || '';
            document.getElementById('pf-baseurl').value = active.base_url || '';
            document.getElementById('pf-apikey').value = '';
            document.getElementById('pf-temp').value = active.temperature ?? '';
            document.getElementById('pf-maxtok').value = active.max_tokens ?? '';
        });
    },

    async _addProvider(providerId) {
        // 自动生成不重复的 alias（如 qwen / qwen-1 / qwen-2）
        let alias = providerId;
        try {
            const existing = await this.apiGet('/api/chat/providers');
            const aliases = new Set((existing.providers || []).map(p => p.alias));
            if (aliases.has(alias)) {
                let suffix = 1;
                while (aliases.has(`${providerId}-${suffix}`)) {
                    suffix++;
                }
                alias = `${providerId}-${suffix}`;
            }
        } catch (err) {
            console.warn('生成 alias 失败:', err);
        }
        const defaults = {
            provider_id: providerId,
            model_id: '',
            base_url: '',
            temperature: 0.1,
            max_tokens: 8192,
        };
        const data = await this.apiSend(`/api/chat/providers/${encodeURIComponent(alias)}`, 'PUT', defaults);
        if (data.status === 'ok') {
            this.toast(`已添加 Provider 配置: ${alias}`);
            this._loadProviderTab();
            // 同步刷新聊天工具栏的 Provider 下拉选择器
            if (typeof AI_CHAT !== 'undefined' && AI_CHAT.refreshProviders) {
                AI_CHAT.refreshProviders();
            }
        } else {
            this.toast(`添加失败: ${data.message || ''}`);
        }
    },

    async _deleteProvider(alias) {
        if (!confirm(`确认删除 Provider 配置 ${alias}？删除后回退到环境变量默认值。`)) return;
        const data = await this.apiSend(`/api/chat/providers/${encodeURIComponent(alias)}`, 'DELETE');
        if (data.status === 'ok') {
            this.toast(`已删除 Provider 配置: ${alias}`);
            this._loadProviderTab();
            // 同步刷新聊天工具栏的 Provider 下拉选择器
            if (typeof AI_CHAT !== 'undefined' && AI_CHAT.refreshProviders) {
                AI_CHAT.refreshProviders();
            }
        } else {
            this.toast(`删除失败: ${data.message || ''}`);
        }
    },

    async _editProvider(alias) {
        const body = document.getElementById('settings-body');
        body.innerHTML = `
            <div class="settings-section">
                <div class="section-title">编辑 Provider: ${this.esc(alias)}</div>
                <div class="form-row"><label>alias</label><input id="pf-alias" type="text" readonly value="${this.esc(alias)}"></div>
                <div class="form-row"><label>provider_id</label><input id="pf-pid" type="text" placeholder="如 qwen / deepseek / openai"></div>
                <div class="form-row"><label>model_id</label><input id="pf-model" type="text" placeholder="如 qwen-plus"></div>
                <div class="form-row"><label>base_url</label><input id="pf-baseurl" type="text" placeholder="https://..."></div>
                <div class="form-row"><label>api_key</label><input id="pf-apikey" type="password" placeholder="留空保留现有配置；输入后保存到 providers.yaml"></div>
                <div class="form-row"><label>temperature</label><input id="pf-temp" type="number" step="0.1" placeholder="0.1"></div>
                <div class="form-row"><label>max_tokens</label><input id="pf-maxtok" type="number" placeholder="8192"></div>
                <div class="form-actions">
                    <button class="btn-primary" onclick="AI_SETTINGS._saveProvider('${this.esc(alias)}')">保存</button>
                    <button class="btn-small" onclick="AI_SETTINGS._loadProviderTab()">取消</button>
                </div>
            </div>`;
        // 拉取当前值填充（api_key 不回显明文，留空让用户重新输入或清空）
        try {
            const data = await this.apiGet(`/api/chat/providers/${encodeURIComponent(alias)}`);
            if (data.status === 'ok' && data.provider) {
                const p = data.provider;
                document.getElementById('pf-pid').value = p.provider_id || '';
                document.getElementById('pf-model').value = p.model_id || '';
                document.getElementById('pf-baseurl').value = p.base_url || '';
                document.getElementById('pf-apikey').value = '';
                document.getElementById('pf-temp').value = p.temperature ?? '';
                document.getElementById('pf-maxtok').value = p.max_tokens ?? '';
            }
        } catch (err) { /* 忽略，让用户手动填 */ }
    },

    async _saveProvider(alias) {
        const pidInput = document.getElementById('pf-pid');
        const apiKeyInput = document.getElementById('pf-apikey').value;
        const payload = {
            provider_id: pidInput ? pidInput.value.trim() : '',
            model_id: document.getElementById('pf-model').value.trim(),
            base_url: document.getElementById('pf-baseurl').value.trim(),
            temperature: parseFloat(document.getElementById('pf-temp').value) || 0.1,
            max_tokens: parseInt(document.getElementById('pf-maxtok').value) || 8192,
        };
        // api_key 仅在有输入时才提交，避免误清空已保存的 key
        if (apiKeyInput) {
            payload.api_key = apiKeyInput;
        }
        const data = await this.apiSend(`/api/chat/providers/${encodeURIComponent(alias)}`, 'PUT', payload);
        if (data.status === 'ok') {
            this.toast(`Provider ${alias} 已保存`);
            this._loadProviderTab();
            // 同步刷新聊天工具栏的 Provider 下拉选择器
            if (typeof AI_CHAT !== 'undefined' && AI_CHAT.refreshProviders) {
                AI_CHAT.refreshProviders();
            }
        } else {
            this.toast(`保存失败: ${data.message || ''}`);
        }
    },

    // ============ Mode Tab ============
    async _loadModeTab() {
        const body = document.getElementById('settings-body');
        const sid = this._getSessionId();
        // 先用 AI_CHAT.currentMode 渲染，避免空白/闪烁；同时异步从后端同步最新状态
        let currentMode = (typeof AI_CHAT !== 'undefined' && AI_CHAT.currentMode) || 'act';
        body.innerHTML = this._renderModeForm(sid, currentMode);
        if (sid) {
            try {
                const data = await this.apiGet(`/api/chat/mode?session_id=${encodeURIComponent(sid)}`);
                if (data.status === 'ok' && data.mode !== currentMode) {
                    currentMode = data.mode;
                    // 同步 AI_CHAT 的 currentMode 和 UI
                    if (typeof AI_CHAT !== 'undefined') {
                        AI_CHAT.currentMode = currentMode;
                        try { localStorage.setItem('ai_chat_mode', currentMode); } catch(e) {}
                        AI_CHAT._updateModeUI();
                    }
                    body.innerHTML = this._renderModeForm(sid, currentMode);
                }
            } catch (err) {
                console.warn('从后端同步 mode 失败:', err);
            }
        }
    },

    _renderModeForm(sid, currentMode) {
        const sidText = sid || '(未选择)';
        return `
            <div class="settings-section">
                <div class="section-title">当前会话工作模式</div>
                <div class="section-desc">Plan 模式禁用 editor/apply_patch/file_write 工具，仅做探索和规划；Act 模式允许全部工具调用；Yolo 模式自动执行，无需逐步确认。</div>
                <div class="mode-switcher">
                    <label class="mode-radio">
                        <input type="radio" name="mode-radio" value="act" ${currentMode === 'act' ? 'checked' : ''} onchange="AI_SETTINGS._setMode('act')">
                        <span><strong>Act 模式</strong>：直接执行任务，可读写文件、运行命令</span>
                    </label>
                    <label class="mode-radio">
                        <input type="radio" name="mode-radio" value="plan" ${currentMode === 'plan' ? 'checked' : ''} onchange="AI_SETTINGS._setMode('plan')">
                        <span><strong>Plan 模式</strong>：仅探索分析、呈现计划，不修改文件</span>
                    </label>
                    <label class="mode-radio mode-radio-yolo">
                        <input type="radio" name="mode-radio" value="yolo" ${currentMode === 'yolo' ? 'checked' : ''} onchange="AI_SETTINGS._setMode('yolo')">
                        <span><strong>Yolo 模式</strong>：自动执行，无需逐步确认（适合后台自动化场景）</span>
                    </label>
                </div>
                <div class="section-desc" style="margin-top:12px;">会话 ID: <code>${this.esc(sidText)}</code></div>
            </div>`;
    },

    async _setMode(mode) {
        const sid = (AI_CHAT && AI_CHAT.currentConvId) || '';
        if (!sid) {
            this.toast('请先选择一个对话');
            return;
        }
        const data = await this.apiSend('/api/chat/mode', 'POST', { session_id: sid, mode });
        if (data.status === 'ok') {
            const modeName = { act: 'Act', plan: 'Plan', yolo: 'Yolo' }[mode] || mode;
            this.toast(`已切换到 ${modeName} 模式`);
            // 同步 AI_CHAT 的 currentMode
            if (AI_CHAT) {
                AI_CHAT.currentMode = mode;
                try { localStorage.setItem('ai_chat_mode', mode); } catch(e) {}
                AI_CHAT._updateModeUI();
            }
        } else {
            this.toast(`切换失败: ${data.message || ''}`);
        }
    },

    // ============ Approval Memory Tab ============
    async _loadApprovalTab() {
        const body = document.getElementById('settings-body');
        try {
            const data = await this.apiGet('/api/chat/approval_memory');
            if (data.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(data.message || '加载失败')}</div>`;
                return;
            }
            const tools = data.tools || [];
            let html = `
                <div class="settings-section">
                    <div class="section-title">持久化审批记忆</div>
                    <div class="section-desc">已标记"始终允许"的工具列表。重启 agent 后仍生效。可单条删除或全部清空。</div>
                    <div class="section-actions">
                        <button class="btn-small btn-danger" onclick="AI_SETTINGS._clearAllApproval()">全部清空</button>
                    </div>
                    <div id="approval-list">`;
            if (tools.length === 0) {
                html += '<div class="empty-hint">暂无持久化审批记忆</div>';
            } else {
                for (const t of tools) {
                    html += `
                        <div class="approval-row">
                            <span class="approval-tool">${this.esc(t)}</span>
                            <button class="btn-small btn-danger" onclick="AI_SETTINGS._deleteApproval('${this.esc(t)}')">删除</button>
                        </div>`;
                }
            }
            html += '</div></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _deleteApproval(toolName) {
        if (!confirm(`确认删除 ${toolName} 的审批记忆？`)) return;
        const data = await this.apiSend(`/api/chat/approval_memory/${encodeURIComponent(toolName)}`, 'DELETE');
        if (data.status === 'ok') {
            this.toast(`已删除 ${toolName} 的审批记忆`);
            this._loadApprovalTab();
        } else {
            this.toast(`删除失败: ${data.message || ''}`);
        }
    },

    async _clearAllApproval() {
        if (!confirm('确认清空全部审批记忆？下次调用工具将重新弹审批。')) return;
        const data = await this.apiSend('/api/chat/approval_memory', 'DELETE');
        if (data.status === 'ok') {
            this.toast('已清空全部审批记忆');
            this._loadApprovalTab();
        } else {
            this.toast(`清空失败: ${data.message || ''}`);
        }
    },

    // ============ Rules Toggles Tab ============
    async _loadRulesTab() {
        const body = document.getElementById('settings-body');
        const sid = this._getSessionId();
        if (!sid) {
            body.innerHTML = '<div class="empty-hint">请先选择一个对话</div>';
            return;
        }
        try {
            const [mergedResp, globalResp] = await Promise.all([
                this.apiGet(`/api/chat/sessions/${encodeURIComponent(sid)}/rule_toggles?scope=merged`),
                this.apiGet(`/api/chat/sessions/${encodeURIComponent(sid)}/rule_toggles?scope=global`),
            ]);
            if (mergedResp.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(mergedResp.message || '加载失败')}</div>`;
                return;
            }
            const merged = mergedResp.toggles || {};
            const globalToggles = globalResp.toggles || {};
            const keys = Object.keys(merged).sort();
            let html = `
                <div class="settings-section">
                    <div class="section-title">规则文件开关</div>
                    <div class="section-desc">控制 agent_config/rules/ 下规则文件的启用状态。本会话的 local 设置会覆盖 global。</div>
                    <table class="rules-table">
                        <thead>
                            <tr><th>规则文件</th><th>global</th><th>本会话 local</th></tr>
                        </thead>
                        <tbody>`;
            if (keys.length === 0) {
                html += '<tr><td colspan="3" class="empty-hint">暂无规则文件</td></tr>';
            } else {
                for (const k of keys) {
                    const gval = globalToggles[k] !== false;
                    const lval = merged[k] !== false;
                    html += `
                        <tr>
                            <td>${this.esc(k)}</td>
                            <td>${gval ? '启用' : '禁用'}</td>
                            <td>
                                <label class="switch">
                                    <input type="checkbox" ${lval ? 'checked' : ''} onchange="AI_SETTINGS._toggleRule('${this.esc(k)}', this.checked)">
                                    <span class="slider"></span>
                                </label>
                            </td>
                        </tr>`;
                }
            }
            html += '</tbody></table></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _toggleRule(ruleKey, enabled) {
        const sid = this._getSessionId();
        if (!sid) return;
        // 先读当前 local toggles，再合并本次变更
        try {
            const resp = await this.apiGet(`/api/chat/sessions/${encodeURIComponent(sid)}/rule_toggles?scope=local`);
            const toggles = resp.toggles || {};
            toggles[ruleKey] = enabled;
            await this.apiSend(`/api/chat/sessions/${encodeURIComponent(sid)}/rule_toggles`, 'PUT', { toggles });
            this.toast(`规则 ${ruleKey} 已${enabled ? '启用' : '禁用'}`);
        } catch (err) {
            this.toast(`更新失败: ${err.message}`);
        }
    },

    // ============ MCP Servers Tab ============
    async _loadMcpTab() {
        const body = document.getElementById('settings-body');
        try {
            const data = await this.apiGet('/api/chat/mcp/servers');
            if (data.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(data.message || '加载失败')}</div>`;
                return;
            }
            const servers = data.servers || [];
            let html = `
                <div class="settings-section">
                    <div class="section-title">MCP 服务器</div>
                    <div class="section-desc">已配置的 MCP 服务器及其工具。可在前端添加、编辑、删除服务器配置，也可修改 agent_config/mcp_servers.yaml 后点击"重新加载"。</div>
                    <div class="section-actions">
                        <button class="btn-primary" onclick="AI_SETTINGS._reloadMcp()">重新加载配置</button>
                        <button class="btn-small" onclick="AI_SETTINGS._showMcpForm()">+ 添加服务器</button>
                    </div>
                    <div id="mcp-list">`;
            if (servers.length === 0) {
                html += '<div class="empty-hint">暂无 MCP 服务器配置，点击"添加服务器"创建</div>';
            } else {
                for (const s of servers) {
                    const tools = (s.tools || []).map(t => `<span class="mcp-tool-chip">${this.esc(t.name)}</span>`).join('');
                    html += `
                        <div class="mcp-card ${s.enabled ? '' : 'disabled'}">
                            <div class="mcp-header">
                                <span class="mcp-name">${this.esc(s.name)}</span>
                                <span class="mcp-transport">${this.esc(s.transport)}</span>
                                <span class="mcp-status ${s.enabled ? 'on' : 'off'}">${s.enabled ? '启用' : '禁用'}</span>
                                <span class="mcp-card-actions">
                                    <button class="btn-small" onclick="AI_SETTINGS._showMcpForm('${this.esc(s.name)}')">编辑</button>
                                    <button class="btn-small btn-danger" onclick="AI_SETTINGS._deleteMcpServer('${this.esc(s.name)}')">删除</button>
                                </span>
                            </div>
                            <div class="mcp-desc">${this.esc(s.description || '')}</div>
                            <div class="mcp-tools">${tools || '<span class="empty-hint">无工具</span>'}</div>
                        </div>`;
                }
            }
            html += '</div></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _reloadMcp() {
        try {
            const data = await this.apiSend('/api/chat/mcp/reload', 'POST');
            if (data.status === 'ok') {
                this.toast(data.message || 'MCP 配置已重载');
                this._loadMcpTab();
            } else {
                this.toast(`重载失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`重载失败: ${err.message}`);
        }
    },

    // 渲染添加/编辑 MCP 服务器的模态框
    _showMcpForm(serverName) {
        const isEdit = !!serverName;
        // 移除已有模态框
        this._closeMcpForm();

        const overlay = document.createElement('div');
        overlay.className = 'mcp-modal-overlay';
        overlay.id = 'mcp-modal-overlay';
        overlay.innerHTML = `
            <div class="mcp-modal">
                <div class="mcp-modal-header">
                    <span class="mcp-modal-title">${isEdit ? '编辑 MCP 服务器' : '添加 MCP 服务器'}</span>
                    <button class="mcp-modal-close" onclick="AI_SETTINGS._closeMcpForm()">×</button>
                </div>
                <div class="mcp-modal-body">
                    <div class="form-row">
                        <label>服务器名称 *</label>
                        <input id="mcp-name" type="text" placeholder="如 tavily-search" ${isEdit ? 'disabled' : ''}>
                    </div>
                    <div class="form-row">
                        <label>传输方式 *</label>
                        <select id="mcp-transport" onchange="AI_SETTINGS._onMcpTransportChange()">
                            <option value="stdio">stdio</option>
                            <option value="http">http</option>
                        </select>
                    </div>
                    <div class="form-row form-row-inline">
                        <label>启用状态</label>
                        <label class="switch">
                            <input id="mcp-enabled" type="checkbox" checked>
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="form-row">
                        <label>描述</label>
                        <input id="mcp-description" type="text" placeholder="服务器用途说明">
                    </div>

                    <div id="mcp-stdio-fields">
                        <div class="form-row">
                            <label>命令 (command)</label>
                            <input id="mcp-command" type="text" placeholder="如 npx / python / node">
                        </div>
                        <div class="form-row">
                            <label>参数 (args，每行一个)</label>
                            <textarea id="mcp-args" rows="3" placeholder="-y&#10;tavily-mcp@latest"></textarea>
                        </div>
                        <div class="form-row">
                            <label>环境变量 (env，每行 KEY: VALUE)</label>
                            <textarea id="mcp-env" rows="3" placeholder="TAVILY_API_KEY: \${TAVILY_API_KEY}"></textarea>
                        </div>
                    </div>

                    <div id="mcp-http-fields" style="display:none;">
                        <div class="form-row">
                            <label>URL</label>
                            <input id="mcp-url" type="text" placeholder="http://host:port/path">
                        </div>
                        <div class="form-row">
                            <label>请求头 (headers，每行 KEY: VALUE)</label>
                            <textarea id="mcp-headers" rows="3" placeholder="Authorization: Bearer \${MCP_TOKEN}"></textarea>
                        </div>
                    </div>

                    <div class="form-row">
                        <label>自动批准工具 (auto_approve，每行一个工具名)</label>
                        <textarea id="mcp-auto-approve" rows="2" placeholder="tavily-search"></textarea>
                    </div>
                </div>
                <div class="mcp-modal-footer">
                    <button class="btn-primary" onclick="AI_SETTINGS._saveMcpServer(${isEdit ? `'${this.esc(serverName)}'` : 'null'})">保存</button>
                    <button class="btn-small" onclick="AI_SETTINGS._closeMcpForm()">取消</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        // 点击遮罩关闭
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this._closeMcpForm();
        });

        // 编辑模式：异步拉取现有配置回填
        if (isEdit) {
            this._fillMcpForm(serverName);
        }
    },

    // 异步拉取服务器配置并回填表单（编辑模式）
    async _fillMcpForm(serverName) {
        try {
            const raw = await this._fetchMcpRawConfig(serverName);
            if (!raw) return;
            document.getElementById('mcp-name').value = raw.name || '';
            document.getElementById('mcp-transport').value = raw.transport || 'stdio';
            document.getElementById('mcp-enabled').checked = raw.enabled !== false;
            document.getElementById('mcp-description').value = raw.description || '';
            if (raw.command) document.getElementById('mcp-command').value = raw.command || '';
            if (Array.isArray(raw.args)) {
                document.getElementById('mcp-args').value = raw.args.join('\n');
            }
            if (raw.env && typeof raw.env === 'object') {
                document.getElementById('mcp-env').value = Object.entries(raw.env)
                    .map(([k, v]) => `${k}: ${v}`).join('\n');
            }
            if (raw.url) document.getElementById('mcp-url').value = raw.url || '';
            if (raw.headers && typeof raw.headers === 'object') {
                document.getElementById('mcp-headers').value = Object.entries(raw.headers)
                    .map(([k, v]) => `${k}: ${v}`).join('\n');
            }
            if (Array.isArray(raw.auto_approve)) {
                document.getElementById('mcp-auto-approve').value = raw.auto_approve.join('\n');
            }
            this._onMcpTransportChange();
        } catch (err) {
            console.warn('回填 MCP 表单失败:', err);
        }
    },

    // 获取单个 MCP 服务器的原始配置（从 yaml 读取，含 command/args/env 等敏感字段）
    async _fetchMcpRawConfig(serverName) {
        try {
            const data = await this.apiGet(`/api/chat/mcp/servers/raw?name=${encodeURIComponent(serverName)}`);
            if (data.status === 'ok' && data.server) {
                return data.server;
            }
        } catch (err) {
            console.warn('获取 MCP 原始配置失败:', err);
        }
        return null;
    },

    // 根据传输方式显示/隐藏对应字段
    _onMcpTransportChange() {
        const transport = document.getElementById('mcp-transport').value;
        const stdioFields = document.getElementById('mcp-stdio-fields');
        const httpFields = document.getElementById('mcp-http-fields');
        if (transport === 'http') {
            stdioFields.style.display = 'none';
            httpFields.style.display = '';
        } else {
            stdioFields.style.display = '';
            httpFields.style.display = 'none';
        }
    },

    // 关闭模态框
    _closeMcpForm() {
        const overlay = document.getElementById('mcp-modal-overlay');
        if (overlay) overlay.remove();
    },

    // 解析"每行一个"的文本域为列表
    _parseLines(text) {
        return text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    },

    // 解析"KEY: VALUE"格式的文本为字典
    _parseKvPairs(text) {
        const result = {};
        for (const line of text.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            const idx = trimmed.indexOf(':');
            if (idx === -1) continue;
            const key = trimmed.substring(0, idx).trim();
            const val = trimmed.substring(idx + 1).trim();
            if (key) result[key] = val;
        }
        return result;
    },

    // 保存服务器（添加或编辑）
    async _saveMcpServer(originalName) {
        const isEdit = !!originalName;
        const name = document.getElementById('mcp-name').value.trim();
        const transport = document.getElementById('mcp-transport').value;
        const enabled = document.getElementById('mcp-enabled').checked;
        const description = document.getElementById('mcp-description').value.trim();

        // 必填校验
        if (!name) {
            this.toast('服务器名称不能为空');
            return;
        }
        if (!transport) {
            this.toast('传输方式不能为空');
            return;
        }

        const payload = { name, transport, enabled, description };

        if (transport === 'stdio') {
            const command = document.getElementById('mcp-command').value.trim();
            const argsText = document.getElementById('mcp-args').value;
            const envText = document.getElementById('mcp-env').value;
            if (command) payload.command = command;
            const args = this._parseLines(argsText);
            if (args.length > 0) payload.args = args;
            const env = this._parseKvPairs(envText);
            if (Object.keys(env).length > 0) payload.env = env;
        } else if (transport === 'http') {
            const url = document.getElementById('mcp-url').value.trim();
            const headersText = document.getElementById('mcp-headers').value;
            if (url) payload.url = url;
            const headers = this._parseKvPairs(headersText);
            if (Object.keys(headers).length > 0) payload.headers = headers;
        }

        const autoApproveText = document.getElementById('mcp-auto-approve').value;
        const autoApprove = this._parseLines(autoApproveText);
        if (autoApprove.length > 0) payload.auto_approve = autoApprove;

        const url = isEdit
            ? `/api/chat/mcp/servers/${encodeURIComponent(originalName)}`
            : '/api/chat/mcp/servers';
        const method = isEdit ? 'PUT' : 'POST';

        try {
            const data = await this.apiSend(url, method, payload);
            if (data.status === 'ok') {
                this.toast(data.message || (isEdit ? '已更新' : '已添加'));
                this._closeMcpForm();
                this._loadMcpTab();
            } else {
                this.toast(`保存失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`保存失败: ${err.message}`);
        }
    },

    // 删除服务器（带确认）
    async _deleteMcpServer(name) {
        if (!confirm(`确认删除 MCP 服务器 "${name}" 吗？此操作不可撤销。`)) return;
        try {
            const data = await this.apiSend(`/api/chat/mcp/servers/${encodeURIComponent(name)}`, 'DELETE');
            if (data.status === 'ok') {
                this.toast(data.message || '已删除');
                this._loadMcpTab();
            } else {
                this.toast(`删除失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`删除失败: ${err.message}`);
        }
    },

    // ============ Checkpoints Tab ============
    async _loadCheckpointTab() {
        const body = document.getElementById('settings-body');
        const sid = this._getSessionId();
        if (!sid) {
            body.innerHTML = '<div class="empty-hint">请先选择一个对话</div>';
            return;
        }
        try {
            const data = await this.apiGet(`/api/chat/checkpoints?session_id=${encodeURIComponent(sid)}`);
            if (data.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(data.message || '加载失败')}</div>`;
                return;
            }
            const cps = data.checkpoints || [];
            let html = `
                <div class="settings-section">
                    <div class="section-title">会话检查点</div>
                    <div class="section-desc">在调用 requires_approval 工具前自动创建的消息快照。可回滚到指定检查点（消息 + 工作区文件）。</div>
                    <div id="cp-list">`;
            if (cps.length === 0) {
                html += '<div class="empty-hint">暂无检查点（agent 调用危险工具时会自动创建）</div>';
            } else {
                // 倒序展示（最新在上）
                for (let i = cps.length - 1; i >= 0; i--) {
                    const cp = cps[i];
                    html += `
                        <div class="cp-card">
                            <div class="cp-header">
                                <span class="cp-id">${this.esc(cp.checkpoint_id)}</span>
                                <span class="cp-time">${this.esc(cp.created_at || '')}</span>
                            </div>
                            <div class="cp-meta">
                                <span class="field-label">工具:</span> <span class="field-value">${this.esc(cp.tool_name || '-')}</span>
                                &nbsp;|&nbsp;
                                <span class="field-label">消息数:</span> <span class="field-value">${cp.message_count ?? '-'}</span>
                            </div>
                            <div class="cp-desc">${this.esc(cp.description || '')}</div>
                            <div class="cp-actions">
                                <button class="btn-small btn-danger" onclick="AI_SETTINGS._rollbackCp('${this.esc(cp.checkpoint_id)}')">回滚到此点</button>
                            </div>
                        </div>`;
                }
            }
            html += '</div></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _rollbackCp(checkpointId) {
        const sid = this._getSessionId();
        if (!sid) return;
        if (!confirm(`确认回滚到检查点 ${checkpointId}？\n\n回滚后：\n- 会话消息将恢复到该检查点时的状态\n- 该检查点之后的所有检查点将被清除\n- 若启用文件 checkpoint，工作区文件也会还原`)) return;
        try {
            const data = await this.apiSend('/api/chat/rollback', 'POST', {
                session_id: sid,
                checkpoint_id: checkpointId,
            });
            if (data.status === 'ok') {
                this.toast('已回滚，正在刷新会话...');
                // 刷新前端会话消息
                if (AI_CHAT) {
                    AI_CHAT.renderMessages();
                }
                this._loadCheckpointTab();
            } else {
                this.toast(`回滚失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`回滚失败: ${err.message}`);
        }
    },

    // ============ 文件检查点 Tab — 对接 /api/chat/settings/file_checkpoint ============
    // 系统级功能开关，集中存储于 agent_config/settings.yaml，由前端统一管理。
    async _loadFileCheckpointTab() {
        const body = document.getElementById('settings-body');
        try {
            const data = await this.apiGet('/api/chat/settings/file_checkpoint');
            if (data.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(data.message || '加载失败')}</div>`;
                return;
            }
            const enabled = !!data.enabled;
            const source = data.source === 'env'
                ? '环境变量（AGENT_ENABLE_FILE_CHECKPOINT）'
                : '配置文件（agent_config/settings.yaml）';
            body.innerHTML = `
                <div class="settings-section">
                    <div class="section-title">文件检查点</div>
                    <div class="section-desc">在调用危险写工具前保存工作区文件状态快照，支持回滚文件修改（对标 Cline shadow-git checkpoint）。属系统级功能开关，集中存储于 agent_config/settings.yaml。</div>
                    <div class="form-row form-row-inline">
                        <label>启用文件检查点</label>
                        <label class="switch">
                            <input type="checkbox" ${enabled ? 'checked' : ''} onchange="AI_SETTINGS._setFileCheckpoint(this.checked)">
                            <span class="slider"></span>
                        </label>
                    </div>
                    <div class="section-desc" style="margin-top:12px;">当前来源: ${this.esc(source)}</div>
                    <div class="section-desc" style="margin-top:8px;">注意: 本钩子在服务启动时注册，此处切换后需<strong>重启服务</strong>才能生效。</div>
                </div>`;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _setFileCheckpoint(enabled) {
        try {
            const data = await this.apiSend('/api/chat/settings/file_checkpoint', 'PUT', { enabled: !!enabled });
            if (data.status === 'ok') {
                this.toast(data.message || (enabled ? '已启用' : '已禁用'));
            } else {
                this.toast(`保存失败: ${data.message || ''}`);
                this._loadFileCheckpointTab();
            }
        } catch (err) {
            this.toast(`保存失败: ${err.message}`);
            this._loadFileCheckpointTab();
        }
    },

    // ============ Cron 定时任务 Tab — 对接 /cron/* API ============
    async _loadCronTab() {
        const body = document.getElementById('settings-body');
        body.innerHTML = '<div class="settings-loading">加载定时任务...</div>';
        try {
            const [specsResp, runsResp] = await Promise.all([
                this.apiGet('/api/chat/cron/specs'),
                this.apiGet('/api/chat/cron/all_runs'),
            ]);
            if (specsResp.status !== 'ok') {
                body.innerHTML = `<div class="settings-error">${this.esc(specsResp.message || '加载失败')}</div>`;
                return;
            }
            const specs = Array.isArray(specsResp.specs) ? specsResp.specs : [];
            const runs = (runsResp.status === 'ok' && Array.isArray(runsResp.runs)) ? runsResp.runs : [];

            // Spec 列表
            let specsHtml = '';
            if (specs.length === 0) {
                specsHtml = '<div class="empty-hint">暂无定时任务（在 agent_config/cron/ 下添加 yaml 配置）</div>';
            } else {
                specsHtml = specs.map(s => {
                    const name = this.esc(s.name || '');
                    const schedule = this.esc(s.schedule || s.cron || '');
                    const prompt = this.esc(this._truncate(s.prompt || s.task || '', 120));
                    const lastRun = runs.find(r => r.name === s.name);
                    const lastRunHtml = lastRun ? this._renderCronLastRun(lastRun) : '';
                    return `<div class="cron-spec-card">
                        <div class="cron-spec-header">
                            <span class="cron-spec-name">${name}</span>
                            <span class="cron-spec-schedule">${schedule}</span>
                            <button class="btn-small" onclick="AI_SETTINGS._showCronLastRun('${name}')">上次运行</button>
                        </div>
                        <div class="cron-spec-prompt">${prompt}</div>
                        ${lastRunHtml}
                    </div>`;
                }).join('');
            }

            // 运行历史
            let runsHtml = '';
            if (runs.length === 0) {
                runsHtml = '<div class="empty-hint">暂无运行记录</div>';
            } else {
                runsHtml = runs.map(r => this._renderCronLastRun(r)).join('');
            }

            body.innerHTML = `
                <div class="settings-section">
                    <div class="section-title">定时任务（Cron）</div>
                    <div class="section-desc">agent_config/cron/ 下的 yaml spec 列表。定时任务由独立 scheduler 进程执行。</div>
                    <div class="section-actions">
                        <button class="btn-primary" onclick="AI_SETTINGS._reconcileCron()">手动调和</button>
                        <button class="btn-small" onclick="AI_SETTINGS._loadCronTab()">刷新</button>
                    </div>
                    <div id="cron-specs-list">${specsHtml}</div>
                </div>
                <div class="settings-section">
                    <div class="section-title">运行历史</div>
                    <div class="section-desc">所有 cron job 的上次执行结果。</div>
                    <div id="cron-runs-list">${runsHtml}</div>
                </div>`;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    /** 渲染单条 cron 上次运行记录 */
    _renderCronLastRun(r) {
        const name = this.esc(r.name || '');
        const isSuccess = r.status === 'success' || r.success === true;
        const status = isSuccess ? '成功' : '失败';
        const statusCls = isSuccess ? 'cron-run-success' : 'cron-run-failed';
        const ts = r.ts || r.finished_at || r.started_at || '';
        const time = ts ? new Date(ts).toLocaleString('zh-CN') : '-';
        const errMsg = r.error ? `<div class="cron-run-error">${this.esc(r.error)}</div>` : '';
        return `<div class="cron-run-card ${statusCls}">
            <div class="cron-run-header">
                <span class="cron-run-name">${name}</span>
                <span class="cron-run-status">${status}</span>
                <span class="cron-run-time">${this.esc(time)}</span>
            </div>
            ${errMsg}
        </div>`;
    },

    /** 查询单个 cron job 的上次运行结果 — 对接 GET /cron/last_run/{name} */
    async _showCronLastRun(name) {
        try {
            const data = await this.apiGet(`/api/chat/cron/last_run/${encodeURIComponent(name)}`);
            if (data.status === 'ok') {
                App.toast(`${name} 上次运行:\n${JSON.stringify(data.last_run, null, 2)}`, 'info');
            } else {
                this.toast(data.message || '无运行记录');
            }
        } catch (err) {
            this.toast(`查询失败: ${err.message}`);
        }
    },

    /** 手动触发 cron 调和 — 对接 POST /cron/reconcile */
    async _reconcileCron() {
        try {
            const data = await this.apiSend('/api/chat/cron/reconcile', 'POST');
            if (data.status === 'ok') {
                this.toast('已触发调和（实际 reconcile 在 scheduler 进程中执行）');
                this._loadCronTab();
            } else {
                this.toast(`调和失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`调和失败: ${err.message}`);
        }
    },

    /** 截断工具 — 复用 AI_CHAT 的 truncate 逻辑 */
    _truncate(text, max) {
        const s = String(text || '');
        return s.length > max ? s.substring(0, max) + '...' : s;
    },

    // ============ 待处理提示词 Tab — 对接 /sessions/{id}/pending_prompts ============
    async _loadPendingTab() {
        const body = document.getElementById('settings-body');
        const sid = this._getSessionId();
        if (!sid) {
            body.innerHTML = '<div class="empty-hint">请先选择一个对话</div>';
            return;
        }
        try {
            const data = await this.apiGet(`/api/chat/sessions/${encodeURIComponent(sid)}/pending_prompts`);
            // 注意：该端点返回 {session_id, prompts, total}，无 status 字段
            const prompts = data.prompts || [];
            let html = `
                <div class="settings-section">
                    <div class="section-title">待处理提示词队列</div>
                    <div class="section-desc">会话运行时排队的输入消息。可编辑投递模式或删除排队消息。</div>
                    <div class="section-actions">
                        <button class="btn-small btn-danger" onclick="AI_SETTINGS._clearAllPending()">全部清空</button>
                        <button class="btn-small" onclick="AI_SETTINGS._loadPendingTab()">刷新</button>
                    </div>
                    <div id="pending-list">`;
            if (prompts.length === 0) {
                html += '<div class="empty-hint">暂无待处理提示词（agent 运行时发送消息会自动入队）</div>';
            } else {
                for (const p of prompts) {
                    const pid = this.esc(p.id || '');
                    const prompt = this.esc(p.prompt || '');
                    const delivery = this.esc(p.delivery || 'queue');
                    const mode = this.esc(p.mode || '');
                    html += `
                        <div class="pending-card">
                            <div class="pending-prompt">${prompt}</div>
                            <div class="pending-meta">
                                <span class="field-label">投递:</span>
                                <span class="field-value">${delivery}</span>
                                ${mode ? `<span class="field-label" style="margin-left:8px;">模式:</span> <span class="field-value">${mode}</span>` : ''}
                            </div>
                            <div class="pending-actions">
                                <button class="btn-small" onclick="AI_SETTINGS._editPending('${pid}')">编辑</button>
                                <button class="btn-small btn-danger" onclick="AI_SETTINGS._deletePending('${pid}')">删除</button>
                            </div>
                        </div>`;
                }
            }
            html += '</div></div>';
            body.innerHTML = html;
        } catch (err) {
            body.innerHTML = `<div class="settings-error">加载失败: ${this.esc(err.message)}</div>`;
        }
    },

    /** 编辑待处理提示词 — 对接 PUT /sessions/{id}/pending_prompts/{prompt_id} */
    async _editPending(promptId) {
        const body = document.getElementById('settings-body');
        const sid = this._getSessionId();
        if (!sid) return;
        body.innerHTML = `
            <div class="settings-section">
                <div class="section-title">编辑待处理提示词</div>
                <div class="form-row"><label>消息内容</label><textarea id="pf-prompt" rows="4" style="width:100%;padding:6px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:13px;font-family:inherit;resize:vertical;"></textarea></div>
                <div class="form-row"><label>投递模式（queue / steer）</label><input id="pf-delivery" type="text" placeholder="queue 或 steer"></div>
                <div class="form-row"><label>工作模式（act / plan / yolo，可选）</label><input id="pf-mode" type="text" placeholder="act"></div>
                <div class="form-actions">
                    <button class="btn-primary" onclick="AI_SETTINGS._savePending('${this.esc(promptId)}')">保存</button>
                    <button class="btn-small" onclick="AI_SETTINGS._loadPendingTab()">取消</button>
                </div>
            </div>`;
        // 拉取当前值填充
        try {
            const data = await this.apiGet(`/api/chat/sessions/${encodeURIComponent(sid)}/pending_prompts`);
            const p = (data.prompts || []).find(x => x.id === promptId);
            if (p) {
                document.getElementById('pf-prompt').value = p.prompt || '';
                document.getElementById('pf-delivery').value = p.delivery || 'queue';
                document.getElementById('pf-mode').value = p.mode || '';
            }
        } catch (err) { /* 忽略 */ }
    },

    async _savePending(promptId) {
        const sid = this._getSessionId();
        if (!sid) return;
        const payload = {
            prompt: document.getElementById('pf-prompt').value,
            delivery: document.getElementById('pf-delivery').value.trim() || 'queue',
            mode: document.getElementById('pf-mode').value.trim() || undefined,
        };
        const data = await this.apiSend(`/api/chat/sessions/${encodeURIComponent(sid)}/pending_prompts/${encodeURIComponent(promptId)}`, 'PUT', payload);
        if (data.updated !== undefined && data.updated !== null) {
            this.toast('待处理提示词已更新');
            this._loadPendingTab();
        } else {
            this.toast(`更新失败: ${data.message || ''}`);
        }
    },

    /** 删除单条待处理提示词 — 对接 DELETE /sessions/{id}/pending_prompts/{prompt_id} */
    async _deletePending(promptId) {
        const sid = this._getSessionId();
        if (!sid) return;
        if (!confirm('确认删除这条待处理提示词？')) return;
        try {
            const data = await this.apiSend(`/api/chat/sessions/${encodeURIComponent(sid)}/pending_prompts/${encodeURIComponent(promptId)}`, 'DELETE');
            if (data.removed) {
                this.toast('已删除');
                this._loadPendingTab();
            } else {
                this.toast(`删除失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`删除失败: ${err.message}`);
        }
    },

    /** 清空全部待处理提示词 — 对接 DELETE /sessions/{id}/pending_prompts */
    async _clearAllPending() {
        const sid = this._getSessionId();
        if (!sid) return;
        if (!confirm('确认清空全部待处理提示词？')) return;
        try {
            const data = await this.apiSend(`/api/chat/sessions/${encodeURIComponent(sid)}/pending_prompts`, 'DELETE');
            if (data.status === 'ok') {
                this.toast('已清空全部待处理提示词');
                this._loadPendingTab();
            } else {
                this.toast(`清空失败: ${data.message || ''}`);
            }
        } catch (err) {
            this.toast(`清空失败: ${err.message}`);
        }
    },
};
