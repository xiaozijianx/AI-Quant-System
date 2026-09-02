// RL 因子挖掘 Alpine.js 逻辑
window.factorRlMining = {
  // ---- RL 强化学习因子挖掘 (阶段6.1 独立引擎, 深度复刻 AlphaMaster) ----
  rlBatchSize: 192,
  rlTrainSteps: 2000,
  rlMaxLen: 8,
  rlLr: 0.001,
  rlEntropyMax: 1.0,
  rlRebalPeriod: 5,
  rlEliteSize: 60,
  rlEliteFrac: 0.25,
  rlMaxRestarts: 10,
  rlRestartNoise: 0.25,
  rlIcWeight: 1.0,
  rlIrWeight: 0.3,
  rlLayeredWeight: 0.2,
  rlParsimony: 0.001,
  rlCorrThresh: 0.8,
  rlReturnCandidates: 20,
  rlUseLord: true,
  rlTrainRatio: 0.7,
  rlValRatio: 0.15,
  rlRandomState: 42,
  rlNIslands: 1,
  rlMigInterval: 100,
  rlUseGpu: false,
  rlNFolds: 3,
  rlPermN: 0,
  rlResume: false,
  rlMining: false,
  rlResult: null,
  rlProgress: null,
  rlLiveCurve: [],
  rlRestartLog: [],
  rlShowAdvanced: false,

  async runRl() {
    this.rlMining = true;
    this.stopMiningWatcher('rl');
    this.rlResult = null;
    this.rlProgress = null;
    this.rlLiveCurve = [];
    this.rlRestartLog = [];
    try {
      const body = {
        start_date: this.startDate,
        end_date: this.endDate,
        batch_size: this.rlBatchSize,
        train_steps: this.rlTrainSteps,
        max_formula_len: this.rlMaxLen,
        lr: this.rlLr,
        entropy_coeff_max: this.rlEntropyMax,
        rebal_period: this.rlRebalPeriod,
        elite_pool_size: this.rlEliteSize,
        elite_replay_frac: this.rlEliteFrac,
        max_restarts: this.rlMaxRestarts,
        restart_noise: this.rlRestartNoise,
        reward_ic_weight: this.rlIcWeight,
        reward_ir_weight: this.rlIrWeight,
        reward_layered_weight: this.rlLayeredWeight,
        parsimony: this.rlParsimony,
        corr_thresh: this.rlCorrThresh,
        return_candidates: this.rlReturnCandidates,
        use_lord: this.rlUseLord,
        train_ratio: this.rlTrainRatio,
        val_ratio: this.rlValRatio,
        random_state: this.rlRandomState,
        n_islands: this.rlNIslands,
        migration_interval: this.rlMigInterval,
        use_gpu: this.rlUseGpu,
        n_folds: this.rlNFolds,
        perm_n: this.rlPermN,
        resume: this.rlResume,
      };
      if (this.poolType && this.poolType !== 'active' && this.poolRef) {
        body.pool_type = this.poolType;
        body.pool_ref = this.poolRef;
      } else if (this.stockCodes.length > 0) {
        body.stock_codes = this.stockCodes;
      }
      const r = await this.postSse('/api/factor/mine_rl/stream', body, (ev, data) => {
        if (!data) return;
        if (ev === 'progress') {
          this.rlProgress = data;
          if (!this.rlLiveCurve) this.rlLiveCurve = [];
          this.rlLiveCurve.push({step: data.step, best_score: data.best_score, avg_reward: data.avg_reward, entropy: data.entropy});
          this.$nextTick(() => this.drawRlCurve(this.rlLiveCurve));
        } else if (ev === 'restart') {
          this.rlRestartLog.push(data);
        }
      });
      this.rlResult = r;
      this.$nextTick(() => this.drawRlCurve(r.training_history || []));
    } catch (e) {
      this.showToast('RL挖掘失败: ' + e.message, 'error');
    } finally {
      this.rlMining = false;
      this.rlProgress = null;
    }
  },

  drawRlCurve(curve) {
    if (!curve || !curve.length) return;
    const el = document.getElementById('rl-training-chart');
    if (!el) return;
    const steps = curve.map(d => d.step ?? d.gen ?? 0);
    const data = [
      {type: 'scatter', x: steps, y: curve.map(d => d.best_score), name: 'best_score', mode: 'lines+markers', line: {color: '#3b82f6'}},
      {type: 'scatter', x: steps, y: curve.map(d => d.avg_reward), name: 'avg_reward', mode: 'lines+markers', line: {color: '#10b981'}},
      {type: 'scatter', x: steps, y: curve.map(d => d.entropy), name: 'entropy', mode: 'lines+markers', yaxis: 'y2', line: {color: '#f59e0b'}},
    ];
    const layout = {
      margin: {l: 50, r: 50, t: 10, b: 30},
      yaxis: {title: '得分'},
      yaxis2: {title: '熵', overlaying: 'y', side: 'right'},
      legend: {x: 0.7, y: 0.9},
      showlegend: true,
    };
    if (el.data) {
      Plotly.react('rl-training-chart', data, layout);
    } else {
      Plotly.newPlot('rl-training-chart', data, layout, {responsive: true});
    }
  },

  async rlSaveOne(c) {
    const factor_id = 'rl_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6);
    const desc = ['RL强化学习挖掘复合因子',
                  'RankIC=' + (c.rank_ic != null ? c.rank_ic.toFixed(4) : ''),
                  'ICIR=' + (c.rank_ic_ir != null ? c.rank_ic_ir.toFixed(4) : ''),
                  '方向=' + (c.direction === 1 ? '正向' : '反向'),
                  'OOS=' + (c.oos_ok ? '通过' : '未过'),
                  'WF=' + (c.wf_ok != null ? (c.wf_ok ? '通过' : '未过') : 'NA'),
                  'P值=' + (c.p_value != null ? c.p_value.toFixed(4) : 'NA')].join(' | ');
    const body = {
      factor_id,
      name: 'RL复合_' + c.expr.slice(0, 20),
      expression: c.expr,
      category: '复合',
      description: desc,
      direction: c.direction === -1 ? 'negative' : 'positive',
      is_custom: true,
    };
    try {
      await this.api('/api/factor/save', {method: 'POST', body: JSON.stringify(body)});
      this.showToast('已入库: ' + factor_id, 'success');
      this.loadFactors();
    } catch (e) {
      this.showToast('入库失败: ' + e.message, 'error');
    }
  },
};
