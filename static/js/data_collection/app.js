function dataCollectionApp() {
    return {
        jobs: [],
        groups: [],
        logs: [],
        running: false,
        stopping: false,
        currentJob: null,
        currentJobName: '',
        lastStatus: 'idle',
        startTime: null,
        elapsedFmt: '0s',
        pollTimer: null,
        es: null,
        maxDisplayLogs: 300,   // 页面最多渲染 300 条日志, 防止 DOM 过大卡顿

        async init() {
            await this.loadJobs();
            await this.restoreStatus();
            // 轮询: 更新运行状态和日志(页面切换后恢复用), 5 秒一次足够
            this.pollTimer = setInterval(() => this.tick(), 5000);
            // 每秒更新已运行时间
            setInterval(() => {
                if (this.running && this.startTime) {
                    const sec = Math.floor((Date.now() - this.startTime) / 1000);
                    this.elapsedFmt = sec + 's';
                }
            }, 1000);
        },

        async loadJobs() {
            try {
                const data = await App.get('/api/data-collection/jobs');
                this.jobs = data.jobs || [];
                this.groups = data.groups || [];
            } catch (e) {
                console.error('加载任务失败:', e);
            }
        },

        async restoreStatus() {
            // 页面切换回来后, 从后端恢复当前运行状态和最近日志
            try {
                const data = await App.get('/api/data-collection/status');
                if (data.running && data.job_id) {
                    this.running = true;
                    this.currentJob = data.job_id;
                    this.currentJobName = data.job_name || '';
                    this.startTime = data.start_time ? data.start_time * 1000 : Date.now();
                    this.logs = data.logs || [];
                    this.lastStatus = 'running';
                } else if ((data.logs || []).length > 0) {
                    // 任务已结束但保留最近日志, 方便查看
                    this.logs = data.logs || [];
                    this.lastStatus = data.last_status || 'idle';
                }
            } catch (e) {
                console.error('恢复状态失败:', e);
            }
        },

        async tick() {
            // 如果当前有活跃 SSE 连接, 只检查 running 状态, 不重复更新日志
            const sseActive = this.es && this.es.readyState === EventSource.OPEN;
            try {
                const data = await App.get('/api/data-collection/status');
                if (data.running && data.job_id) {
                    this.running = true;
                    this.currentJob = data.job_id;
                    this.currentJobName = data.job_name || '';
                    this.startTime = data.start_time ? data.start_time * 1000 : Date.now();
                    if (!sseActive) {
                        this.logs = data.logs || [];
                    }
                    this.lastStatus = 'running';
                } else {
                    if (this.running) {
                        // 任务已结束
                        this.running = false;
                        this.currentJob = null;
                        this.currentJobName = '';
                        this.lastStatus = data.last_status || 'idle';
                        if (!sseActive) {
                            this.logs = data.logs || [];
                        }
                        this.loadJobs(); // 刷新历史时间
                    }
                }
            } catch (e) {
                console.error('轮询状态失败:', e);
            }
        },

        formatTime(iso) {
            if (!iso) return '从未';
            const d = new Date(iso);
            return d.toLocaleString('zh-CN', {
                month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit'
            });
        },

        lineClass(line) {
            if (line.type === 'error') return 'text-red-400';
            if (line.type === 'success') return 'text-green-400';
            if (line.type === 'start') return 'text-purple-400';
            return 'text-gray-300';
        },

        run(job) {
            if (this.running) {
                App.toast('已有任务在运行，请等待完成', 'warn');
                return;
            }
            this.startStream(`/api/data-collection/stream?job_id=${job.id}`, job.id, job.name);
        },

        runGroup(group) {
            if (this.running) {
                App.toast('已有任务在运行，请等待完成', 'warn');
                return;
            }
            this.startStream(`/api/data-collection/stream?group_id=${group.id}`, group.id, group.name);
        },

        // 一键执行按钮配色: 基础/扩展/全部 使用不同颜色区分
        groupBtnClass(group) {
            if (group.id === 'basic') return 'btn-success';
            if (group.id === 'aux') return 'btn-warning';
            return 'btn-primary';
        },

        // 通用 SSE 执行入口: 单任务与任务组共用一套日志/状态处理逻辑
        startStream(url, id, name) {
            this.running = true;
            this.currentJob = id;
            this.currentJobName = name;
            this.lastStatus = 'running';
            this.logs = [];
            this.startTime = Date.now();
            this.elapsedFmt = '0s';

            const es = new EventSource(url);
            this.es = es;

            es.addEventListener('start', (e) => {
                const data = JSON.parse(e.data);
                this.logs.push({
                    time: new Date().toLocaleTimeString('zh-CN'),
                    text: `开始执行: ${data.job_name}`,
                    type: 'start'
                });
                this.scrollLog();
            });

            es.addEventListener('log', (e) => {
                const data = JSON.parse(e.data);
                // 后端 80ms 时间窗合并: data 可能是数组(多条 stdout)或单条字符串
                const lines = Array.isArray(data) ? data : [data];
                for (const text of lines) {
                    this.logs.push({
                        time: new Date().toLocaleTimeString('zh-CN'),
                        text: text,
                        type: 'log'
                    });
                }
                this.scrollLog();
            });

            es.addEventListener('success', (e) => {
                const data = JSON.parse(e.data);
                this.lastStatus = 'success';
                // 任务组: data.job_name 为完成的子任务名, 显示更明确
                const msg = data.job_name
                    ? `完成: ${data.job_name}，耗时 ${data.elapsed}s`
                    : `执行成功，耗时 ${data.elapsed}s`;
                this.logs.push({
                    time: new Date().toLocaleTimeString('zh-CN'),
                    text: msg,
                    type: 'success'
                });
                this.scrollLog();
            });

            es.addEventListener('error', (e) => {
                let msg = '执行出错';
                try {
                    const data = JSON.parse(e.data);
                    msg = data.error || msg;
                } catch (_) {}
                this.lastStatus = 'error';
                this.logs.push({
                    time: new Date().toLocaleTimeString('zh-CN'),
                    text: msg,
                    type: 'error'
                });
                this.scrollLog();
            });

            es.addEventListener('done', () => {
                es.close();
                this.es = null;
                this.running = false;
                this.currentJob = null;
                this.loadJobs(); // 刷新历史时间
            });

            es.onerror = () => {
                es.close();
                this.es = null;
                if (this.running) {
                    this.running = false;
                    this.currentJob = null;
                    this.loadJobs();
                }
            };
        },

        async stopCurrentJob() {
            if (!confirm('确定要终止当前任务吗? 正在运行的脚本会被强制停止。')) {
                return;
            }
            this.stopping = true;
            try {
                const res = await App.post('/api/data-collection/stop');
                if (res.ok) {
                    this.logs.push({
                        time: new Date().toLocaleTimeString('zh-CN'),
                        text: res.message,
                        type: 'error'
                    });
                    this.scrollLog();
                    // 关闭 SSE, 等待轮询把最终状态同步下来
                    if (this.es) {
                        this.es.close();
                        this.es = null;
                    }
                } else {
                    App.toast(res.error || '终止失败', 'danger');
                }
            } catch (e) {
                console.error('停止任务失败:', e);
                App.toast('停止任务失败: ' + e.message, 'danger');
            } finally {
                this.stopping = false;
            }
        },

        scrollLog() {
            // 滚动节流: 高频日志时避免每次强制同步布局 (性能优化)
            if (this._scrollScheduled) return;
            this._scrollScheduled = true;
            this.$nextTick(() => {
                this._scrollScheduled = false;
                const box = this.$refs.logBox;
                if (box) box.scrollTop = box.scrollHeight;
            });
        }
    }
}
