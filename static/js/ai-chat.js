/* AI 投研对话 -- 前端逻辑 (v2: 参考 TRAE 多阶段展示) */

const AI_CHAT = {
    currentConvId: null,
    conversations: {},
    isStreaming: false,
    abortController: null,
    // 当前流式会话的DOM引用
    _streamBlocks: null,   // 当前 assistant 消息的 blocks 数组
    _streamEl: null,       // 当前 assistant 消息的容器
    // Phase 15: 当前工作模式 act | plan | yolo
    currentMode: 'act',
    // 当前会话选中的 Provider（前端偏好，空字符串表示使用默认）
    currentProvider: '',

    async init() {
        this.loadConversations();
        this.loadMode();
        this.renderSidebar();
        this.bindEvents();
        this._updateModeUI();
        // 先读取后端保存的"当前对话", 并提前设置 currentConvId,
        // 避免 syncFromBackend 内部自动切换到最后一个会话覆盖该记录
        const savedConvId = await this.loadCurrentConvFromBackend();
        if (savedConvId && this.conversations[savedConvId]) {
            this.currentConvId = savedConvId;
        } else {
            const ids = Object.keys(this.conversations);
            if (ids.length > 0) {
                this.currentConvId = ids[ids.length - 1];
            }
        }
        // 从后端同步会话列表 (localStorage 丢失/换端口后仍能恢复对话记录, 后端文件为权威存储)
        await this.syncFromBackend();
        // 仅全屏模式注入功能面板按钮 (侧栏精简版不注入, 避免挤占输入区)
        if (document.body.dataset.chatMode !== 'sidebar') {
            this._injectCheckpointButton();
            // 看板功能已屏蔽：TodoWrite 工具已移除，todos 无数据源，看板失去意义，故不再注入看板按钮
            // this._injectKanbanButton();
            this._injectTelemetryButton();
        }
        this._initToolbar();
        // 优先恢复后端保存的"当前对话", 保证所有页面/子页面右侧栏显示的对话一致
        // 需要在 syncFromBackend 之后再次确认, 因为后端可能新增了不在 localStorage 中的会话
        if (savedConvId && this.conversations[savedConvId]) {
            this.switchConversation(savedConvId);
        } else if (this.currentConvId && this.conversations[this.currentConvId]) {
            this.switchConversation(this.currentConvId);
        } else {
            const ids = Object.keys(this.conversations);
            if (ids.length > 0) {
                this.switchConversation(ids[ids.length - 1]);
            }
        }
        // 会话级事件广播: 页面加载/刷新后接管该会话进行中的活跃 run
        // （在另一标签页发起的对话，本页刷新后信息流不打断，可同时开多个页面）
        this.takeoverActiveRun();
        // 侧栏收起时不接管（避免后台页面卡顿），用户展开侧栏时再触发接管
        const expandBtn = document.getElementById('ai-sidebar-expand-btn');
        if (expandBtn) {
            expandBtn.addEventListener('click', () => this.takeoverActiveRun());
        }
    },

    /** 将当前会话ID持久化到后端 (多页面/多实例共享, 保证右侧栏对话一致)
     *  无当前会话(全部删除)时写空串, 清除后端旧记录, 让其他页面回退到最新会话 */
    async saveCurrentConvToBackend() {
        try {
            await fetch('/api/page-settings/ai_chat_current', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_conv_id: this.currentConvId || '' }),
            });
        } catch(e) {
            console.warn('保存当前会话到后端失败:', e);
        }
    },

    /** 从后端读取上次的当前会话ID (换页面/换实例后恢复同一对话) */
    async loadCurrentConvFromBackend() {
        try {
            const resp = await fetch('/api/page-settings/ai_chat_current');
            const data = await resp.json();
            const s = (data && data.data) || {};
            return s.current_conv_id || null;
        } catch(e) {
            return null;
        }
    },

    /** 加载持久化的工作模式 — Phase 15 新增，P2-18 扩展支持 yolo */
    loadMode() {
        try {
            const m = localStorage.getItem('ai_chat_mode');
            if (m === 'plan' || m === 'act' || m === 'yolo') {
                this.currentMode = m;
            }
        } catch(e) {}
    },

    /** 切换工作模式 — Phase 15 新增，P0-2 增强：立即同步到后端
     * P2-18: 三选项循环切换 Act -> Plan -> Yolo -> Act
     *  - Act: 直接执行任务，可读写文件、运行命令
     *  - Plan: 仅探索分析、呈现计划，不修改文件
     *  - Yolo: 自动执行模式，无需逐步确认（对标 Cline YOLO）
     */
    async toggleMode() {
        const order = ['act', 'plan', 'yolo'];
        const idx = order.indexOf(this.currentMode);
        this.currentMode = order[(idx + 1) % order.length];
        try { localStorage.setItem('ai_chat_mode', this.currentMode); } catch(e) {}
        this._updateModeUI();
        // P0-2: 立即同步到后端 SessionState，不依赖下次 /stream 请求
        if (this.currentConvId) {
            try {
                await fetch('/api/chat/mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: this.currentConvId,
                        mode: this.currentMode,
                    }),
                });
            } catch(err) {
                console.warn('同步模式到后端失败:', err);
            }
        }
        // P0-2: 显示明显的切换提示
        const modeName = { act: 'Act', plan: 'Plan', yolo: 'Yolo' }[this.currentMode];
        this._showToast(`已切换到 ${modeName} 模式，下次发送消息生效`);
    },

    /** 显示轻量级 toast 提示 — P0-2 新增 */
    _showToast(text) {
        let toast = document.getElementById('chat-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'chat-toast';
            toast.className = 'chat-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = text;
        toast.classList.add('show');
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => {
            toast.classList.remove('show');
        }, 2500);
    },

    /** 更新模式按钮 UI — Phase 15 新增，P2-18 扩展 yolo 样式 */
    _updateModeUI() {
        const label = document.getElementById('mode-label');
        const btn = document.getElementById('mode-toggle-btn');
        const hint = document.getElementById('chat-input-hint');
        const modeName = { act: 'Act', plan: 'Plan', yolo: 'Yolo' }[this.currentMode] || 'Act';
        if (label) label.textContent = modeName;
        if (btn) {
            btn.classList.toggle('mode-plan', this.currentMode === 'plan');
            btn.classList.toggle('mode-act', this.currentMode === 'act');
            btn.classList.toggle('mode-yolo', this.currentMode === 'yolo');
        }
        if (hint) {
            const hints = {
                plan: 'Plan 模式：Charles 会先探索分析并规划，批准后再执行（不直接修改文件）',
                yolo: 'Yolo 模式：自动执行，无需逐步确认（适合后台自动化场景）',
                act: 'Charles 采用国泰君安五步法进行分析，工具调用过程会实时展示并可折叠查看',
            };
            hint.textContent = hints[this.currentMode] || hints.act;
        }
    },

    // ===== 对话管理 =====
    newConversation() {
        const id = 'conv_' + Date.now();
        this.conversations[id] = {
            id, title: '新对话', messages: [], createdAt: new Date().toISOString()
        };
        this.currentConvId = id;
        this.saveConversations();
        this.saveCurrentConvToBackend();
        this.renderSidebar();
        this.renderMessages();
        document.getElementById('chat-input').focus();
    },

    switchConversation(id) {
        if (!this.conversations[id]) return;
        this.currentConvId = id;
        this.renderSidebar();
        this.renderMessages();
        // 当前对话选择持久化到后端, 保证其他页面/实例右侧栏显示同一对话
        this.saveCurrentConvToBackend();
        // P0-2: 切换会话时从后端读取该会话的 mode，避免沿用上一个会话的模式
        this._syncModeFromBackend();
        document.getElementById('chat-input').focus();
    },

    /** 从后端同步当前会话的 mode — P0-2 新增，P2-18 扩展接受 yolo */
    async _syncModeFromBackend() {
        if (!this.currentConvId) return;
        try {
            const resp = await fetch(`/api/chat/mode?session_id=${encodeURIComponent(this.currentConvId)}`);
            const data = await resp.json();
            if (data.status === 'ok' && (data.mode === 'act' || data.mode === 'plan' || data.mode === 'yolo')) {
                this.currentMode = data.mode;
                try { localStorage.setItem('ai_chat_mode', this.currentMode); } catch(e) {}
                this._updateModeUI();
            }
        } catch(err) {
            console.warn('从后端同步 mode 失败:', err);
        }
    },

    deleteConversation(id, e) {
        e.stopPropagation();
        if (!confirm('确定删除这个对话吗？')) return;
        delete this.conversations[id];
        if (this.currentConvId === id) {
            const ids = Object.keys(this.conversations);
            this.currentConvId = ids.length > 0 ? ids[ids.length - 1] : null;
        }
        this.saveConversations();
        // 删除后把新的当前会话同步到后端 (若已无会话则写空, 让其他页面回退到最新会话)
        this.saveCurrentConvToBackend();
        this.renderSidebar();
        this.renderMessages();
        // 同步删除后端持久化的会话文件，避免 agent_data/sessions 下残留孤儿文件
        fetch(`/api/chat/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
            .catch(() => {});
    },

    saveConversations() {
        try { localStorage.setItem('ai_chat_conversations', JSON.stringify(this.conversations)); } catch(e) {}
    },

    loadConversations() {
        try {
            const raw = localStorage.getItem('ai_chat_conversations');
            if (raw) this.conversations = JSON.parse(raw);
        } catch(e) { this.conversations = {}; }
    },

    /** 从后端同步会话列表 — 后端为唯一标准, 所有前端共享同一份对话
     *
     * 后端 agent_data/sessions/*.json 是权威存储; 每次加载页面都以后端为准:
     *   - 本地缺失的会话 → 从后端拉完整消息补进侧栏
     *   - 本地已有的会话 → 用后端消息覆盖刷新 (多前端共享, 内容一致)
     *   - 本地有而后端已删除的非空会话 → 从本地移除 (同步其他前端的删除操作)
     * 恢复/刷新后的会话可正常删除/继续对话, buildHistory 会带上完整上下文供 agent 接续。
     */
    async syncFromBackend() {
        try {
            const resp = await fetch('/api/chat/sessions');
            const data = await resp.json();
            const remote = data.sessions || [];
            if (!remote.length) return;
            let changed = false;
            const remoteIds = new Set();
            for (const s of remote) {
                remoteIds.add(s.session_id);
                try {
                    const mresp = await fetch(`/api/chat/sessions/${encodeURIComponent(s.session_id)}/messages`);
                    const mdata = await mresp.json();
                    const messages = this._backendMessagesToLocal(mdata.messages || []);
                    if (!messages.length) continue;
                    this.conversations[s.session_id] = {
                        id: s.session_id,
                        title: this._normalizeTitle(s.title || '新对话'),
                        messages,
                        createdAt: s.created_at
                            ? new Date(s.created_at * 1000).toISOString()
                            : new Date().toISOString(),
                        restored: true,
                    };
                    changed = true;
                } catch(e) { /* 单个会话拉取失败不影响其余 */ }
            }
            // 后端为唯一标准: 本地有而后端已删除的非空会话, 从本地移除
            for (const id of Object.keys(this.conversations)) {
                if (!remoteIds.has(id) && (this.conversations[id].messages || []).length > 0) {
                    delete this.conversations[id];
                    changed = true;
                }
            }
            if (changed) {
                this.saveConversations();
                this.renderSidebar();
                if (this.currentConvId && this.conversations[this.currentConvId]) {
                    this.renderMessages();
                } else {
                    const ids = Object.keys(this.conversations);
                    if (ids.length) this.switchConversation(ids[ids.length - 1]);
                }
            }
        } catch(e) {
            console.warn('从后端同步会话失败:', e);
        }
    },

    /**
     * 后端会话消息序列 → 前端 conversations 消息结构 (完整还原 thinking/answer/tool)
     *
     * 后端以多条消息存储一轮 agent 响应: assistant 消息含 reasoning/text/tool-call parts,
     * 独立 role=tool 消息含 tool-result; 前端则把一轮响应合并为一条 assistant 消息,
     * 内含 thinking/answer/tool 等多个 block。此转换按 tool_call_id 合并工具调用与结果。
     */
    _backendMessagesToLocal(bmessages) {
        const out = [];
        let cur = null;          // 当前累积的 assistant 前端消息
        let lastUserText = null; // 相邻重复 user 去重 (后端偶发重复存储)
        const pendingTools = []; // 未完成的 tool block (按 tool_call_id 匹配)
        for (const m of (bmessages || [])) {
            const role = m.role;
            const parts = m.content || [];
            if (role === 'user') {
                cur = null;
                pendingTools.length = 0;
                const text = this._textFromParts(parts);
                if (text && text !== lastUserText) {
                    out.push({ role: 'user', content: text });
                    lastUserText = text;
                }
            } else if (role === 'assistant') {
                if (!cur) { cur = { role: 'assistant', blocks: [] }; out.push(cur); }
                for (const p of parts) {
                    if (!p) continue;
                    if (p.type === 'text' && p.text) {
                        cur.blocks.push({ type: 'answer', text: p.text });
                    } else if (p.type === 'reasoning' && p.text) {
                        cur.blocks.push({ type: 'thinking', text: p.text, expanded: false });
                    } else if (p.type === 'tool-call') {
                        const tb = {
                            type: 'tool',
                            name: p.tool_name || 'unknown',
                            args: typeof p.input === 'string' ? p.input : JSON.stringify(p.input || {}),
                            status: 'running',
                            output: null,
                            isError: false,
                            tool_call_id: p.tool_call_id || '',
                            expanded: false,
                        };
                        cur.blocks.push(tb);
                        pendingTools.push(tb);
                    }
                }
            } else if (role === 'tool') {
                for (const p of parts) {
                    if (!p || p.type !== 'tool-result') continue;
                    let tb = pendingTools.find(t => t.tool_call_id && t.tool_call_id === p.tool_call_id);
                    if (!tb) tb = pendingTools[pendingTools.length - 1]; // 兜底: 按顺序匹配最后一个
                    if (tb) {
                        tb.status = p.is_error ? 'error' : 'done';
                        tb.output = p.output;
                        tb.isError = !!p.is_error;
                        const i = pendingTools.indexOf(tb);
                        if (i >= 0) pendingTools.splice(i, 1);
                    }
                }
            }
        }
        // 模拟 _finishStream: 有 answer 的 assistant 消息折叠过程信息
        for (const msg of out) {
            if (msg.role === 'assistant' && msg.blocks.some(b => b.type === 'answer')) {
                for (const b of msg.blocks) {
                    if (b.type === 'thinking' || b.type === 'tool' || b.type === 'plan') b.expanded = false;
                }
            }
        }
        return out;
    },

    /** 从后端消息 content parts 中提取纯文本 (text parts 拼接)
     * 同时去掉后端 user 消息的 <user_input ...>/</user_input> 包装标签,
     * 避免恢复后用户提问显示"<user_input mode=...>"等前后缀
     */
    _textFromParts(parts) {
        if (!Array.isArray(parts)) return '';
        const text = parts
            .filter(p => p && p.type === 'text' && typeof p.text === 'string' && p.text)
            .map(p => p.text)
            .join('\n');
        return text
            .replace(/<user_input\b[^>]*>/gi, '')
            .replace(/<\/user_input>/gi, '')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    },

    /** 后端标题可能带 <user_input mode=...> 等包装标签, 去掉标签并截断 */
    _normalizeTitle(title) {
        const t = String(title || '').replace(/<[^>]*>/g, '').trim();
        if (!t) return '新对话';
        return t.length > 30 ? t.substring(0, 30) + '...' : t;
    },

    // ===== 渲染历史消息 =====
    renderSidebar() {
        const list = document.getElementById('conversation-list');
        if (!list) return;
        const ids = Object.keys(this.conversations);
        list.innerHTML = ids.map(id => {
            const c = this.conversations[id];
            const active = id === this.currentConvId ? ' active' : '';
            return `<div class="conv-item${active}" onclick="AI_CHAT.switchConversation('${id}')">
                <span class="conv-title">${this.esc(c.title || '新对话')}</span>
                <button class="conv-delete" onclick="AI_CHAT.deleteConversation('${id}', event)">x</button>
            </div>`;
        }).join('');
    },

    renderMessages() {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        const conv = this.currentConvId ? this.conversations[this.currentConvId] : null;
        if (!conv || conv.messages.length === 0) {
            container.innerHTML = this.welcomeHTML();
            return;
        }
        let html = '';
        // 用户消息序号(0 起，相邻去重计数)，用于消息级回滚定位。
        // 与后端回滚接口的"相邻去重"定位保持一致，避免后端重复 user 导致索引错位。
        let userIndex = 0;
        let lastUserText = null;
        for (const msg of conv.messages) {
            if (msg.role === 'user') {
                const isDup = (msg.content === lastUserText);
                if (!isDup) lastUserText = msg.content;
                html += `<div class="msg-row user">
                    <div class="msg-avatar">U</div>
                    <div class="msg-bubble user">${this.esc(msg.content)}</div>
                    <button class="msg-rollback-btn" title="回滚到这条提问之前，删除该提问及其后的所有回答和工具调用"
                            onclick="AI_CHAT.rollbackToUserMsg(${userIndex}, event)">回滚到此</button>
                </div>`;
                if (!isDup) userIndex++;
            } else {
                html += `<div class="msg-row assistant">
                    <div class="msg-avatar">C</div>
                    <div class="msg-body">${this.renderBlocks(msg.blocks || [])}</div>
                </div>`;
            }
        }
        container.innerHTML = html;
        this.scrollToBottom();
    },

    /** 渲染静态 blocks */
    renderBlocks(blocks) {
        return blocks.map(b => {
            switch (b.type) {
                case 'phase':
                    return `<div class="block-phase">${this.phaseIcon(b.phase)} ${this.phaseLabel(b.phase)}</div>`;
                case 'plan':
                    return this.renderPlanBlock(b);
                case 'tool':
                    return this.renderToolCard(b, true);
                case 'todo_list':
                    return this.renderTodoListBlock(b);
                case 'approval':
                    return this.renderApprovalBlock(b);
                case 'question':
                    return this.renderQuestionBlock(b);
                case 'thinking':
                    if (!b.text) return '';
                    return `<details class="block-thinking" ${b.expanded ? 'open' : ''}>
                        <summary>
                            <span class="thinking-icon">${this.toolSvg('think')}</span>
                            <span class="thinking-title">思考过程</span>
                        </summary>
                        <div class="thinking-text">${this.esc(b.text)}</div>
                    </details>`;
                case 'answer':
                    return `<div class="block-answer markdown-body">${this.markdown(b.text || '')}</div>`;
                case 'error':
                    return `<div class="block-error">${this.esc(b.text || '')}</div>`;
                default:
                    return '';
            }
        }).join('');
    },

    /**
     * 渲染任务清单卡片 — Phase 15 新增
     *
     * TodoWrite 工具维护的任务清单，显示每个 todo 的状态和进度。
     * 对标 Claude/Cline 的 TodoList 可视化卡片。
     */
    renderTodoListBlock(b) {
        const todos = b.todos || [];
        if (todos.length === 0) return '';
        const completed = todos.filter(t => t.status === 'completed').length;
        const isOpen = b.expanded !== false;
        const items = todos.map(t => {
            const icon = t.status === 'completed' ? 'check' :
                         t.status === 'in_progress' ? 'arrow' : 'circle';
            const cls = t.status === 'completed' ? 'todo-done' :
                        t.status === 'in_progress' ? 'todo-running' : 'todo-pending';
            const iconHtml = icon === 'check' ?
                '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="6" fill="#10b981"/><path d="M5 8l2 2 4-4" stroke="#fff" stroke-width="1.5" fill="none"/></svg>' :
                icon === 'arrow' ?
                '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="6" fill="#3b82f6"/><path d="M6 5l4 3-4 3z" fill="#fff"/></svg>' :
                '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="5" fill="none" stroke="#9ca3af" stroke-width="1.5"/></svg>';
            return `<li class="todo-item ${cls}">
                <span class="todo-icon">${iconHtml}</span>
                <span class="todo-text">${this.esc(t.content || '')}</span>
                ${t.active_form && t.status === 'in_progress' ? `<span class="todo-active">${this.esc(t.active_form)}</span>` : ''}
            </li>`;
        }).join('');
        return `<details class="block-todo-list" ${isOpen ? 'open' : ''}>
            <summary>
                <span class="todo-title">任务清单</span>
                <span class="todo-progress">${completed}/${todos.length}</span>
            </summary>
            <ol class="todo-items">${items}</ol>
        </details>`;
    },

    /**
     * 渲染工具审批卡片 — Phase 19 新增
     *
     * 显示危险工具调用的审批请求，包含工具名、参数预览、批准/拒绝按钮。
     * 状态: pending（等待中）/ approved（已批准）/ denied（已拒绝）
     *
     * 对标 Cline:
     *   - sdk/packages/core/src/runtime/tools/tool-approval.ts
     *   - 审批弹窗 + 批准/拒绝按钮
     */
    renderApprovalBlock(b) {
        const toolName = b.tool_name || 'unknown';
        const toolCallId = b.tool_call_id || '';
        const status = b.status || 'pending';
        const friendlyName = { use_skill: '加载技能', web_search: '网络搜索',
            run_commands: '执行命令', file_read: '读取文件', read_files: '读取文件',
            file_write: '写入文件', write_file: '写入文件', edit_file: '编辑文件',
            editor: '行级编辑', apply_patch: '应用补丁', list_dir: '列出目录',
            attempt_completion: '完成任务' };
        const displayName = friendlyName[toolName] || toolName;

        // 参数预览 — JSON 格式化，截断防止过长
        let inputPreview = '';
        try {
            const inputStr = typeof b.input === 'string' ? b.input : JSON.stringify(b.input, null, 2);
            inputPreview = this.truncate(inputStr, 600);
        } catch(e) {
            inputPreview = String(b.input || '');
        }

        // 状态相关的样式和按钮
        const statusCls = status === 'pending' ? ' approval-pending' :
                          status === 'approved' ? ' approval-approved' :
                          ' approval-denied';
        const statusText = status === 'pending' ? '等待审批' :
                           status === 'approved' ? '已批准' : '已拒绝';
        const statusIcon = status === 'pending' ? '<span class="approval-spinner"></span>' :
                           status === 'approved' ? '<span class="approval-check">&#10003;</span>' :
                           '<span class="approval-deny-icon">&#10007;</span>';

        // 仅 pending 状态显示按钮
        // Stage 5.6 (U10): 新增"始终允许此工具"复选框，勾选后写入会话级记忆
        const buttonsHtml = status === 'pending' ? `
            <div class="approval-buttons">
                <button class="approval-btn approval-btn-approve" onclick="AI_CHAT._sendApproval('${this.esc(toolCallId)}', true)">批准执行</button>
                <button class="approval-btn approval-btn-deny" onclick="AI_CHAT._sendApproval('${this.esc(toolCallId)}', false)">拒绝</button>
            </div>
            <label class="approval-auto-approve">
                <input type="checkbox" id="auto-approve-${this.esc(toolCallId)}">
                始终允许此工具（本次会话内不再询问）
            </label>
        ` : '';

        return `<details class="block-approval${statusCls}" open>
            <summary>
                <span class="approval-icon">${this.toolSvg('wrench')}</span>
                <span class="approval-title">工具审批: ${this.esc(displayName)}</span>
                ${statusIcon}
                <span class="approval-status">${statusText}</span>
            </summary>
            <div class="approval-body">
                <div class="approval-section">
                    <strong>工具</strong>
                    <code>${this.esc(toolName)}</code>
                </div>
                <div class="approval-section">
                    <strong>参数</strong>
                    <pre>${this.esc(inputPreview)}</pre>
                </div>
                ${buttonsHtml}
            </div>
        </details>`;
    },

    /**
     * 渲染问题卡片 — 对标 Cline ask_followup_question
     *
     * 显示问题文本和选项按钮，用户点击后发送回答到后端。
     * 状态: pending（等待回答）/ answered（已回答）
     */
    renderQuestionBlock(b) {
        const toolCallId = b.tool_call_id || '';
        const question = b.question || '';
        const options = b.options || [];
        const status = b.status || 'pending';
        const statusCls = status === 'pending' ? ' question-pending' :
                         status === 'answered' ? ' question-answered' :
                         ' question-expired';
        const statusText = status === 'pending' ? '等待回答' :
                          status === 'answered' ? '已回答' : '已超时';
        const statusIcon = status === 'pending' ? '<span class="approval-spinner"></span>' :
                          status === 'answered' ? '<span class="approval-check">&#10003;</span>' :
                          '<span class="approval-deny-icon">&#10007;</span>';

        // 选项按钮
        const optionsHtml = options.map((opt, i) => {
            const label = typeof opt === 'string' ? opt : opt.label || opt.value || '';
            const value = typeof opt === 'string' ? opt : opt.value || opt.label || '';
            const desc = typeof opt === 'object' && opt.description ? opt.description : '';
            // 仅 pending 状态显示可点击按钮
            if (status !== 'pending') {
                return `<div class="question-option question-option-disabled">
                    <span class="question-option-label">${this.esc(label)}</span>
                    ${desc ? `<span class="question-option-desc">${this.esc(desc)}</span>` : ''}
                </div>`;
            }
            // 转义 onelick 中的特殊字符
            const safeValue = this.esc(value);
            const safeToolCallId = this.esc(toolCallId);
            return `<button class="question-option-btn" onclick="AI_CHAT._sendAnswer('${safeToolCallId}', '${safeValue}')">
                <span class="question-option-label">${this.esc(label)}</span>
                ${desc ? `<span class="question-option-desc">${this.esc(desc)}</span>` : ''}
            </button>`;
        }).join('');

        return `<details class="block-question${statusCls}" open>
            <summary>
                <span class="question-icon">${this.toolSvg('question')}</span>
                <span class="question-title">AI 需要确认</span>
                ${statusIcon}
                <span class="question-status">${statusText}</span>
            </summary>
            <div class="question-body">
                <div class="question-text">${this.esc(question)}</div>
                ${options.length > 0 ? `<div class="question-options">${optionsHtml}</div>` : ''}
            </div>
        </details>`;
    },

    renderToolCard(b, staticMode) {
        const iconMap = {
            web_search: 'search', web_fetch: 'globe', exec: 'terminal',
            read_file: 'file', write_file: 'edit', edit_file: 'edit',
            list_dir: 'folder', use_skill: 'skill', file_read: 'file',
            file_write: 'edit', run_commands: 'terminal', read_files: 'file',
            todo_write: 'plan', switch_to_act_mode: 'plan', switch_to_plan_mode: 'plan',
            attempt_completion: 'answer',
        };
        const icon = iconMap[b.name] || 'wrench';
        const statusCls = b.status === 'running' ? ' status-running' :
                          b.status === 'error' ? ' status-error' :
                          b.status === 'done' ? ' status-done' : '';
        // staticMode 下用 expanded 属性控制；流式模式下 running 的自动展开
        const isOpen = staticMode ? (b.expanded === true) : (b.status === 'running');
        let queryHint = '';
        const friendlyName = { use_skill: '加载技能', web_search: '网络搜索', exec: '执行命令',
            file_read: '读取文件', file_write: '写入文件', read_file: '读取文件',
            write_file: '写入文件', edit_file: '编辑文件', list_dir: '列出目录',
            run_commands: '执行命令', read_files: '读取文件', todo_write: '更新任务清单',
            switch_to_act_mode: '切换到执行模式', switch_to_plan_mode: '切换到规划模式',
            attempt_completion: '完成任务' };
        const displayName = friendlyName[b.name] || b.name;
        // Phase 15: 增强 queryHint 提取，支持结构化工具
        if (b.name === 'web_search') {
            try { queryHint = JSON.parse(b.args || '{}').query || ''; } catch(e) {}
        } else if (b.name === 'use_skill') {
            try { queryHint = JSON.parse(b.args || '{}').skill_name || ''; } catch(e) {}
        } else if (b.name === 'exec') {
            try { queryHint = JSON.parse(b.args || '{}').command || ''; } catch(e) {}
        } else if (b.name === 'run_commands') {
            // Phase 15: run_commands 显示第一条命令作为提示
            try {
                const cmds = JSON.parse(b.args || '{}').commands;
                if (Array.isArray(cmds) && cmds[0]) queryHint = cmds[0];
            } catch(e) {}
        } else if (b.name === 'read_files' || b.name === 'file_read') {
            // Phase 15: read_files 显示第一个文件路径作为提示
            try {
                const parsed = JSON.parse(b.args || '{}');
                if (parsed.path) queryHint = parsed.path;
                else if (Array.isArray(parsed.files) && parsed.files[0]) queryHint = parsed.files[0].path || '';
            } catch(e) {}
        }

        // Phase 15: run_commands 结构化展示命令列表
        let paramsHtml;
        if (b.name === 'run_commands') {
            paramsHtml = this._renderRunCommandsParams(b.args);
        } else {
            paramsHtml = `<pre>${this.esc(this.truncate(b.args || '', 600))}</pre>`;
        }

        const terminalHtml = this._renderToolTerminal(b);

        return `<details class="block-tool${statusCls}" ${isOpen ? 'open' : ''} data-tool-idx="${b.idx || ''}">
            <summary>
                <span class="tool-icon">${this.toolSvg(icon)}</span>
                <span class="tool-name">${this.esc(displayName)}</span>
                ${b.status === 'running' ? '<span class="tool-spinner"></span>' : ''}
                ${b.status === 'done' ? '<span class="tool-check">&#10003;</span>' : ''}
                ${b.status === 'error' ? '<span class="tool-error-icon">&#10007;</span>' : ''}
                ${queryHint ? `<span class="tool-query">${this.esc(this.truncate(queryHint, 25))}</span>` : ''}
            </summary>
            <div class="tool-body">
                <div class="tool-section"><strong>参数</strong>${paramsHtml}</div>
                ${terminalHtml}
                ${b.output ? `<div class="tool-section"><strong>结果</strong><pre class="${b.isError ? 'error' : ''}">${this.esc(this.truncate(b.output || '', 1200))}</pre></div>` : ''}
                ${b.status === 'running' && !terminalHtml ? '<div class="tool-section"><em>执行中...</em></div>' : ''}
            </div>
        </details>`;
    },

    /**
     * 渲染 run_commands 的结构化参数 — Phase 15 新增
     *
     * 将 commands 数组展示为命令列表，每条命令前加 $ 前缀，
     * 比原始 JSON 更易读。
     */
    _renderRunCommandsParams(argsStr) {
        try {
            const parsed = JSON.parse(argsStr || '{}');
            const cmds = parsed.commands;
            if (!Array.isArray(cmds) || cmds.length === 0) {
                return `<pre>${this.esc(this.truncate(argsStr || '', 600))}</pre>`;
            }
            const cmdItems = cmds.map(c => `<div class="cmd-item"><span class="cmd-prefix">$</span><code>${this.esc(this.truncate(c, 200))}</code></div>`).join('');
            return `<div class="cmd-list">${cmdItems}</div>`;
        } catch(e) {
            return `<pre>${this.esc(this.truncate(argsStr || '', 600))}</pre>`;
        }
    },

    /**
     * 渲染工具卡片的实时终端输出区域
     *
     * 将 block.terminal.lines 渲染为带 stderr 高亮的终端输出。
     * 若命令已结束，追加完成/超时/退出码提示。
     */
    _renderToolTerminal(b) {
        if (!b.terminal || b.terminal.lines.length === 0) return '';
        const linesHtml = b.terminal.lines.map(l =>
            `<span class="${l.is_stderr ? 'term-stderr' : 'term-stdout'}">${this.esc(l.text)}</span>`
        ).join('');
        let finishHtml = '';
        if (b.terminal.finished) {
            if (b.terminal.timed_out) {
                finishHtml = '<span class="term-finish">\n[命令执行超时]</span>';
            } else if (b.terminal.exit_code !== 0) {
                finishHtml = `<span class="term-finish">\n[命令结束，退出码: ${b.terminal.exit_code}]</span>`;
            } else {
                finishHtml = '<span class="term-finish">\n[命令执行完成]</span>';
            }
        }
        return `<div class="tool-section tool-terminal-section">
            <strong>实时终端输出</strong>
            <pre class="tool-terminal">${linesHtml}${finishHtml}</pre>
        </div>`;
    },

    welcomeHTML() {
        const suggestions = [
            '帮我用五步法分析贵州茅台(600519)',
            '比亚迪 vs 长城汽车横向对比',
            '分析中芯国际(688981)的估值',
            '宁德时代(300750)最新财务数据',
            '最近有什么影响A股的政策？',
        ];
        return `<div class="chat-welcome">
            <h2>Charles 投研助手</h2>
            <p>我是你的 AI 投研情报官，采用国泰君安五步法进行深度研究分析。</p>
            <div class="welcome-suggestions">
                ${suggestions.map(s => `<span class="welcome-suggestion" onclick="AI_CHAT.sendSuggestion('${this.esc(s)}')">${this.esc(s)}</span>`).join('')}
            </div>
        </div>`;
    },

    // ===== 发送消息 =====
    sendMessage() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        input.style.height = 'auto';

        if (!this.currentConvId || !this.conversations[this.currentConvId]) {
            this.newConversation();
        }
        const conv = this.conversations[this.currentConvId];

        // 用户消息
        conv.messages.push({ role: 'user', content: text });
        if (conv.messages.length === 1) {
            conv.title = text.substring(0, 30) + (text.length > 30 ? '...' : '');
        }

        this.saveConversations();
        this.renderSidebar();

        // Phase 30.1 P0 修复：agent 运行中，入队而非启动新 run
        // 对标 Cline enqueue pending prompt — 服务端检测到活跃 runtime 后入队
        if (this.isStreaming) {
            this.renderMessages(); // 立即显示用户消息
            this._enqueueMessage(text);
            return;
        }

        // assistant 消息
        const assistMsg = { role: 'assistant', blocks: [], _streaming: true };
        conv.messages.push(assistMsg);

        this.renderMessages();

        // 发起 SSE
        this.startStreaming(text);
    },

    /** Phase 30.1 P0: 将消息入队到 turn_queue
     *
     * 服务端 /api/chat/stream 检测到活跃 runtime 后会入队并返回短 SSE
     * 包含 pending_prompts_updated 事件用于更新 badge。
     * 不调用 _finishStream，因为当前仍在 streaming 主流程。
     */
    async _enqueueMessage(text) {
        try {
            const response = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    session_id: this.currentConvId,
                    mode: this.currentMode,
                    provider_id: this.currentProvider || undefined,
                    delivery: 'queue',
                }),
            });
            if (!response.ok) throw new Error('入队请求失败: ' + response.status);

            // 读取短 SSE 响应（包含 pending_prompts_updated + done）
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.substring(6));
                        this._handleSSEEvent(data);
                    } catch(e) {}
                }
            }
        } catch (err) {
            console.error('turn_queue: 入队失败', err);
        }
    },

    sendSuggestion(text) {
        document.getElementById('chat-input').value = text;
        this.sendMessage();
    },

    /** 将文本填入输入框 (不发送), 供其他页面注入上下文用。
     *  若右侧 AI 侧栏处于收起态, 自动展开, 便于用户看到注入内容并确认发送。
     *  调用示例: AI_CHAT.preload('请分析以下持仓...') */
    preload(text) {
        // 侧栏收起时自动展开
        const sidebar = document.getElementById('ai-sidebar');
        if (sidebar && sidebar.classList.contains('collapsed')) {
            sidebar.classList.remove('collapsed');
            const expandBtn = document.getElementById('ai-sidebar-expand-btn');
            if (expandBtn) expandBtn.classList.remove('show');
            try { localStorage.setItem('ai_sidebar_collapsed', '0'); } catch(e) {}
        }
        const input = document.getElementById('chat-input');
        if (!input) return;
        input.value = text;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 200) + 'px';
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    },

    startStreaming(message) {
        this.isStreaming = true;
        this.updateSendButton();
        this.abortController = new AbortController();

        const conv = this.conversations[this.currentConvId];
        const assistMsg = conv.messages[conv.messages.length - 1];
        this._streamBlocks = assistMsg.blocks;
        this._streamEl = document.querySelector('#chat-messages .msg-row:last-child .msg-body');
        this._currentPhase = 'init';  // init | planning | thinking | answering
        this._streamActiveBlock = null;
        this._scrollScheduled = false;  // scrollToBottom 节流标志, 同一帧内只执行一次

        fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                session_id: this.currentConvId,
                history: this.buildHistory(),
                mode: this.currentMode,  // Phase 15: 传递当前工作模式
                provider_id: this.currentProvider || undefined,  // 前端选择的 Provider
            }),
            signal: this.abortController.signal,
        }).then(response => {
            if (!response.ok) throw new Error('请求失败: ' + response.status);
            return this.readSSEStream(response);
        }).catch(err => {
            if (err.name === 'AbortError') return;
            this._addBlock({ type: 'error', text: err.message || String(err) });
            this._finishStream();
        });
    },

    /**
     * 接管进行中的活跃 run — 会话级事件广播的前端侧
     *
     * 场景: 用户在另一标签页发起对话后，本页面刷新/重新打开。
     * 本页 localStorage 没有对应的 assistant 消息，但后端该会话仍有活跃 run。
     * 通过 /api/chat/stream/subscribe 订阅广播流:
     *   1. 重放 event_log（该 run 已产生的全部事件，重建流式界面）
     *   2. 实时接收增量事件
     * 事件渲染到当前会话新建的 assistant 消息，run 结束（EOF）后标记完成。
     * 无活跃 run 时订阅返回空流（仅注释行），本方法不做任何事。
     *
     * 性能优化:
     *   - 侧栏收起时不接管（后台页面不渲染聊天流，避免卡住页面主线程）
     *   - 重放事件统一批处理（_replayMode 只累积数据），收到后端 ": replay-end"
     *     注释标记后一次性渲染，避免逐事件全量重建 DOM
     */
    async takeoverActiveRun() {
        if (!this.currentConvId || this.isStreaming) return;
        // 防止并发接管（页面加载 + 展开侧栏按钮可能重复触发）
        if (this._takeoverPending) return;
        // 侧栏模式且侧栏收起: 不接管，避免后台页面同步渲染聊天流卡住页面
        // （用户展开侧栏时通过 expand 按钮事件触发接管）
        if (document.body.dataset.chatMode === 'sidebar' &&
            localStorage.getItem('ai_sidebar_collapsed') === '1') {
            return;
        }
        this._takeoverPending = true;
        const takeoverConvId = this.currentConvId;
        // 接管期间可中止: 与 startStreaming 一致设置 abortController，停止按钮可直接断开接管流
        this.abortController = new AbortController();
        let resp;
        let reader = null;
        try {
            try {
                resp = await fetch(`/api/chat/stream/subscribe?session_id=${encodeURIComponent(takeoverConvId)}`, {
                    signal: this.abortController.signal,
                });
            } catch (err) {
                if (err.name === 'AbortError') return; // 用户主动停止接管
                console.warn('接管活跃 run: 订阅请求失败', err);
                return;
            }
            if (!resp.ok || !resp.body) return;

            reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            // 阶段1: 探测是否有活跃 run（读到第一个 data 事件或 EOF）
            // 无活跃 run 时后端返回注释行 ": no-active-run"，不含任何 data 事件
            let hasData = false;
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) { hasData = true; break; }
                }
                if (hasData) break;
            }
            if (!hasData) return; // 无活跃 run，不接管

            // 探测等待期间用户可能已发送新消息（走 startStreaming），放弃接管避免双流并发
            if (this.isStreaming) return;

            // 阶段2: 创建流式 assistant 消息并渲染（位于消息列表末尾，与活跃 run 对应）
            const conv = this.conversations[takeoverConvId];
            if (!conv) return;
            this._takeoverActive = true;
            const assistMsg = { role: 'assistant', blocks: [], _streaming: true };
            conv.messages.push(assistMsg);
            this.isStreaming = true;
            this.updateSendButton();
            this._streamBlocks = assistMsg.blocks;
            this._currentPhase = 'init';
            this._streamActiveBlock = null;
            // 重放批处理模式: 事件只累积到 blocks 数据，收到 ": replay-end" 后统一渲染
            this._replayMode = true;
            this._replayDirty = false;
            this.renderMessages();
            this._streamEl = document.querySelector('#chat-messages .msg-row:last-child .msg-body');

            // 阶段3: 先处理探测阶段已缓冲的完整行，再持续消费增量直到流结束
            const handleLine = (line) => {
                if (line.startsWith(': replay-end')) {
                    // 重放结束标记: 统一渲染一次，之后进入实时增量模式
                    if (this._replayMode) {
                        this._replayMode = false;
                        if (this._replayDirty) this._renderStreamingDOM();
                    }
                    return;
                }
                if (!line.startsWith('data: ')) return;
                try {
                    const data = JSON.parse(line.substring(6));
                    this._handleSSEEvent(data);
                } catch (e) {}
            };
            let lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) handleLine(line);
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) handleLine(line);
            }
            // 流结束: 若仍处于重放模式（异常流无 replay-end），强制退出并渲染
            if (this._replayMode) {
                this._replayMode = false;
                if (this._replayDirty) this._renderStreamingDOM();
            }

            // 阶段4: 收尾 — 若用户已切换到其他会话，先切回接管会话再统一收尾
            if (this.currentConvId !== takeoverConvId) {
                this.switchConversation(takeoverConvId);
            }
            this._finishStream();
        } catch (err) {
            if (err.name !== 'AbortError') {
                console.warn('接管活跃 run 异常:', err);
            }
        } finally {
            // 释放 SSE 流资源（正常 EOF 后 cancel 无害）
            if (reader) {
                try { reader.cancel(); } catch (e) {}
            }
            this._takeoverPending = false;
            // 异常/中止路径: 清理接管状态（正常路径已由 _finishStream 清理）
            if (this.isStreaming && this._takeoverActive) {
                this._takeoverActive = false;
                this._replayMode = false;
                this._replayDirty = false;
                if (this._answerUpdateTimer) {
                    clearTimeout(this._answerUpdateTimer);
                    this._answerUpdateTimer = null;
                }
                this.isStreaming = false;
                this.abortController = null;
                this.updateSendButton();
                this.saveConversations();
            }
        }
    },

    async readSSEStream(response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            // 批统计: 单批行数大 = 事件在订阅队列积压后一次性到达（积压的直接证据）
            const _perf = this._perf();
            const _batchStart = _perf ? performance.now() : 0;
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.substring(6));
                    this._handleSSEEvent(data);
                } catch(e) {}
            }
            if (_perf) {
                _perf.batchCount++;
                _perf.batchEvents += lines.length;
                _perf.maxBatchEvents = Math.max(_perf.maxBatchEvents, lines.length);
                _perf.batchTotalMs += performance.now() - _batchStart;
            }
        }
        this._finishStream();
    },

    // ===== 性能日志（本地调试用）=====
    // 用于定位 SSE 事件积压与渲染瓶颈:
    //   - 事件接收/处理速率与批大小（单批事件数大 = 队列积压后一次性到达）
    //   - 渲染耗时（_renderStreamingDOM 全量重建 / thinking / answer markdown / scroll）
    //   - rAF 延迟（渲染重时 rAF 回调被推迟，页面掉帧的直接证据）
    //   - 端到端接收滞后（后端 ts → 前端接收，事件在订阅队列中积压的时长）
    // 开关: localStorage ai_chat_perf_log = '0' 关闭，未设置或 '1' 开启（默认开启）
    _perf() {
        if (!this._perfEnabled) {
            if (this._perfChecked) return null;
            this._perfChecked = true;
            try {
                this._perfEnabled = localStorage.getItem('ai_chat_perf_log') !== '0';
            } catch(e) { this._perfEnabled = true; }
            if (this._perfEnabled) {
                console.log('[SSE性能] 日志已开启（localStorage ai_chat_perf_log=0 可关闭）');
            }
            if (!this._perfEnabled) return null;
        }
        if (!this._perfStat) {
            this._perfStat = {
                winStart: performance.now(),
                events: 0, batchCount: 0, batchEvents: 0, batchTotalMs: 0, maxBatchEvents: 0,
                renderCount: 0, renderMs: 0, maxRenderMs: 0,
                thinkCount: 0, thinkMs: 0,
                answerCount: 0, answerMs: 0, markdownCount: 0, markdownMs: 0,
                scrollCount: 0, scrollMs: 0,
                rafDelayMax: 0, recvMaxLagMs: 0,
                typeStats: {},
            };
        }
        return this._perfStat;
    },

    /** 输出当前统计窗口的汇总日志并重置窗口 */
    _perfReport() {
        const s = this._perfStat;
        if (!s) return;
        const winMs = performance.now() - s.winStart;
        const avgPerEvent = s.events ? (s.batchTotalMs / s.events).toFixed(3) : '-';
        const avgBatch = s.batchCount ? (s.batchEvents / s.batchCount).toFixed(0) : 0;
        console.log(
            `[SSE性能] ${(winMs/1000).toFixed(1)}s窗口: ` +
            `事件=${s.events} 批=${s.batchCount} 批均${avgBatch}件 最大批=${s.maxBatchEvents}件 ` +
            `处理均${avgPerEvent}ms/件 ` +
            `| 渲染DOM=${s.renderCount}次/${s.renderMs.toFixed(0)}ms(单次峰${s.maxRenderMs.toFixed(0)}ms) ` +
            `thinking=${s.thinkCount}次/${s.thinkMs.toFixed(0)}ms ` +
            `answer=${s.answerCount}次/${s.answerMs.toFixed(0)}ms ` +
            `markdown=${s.markdownCount}次/${s.markdownMs.toFixed(0)}ms ` +
            `scroll=${s.scrollCount}次/${s.scrollMs.toFixed(0)}ms ` +
            `| rAF延迟峰=${s.rafDelayMax.toFixed(0)}ms 接收滞后峰=${s.recvMaxLagMs.toFixed(0)}ms`
        );
        const types = Object.entries(s.typeStats).sort((a, b) => b[1].ms - a[1].ms).slice(0, 6);
        if (types.length) {
            console.log('[SSE性能] 事件耗时TOP: ' +
                types.map(([t, v]) => `${t}=${v.count}次/${v.ms.toFixed(0)}ms`).join('  '));
        }
        // 重置窗口
        Object.assign(s, {
            winStart: performance.now(),
            events: 0, batchCount: 0, batchEvents: 0, batchTotalMs: 0, maxBatchEvents: 0,
            renderCount: 0, renderMs: 0, maxRenderMs: 0,
            thinkCount: 0, thinkMs: 0,
            answerCount: 0, answerMs: 0, markdownCount: 0, markdownMs: 0,
            scrollCount: 0, scrollMs: 0,
            rafDelayMax: 0, recvMaxLagMs: 0,
            typeStats: {},
        });
    },

    _handleSSEEvent(data) {
        const _perf = this._perf();
        const _start = _perf ? performance.now() : 0;
        // 端到端接收滞后: 后端 ts(墙钟毫秒) → 本地 Date.now()
        // 仅在实时增量模式统计（重放事件的 ts 是历史时间，滞后会被放大，无参考意义）
        if (_perf && !this._replayMode && typeof data.ts === 'number') {
            const lag = Date.now() - data.ts;
            if (lag > _perf.recvMaxLagMs) _perf.recvMaxLagMs = lag;
        }
        switch (data.type) {
            case 'phase':
                this._onPhase(data.phase);
                break;
            case 'reasoning':
                this._onReasoning(data.text);
                break;
            case 'token':
                this._onToken(data.text);
                break;
            case 'plan':
                this._onPlanEvent(data.text);
                break;
            case 'tool_call':
                this._onToolCall(data);
                break;
            case 'tool_output':
                this._onToolOutput(data);
                break;
            case 'todos_updated':
                this._onTodosUpdated(data.todos);
                break;
            case 'mode_changed':
                this._onModeChanged(data);
                break;
            case 'approval_request':
                this._onApprovalRequest(data);
                break;
            case 'ask_question':
                this._onAskQuestion(data);
                break;
            // Phase 30.1 P0 修复：turn_queue 事件处理 — 对标 Cline pending_prompts/pending_prompt_submitted
            case 'pending_prompts':
                this._onPendingPrompts(data);
                break;
            case 'pending_prompt_submitted':
                this._onPendingPromptSubmitted(data);
                break;
            case 'pending_prompts_drained':
                // 服务端已自动消费，前端仅用于 UI 反馈
                this._onPendingPromptsDrained(data);
                break;
            case 'pending_prompts_updated':
                // 入队确认事件，更新 badge
                this._onPendingPromptsUpdated(data);
                break;
            case 'file_context_updated':
                // Stage 6.7: 文件上下文更新事件 — runtime 主动推送
                // 工具执行后 _file_context_tracker_hook 通过 SSE 回调推送
                this._onFileContextUpdated(data.state);
                break;
            case 'terminal_output':
                // 实时终端输出 — run_commands 长耗时命令进度推送
                this._onTerminalOutput(data);
                break;
            case 'done':
                break;
            case 'error':
                this._addBlock({ type: 'error', text: data.text });
                break;
        }
        if (_perf) {
            const ms = performance.now() - _start;
            _perf.events++;
            const st = _perf.typeStats[data.type] || (_perf.typeStats[data.type] = { count: 0, ms: 0 });
            st.count++;
            st.ms += ms;
            // 每 500 事件或每 5 秒输出一次汇总
            if (_perf.events % 500 === 0 || (performance.now() - _perf.winStart) > 5000) {
                this._perfReport();
            }
        }
    },

    /** 文件上下文更新回调 — Stage 6.7 新增
     *
     * runtime 在工具执行后通过 SSE 事件推送 file_context_updated，
     * 前端无需轮询 GET /file_context 端点即可实时刷新文件面板。
     *
     * @param state 精简视图 {read: [...], edited: [...], created: [...], deleted: [...]}
     */
    _onFileContextUpdated(state) {
        // 缓存最新状态，供文件面板打开时直接渲染
        this._lastFileContext = state;
        // 通过 CustomEvent 分发，与文件面板组件解耦
        // 文件面板组件监听 'file-context-updated' 事件并刷新
        document.dispatchEvent(new CustomEvent('file-context-updated', {
            detail: { state: state, session_id: this.currentConvId }
        }));
    },

    // ========================================================================
    // Phase 30.1 P0 修复：turn_queue 排队消息 UI 处理
    // 对标 Cline pending_prompts/pending_prompt_submitted 事件
    // ========================================================================

    /** 队列状态变更：更新排队 badge 数量与提示 */
    _onPendingPrompts(data) {
        const prompts = data.prompts || [];
        this._updateQueueIndicator(prompts.length, false);
    },

    /** 入队确认事件：更新 badge（与 _onPendingPrompts 同逻辑） */
    _onPendingPromptsUpdated(data) {
        const prompts = data.prompts || [];
        this._updateQueueIndicator(prompts.length, false);
    },

    /** 队首条目已提交消费：从排队列表移除，badge 递减，切换为 draining 样式 */
    _onPendingPromptSubmitted(data) {
        // 服务端已取出队首启动新 run，前端切换为 draining 样式提示用户
        const indicator = document.getElementById('queue-indicator');
        if (indicator && indicator.style.display !== 'none') {
            indicator.classList.add('queue-draining');
            const hint = document.getElementById('queue-hint');
            if (hint) hint.textContent = '正在处理排队消息...';
        }
    },

    /** 队列已全部消费：隐藏 badge */
    _onPendingPromptsDrained(data) {
        const prompts = data.prompts || [];
        if (prompts.length === 0) {
            this._updateQueueIndicator(0, false);
        } else {
            this._updateQueueIndicator(prompts.length, false);
        }
    },

    /** 更新排队指示器 UI
     * @param count 排队消息数
     * @param draining 是否正在消费
     */
    _updateQueueIndicator(count, draining) {
        const indicator = document.getElementById('queue-indicator');
        const numEl = document.getElementById('queue-badge-num');
        const hintEl = document.getElementById('queue-hint');
        if (!indicator || !numEl || !hintEl) return;

        if (count <= 0) {
            indicator.style.display = 'none';
            indicator.classList.remove('queue-draining');
            return;
        }

        indicator.style.display = 'flex';
        numEl.textContent = String(count);
        if (draining) {
            indicator.classList.add('queue-draining');
            hintEl.textContent = '正在处理排队消息...';
        } else {
            indicator.classList.remove('queue-draining');
            hintEl.textContent = '条消息排队中，等待当前任务完成后自动处理';
        }
    },

    _onPhase(phase) {
        // 后端不再区分 planning/executing, 统一映射为 thinking/answering
        if (phase === 'planning' || phase === 'executing') {
            phase = 'thinking';
        }
        if (phase === this._currentPhase) return;
        this._currentPhase = phase;

        // 结束上一个 active block 的 token 收集
        this._flushActiveBlock();

        if (phase === 'thinking') {
            // 创建新的 thinking block
            this._streamBlocks.push({ type: 'thinking', text: '', expanded: true });
            this._renderStreamingDOM();
            this._streamActiveBlock = this._streamBlocks[this._streamBlocks.length - 1];
        } else if (phase === 'answering') {
            // 创建新的 answer block
            this._streamBlocks.push({ type: 'answer', text: '' });
            this._renderStreamingDOM();
            this._streamActiveBlock = this._streamBlocks[this._streamBlocks.length - 1];
        }
    },

    /** 接收后端发来的 plan 事件，直接创建 plan block */
    _onPlanEvent(text) {
        this._flushActiveBlock();
        const steps = this._parsePlanSteps(text);
        this._streamBlocks.push({ type: 'plan', text: text, steps: steps });
        this._renderStreamingDOM();
    },

    _parsePlanSteps(text) {
        // 解析 <plan>...</plan> 中的步骤列表
        const planMatch = text.match(/<plan>([\s\S]*?)<\/plan>/);
        const body = planMatch ? planMatch[1] : text;
        const lines = body.split('\n').filter(l => l.trim());
        const steps = [];
        for (const line of lines) {
            const match = line.match(/^\s*(\d+)[\.\、]\s*(.+)/);
            if (match) {
                steps.push({ num: match[1], text: match[2].trim(), status: 'pending' });
            }
        }
        return steps.length > 0 ? steps : null;
    },

    /** 接收 reasoning 事件 — 渲染到 thinking 块 */
    _onReasoning(text) {
        if (!text) return;
        // 如果当前没有 active block 或 active block 不是 thinking，创建新的 thinking block
        if (!this._streamActiveBlock || this._streamActiveBlock.type !== 'thinking') {
            this._flushActiveBlock();
            this._streamBlocks.push({ type: 'thinking', text: '', expanded: true });
            this._renderStreamingDOM();
            this._streamActiveBlock = this._streamBlocks[this._streamBlocks.length - 1];
        }
        this._streamActiveBlock.text = (this._streamActiveBlock.text || '') + text;
        this._tryExtractPlan();
    },

    _onToken(text) {
        // token 事件 = LLM 正文输出（text-delta），直接渲染到 answer 块
        if (!text) return;
        // 如果当前没有 active block 或 active block 不是 answer，创建新的 answer block
        if (!this._streamActiveBlock || this._streamActiveBlock.type !== 'answer') {
            this._flushActiveBlock();
            this._streamBlocks.push({ type: 'answer', text: '' });
            this._renderStreamingDOM();
            this._streamActiveBlock = this._streamBlocks[this._streamBlocks.length - 1];
        }
        this._streamActiveBlock.text = (this._streamActiveBlock.text || '') + text;
        this._updateStreamBlockDOM();
    },

    _tryExtractPlan() {
        if (!this._streamActiveBlock || this._streamActiveBlock.type !== 'thinking') return;
        const text = this._streamActiveBlock.text || '';
        // 只处理第一次出现的 plan；后续出现的 <plan> 保留在 thinking 里不单独提取
        const hasPlan = this._streamBlocks.some(b => b.type === 'plan');
        const match = text.match(/<plan>([\s\S]*?)<\/plan>/);
        if (!match || hasPlan) {
            this._updateStreamBlockDOM();
            return;
        }

        const fullMatch = match[0];
        const before = text.substring(0, match.index);
        const after = text.substring(match.index + fullMatch.length);
        const steps = this._parsePlanSteps(fullMatch);

        // 找到当前 active block 在数组中的位置
        const idx = this._streamBlocks.indexOf(this._streamActiveBlock);
        if (idx < 0) return;

        // 拆分成: before(thinking) + plan + after(新的 thinking)
        const newBlocks = [];
        if (before.trim()) {
            newBlocks.push({ type: 'thinking', text: before, expanded: true });
        }
        newBlocks.push({ type: 'plan', text: fullMatch, steps });

        this._streamBlocks.splice(idx, 1, ...newBlocks);

        // 创建新的 active block 接收后续 token
        this._streamActiveBlock = { type: 'thinking', text: after, expanded: true };
        this._streamBlocks.push(this._streamActiveBlock);

        this._renderStreamingDOM();
    },

    _onToolCall(data) {
        // 工具调用前的文本一定是思考过程，不是最终答案
        // 把当前 active block（如果有且是 thinking）保持为 thinking
        // 如果当前 active block 不存在或不是 thinking，不做转换
        this._flushActiveBlock();
        // 工具开始执行时，推进计划步骤：running -> done, pending -> running
        this._advancePlanStep();
        // 新增 tool block
        const toolBlock = {
            type: 'tool', name: data.name, args: data.args,
            idx: data.idx, status: 'running', output: null, isError: false,
        };
        this._streamBlocks.push(toolBlock);
        this._renderStreamingDOM();
    },

    _onToolOutput(data) {
        // 找到最后一个 running 的 tool block
        for (let i = this._streamBlocks.length - 1; i >= 0; i--) {
            const b = this._streamBlocks[i];
            if (b.type === 'tool' && b.status === 'running') {
                b.status = data.error ? 'error' : 'done';
                b.output = data.output;
                b.isError = data.error;
                break;
            }
        }
        // 工具完成时不推进 plan 步骤（等下一个工具开始时再推进）
        this._renderStreamingDOM();
    },

    /**
     * 处理任务清单更新 — Phase 15 新增
     *
     * TodoWrite 工具触发的任务清单更新事件。
     * 前端将任务清单渲染为可折叠卡片，显示每个 todo 的状态。
     *
     * 渲染策略:
     *   - 每个会话只有一个 todoList block（替换式更新）
     *   - 若已存在 todoList block 则更新，否则新建
     *   - 卡片显示进度（已完成/总数）
     */
    _onTodosUpdated(todos) {
        if (!Array.isArray(todos)) return;
        // 查找已有的 todoList block
        let todoBlock = this._streamBlocks.find(b => b.type === 'todo_list');
        if (!todoBlock) {
            todoBlock = { type: 'todo_list', todos: [], expanded: true };
            this._streamBlocks.push(todoBlock);
        }
        todoBlock.todos = todos;
        this._renderStreamingDOM();
        // 看板功能已屏蔽：TodoWrite 工具已移除，todos 无数据源，看板失去意义，故不再实时刷新看板面板
        // const kanbanPanel = document.getElementById('kanban-panel');
        // if (kanbanPanel) {
        //     kanbanPanel.innerHTML = this._renderKanbanBoard(this._buildBoardFromTodos(todos));
        // }
    },

    /**
     * 处理模式切换事件 — Phase 15 新增
     *
     * switch_to_act_mode / switch_to_plan_mode 工具触发的模式切换。
     * 前端更新按钮状态和提示文字。
     */
    _onModeChanged(data) {
        const newMode = data.new_mode || 'act';
        this.currentMode = newMode;
        this._updateModeUI();
        // 持久化模式状态
        try { localStorage.setItem('ai_chat_mode', newMode); } catch(e) {}
    },

    /**
     * 处理工具审批请求 — Phase 19 新增
     *
     * 后端 runtime 在执行危险工具前（requires_approval=True 且非 auto_approve），
     * 通过 SSE 发送 approval_request 事件，前端显示审批卡片等待用户决策。
     *
     * 事件结构:
     *   {type: "approval_request", tool_call_id, tool_name, input}
     *
     * 渲染策略:
     *   - 创建 approval block，状态为 pending
     *   - 显示工具名、参数预览、批准/拒绝按钮
     *   - 用户点击按钮后，POST /api/chat/approve 发送决策
     *   - 更新 block 状态为 approved/denied
     *
     * 对标 Cline:
     *   - sdk/packages/core/src/runtime/tools/tool-approval.ts
     *   - 审批弹窗 + 批准/拒绝按钮
     */
    _onApprovalRequest(data) {
        const toolCallId = data.tool_call_id || '';
        const toolName = data.tool_name || 'unknown';
        const input = data.input || {};

        // 创建审批 block
        const approvalBlock = {
            type: 'approval',
            tool_call_id: toolCallId,
            tool_name: toolName,
            input: input,
            status: 'pending',  // pending | approved | denied
            expanded: true,
        };
        this._streamBlocks.push(approvalBlock);
        this._renderStreamingDOM();
    },

    /**
     * 发送审批决策到后端 — Phase 19 新增
     *
     * 用户点击批准/拒绝按钮后调用，POST /api/chat/approve。
     * 后端 set_approval_result 唤醒等待的 runtime 协程。
     *
     * Args:
     *   toolCallId: 工具调用 ID
     *   approved: true=批准, false=拒绝
     */
    async _sendApproval(toolCallId, approved) {
        // Stage 5.6 (U10): 读取"始终允许此工具"复选框状态
        let autoApprove = false;
        const checkbox = document.getElementById(`auto-approve-${toolCallId}`);
        if (checkbox) {
            autoApprove = checkbox.checked;
        }
        try {
            const resp = await fetch('/api/chat/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tool_call_id: toolCallId,
                    approved: approved,
                    auto_approve: autoApprove,
                }),
            });
            if (!resp.ok) {
                console.error('审批请求失败:', resp.status);
            }
        } catch(err) {
            console.error('发送审批决策失败:', err);
        }

        // 更新本地 block 状态
        for (const b of this._streamBlocks) {
            if (b.type === 'approval' && b.tool_call_id === toolCallId) {
                b.status = approved ? 'approved' : 'denied';
                break;
            }
        }
        this._renderStreamingDOM();
    },

    /**
     * 处理 ask_question 事件 — 显示问题弹窗，等待用户回答
     *
     * 后端通过 SSE 发送 ask_question 事件，前端创建 question block，
     * 显示问题文本和选项按钮，用户点击后 POST /api/chat/answer_question。
     *
     * 事件结构:
     *   {type: "ask_question", tool_call_id, question, options}
     */
    _onAskQuestion(data) {
        const questionBlock = {
            type: 'question',
            tool_call_id: data.tool_call_id || '',
            question: data.question || '',
            options: data.options || [],
            status: 'pending',  // pending | answered
            expanded: true,
        };
        this._streamBlocks.push(questionBlock);
        this._renderStreamingDOM();
    },

    /**
     * 发送问题回答到后端 — 对标 Cline ask_followup_question
     *
     * 用户点击选项按钮后调用，POST /api/chat/answer_question。
     * 后端 set_question_answer 唤醒等待的 runtime 协程。
     */
    async _sendAnswer(toolCallId, answer) {
        try {
            const resp = await fetch('/api/chat/answer_question', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tool_call_id: toolCallId,
                    answer: answer,
                }),
            });
            if (!resp.ok) {
                console.error('回答问题请求失败:', resp.status);
            }
        } catch(err) {
            console.error('发送回答失败:', err);
        }

        // 更新本地 block 状态
        for (const b of this._streamBlocks) {
            if (b.type === 'question' && b.tool_call_id === toolCallId) {
                b.status = 'answered';
                break;
            }
        }
        this._renderStreamingDOM();
    },

    /**
     * 发送实时终端输出 — run_commands 流式推送
     *
     * 后端通过 SSE 实时推送子进程 stdout/stderr，前端将其追加到
     * 当前 running 的 run_commands 工具卡片内，实现 TRAE 式终端监控。
     *
     * 事件结构:
     *   {type: "terminal_output", command_id, command, index, text, is_stderr, finished}
     *
     * 渲染策略:
     *   - 数据先写入 block.terminal（保证切换对话后重新渲染不丢失）
     *   - 同时直接操作 DOM 增量追加，避免高频输出时整页重刷
     *   - 终端区域自动滚动到底部
     */
    _onTerminalOutput(data) {
        if (!this._streamBlocks) return;

        // 找到当前 running 的 run_commands 工具块；没有 running 则取最后一个
        let toolBlock = null;
        for (let i = this._streamBlocks.length - 1; i >= 0; i--) {
            const b = this._streamBlocks[i];
            if (b.type === 'tool' && b.name === 'run_commands') {
                if (b.status === 'running') {
                    toolBlock = b;
                    break;
                }
                if (!toolBlock) toolBlock = b;
            }
        }
        if (!toolBlock) return;

        if (!toolBlock.terminal) {
            toolBlock.terminal = {
                lines: [],
                finished: false,
                exit_code: null,
                timed_out: false,
            };
        }
        const term = toolBlock.terminal;

        if (data.finished) {
            term.finished = true;
            term.exit_code = data.exit_code;
            term.timed_out = data.timed_out;
        } else if (data.text !== '') {
            term.lines.push({ text: data.text, is_stderr: !!data.is_stderr });
        }

        // Phase 35.1: 若工具已完成（status !== 'running'），事件可能是延迟到达，
        // 此时 DOM 可能已被 _renderStreamingDOM 重建（block.terminal 当初为空未渲染终端区），
        // 增量追加的元素会在下次重建时丢失。因此工具已完成时直接触发全量重渲染，
        // 通过 _renderToolTerminal 从 block.terminal.lines 重新渲染完整终端区。
        // 工具运行中时仍用增量追加，避免高频输出时整页重刷卡顿。
        if (toolBlock.status !== 'running') {
            this._renderStreamingDOM();
            this.scrollToBottom();
            return;
        }

        // 增量更新 DOM：直接追加到当前工具卡片的 terminal 容器
        if (this._streamEl && toolBlock.idx !== undefined) {
            const detailsEl = this._streamEl.querySelector(
                `.block-tool[data-tool-idx="${toolBlock.idx}"]`
            );
            if (detailsEl) {
                let termEl = detailsEl.querySelector('.tool-terminal');
                let sectionEl = detailsEl.querySelector('.tool-terminal-section');
                if (!sectionEl) {
                    const body = detailsEl.querySelector('.tool-body');
                    if (body) {
                        sectionEl = document.createElement('div');
                        sectionEl.className = 'tool-section tool-terminal-section';
                        sectionEl.innerHTML = '<strong>实时终端输出</strong>';
                        termEl = document.createElement('pre');
                        termEl.className = 'tool-terminal';
                        sectionEl.appendChild(termEl);
                        body.appendChild(sectionEl);
                        // 确保展开以显示实时输出
                        detailsEl.setAttribute('open', '');
                    }
                }
                if (termEl && !data.finished) {
                    const span = document.createElement('span');
                    span.className = data.is_stderr ? 'term-stderr' : 'term-stdout';
                    span.textContent = data.text;
                    termEl.appendChild(span);
                    // rAF 节流滚动: 高频终端输出时避免每次强制同步布局 (性能优化)
                    this._scrollTermToBottom(termEl);
                }
                if (termEl && data.finished) {
                    const finishSpan = document.createElement('span');
                    finishSpan.className = 'term-finish';
                    if (data.timed_out) {
                        finishSpan.textContent = '\n[命令执行超时]';
                    } else if (data.exit_code !== 0) {
                        finishSpan.textContent = `\n[命令结束，退出码: ${data.exit_code}]`;
                    } else {
                        finishSpan.textContent = '\n[命令执行完成]';
                    }
                    termEl.appendChild(finishSpan);
                    this._scrollTermToBottom(termEl);
                }
            }
        }

        this.scrollToBottom();
    },

    /** 终端区滚动到底部 — rAF 节流 (性能优化)
     *
     * 高频终端输出时, 每次 appendChild 后立即设置 scrollTop 会触发强制同步布局,
     * 终端行数越多单次布局越慢 (O(n^2))。改为同一帧内合并所有待滚动终端,
     * 每帧最多一次布局。
     */
    _scrollTermToBottom(el) {
        if (!this._termScrollSet) this._termScrollSet = new Set();
        this._termScrollSet.add(el);
        if (this._termScrollScheduled) return;
        this._termScrollScheduled = true;
        requestAnimationFrame(() => {
            this._termScrollScheduled = false;
            const set = this._termScrollSet;
            this._termScrollSet = new Set();
            set.forEach(e => {
                if (e && e.isConnected) e.scrollTop = e.scrollHeight;
            });
        });
    },

    /** 工具开始时推进计划步骤：running -> done, pending -> running */
    _advancePlanStep() {
        for (const b of this._streamBlocks) {
            if (b.type !== 'plan' || !b.steps) continue;
            // 把 running 标记为 done
            for (const step of b.steps) {
                if (step.status === 'running') {
                    step.status = 'done';
                    break;
                }
            }
            // 推进第一个 pending 为 running
            for (const step of b.steps) {
                if (step.status === 'pending') {
                    step.status = 'running';
                    return;
                }
            }
            return;
        }
    },

    _addBlock(block) {
        this._streamBlocks.push(block);
        this._renderStreamingDOM();
    },

    _flushActiveBlock() {
        this._streamActiveBlock = null;
    },

    /** 重新渲染流式消息的 DOM (替换整个 msg-body)
     *
     * 性能优化: 同一帧内多次调用合并为一次重建（requestAnimationFrame 节流），
     * 避免批量工具完成/重放事件时逐事件全量重建 DOM 导致页面卡顿。
     * 重放模式下（_replayMode）只累积数据不渲染，重放结束统一渲染一次。
     */
    _renderStreamingDOM() {
        if (this._replayMode) { this._replayDirty = true; return; }
        if (!this._streamEl) return;
        if (this._renderScheduled) return;
        this._renderScheduled = true;
        const schedAt = performance.now();
        requestAnimationFrame(() => {
            this._renderScheduled = false;
            if (!this._streamEl) return;
            const _perf = this._perf();
            // rAF 延迟: 从调度到执行的时间，渲染重时该值会明显增大（掉帧证据）
            if (_perf) _perf.rafDelayMax = Math.max(_perf.rafDelayMax, performance.now() - schedAt);
            const _start = _perf ? performance.now() : 0;
            this._streamEl.innerHTML = this.renderBlocks(this._streamBlocks);
            if (_perf) {
                const ms = performance.now() - _start;
                _perf.renderCount++;
                _perf.renderMs += ms;
                _perf.maxRenderMs = Math.max(_perf.maxRenderMs, ms);
            }
            this.scrollToBottom();
        });
    },

    /** 只更新最后一个 active block 的内容 (增量, 用于 token 流)
     *
     * 性能优化:
     *   - thinking: 增量追加 O(1)，requestAnimationFrame 节流保持高频（思考过程实时性重要）
     *   - answer: markdown 全量渲染开销大（O(n²)），300ms 定时器节流合并，
     *     每 300ms 最多渲染一次，最终显示内容不变（流结束时 _finishStream 统一渲染）
     *   - 重放模式下只累积数据（_streamActiveBlock.text），重放结束统一渲染
     */
    _updateStreamBlockDOM() {
        if (this._replayMode) return;
        if (!this._streamEl || !this._streamActiveBlock) return;
        const lastBlockType = this._streamActiveBlock.type;
        if (lastBlockType === 'thinking') {
            if (this._thinkUpdateScheduled) return;
            this._thinkUpdateScheduled = true;
            requestAnimationFrame(() => {
                this._thinkUpdateScheduled = false;
                if (!this._streamEl || !this._streamActiveBlock) return;
                const _perf = this._perf();
                const _start = _perf ? performance.now() : 0;
                // 选择最后一个 thinking block 里的文本容器，而不是任意一个 .thinking-text:last-child
                const el = this._streamEl.querySelector('.block-thinking:last-of-type .thinking-text');
                if (el) {
                    const text = this._streamActiveBlock.text || '';
                    // 增量追加: 只追加自上次渲染后新增的文本, 避免每次重设全部思考文本 (O(n^2) -> O(n))
                    const curLen = el.textContent.length;
                    if (text.length > curLen) {
                        el.appendChild(document.createTextNode(text.substring(curLen)));
                    }
                }
                if (_perf) {
                    const ms = performance.now() - _start;
                    _perf.thinkCount++;
                    _perf.thinkMs += ms;
                }
                this.scrollToBottom();
            });
        } else if (lastBlockType === 'answer') {
            if (this._answerUpdateTimer) return;
            // 100ms 节流: 平衡 markdown 渲染频率与吐字流畅度 (之前 300ms 吐字过慢)
            this._answerUpdateTimer = setTimeout(() => {
                this._answerUpdateTimer = null;
                if (!this._streamEl || !this._streamActiveBlock) return;
                if (this._streamActiveBlock.type !== 'answer') return;
                const _perf = this._perf();
                const _start = _perf ? performance.now() : 0;
                const el = this._streamEl.querySelector('.block-answer:last-of-type');
                // 单独统计 markdown 渲染耗时（answer 全量渲染的主要开销），仅调用一次
                const _mdStart = _perf ? performance.now() : 0;
                const _html = this.markdown(this._streamActiveBlock.text || '');
                if (_perf) {
                    _perf.markdownCount++;
                    _perf.markdownMs += performance.now() - _mdStart;
                }
                if (el) el.innerHTML = _html;
                if (_perf) {
                    const ms = performance.now() - _start;
                    _perf.answerCount++;
                    _perf.answerMs += ms;
                }
                this.scrollToBottom();
            }, 100);
        }
    },

    _finishStream() {
        const conv = this.currentConvId ? this.conversations[this.currentConvId] : null;
        if (conv) {
            const last = conv.messages[conv.messages.length - 1];
            if (last) {
                last._streaming = false;
                // 把最后一个 thinking block 转成 answer block（最终回复）
                if (last.blocks) {
                    let hasAnswer = last.blocks.some(b => b.type === 'answer');
                    if (!hasAnswer) {
                        for (let i = last.blocks.length - 1; i >= 0; i--) {
                            if (last.blocks[i].type === 'thinking' && (last.blocks[i].text || '').trim()) {
                                last.blocks[i].type = 'answer';
                                hasAnswer = true;
                                break;
                            }
                        }
                    }
                    // 把所有 running 的 plan 步骤标记为 done
                    for (const b of last.blocks) {
                        if (b.type === 'plan' && b.steps) {
                            for (const step of b.steps) {
                                if (step.status === 'running') step.status = 'done';
                            }
                        }
                    }
                    // Phase 19: 把所有 pending 的审批标记为 denied
                    // （流结束/中止时，未决的审批视为超时拒绝，避免 UI 卡在等待状态）
                    for (const b of last.blocks) {
                        if (b.type === 'approval' && b.status === 'pending') {
                            b.status = 'denied';
                        }
                    }
                    // 把所有 pending 的问题标记为 expired（用户终止后不再等待回答）
                    for (const b of last.blocks) {
                        if (b.type === 'question' && b.status === 'pending') {
                            b.status = 'expired';
                        }
                    }
                    // 如果有 answer block，折叠过程信息
                    if (hasAnswer) {
                        for (const b of last.blocks) {
                            if (b.type === 'thinking' || b.type === 'plan' || b.type === 'tool') {
                                b.expanded = false;
                            }
                        }
                    }
                }
            }
        }
        this._streamBlocks = null;
        this._streamEl = null;
        this._streamActiveBlock = null;
        // 清理挂起的 answer 渲染节流定时器（流结束后不再需要）
        if (this._answerUpdateTimer) {
            clearTimeout(this._answerUpdateTimer);
            this._answerUpdateTimer = null;
        }
        this.isStreaming = false;
        this.abortController = null;
        this.updateSendButton();
        this.saveConversations();
        this.renderMessages();
    },

    buildHistory() {
        const conv = this.conversations[this.currentConvId];
        const history = [];
        for (let i = 0; i < conv.messages.length - 1; i++) {
            const m = conv.messages[i];
            history.push({ role: m.role, content: m.role === 'user' ? m.content : this._extractText(m) });
        }
        return history;
    },

    _extractText(msg) {
        if (!msg.blocks) return msg.content || '';
        // 从 blocks 中提取 answer 文本
        for (const b of msg.blocks) {
            if (b.type === 'answer') return b.text || '';
        }
        return '';
    },

    /** 消息级回滚 — 回滚到某条用户提问之前
     *
     * 删除指定用户消息及其之后的所有内容（AI 回答、工具调用、工具结果等），
     * 使对话上下文恢复到该提问之前的状态，便于重新生成。
     * 调用后端 /api/chat/rollback_message，并同步截断前端消息。
     */
    async rollbackToUserMsg(userIndex, e) {
        if (e) e.stopPropagation();
        if (!this.currentConvId) return;
        if (this.isStreaming) {
            this._showToast('当前有消息正在生成，请等待完成后再回滚');
            return;
        }
        if (!confirm('确定回滚到这条提问之前吗？将删除该提问及其后的所有回答和工具调用。')) return;
        // 从当前会话消息中定位该提问的文本（与后端按文本匹配定位保持一致）
        const conv = this.conversations[this.currentConvId];
        let userText = '';
        if (conv) {
            let idx = 0;
            let last = null;
            for (const msg of conv.messages) {
                if (msg.role !== 'user') continue;
                if (msg.content === last) continue;  // 相邻去重
                if (idx === userIndex) { userText = msg.content; break; }
                last = msg.content;
                idx++;
            }
        }
        try {
            const resp = await fetch('/api/chat/rollback_message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.currentConvId, user_index: userIndex, text: userText }),
            });
            const data = await resp.json();
            if (data.status !== 'ok') {
                App.toast(data.message || '回滚失败', 'danger');
                return;
            }
            // 前端同步截断 conv.messages（找到第 userIndex 条用户消息并删除其及之后）
            const conv = this.conversations[this.currentConvId];
            if (conv) {
                let count = 0;
                let idx = -1;
                for (let i = 0; i < conv.messages.length; i++) {
                    if (conv.messages[i].role === 'user') {
                        if (count === userIndex) { idx = i; break; }
                        count++;
                    }
                }
                if (idx >= 0) {
                    conv.messages.splice(idx);
                }
                this.saveConversations();
            }
            this.renderMessages();
            this._showToast('已回滚到该提问之前的状态');
        } catch (err) {
            App.toast('回滚请求失败: ' + err.message, 'danger');
        }
    },

    stopStreaming() {
        // 通知后端中止 Agent 运行
        if (this.currentConvId) {
            fetch('/api/chat/abort', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.currentConvId }),
            }).catch(() => {});
        }
        // 客户端中止 SSE 连接
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        this._finishStream();
    },

    // ===== UI 辅助 =====
    updateSendButton() {
        const btn = document.getElementById('send-btn');
        if (!btn) return;
        if (this.isStreaming) {
            btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18"><rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/></svg>';
            btn.onclick = () => this.stopStreaming();
        } else {
            btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
            btn.onclick = () => this.sendMessage();
        }
    },

    /** 自动滚动到底部（仅在用户已经在底部时）

    避免流式输出时强制锁定滚动条，让用户可以回看历史内容。
    */
    scrollToBottom() {
        // 节流: 同一帧内多次调用只执行一次, 减少强制同步布局次数
        if (this._scrollScheduled) return;
        this._scrollScheduled = true;
        requestAnimationFrame(() => {
            this._scrollScheduled = false;
            const _perf = this._perf();
            const _start = _perf ? performance.now() : 0;
            const c = document.getElementById('chat-messages');
            if (!c || this._userScrolledUp) return;
            const threshold = 80; // 距离底部 80px 以内视为"在底部"
            const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight <= threshold;
            if (nearBottom) {
                c.scrollTop = c.scrollHeight;
            }
            if (_perf) {
                const ms = performance.now() - _start;
                _perf.scrollCount++;
                _perf.scrollMs += ms;
            }
        });
    },

    bindEvents() {
        document.getElementById('send-btn').onclick = () => this.sendMessage();
        document.getElementById('new-chat-btn').onclick = () => this.newConversation();
        // Phase 15: Plan Mode 切换按钮
        const modeBtn = document.getElementById('mode-toggle-btn');
        if (modeBtn) modeBtn.onclick = () => this.toggleMode();
        const input = document.getElementById('chat-input');
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendMessage(); }
        });
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 150) + 'px';
        });

        // 监听用户手动滚动：上滑时暂停自动滚动到底部
        const c = document.getElementById('chat-messages');
        if (c) {
            this._userScrolledUp = false;
            c.addEventListener('scroll', () => {
                const threshold = 80;
                this._userScrolledUp = c.scrollHeight - c.scrollTop - c.clientHeight > threshold;
            });
        }
    },

    // ===== 聊天工具栏 — Provider 快速切换 + 功能面板入口 =====

    /**
     * 初始化聊天工具栏 — 绑定 Provider 选择器和功能面板按钮事件
     */
    _initToolbar() {
        this._initProviderSelector();
        // 工具栏功能面板按钮
        // 看板功能已屏蔽：TodoWrite 工具已移除，todos 无数据源，看板失去意义，故不再绑定看板概览按钮事件
        // const kanbanBtn = document.getElementById('toolbar-kanban-btn');
        // if (kanbanBtn) kanbanBtn.onclick = () => this._toggleKanbanOverview();
        const checkpointBtn = document.getElementById('toolbar-checkpoint-btn');
        if (checkpointBtn) checkpointBtn.onclick = () => this._toggleCheckpointPanel();
        const cronBtn = document.getElementById('toolbar-cron-btn');
        if (cronBtn) cronBtn.onclick = () => {
            if (typeof AI_SETTINGS !== 'undefined') {
                AI_SETTINGS.open();
                AI_SETTINGS.switchTab('cron');
            }
        };
        const pendingBtn = document.getElementById('toolbar-pending-btn');
        if (pendingBtn) pendingBtn.onclick = () => {
            if (typeof AI_SETTINGS !== 'undefined') {
                AI_SETTINGS.open();
                AI_SETTINGS.switchTab('pending');
            }
        };
    },

    /**
     * 初始化 Provider 选择器
     *
     * 对接后端 GET /api/chat/providers，读取 providers 与 active_provider。
     * 若未配置 providers.yaml，下拉列表至少显示当前生效的 active_provider。
     * 用户选择后保存到 localStorage，发送消息时随 /stream 请求传递。
     */
    _initProviderSelector() {
        const providerSelect = document.getElementById('provider-select');
        if (!providerSelect) return;
        providerSelect.addEventListener('change', (e) => this._onProviderChange(e.target.value));
        this._loadProviders();
        // 恢复上次选择的 Provider
        try {
            const saved = localStorage.getItem('ai_chat_provider') || '';
            this.currentProvider = saved;
            if (saved) providerSelect.value = saved;
        } catch(e) {}

        const editBtn = document.getElementById('provider-edit-btn');
        if (editBtn) editBtn.onclick = () => {
            if (typeof AI_SETTINGS !== 'undefined') {
                AI_SETTINGS.open();
                AI_SETTINGS.switchTab('provider');
            }
        };
    },

    /** 从后端加载 Provider 列表并填充下拉选择器 */
    async _loadProviders() {
        const select = document.getElementById('provider-select');
        if (!select) return;
        try {
            const resp = await fetch('/api/chat/providers');
            const data = await resp.json();
            if (data.status !== 'ok') return;
            const providers = data.providers || [];
            const builtin = data.builtin || [];
            const active = data.active_provider || {};
            const configuredAliases = new Set(providers.map(p => p.alias));

            // 按 provider_id 对配置分组
            const byProvider = {};
            for (const p of providers) {
                if (!byProvider[p.provider_id]) byProvider[p.provider_id] = [];
                byProvider[p.provider_id].push(p);
            }

            // 保留默认选项
            let html = '<option value="">默认 Provider</option>';

            // 当前生效的 Provider（环境变量默认，且未持久化时）
            const activeAlias = active.alias || '';
            if (activeAlias && !configuredAliases.has(activeAlias)) {
                const label = active.model_id || active.provider_id || active.alias;
                html += `<option value="${this.esc(active.alias)}">${this.esc(label)}</option>`;
            }

            // 已配置的 Provider：按 provider_id 分组，组内只显示模型名
            for (const pid of Object.keys(byProvider).sort()) {
                const list = byProvider[pid];
                if (list.length === 1) {
                    const p = list[0];
                    const label = p.model_id || p.alias;
                    html += `<option value="${this.esc(p.alias)}">${this.esc(label)}</option>`;
                } else {
                    html += `<optgroup label="${this.esc(pid)}">`;
                    for (const p of list) {
                        const label = p.model_id || p.alias;
                        html += `<option value="${this.esc(p.alias)}">${this.esc(label)}</option>`;
                    }
                    html += '</optgroup>';
                }
            }

            // 内置但未配置的 Provider 类型（灰色提示可去配置）
            const configuredProviderIds = new Set(providers.map(p => p.provider_id));
            const unconfigured = builtin.filter(id => !configuredProviderIds.has(id) && id !== active.provider_id);
            if (unconfigured.length > 0) {
                html += '<optgroup label="未配置（需在设置中添加）">';
                for (const id of unconfigured) {
                    html += `<option value="${this.esc(id)}" disabled>${this.esc(id)}</option>`;
                }
                html += '</optgroup>';
            }
            select.innerHTML = html;
            // 恢复当前选中；若保存的值已不存在（如 alias 体系切换后），重置为默认
            if (this.currentProvider && configuredAliases.has(this.currentProvider)) {
                select.value = this.currentProvider;
            } else if (this.currentProvider && this.currentProvider === activeAlias) {
                select.value = this.currentProvider;
            } else {
                this.currentProvider = '';
                try { localStorage.removeItem('ai_chat_provider'); } catch(e) {}
            }
        } catch(err) {
            console.warn('加载 Provider 列表失败:', err);
        }
    },

    /** Provider 切换回调 — 保存到 localStorage 并提示 */
    _onProviderChange(providerId) {
        this.currentProvider = providerId;
        try { localStorage.setItem('ai_chat_provider', providerId); } catch(e) {}
        const label = providerId ? providerId : '默认 Provider';
        this._showToast(`已切换到 ${label}，下次发送消息生效`);
    },

    /** 刷新 Provider 列表（供设置面板保存后调用） */
    refreshProviders() {
        this._loadProviders();
    },

    // ===== Phase 24: Kanban 看板管理 =====
    // 看板功能已屏蔽（2026-08-04）：
    //   - 原因：TodoWrite 工具已从代码中移除，SessionState.todos 无数据源，看板失去意义。
    //   - 处理：上述调用点（_injectKanbanButton / 工具栏按钮 / SSE 实时刷新）均已注释，
    //     下方看板函数保留为死代码，不再被调用。若日后恢复 TodoWrite 工具，可取消各调用点注释并复用。
    //   - 涉及函数：_injectKanbanButton / _toggleKanbanPanel / _toggleKanbanOverview /
    //     _showKanbanOverview / _showKanbanPanel / _renderKanbanBoard / _buildBoardFromTodos

    /**
     * 在输入区注入看板按钮 — Phase 24 新增
     *
     * 动态在输入行添加"看板"按钮，点击后显示当前会话的任务看板。
     * 看板数据来自 SessionState.todos，通过 /api/chat/kanban 端点获取。
     */
    _injectKanbanButton() {
        const inputRow = document.querySelector('.chat-input-row');
        if (!inputRow) return;
        if (document.getElementById('kanban-btn')) return;
        const btn = document.createElement('button');
        btn.id = 'kanban-btn';
        btn.className = 'kanban-toggle-btn';
        btn.title = '查看任务看板';
        btn.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><rect x="2" y="3" width="4" height="14" rx="1"/><rect x="8" y="3" width="4" height="9" rx="1"/><rect x="14" y="3" width="4" height="11" rx="1"/></svg>';
        btn.onclick = () => this._toggleKanbanPanel();
        // 插入到检查点按钮后面（如果存在）或输入框前面
        const checkpointBtn = document.getElementById('checkpoint-btn');
        if (checkpointBtn) {
            checkpointBtn.parentNode.insertBefore(btn, checkpointBtn.nextSibling);
        } else {
            inputRow.insertBefore(btn, inputRow.firstChild);
        }
    },

    /**
     * 切换看板面板的显示 — Phase 24 新增
     */
    async _toggleKanbanPanel() {
        const panel = document.getElementById('kanban-panel');
        if (panel) {
            panel.remove();
            return;
        }
        await this._showKanbanPanel();
    },

    /**
     * 切换多会话看板概览面板 — 对接 GET /api/chat/kanban/overview
     *
     * 展示所有持久化会话的看板摘要，用于多项目看板视图。
     * 与单会话 _toggleKanbanPanel 区分：本面板展示全部会话的任务进度概览。
     */
    async _toggleKanbanOverview() {
        const panel = document.getElementById('kanban-overview-panel');
        if (panel) {
            panel.remove();
            return;
        }
        await this._showKanbanOverview();
    },

    /** 显示多会话看板概览面板 */
    async _showKanbanOverview() {
        const panel = document.createElement('div');
        panel.id = 'kanban-overview-panel';
        panel.className = 'kanban-overview-panel';
        panel.innerHTML = '<div class="kanban-loading">加载多会话概览...</div>';
        document.body.appendChild(panel);

        try {
            const resp = await fetch('/api/chat/kanban/overview');
            const data = await resp.json();
            if (data.status !== 'ok') {
                panel.innerHTML = `<div class="kanban-empty">${this.esc(data.message || '获取概览失败')}</div>`;
                return;
            }
            const sessions = data.sessions || [];
            const totalSessions = data.total_sessions || 0;
            const totalTasks = data.total_tasks || 0;
            if (sessions.length === 0) {
                panel.innerHTML = `
                    <div class="kanban-panel-header">
                        <span>多会话看板概览</span>
                        <button class="kanban-close" onclick="AI_CHAT._toggleKanbanOverview()">&times;</button>
                    </div>
                    <div class="kanban-empty">暂无会话（agent 运行后会产生看板数据）</div>`;
                return;
            }
            const sessionsHtml = sessions.map(s => {
                const rate = Math.round((s.completion_rate || 0) * 100);
                const sid = this.esc(s.session_id || '');
                const title = this.esc(s.title || s.session_id || '未命名会话');
                return `<div class="overview-session-card">
                    <div class="overview-session-header">
                        <span class="overview-session-title">${title}</span>
                        <span class="overview-session-tasks">${s.completed || 0}/${s.total || 0}</span>
                    </div>
                    <div class="overview-progress-bar">
                        <div class="overview-progress-fill" style="width: ${rate}%"></div>
                    </div>
                    <div class="overview-session-stats">
                        <span class="overview-stat">待办 ${s.pending || 0}</span>
                        <span class="overview-stat">进行中 ${s.in_progress || 0}</span>
                        <span class="overview-stat">已完成 ${s.completed || 0}</span>
                        <span class="overview-stat-rate">${rate}%</span>
                    </div>
                </div>`;
            }).join('');
            panel.innerHTML = `
                <div class="kanban-panel-header">
                    <span>多会话看板概览</span>
                    <span class="kanban-progress-text">${totalSessions} 会话 / ${totalTasks} 任务</span>
                    <button class="kanban-close" onclick="AI_CHAT._toggleKanbanOverview()">&times;</button>
                </div>
                <div class="overview-sessions">${sessionsHtml}</div>`;
        } catch(err) {
            panel.innerHTML = `<div class="kanban-empty">获取概览失败: ${this.esc(err.message)}</div>`;
        }
    },

    /**
     * 显示看板面板 — Phase 24 新增
     *
     * 从后端获取当前会话的看板数据，渲染为 3 列浮动面板。
     * 看板数据实时从 SessionState.todos 构建，与 TodoWrite 工具联动。
     */
    async _showKanbanPanel() {
        if (!this.currentConvId) {
            App.toast('请先选择一个对话', 'warn');
            return;
        }

        const panel = document.createElement('div');
        panel.id = 'kanban-panel';
        panel.className = 'kanban-panel';
        panel.innerHTML = '<div class="kanban-loading">加载看板...</div>';
        document.body.appendChild(panel);

        try {
            const resp = await fetch(`/api/chat/kanban?session_id=${encodeURIComponent(this.currentConvId)}`);
            const data = await resp.json();
            if (data.status !== 'ok') {
                panel.innerHTML = `<div class="kanban-empty">${this.esc(data.message || '获取看板失败')}</div>`;
                return;
            }
            // 渲染看板 — 复用 _renderKanbanBoard，与 SSE 实时刷新保持一致
            panel.innerHTML = this._renderKanbanBoard(data.board);
        } catch(err) {
            panel.innerHTML = `<div class="kanban-empty">获取看板失败: ${this.esc(err.message)}</div>`;
        }
    },

    /**
     * 构建看板 HTML — Phase 24 实时刷新增强
     *
     * 将看板数据渲染为 HTML 字符串。供两处调用方共用，保证渲染一致：
     *   - _showKanbanPanel：首次打开时从后端 /api/chat/kanban 拉取后渲染
     *   - _onTodosUpdated：todos_updated SSE 事件到达时本地构建后即时刷新
     *
     * @param board 后端 KanbanBoard.to_dict() 结构，含 stats 与 columns
     * @returns {string} 看板 innerHTML
     */
    _renderKanbanBoard(board) {
        // 空看板
        if (!board || !board.stats || board.stats.total === 0) {
            return `
                <div class="kanban-panel-header">
                    <span>任务看板</span>
                    <button class="kanban-close" onclick="AI_CHAT._toggleKanbanPanel()">&times;</button>
                </div>
                <div class="kanban-empty">暂无任务（agent 使用 todo_write 工具后会自动显示）</div>`;
        }
        const completionRate = Math.round((board.stats.completion_rate || 0) * 100);
        const columnsHtml = board.columns.map(col => {
            const cards = (col.cards || []).map(c => {
                const activeHtml = c.active_form ?
                    `<div class="kanban-card-active">${this.esc(c.active_form)}</div>` : '';
                return `<div class="kanban-card">${this.esc(c.content)}${activeHtml}</div>`;
            }).join('');
            return `<div class="kanban-column" data-status="${col.id}">
                <div class="kanban-column-header">
                    <span>${this.esc(col.title)}</span>
                    <span class="column-count">${col.count}</span>
                </div>
                <div class="kanban-column-cards">${cards || '<div style="padding:12px;text-align:center;color:#9ca3af;font-size:11px;">空</div>'}</div>
            </div>`;
        }).join('');
        return `
            <div class="kanban-panel-header">
                <span>任务看板</span>
                <div class="kanban-progress-bar">
                    <div class="kanban-progress-fill" style="width: ${completionRate}%"></div>
                </div>
                <span class="kanban-progress-text">${board.stats.completed}/${board.stats.total}</span>
                <button class="kanban-close" onclick="AI_CHAT._toggleKanbanPanel()">&times;</button>
            </div>
            <div class="kanban-columns">${columnsHtml}</div>`;
    },

    /**
     * 从 todos 数组本地构建看板数据 — 实时刷新增强
     *
     * todos_updated SSE 事件已携带完整 todos，前端无需再请求后台即可即时刷新看板。
     * 构建逻辑与后端 agent.kanban.KanbanManager._build_board 保持一致：
     * 按 status 分组为 pending / in_progress / completed 三列。
     *
     * @param todos TodoItem 数组，每项含 content/status/active_form
     * @returns 看板字典，结构同后端 KanbanBoard.to_dict()
     */
    _buildBoardFromTodos(todos) {
        const safe = Array.isArray(todos) ? todos : [];
        const pending = safe.filter(t => t.status === 'pending');
        const inProgress = safe.filter(t => t.status === 'in_progress');
        const completed = safe.filter(t => t.status === 'completed');
        const total = safe.length;
        const columns = [
            { id: 'pending', title: '待办', cards: pending, count: pending.length },
            { id: 'in_progress', title: '进行中', cards: inProgress, count: inProgress.length },
            { id: 'completed', title: '已完成', cards: completed, count: completed.length },
        ];
        return {
            stats: {
                total,
                pending: pending.length,
                in_progress: inProgress.length,
                completed: completed.length,
                completion_rate: total > 0 ? Math.round((completed.length / total) * 10000) / 10000 : 0,
            },
            columns,
        };
    },

    // ===== Phase 24: Telemetry 事件查看器 =====

    /**
     * 在输入区注入 Telemetry 按钮 — Phase 24 新增
     */
    _injectTelemetryButton() {
        const inputRow = document.querySelector('.chat-input-row');
        if (!inputRow) return;
        if (document.getElementById('telemetry-btn')) return;
        const btn = document.createElement('button');
        btn.id = 'telemetry-btn';
        btn.className = 'telemetry-toggle-btn';
        btn.title = '查看遥测事件';
        btn.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M2 12h3l3-8 4 16 3-8h3"/></svg>';
        btn.onclick = () => this._toggleTelemetryPanel();
        // 插入到看板按钮后面
        const kanbanBtn = document.getElementById('kanban-btn');
        if (kanbanBtn) {
            kanbanBtn.parentNode.insertBefore(btn, kanbanBtn.nextSibling);
        } else {
            const checkpointBtn = document.getElementById('checkpoint-btn');
            if (checkpointBtn) {
                checkpointBtn.parentNode.insertBefore(btn, checkpointBtn.nextSibling);
            } else {
                inputRow.insertBefore(btn, inputRow.firstChild);
            }
        }
    },

    /**
     * 切换 Telemetry 面板的显示 — Phase 24 新增
     */
    async _toggleTelemetryPanel() {
        const panel = document.getElementById('telemetry-panel');
        if (panel) {
            panel.remove();
            return;
        }
        await this._showTelemetryPanel();
    },

    /**
     * 显示 Telemetry 面板 — Phase 24 新增
     *
     * 从后端获取最近的遥测事件，渲染为事件流面板。
     * 支持按会话过滤，按类型着色区分。
     */
    async _showTelemetryPanel() {
        const panel = document.createElement('div');
        panel.id = 'telemetry-panel';
        panel.className = 'telemetry-panel';
        panel.innerHTML = '<div class="telemetry-empty">加载事件...</div>';
        document.body.appendChild(panel);

        await this._loadTelemetryEvents(panel);
    },

    async _loadTelemetryEvents(panel) {
        try {
            const sessionId = this.currentConvId || '';
            const url = `/api/chat/telemetry/events?limit=100` +
                (sessionId ? `&session_id=${encodeURIComponent(sessionId)}` : '');
            const resp = await fetch(url);
            const data = await resp.json();
            if (data.status !== 'ok') {
                panel.innerHTML = `<div class="telemetry-empty">${this.esc(data.message || '获取事件失败')}</div>`;
                return;
            }
            const events = data.events || [];
            if (events.length === 0) {
                panel.innerHTML = `
                    <div class="telemetry-panel-header">
                        <span>遥测事件</span>
                        <button class="telemetry-refresh-btn" onclick="AI_CHAT._refreshTelemetry()">刷新</button>
                        <button class="kanban-close" onclick="AI_CHAT._toggleTelemetryPanel()">&times;</button>
                    </div>
                    <div class="telemetry-empty">暂无事件（agent 运行后会产生事件）</div>`;
                return;
            }
            const eventsHtml = events.map(ev => {
                const time = new Date(ev.ts).toLocaleTimeString('zh-CN');
                let propsStr = '';
                try {
                    propsStr = JSON.stringify(ev.properties || {}, null, 2);
                } catch(e) { propsStr = String(ev.properties || ''); }
                return `<div class="telemetry-event">
                    <div class="telemetry-event-header">
                        <span class="telemetry-event-type" data-event="${this.esc(ev.event)}">${this.esc(ev.event)}</span>
                        <span class="telemetry-event-time">${this.esc(time)}</span>
                    </div>
                    <div class="telemetry-event-props">${this.esc(propsStr)}</div>
                </div>`;
            }).join('');
            panel.innerHTML = `
                <div class="telemetry-panel-header">
                    <span>遥测事件 (${events.length})</span>
                    <button class="telemetry-refresh-btn" onclick="AI_CHAT._refreshTelemetry()">刷新</button>
                    <button class="kanban-close" onclick="AI_CHAT._toggleTelemetryPanel()">&times;</button>
                </div>
                <div class="telemetry-events">${eventsHtml}</div>`;
        } catch(err) {
            panel.innerHTML = `<div class="telemetry-empty">获取事件失败: ${this.esc(err.message)}</div>`;
        }
    },

    async _refreshTelemetry() {
        const panel = document.getElementById('telemetry-panel');
        if (panel) {
            panel.innerHTML = '<div class="telemetry-empty">刷新中...</div>';
            await this._loadTelemetryEvents(panel);
        }
    },

    // ===== Phase 21: 检查点管理 =====

    /**
     * 在输入区注入检查点按钮 — Phase 21 新增
     *
     * 动态在输入行添加"检查点"按钮，点击后显示当前会话的所有检查点。
     * 不修改 HTML 模板，通过 JS 动态注入。
     */
    _injectCheckpointButton() {
        const inputRow = document.querySelector('.chat-input-row');
        if (!inputRow) return;
        // 避免重复注入
        if (document.getElementById('checkpoint-btn')) return;
        const btn = document.createElement('button');
        btn.id = 'checkpoint-btn';
        btn.className = 'checkpoint-toggle-btn';
        btn.title = '查看检查点并回滚';
        btn.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M10 2v6"/><circle cx="10" cy="12" r="6"/><path d="M10 9v3l2 2"/></svg>';
        btn.onclick = () => this._toggleCheckpointPanel();
        // 插入到输入框前面
        inputRow.insertBefore(btn, inputRow.firstChild);
    },

    /**
     * 切换检查点面板的显示 — Phase 21 新增
     */
    async _toggleCheckpointPanel() {
        const panel = document.getElementById('checkpoint-panel');
        if (panel) {
            // 面板已存在，切换显示/隐藏
            panel.remove();
            return;
        }
        // 创建并显示面板
        await this._showCheckpointPanel();
    },

    /**
     * 显示检查点面板 — Phase 21 新增
     *
     * 从后端获取当前会话的检查点列表，渲染为浮动面板。
     * 每个检查点显示工具名、时间、描述，并提供"回滚"按钮。
     */
    async _showCheckpointPanel() {
        if (!this.currentConvId) {
            App.toast('请先选择一个对话', 'warn');
            return;
        }

        // 创建面板容器
        const panel = document.createElement('div');
        panel.id = 'checkpoint-panel';
        panel.className = 'checkpoint-panel';

        // 加载状态
        panel.innerHTML = '<div class="checkpoint-loading">加载检查点...</div>';
        document.body.appendChild(panel);

        // 从后端获取检查点列表
        try {
            const resp = await fetch(`/api/chat/checkpoints?session_id=${encodeURIComponent(this.currentConvId)}`);
            const data = await resp.json();
            if (data.status !== 'ok') {
                panel.innerHTML = `<div class="checkpoint-error">${this.esc(data.message || '获取检查点失败')}</div>`;
                return;
            }
            const checkpoints = data.checkpoints || [];
            if (checkpoints.length === 0) {
                panel.innerHTML = '<div class="checkpoint-empty">暂无检查点（写工具执行后自动创建）</div>';
            } else {
                // 按时间倒序显示（最新的在前）
                const items = checkpoints.slice().reverse().map(cp => {
                    const time = new Date(cp.created_at).toLocaleString('zh-CN');
                    const friendlyName = { file_write: '写入文件', editor: '行级编辑',
                        apply_patch: '应用补丁', run_commands: '执行命令' };
                    const displayName = friendlyName[cp.tool_name] || cp.tool_name;
                    return `<div class="checkpoint-item">
                        <div class="checkpoint-item-header">
                            <span class="checkpoint-tool">${this.esc(displayName)}</span>
                            <span class="checkpoint-time">${this.esc(time)}</span>
                        </div>
                        <div class="checkpoint-desc">${this.esc(cp.description || '')}</div>
                        <div class="checkpoint-actions">
                            <button class="cp-action-btn cp-diff-btn" onclick="AI_CHAT._showDiffModal('${this.esc(cp.checkpoint_id)}')">对比差异</button>
                            <button class="cp-action-btn cp-rollback-msg-btn" onclick="AI_CHAT._rollbackMessagesOnly('${this.esc(cp.checkpoint_id)}')">仅消息回滚</button>
                            <button class="cp-action-btn cp-rollback-file-btn" onclick="AI_CHAT._rollbackFileForCp('${this.esc(cp.checkpoint_id)}')">文件回滚</button>
                            <button class="checkpoint-rollback-btn" onclick="AI_CHAT._rollbackToCheckpoint('${this.esc(cp.checkpoint_id)}')">完整回滚</button>
                        </div>
                    </div>`;
                }).join('');
                panel.innerHTML = `<div class="checkpoint-panel-header">
                    <span>检查点 (${checkpoints.length})</span>
                    <button class="cp-tab-btn" onclick="AI_CHAT._showFileCheckpoints()">文件快照</button>
                    <button class="checkpoint-close" onclick="AI_CHAT._toggleCheckpointPanel()">&times;</button>
                </div>
                <div class="checkpoint-list">${items}</div>`;
            }
        } catch(err) {
            panel.innerHTML = `<div class="checkpoint-error">获取检查点失败: ${this.esc(err.message)}</div>`;
        }
    },

    /**
     * 显示检查点 diff 对比 — P2-23 新增
     *
     * 对接 GET /api/chat/diff_checkpoint，展示目标检查点与前一检查点之间的消息差异。
     * 对标 Cline checkpoint diff 对比视图。
     */
    async _showDiffModal(checkpointId) {
        // 移除已有模态框
        const existing = document.getElementById('cp-diff-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'cp-diff-modal';
        modal.className = 'cp-diff-modal';
        modal.innerHTML = '<div class="cp-diff-loading">加载 diff...</div>';
        document.body.appendChild(modal);

        try {
            const resp = await fetch(`/api/chat/diff_checkpoint?checkpoint_id=${encodeURIComponent(checkpointId)}`);
            const data = await resp.json();
            if (data.status !== 'ok') {
                modal.innerHTML = `<div class="cp-diff-body">
                    <div class="cp-diff-header">
                        <span>检查点差异对比</span>
                        <button class="checkpoint-close" onclick="AI_CHAT._closeDiffModal()">&times;</button>
                    </div>
                    <div class="checkpoint-error">${this.esc(data.message || '获取 diff 失败')}</div>
                </div>`;
                return;
            }
            const diff = data.diff || {};
            const added = diff.added || [];
            const removed = diff.removed || [];
            const stats = diff.stats || {};
            const addedHtml = added.map(m => this._renderDiffMessage(m, 'added')).join('');
            const removedHtml = removed.map(m => this._renderDiffMessage(m, 'removed')).join('');
            modal.innerHTML = `<div class="cp-diff-body">
                <div class="cp-diff-header">
                    <span>检查点差异对比</span>
                    <button class="checkpoint-close" onclick="AI_CHAT._closeDiffModal()">&times;</button>
                </div>
                <div class="cp-diff-stats">
                    <span class="diff-stat-added">新增 ${added.length}</span>
                    <span class="diff-stat-removed">移除 ${removed.length}</span>
                    ${stats.base_checkpoint ? `<span class="diff-stat-base">基准: ${this.esc(stats.base_checkpoint)}</span>` : ''}
                </div>
                <div class="cp-diff-content">
                    <div class="cp-diff-section">
                        <div class="cp-diff-section-title diff-added-title">新增消息 (+${added.length})</div>
                        <div class="cp-diff-messages">${addedHtml || '<div class="cp-diff-empty">无新增</div>'}</div>
                    </div>
                    <div class="cp-diff-section">
                        <div class="cp-diff-section-title diff-removed-title">移除消息 (-${removed.length})</div>
                        <div class="cp-diff-messages">${removedHtml || '<div class="cp-diff-empty">无移除</div>'}</div>
                    </div>
                </div>
            </div>`;
        } catch(err) {
            modal.innerHTML = `<div class="cp-diff-body">
                <div class="cp-diff-header">
                    <span>检查点差异对比</span>
                    <button class="checkpoint-close" onclick="AI_CHAT._closeDiffModal()">&times;</button>
                </div>
                <div class="checkpoint-error">获取 diff 失败: ${this.esc(err.message)}</div>
            </div>`;
        }
    },

    /** 渲染单条 diff 消息 */
    _renderDiffMessage(msg, kind) {
        const role = msg.role || 'unknown';
        const content = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content || '');
        const cls = kind === 'added' ? 'diff-msg-added' : 'diff-msg-removed';
        const sign = kind === 'added' ? '+' : '-';
        return `<div class="cp-diff-msg ${cls}">
            <span class="diff-msg-sign">${sign}</span>
            <span class="diff-msg-role">${this.esc(role)}</span>
            <span class="diff-msg-content">${this.esc(this.truncate(content, 300))}</span>
        </div>`;
    },

    /** 关闭 diff 模态框 */
    _closeDiffModal() {
        const modal = document.getElementById('cp-diff-modal');
        if (modal) modal.remove();
    },

    /**
     * 仅回滚消息历史 — 对标 Cline ClineCheckpointRestore = "task" 模式
     *
     * 对接 POST /api/chat/rollback_messages_only，仅恢复会话消息，
     * 不触动工作区文件，不删除后续检查点。
     */
    async _rollbackMessagesOnly(checkpointId) {
        if (!this.currentConvId) return;
        if (!confirm('确定仅回滚消息吗？\n\n仅消息回滚：\n- 会话消息恢复到该检查点状态\n- 工作区文件变更保留\n- 检查点不会被删除，可再次回滚')) return;

        try {
            const resp = await fetch('/api/chat/rollback_messages_only', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.currentConvId,
                    checkpoint_id: checkpointId,
                }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                const panel = document.getElementById('checkpoint-panel');
                if (panel) panel.remove();
                this._showToast(data.message || '已仅回滚消息');
                this.renderMessages();
            } else {
                App.toast('仅消息回滚失败: ' + (data.message || '未知错误'), 'danger');
            }
        } catch(err) {
            App.toast('仅消息回滚请求失败: ' + err.message, 'danger');
        }
    },

    /**
     * 文件回滚 — 根据消息检查点的 tool_call_id 查找对应文件 checkpoint 并回滚
     *
     * 对接 POST /api/chat/rollback_file，仅还原工作区文件，不影响会话消息。
     * 先通过 GET /api/chat/file_checkpoints 查找匹配的文件检查点。
     */
    async _rollbackFileForCp(checkpointId) {
        if (!this.currentConvId) return;
        // 先获取消息检查点详情，找到 tool_call_id
        // 这里简化处理：直接调用 /rollback_file，后端会根据 checkpoint_id 查找
        if (!confirm('确定回滚文件状态吗？\n\n文件回滚：\n- 工作区文件还原到该检查点状态\n- 会话消息历史不变\n- 仅在 git 仓库内有效')) return;

        try {
            const resp = await fetch('/api/chat/rollback_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.currentConvId,
                    checkpoint_id: checkpointId,
                }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                this._showToast(data.message || '已回滚文件状态');
            } else {
                App.toast('文件回滚失败: ' + (data.message || '未知错误'), 'danger');
            }
        } catch(err) {
            App.toast('文件回滚请求失败: ' + err.message, 'danger');
        }
    },

    /**
     * 显示文件检查点列表 — Phase 33.2 新增
     *
     * 对接 GET /api/chat/file_checkpoints，展示工作区文件状态快照。
     * 点击单条可执行文件回滚（POST /api/chat/rollback_file）。
     */
    async _showFileCheckpoints() {
        const panel = document.getElementById('checkpoint-panel');
        if (!panel) return;
        if (!this.currentConvId) {
            App.toast('请先选择一个对话', 'warn');
            return;
        }
        panel.innerHTML = '<div class="checkpoint-loading">加载文件快照...</div>';
        try {
            const resp = await fetch(`/api/chat/file_checkpoints?session_id=${encodeURIComponent(this.currentConvId)}`);
            const data = await resp.json();
            if (data.status !== 'ok') {
                panel.innerHTML = `<div class="checkpoint-error">${this.esc(data.message || '获取文件快照失败')}</div>`;
                return;
            }
            const cps = data.checkpoints || [];
            if (cps.length === 0) {
                panel.innerHTML = `<div class="checkpoint-panel-header">
                    <span>文件快照 (0)</span>
                    <button class="cp-tab-btn" onclick="AI_CHAT._showCheckpointPanel()">消息检查点</button>
                    <button class="checkpoint-close" onclick="AI_CHAT._toggleCheckpointPanel()">&times;</button>
                </div>
                <div class="checkpoint-empty">暂无文件快照（启用 AGENT_ENABLE_FILE_CHECKPOINT 后自动创建）</div>`;
                return;
            }
            const items = cps.slice().reverse().map(cp => {
                const time = new Date(cp.created_at).toLocaleString('zh-CN');
                const files = (cp.file_paths || []).map(f => `<span class="cp-file-path">${this.esc(f)}</span>`).join('');
                return `<div class="checkpoint-item">
                    <div class="checkpoint-item-header">
                        <span class="checkpoint-tool">${this.esc(cp.tool_name || '-')}</span>
                        <span class="checkpoint-time">${this.esc(time)}</span>
                    </div>
                    <div class="checkpoint-desc">${this.esc(cp.description || '')}</div>
                    <div class="cp-files">${files || '<span class="empty-hint">无文件</span>'}</div>
                    <div class="checkpoint-actions">
                        <button class="cp-action-btn cp-rollback-file-btn" onclick="AI_CHAT._rollbackFileByCpId('${this.esc(cp.checkpoint_id)}')">回滚文件</button>
                    </div>
                </div>`;
            }).join('');
            panel.innerHTML = `<div class="checkpoint-panel-header">
                <span>文件快照 (${cps.length})</span>
                <button class="cp-tab-btn" onclick="AI_CHAT._showCheckpointPanel()">消息检查点</button>
                <button class="checkpoint-close" onclick="AI_CHAT._toggleCheckpointPanel()">&times;</button>
            </div>
            <div class="checkpoint-list">${items}</div>`;
        } catch(err) {
            panel.innerHTML = `<div class="checkpoint-error">获取文件快照失败: ${this.esc(err.message)}</div>`;
        }
    },

    /** 按文件 checkpoint_id 回滚文件 */
    async _rollbackFileByCpId(checkpointId) {
        if (!this.currentConvId) return;
        if (!confirm('确定回滚文件状态到此快照吗？工作区文件将被还原，会话消息不变。')) return;
        try {
            const resp = await fetch('/api/chat/rollback_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.currentConvId,
                    checkpoint_id: checkpointId,
                }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                this._showToast(data.message || '已回滚文件状态');
                this._showFileCheckpoints();
            } else {
                App.toast('文件回滚失败: ' + (data.message || '未知错误'), 'danger');
            }
        } catch(err) {
            App.toast('文件回滚请求失败: ' + err.message, 'danger');
        }
    },

    /**
     * 回滚到检查点 — Phase 21 新增
     *
     * 调用后端 /api/chat/rollback 恢复会话状态。
     * 回滚后前端重新加载会话消息。
     */
    async _rollbackToCheckpoint(checkpointId) {
        if (!this.currentConvId) return;
        if (!confirm('确定回滚到此检查点吗？这将丢弃该工具执行后的所有操作。')) return;

        try {
            const resp = await fetch('/api/chat/rollback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.currentConvId,
                    checkpoint_id: checkpointId,
                }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                // 关闭检查点面板
                const panel = document.getElementById('checkpoint-panel');
                if (panel) panel.remove();
                // 提示用户
                App.toast(data.message + '\n\n注意：前端对话记录保持不变，但后端 agent 上下文已回滚。下次对话将从回滚点继续。', 'success');
            } else {
                App.toast('回滚失败: ' + (data.message || '未知错误'), 'danger');
            }
        } catch(err) {
            App.toast('回滚请求失败: ' + err.message, 'danger');
        }
    },

    // ===== 工具函数 =====
    esc(text) {
        const d = document.createElement('div');
        d.textContent = text || '';
        return d.innerHTML;
    },
    truncate(text, max) {
        const s = String(text || '');
        return s.length > max ? s.substring(0, max) + '...' : s;
    },

    phaseIcon(phase) {
        const m = { planning: 'plan', executing: 'plan', thinking: 'think', answering: 'answer' };
        return this.toolSvg(m[phase] || 'think');
    },
    phaseLabel(phase) {
        const m = { planning: '制定计划中...', executing: '按计划执行', thinking: '思考分析', answering: '生成回答' };
        return m[phase] || phase;
    },

    /** 渲染计划清单 */
    renderPlanBlock(b) {
        const steps = b.steps;
        if (steps && steps.length > 0) {
            const items = steps.map((s, i) => {
                const icon = s.status === 'done' ? 'check' : 'circle';
                return `<li class="plan-step plan-${s.status}">
                    <span class="plan-step-icon">${this._stepIcon(icon)}</span>
                    <span class="plan-step-text">${this.esc(s.text)}</span>
                </li>`;
            }).join('');
            const isOpen = b.expanded !== false ? 'open' : '';
            return `<details class="block-plan" ${isOpen}>
                <summary><span class="plan-title">执行计划</span></summary>
                <ol class="plan-steps">${items}</ol>
            </details>`;
        }
        // fallback: 显示原始文本
        return `<details class="block-plan block-plan-raw" ${b.expanded !== false ? 'open' : ''}>
            <summary><span class="plan-title">执行计划</span></summary>
            ${this.markdown(b.text || '')}
        </details>`;
    },

    _stepIcon(name) {
        if (name === 'check') return '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="6" fill="#10b981" stroke="#059669" stroke-width="1"/><path d="M5 8l2 2 4-4" stroke="#fff" stroke-width="1.5" fill="none"/></svg>';
        return '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="5" fill="none" stroke="#9ca3af" stroke-width="1.5"/></svg>';
    },

    toolSvg(name) {
        const svgs = {
            search: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><circle cx="8.5" cy="8.5" r="5.5"/><line x1="13" y1="13" x2="18" y2="18"/></svg>',
            globe: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><circle cx="10" cy="10" r="8"/><ellipse cx="10" cy="10" rx="3" ry="8"/><line x1="2" y1="10" x2="18" y2="10"/></svg>',
            terminal: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M3 5l4 4-4 4"/><line x1="9" y1="13" x2="17" y2="13"/></svg>',
            file: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M6 2h6l4 4v12H6z"/><line x1="6" y1="8" x2="14" y2="8"/><line x1="6" y1="12" x2="14" y2="12"/></svg>',
            edit: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M13 3l4 4L7 17H3v-4z"/></svg>',
            folder: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M2 5a1 1 0 011-1h4l2 2h7a1 1 0 011 1v8a1 1 0 01-1 1H3a1 1 0 01-1-1z"/></svg>',
            wrench: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M14 6a5 5 0 00-8 4l-4 6 6-1 5-5a5 5 0 001-4z"/></svg>',
            skill: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M10 2l2.5 5 5.5.8-4 3.9.9 5.5L10 15l-4.9 2.6.9-5.5-4-3.9 5.5-.8z"/></svg>',
            plan: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><rect x="3" y="3" width="5" height="5" rx="1"/><rect x="12" y="3" width="5" height="5" rx="1"/><rect x="3" y="12" width="5" height="5" rx="1"/><rect x="12" y="12" width="5" height="5" rx="1"/></svg>',
            think: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><circle cx="10" cy="10" r="8"/><line x1="10" y1="6" x2="10" y2="10"/><line x1="10" y1="14" x2="10.01" y2="14"/></svg>',
            answer: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M3 5h14a1 1 0 011 1v8a1 1 0 01-1 1H9l-4 3V5z"/></svg>',
            question: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><circle cx="10" cy="10" r="8"/><path d="M7 8c0-2 1.5-3 3-3s3 1 3 3c0 2-3 3-3 5v1"/><line x1="10" y1="17" x2="10.01" y2="17"/></svg>',
        };
        return svgs[name] || svgs.wrench;
    },

    /** Markdown 渲染 — 使用 marked.js 完整解析

    支持 GFM 表格、列表、代码块、引用、分隔线、链接、加粗等。
    所有答案块统一走此函数，确保研报内容排版专业。
    */
    markdown(text) {
        if (!text) return '';
        try {
            return marked.parse(text, {
                gfm: true,
                breaks: false,
                headerIds: false,
                mangle: false,
            });
        } catch (e) {
            console.error('markdown parse error:', e);
            return '<p>' + this.esc(text) + '</p>';
        }
    },
};

document.addEventListener('DOMContentLoaded', () => AI_CHAT.init());
