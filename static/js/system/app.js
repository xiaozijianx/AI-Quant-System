// system 页面 Alpine 逻辑 (Stage 4: 健康检查 + 调度器两组件合并为单一 systemApp)
function systemApp() {
    return {
        showHelp: false,
        // ---- 健康检查 ----
        health: null,
        checking: false,
        // ---- 定时任务 (调度器) ----
        jobs: [],
        heartbeat: { online: false },
        saving: false,
        controlling: false,
        // 注意：init 不再自动调 check()，避免 health 接口里的 xtdata 连接阻塞页面首次渲染
        async init() {
            // 调度器配置/在线状态仅在"定时任务"卡片仍展示，故仍在根组件加载
            await this.load();
            // 每 10 秒刷新一次在线状态
            setInterval(() => this.load(), 10000);
        },
        async check() {
            this.checking = true;
            try {
                this.health = await App.get('/api/system/health');
            } catch (e) {
                console.error('健康检查失败:', e);
                this.health = [{item: '健康检查', value: '请求失败: ' + e.message, status: 'ERROR'}];
            }
            this.checking = false;
        },
        async load() {
            try {
                const data = await App.get('/api/system/scheduler/config');
                this.jobs = data.jobs || [];
                this.heartbeat = data.heartbeat || { online: false };
            } catch (e) {
                console.error('加载调度器配置失败:', e);
            }
        },
        async toggle(job) {
            this.saving = true;
            const enabled = !job.enabled;
            try {
                const payload = {};
                payload[job.enabled_by] = enabled;
                await App.post('/api/system/scheduler/config', payload);
                job.enabled = enabled;
            } catch (e) {
                console.error('保存调度器配置失败:', e);
                App.toast('保存失败: ' + e.message, 'danger');
            } finally {
                this.saving = false;
            }
        },
        async control(action) {
            this.controlling = true;
            try {
                const data = await App.post('/api/system/scheduler/control?action=' + action, {});
                if (data.ok) {
                    await this.load();
                } else {
                    App.toast('操作失败: ' + (data.error || '未知错误'), 'danger');
                }
            } catch (e) {
                console.error('scheduler 控制失败:', e);
                App.toast('操作失败: ' + e.message, 'danger');
            } finally {
                this.controlling = false;
            }
        },
    }
}