# AI 量化系统前后端全系统重构方案

> 版本：v1（待审阅）
> 前置：因子库页面已完成按层级重构（见《因子库页面架构重构计划.md》），并验证了
> "routes/<page>/ 包 + templates/<page>/ 子模板 + static/js/<page>/ 外置 JS"模式可行。
> 本方案将该模式推广到全系统，并解决各页面结构不统一、路由层肥胖、跨页面耦合问题。

***

## 一、背景与目标

### 1.1 现状痛点

1. **各页面分次实现，结构互不相同**：13 个业务页的前后端文件布局、业务逻辑归属位置各有各的写法
2. **路由层肥胖**：dragon\_review\.py 2204 行、live.py 1554 行、review\.py 1036 行，大量业务逻辑（SQL 拼装、KPI 计算、进程管理）写在路由文件里
3. **业务逻辑三种形态并存**：lib/、项目根目录散包（sector\_rotation/ 等 10 个）、路由层内联，无统一位置规则
4. **路由间横向耦合**：backtest.py、dragon.py 直接 `from routes.live import SIM_RUNNER`，屏蔽 live 路由会连带挂掉回测和龙头候选
5. **前端公共能力多套并存**：5 套 HTTP 封装、4 套通知、3 套流式解析、Plotly 双版本
6. **复制粘贴级重复**：sector\_rotation 与 concept\_rotation 前后端约 90% 相同
7. **加载冗余**：ai-chat.js（2911 行）+ ai-chat.css（1889 行）全站无条件加载

### 1.2 目标

1. 统一全系统前后端文件结构：按页面层级组织，页面之间低耦合
2. 屏蔽/删除任一页面（及其前后端文件），其他页面不受影响
3. 保留并强化最初的核心设计——**前后端分离**（API 契约不变，见第三节）
4. 异构大功能（agent、因子库、龙头复盘等）各有专属迁移路径，不一刀切
5. 后续新增功能按统一"四件套"模板接入（见第八节）

***

## 二、现状全景

### 2.1 页面 × 前后端映射（13 业务页 + 2 对话页）

| 页面                   | 路由前缀                  | 后端文件（行数）                              | 模板（行数）                      | 问题等级                |
| -------------------- | --------------------- | ------------------------------------- | --------------------------- | ------------------- |
| 实盘监控 live            | /api/live             | routes/live.py（1554）                  | live.html（3512，内联JS 1665）   | ⚠ 重度（sim/real 成对复制） |
| 回测 backtest          | /api/backtest         | routes/backtest.py（202）               | backtest.html（738）          | ✓ 薄，仅需归位            |
| 复盘&策略 review         | /api/review           | routes/review\.py（1036）               | review\.html（1318）          | ⚠ 重度                |
| 晨会 morning           | /api/morning          | routes/morning.py（443）                | morning.html（721）           | ⚠ 中度（SSE）           |
| 板块轮动 sector          | /api/sector-rotation  | routes/sector\_rotation.py（188）       | sector\_rotation.html（526）  | ⚠ 与 concept 重复      |
| 概念轮动 concept         | /api/concept-rotation | routes/concept\_rotation.py（189）      | concept\_rotation.html（541） | ⚠ 与 sector 重复       |
| 龙头复盘 dragon-review   | /api/dragon-review    | routes/dragon\_review\.py（2204）       | dragon\_review\.html（1135）  | ⚠ 最重                |
| 个股行情 stock-quote     | /api/stock-quote      | routes/stock\_quote.py（102）           | stock\_quote.html（569）      | ✓ 薄                 |
| 数据采集 data-collection | /api/data-collection  | routes/data\_collection.py（818）       | data\_collection.html（381）  | ⚠ 特殊（外部脚本）          |
| 交易计划 trade-plan      | /api/trade-plan       | routes/trade\_plan.py（367，页面+API 同文件） | trade\_plan.html（808）       | ⚠ 结构错位              |
| 因子库 factor           | /api/factor           | routes/factor/ 包 ✓                    | factor/ 子模板 ✓               | ✓ 已完成（范式样板）         |
| 系统状态 system          | /api/system           | routes/system.py（130）                 | system.html（222，两组件）        | 轻微                  |
| AI 助手 ai-chat        | /api/chat             | agent/server.py                       | ai-chat.html（178，不继承 base）  | ⚠ 特殊（异构子系统）         |
| 投研对话 chat            | /gradio-chat          | pages/tab1\_chat.py                   | chat.html（9，iframe 壳）       | 特殊（Gradio）          |

### 2.2 后端实际分层（三层混杂）

```
app.py            页面路由（12 个页面的 GET 路由集中于此；trade-plan 例外在自己路由文件里）
routes/           路由层 —— 6 个文件承载重业务逻辑（live/dragon_review/review/
                  data_collection/morning/dragon）
根目录子包/        sector_rotation/ concept_rotation/ dragon_strategy/ morning_brief/
                  attribution/ parameter_tuning/ strategy_lifecycle/ live_trading/
                  alerting/ ml_strategy/  ← 与 lib/ 平级，靠 sys.path 隐式解析，位置规则不统一
lib/              数据层 + 引擎层（30+ 模块：backtest_data、live_simulator、factor_* 等）
外部 CASE 目录     data_collection/scheduler 通过 subprocess 调用
                  （../CASE-数据采集与存储、../CASE-A3/A4/A5 数据准备目录）
```

### 2.3 跨页面交互现状（实测盘点）

**前端跨页 API 调用（合法形态，保留）**：

| 调用方页面                | 被调 API                                                                     | 用途            |
| -------------------- | -------------------------------------------------------------------------- | ------------- |
| live.html            | /api/dragon/candidates、/api/dragon/bind                                    | 龙头候选区 + 绑定监控池 |
| live.html            | /api/trade-plans、/api/trade-plan/{code}                                    | 交易计划入口/详情     |
| dragon\_review\.html | /api/sector-rotation/detail、/api/sector-rotation/sector-index              | 板块详情/板块指数图表   |
| morning.html         | /api/factor/packages                                                       | 晨会引用因子包       |
| trade\_plan.html     | /api/live/watch\_merge、/api/live/real/watch\_merge、/api/live/watch\_quotes | 监控池合并/行情      |
| quant\_gp.html       | /api/factor/stock\_pools                                                   | 因子挖掘用因子库的股票池  |

**后端横向耦合（非法形态，需切断）**：

| 调用方                                        | 被调                                                                 | 问题          |
| ------------------------------------------ | ------------------------------------------------------------------ | ----------- |
| routes/backtest.py、routes/dragon.py        | `from routes.live import SIM_RUNNER`                               | 删 live 路由即挂 |
| routes/live.py                             | routes/live 内部管理 execution\_mode yaml、miniQMT 连接缓存                 | 业务逻辑在路由层    |
| routes/review\.py                          | 动态 import 根目录 attribution/ parameter\_tuning/ strategy\_lifecycle/ | 位置规则不统一     |
| routes/morning.py                          | 动态 import 根目录 morning\_brief/                                      | 同上          |
| routes/dragon.py、routes/dragon\_review\.py | 动态 import 根目录 dragon\_strategy/、lib/stock\_intraday 等              | 同上          |

**agent（AI 助手）与其他页面的交互**：

| 交互               | 机制                                                          | 性质                    |
| ---------------- | ----------------------------------------------------------- | --------------------- |
| 全站 AI 侧栏（右栏）     | base.html include \_ai\_sidebar.html + 全站加载 ai-chat.js      | 前端 UI 层               |
| AI 信号授权下单        | agent 产生下单信号 → live 页面 /api/live/approvals 列表 → 用户批准 → 实盘执行 | 后端业务层（跨 agent 与 live） |
| agent skills 查数据 | skills 脚本直连共享 PostgreSQL（板块/概念/因子/持仓）                       | 数据层共享（天然解耦）           |
| 晨会 AI 工作流        | morning\_brief/graph.py 独立跑，与 agent 无直接依赖                   | 独立子系统                 |

***

## 三、设计原则：前后端分离的继承与强化

**原系统最初设计的核心逻辑是前后端分离，本方案完全保留并从三个层面强化：**

### 3.1 API 契约不变（分离的根基）

- 全部现有 URL 前缀、路径、请求/响应结构**保持不变**（`/api/live/*`、`/api/factor/*` 等）

- 前端重构只做文件重组（模板拆分 + JS 外置），不改任何 fetch 目标

- 后端重构只做文件搬移与分层下沉，路由 handler 的对外行为不变

- 收益：重构前后可用同一套请求做回归验证；已保存的页面状态（page-settings namespace）不受影响

### 3.2 后端纵向分层（分离的深化）

```
路由层 routes/<page>/     只做：解析请求 → 调 service → _json_safe_response 返回
                          约束：单文件 ≤200 行，禁止 import 其他页面的路由
业务层 services/<page>/   页面专属业务逻辑（矩阵构建、KPI 计算、进程管理、SSE 编排）
                          约束：只被本页路由 import；跨页共享的能力下沉 lib/
公共层 lib/               跨页面共享的数据层/引擎（backtest_data、live_simulator、
                          factor_*、stock_utils 等已有的就保留）
```

- 前端只面对路由层；service/lib 的任何内部重构不影响 API 契约——这是解耦的实质

- 现有 `from routes.live import SIM_RUNNER` 改为 `from lib.live_simulator import SIM_RUNNER`：
  单例归属引擎层，路由只是它的 API 门面

### 3.3 前端结构与后端同构（分离的对称性）

```
templates/<page>/index.html   页面壳（x-data、Tab 结构）+ 子块模板
static/js/<page>/app.js       页面逻辑（window.<page>App 展开合并进根组件，Alpine 骨架不变）
```

- 模板只含结构与数据绑定，逻辑全部在 JS 文件——前后端各自可独立演进

- Jinja 仅做页面组装（include），不在模板里写业务

***

## 四、异构大功能与跨页面交互的设计

### 4.1 三大异构功能的专属迁移路径

三个大功能性质差异大，不套用同一刀切模板，各自定制：

**（1）agent（AI 助手子系统）——保持独立，只收编外壳**

- `agent/`（server、skills、providers、memory、cron）是自洽子系统，自带 router（/api/chat/\*），**结构不动**

- 收编项：ai-chat.html 改为继承 base.html（消除手工复制的 70 行导航）；ai-chat.js/ai-settings.js/ai-chat.css 改为仅 ai-chat 相关页面按需加载（base.html 条件 block），其他页面不再背 4800 行

- chat.html（Gradio iframe 壳）保留现状——Gradio 自成体系，强行统一成本大于收益

- AI 信号授权链路（agent → /api/live/approvals → 实盘）：保持"live 路由提供授权 API、agent 写信号、用户在 live 页批准"的现有交互，仅把 live 路由里的授权实现下沉到 services/live/

**（2）因子库（factor + quantgp）——已完成，作为范式**

- routes/factor/ 包 + templates/factor/ 子模板 + static/js/factor/mining/rl.js 已就位

- quant\_gp 路由（/api/factor/quantgp/\*）在迁移期保留独立文件，后续并入 routes/factor/mining/（与 gp/rl/llm\_gp/svd/ml 并列，统一为因子挖掘子 Tab 专属路由）

- 后续其余页面迁移全部复制本页已验证的模式（含 `window.xxxApp` 展开合并、script 先于 Alpine 加载等细节）

**（3）龙头复盘（dragon-review）——路由层瘦身专项**

- 现状 2204 行路由（4 个端点 + \~2000 行业务逻辑），是最典型的"路由层肥胖症"

- 迁移：routes/dragon\_review/（4 个薄端点）+ services/dragon\_review/（matrix\_builder.py 矩阵构建、candidates.py 候选与龙头实体标记、intraday\_query.py 日内查询拼装、notes.py 注释/标签）

- 前端 dragon\_review\.html（1135 行）按 factor 模式拆子模板 + app.js

- 其对 /api/sector-rotation/\* 的前端调用**保留**（见 4.2）

### 4.2 跨页面交互规则（核心设计）

页面间交互按"三种合法通道"归类，规则如下：

**规则 1：前端跨页调用 API —— 合法且保留，但要求被调方 API 稳定**

- 龙头复盘调板块轮动、晨会调因子包、交易计划调实盘监控池、live 调龙头候选/交易计划——这些是**前端聚合**（一个页面组装多个后端域的数据），是前后端分离架构下的正确形态，全部保留

- 约束：被跨页调用的 API 视为"对外契约"，重构时路径与响应结构不变；对应后端能力应放在稳定的 service/lib 层（如 rotation 引擎、因子包读写），而非依赖某个页面的路由内部状态

**规则 2：后端复用能力 —— 必须下沉共享层，禁止路由横向 import**

- 切断 `from routes.live import SIM_RUNNER`：单例移入 lib/live\_simulator（引擎层）

- 被两个以上页面（前端）调用的能力，其实现归属：

  - watch\_pool/watch\_merge（live 与 trade\_plan 共用）→ lib/live\_simulator（已在）

  - rotation detail/index（sector/concept/dragon\_review 共用）→ services/rotation/ 单引擎

  - 因子包（morning 与 factor 共用）→ lib/factor\_db（已在）

- 判定口诀：**被 ≥2 页用的下沉共享层，页面专属的留在 services/<page>/**

**规则 3：数据层共享 —— 天然解耦，保持**

- agent skills、各 service 均直连共享 PostgreSQL，不经过对方路由——保持现状

- 唯一要求：表结构改动须在方案文档记录（跨 CASE 的 schema 契约）

**屏蔽独立性验证标准（继承因子库页 Stage 4 的验收口径）**：

- 删除/屏蔽任一页面的 routes/<page>/ + templates/<page>/ + static/js/<page>/ 后，
  其余页面可正常启动与使用（唯一例外：被删页面是某共享 API 的提供方时，需先把该
  API 的实现随迁到共享层——这正是规则 2 存在的意义）

### 4.3 数据采集页的特殊契约（外部脚本调用）

数据采集页通过 `subprocess.Popen` 调用**项目外部**的 4 个 CASE 目录脚本（路径由 .env 控制）：

| 任务                    | 外部目录                         | env 变量                      |
| --------------------- | ---------------------------- | --------------------------- |
| 行情/财务/宏观/新闻/研报/日历/催化剂 | ../CASE-数据采集与存储              | DATA\_COLLECTION\_CASE\_DIR |
| 板块数据                  | ../CASE-A3-板块数据准备-PostgreSQL | SECTOR\_DATA\_PREP\_DIR     |
| 概念数据                  | ../CASE-A4-概念数据准备-QMT        | CONCEPT\_DATA\_PREP\_DIR    |
| 龙头数据                  | ../CASE-A5-龙头数据准备-PostgreSQL | LEADER\_DATA\_PREP\_DIR     |

**设计决定：保留 subprocess 模式，不收编外部脚本**

- 这些外部目录是独立可运行的数据工程（各有 schema.sql/run\_daily.py），是"数据准备层"而非本系统页面代码

- 收益：数据工程可独立演进/单独执行；本系统只持有"任务定义 + 进程管理"

- 本项目内重构仅限：routes/data\_collection.py 的 818 行（子进程管理、SSE 循环、状态持久化、任务组编排）下沉到 services/collection/（runner.py 进程管理 + jobs.py 任务定义表显式化 + state.py 状态持久化），路由只留 4 个薄端点

- scheduler.py 调外部脚本（run\_daily.py）的机制同样保留

***

## 五、目标架构

```
CASE-AI量化系统/
  app.py                        # 组装 + 全部页面路由集中（含 trade-plan 归位）
  scheduler.py                  # 独立调度进程（不动）
  preprocess.py                 # PDF 预处理脚本（不动）
  agent/                        # AI 助手子系统（结构不动）
  pages/tab1_chat.py            # Gradio 投研对话（不动）

  routes/                       # ── 路由层（薄） ──
    common.py                   # 全站公共工具（_json_safe 等，由 factor_common.py 升级改名）
    page_settings.py            # 页面状态持久化 API（已在，通用层）
    live/                       # 每页一个包：__init__.py 组装 + sim.py/real.py/shared.py
    backtest/                   # （原 backtest.py 归位成包，逻辑本就薄）
    review/  morning/  sector_rotation/  concept_rotation/
    dragon_review/  dragon/     # dragon 路由保留（live 页的龙头候选 API 门面）
    stock_quote/  data_collection/  trade_plan/  system/
    factor/                     # 已完成 ✓；quant_gp.py 后期并入 factor/mining/

  services/                     # ── 页面业务层（根目录散包统一收编） ──
    live/                       # live_trading/ + 执行模式/授权/miniQMT 管理（自 routes/live.py 下沉）
    dragon_review/              # 自 routes/dragon_review.py 下沉（~2000 行）
    review/                     # attribution/ + parameter_tuning/ + strategy_lifecycle/
    morning/                    # morning_brief/（graph/pusher/lib/runners）
    rotation/                   # sector_rotation/ + concept_rotation/ 合并为单引擎双配置
    dragon/                     # dragon_strategy/ + 自 routes/dragon.py 下沉的候选逻辑
    collection/                 # 自 routes/data_collection.py 下沉（runner/jobs/state）

  lib/                          # ── 公共层（跨页共享） ──
    # 现有保留：backtest_data、backtest_engine、live_simulator（SIM_RUNNER 归位于此）、
    #          stock_utils、stock_quote、trading_plan、factor_* 全家、paths 等
    # 迁入：routes/live.py 的 watch/execution 通用实现（若 services 与 lib 需共用）

  templates/
    base.html                   # 统一外壳（导航 + AI 侧栏 + 条件加载 block）
    _components/help_modal.html # 帮助弹窗统一组件（5 页重复收敛）
    live/index.html + sim.html + real.html + shared.html
    backtest/  review/  morning/  rotation/（sector 与 concept 共用一个模板 + 差异参数）
    dragon_review/  stock_quote/  data_collection/  trade_plan/  system/
    factor/                     # 已完成 ✓
    ai-chat.html                # 改为继承 base.html

  static/js/
    common.js                   # main.js 升级：App.http（get/post）+ App.sse + App.toast +
                                #   App.chart（Plotly 统一主题/版本）+ App.state（page-settings 封装）
    live/app.js                 # 页面逻辑外置（window.liveApp 展开合并）
    backtest/app.js  review/app.js  ... 同构
    ai-chat.js  ai-settings.js # 仅 AI 相关页面按需加载
  static/css/
    main.css                    # 全局样式（个股行情页专属段挪入 stock_quote 页内样式）
    ai-chat.css                 # 仅 AI 相关页面加载
```

### 前端公共层收敛（common.js 五合一）

| 能力   | 统一为                                                 | 淘汰                                                 |
| ---- | --------------------------------------------------- | -------------------------------------------------- |
| HTTP | App.get/App.post                                    | AI\_SETTINGS.apiGet、quant\_gp this.api、裸 fetch     |
| 流式   | App.sse(url, {onEvent, onDone, onError})            | 2 种 EventSource 写法、fetch getReader 手写 3 处          |
| 通知   | App.toast（info/success/warn/danger）                 | alert()×17、AI\_CHAT.\_showToast、quant\_gp 自带 toast |
| 图表   | App.chart.plotly(fig, layout) 统一主题、Plotly 统一 2.35.2 | 各页内联 layout 配置、双版本                                 |
| 状态   | App.state.load/save(namespace)                      | factor/quantgp 的裸 fetch 调 page-settings            |

后端公共层：routes/common.py（原 factor\_common.py 升级全站化），`_json_safe`/`_json_safe_response`
成为所有路由的标准出口；各路由私有的 `_clean_nan` 逐个替换。

***

## 六、分阶段迁移计划

### Stage 0：公共层先行（不动任何页面功能）

- [ ] routes/factor\_common.py → routes/common.py（factor 子路由改引用，原文件删除）

- [ ] main.js → common.js：新增 App.sse / App.chart / App.state，App.toast 补 danger 映射修复

- [ ] Plotly 版本统一 2.35.2（base.html 与各页引入处）

- [ ] 帮助 modal 收敛为 templates/\_components/help\_modal.html（5 页替换）

- **验收**：全页面行为无变化（每页冒烟：加载、一次请求、一次 toast）

### Stage 1：消除复制粘贴（收益最大、风险最小）

- [ ] services/rotation/ 合并 sector\_rotation/ + concept\_rotation/（单引擎双配置：表名、指标集、注释差异参数化）

- [ ] routes/sector\_rotation.py + routes/concept\_rotation.py 变薄路由（调同一引擎）

- [ ] templates/rotation/ 合并两个模板为一个（差异用参数区分）

- [ ] 17 处 alert() → App.toast

- **验收**：两个页面功能与重构前一致（矩阵/详情/指数图/轮询/刷新任务）

### Stage 2：路由层瘦身（按页逐个做，每个独立验证）

优先级（按肥胖度与耦合度）：

- [ ] dragon\_review（2204 行 → routes/dragon\_review/ 4 薄端点 + services/dragon\_review/）

- [ ] live（1554 行 → routes/live/{sim,real,shared}.py + services/live/；**SIM\_RUNNER 移入 lib/live\_simulator.py**，切断 backtest/dragon 横向 import）

- [ ] review（1036 行 → routes/review/ + services/review/ 收编 attribution/parameter\_tuning/strategy\_lifecycle）

- [ ] data\_collection（818 行 → routes/data\_collection/ 4 薄端点 + services/collection/；外部脚本契约不动）

- [ ] morning（443 行 → routes/morning/ + services/morning/ 收编 morning\_brief/）

- [ ] dragon（288 行 → routes/dragon/ + services/dragon/ 收编 dragon\_strategy/）

- [ ] trade\_plan 页面路由归位 app.py；剩余薄路由（backtest/stock\_quote/system）仅包化归位

- **验收（每页）**：路由集合零差异（OpenAPI 枚举比对）+ AST 未解析名静态检查 + SSE/轮询/持久化冒烟

### Stage 3：长模板拆分（factor 页模式复制）

- [ ] live.html（3512 行，内联 JS 1665 行）→ templates/live/ 子模板 + static/js/live/app.js（sim/real 拆两文件）

- [ ] review\.html（1318）→ 同构

- [ ] dragon\_review\.html（1135）→ 同构

- [ ] trade\_plan.html（808）→ 同构

- [ ] morning/backtest/stock\_quote/data\_collection/system 中等模板同构处理

- **验收**：展开拼接后 DOM 标签事件序列与旧版一致（本次因子库页验证用的方法）

### Stage 4：加载瘦身与外壳统一

- [ ] base.html 条件 block：ai-chat.js/marked.min.js/ai-chat.css 仅 AI 相关页加载

- [ ] ai-chat.html 继承 base.html（消除复制的 70 行导航）

- [ ] system.html 两个 Alpine 组件合并

- [ ] quant\_gp 路由并入 routes/factor/mining/（与 gp/rl/llm\_gp/svd/ml 并列）

- **验收**：ai-chat 页功能不变；其他页网络加载量显著下降（system 页不再拉 4800 行 JS）

### Stage 5：收尾与全站回归

- [ ] 删除全部旧文件（被包取代的 routes/\*.py、根目录散包、旧模板）

- [ ] `?v=` cache-busting 统一管理

- [ ] 全站路由枚举比对 + 每页冒烟 + 页面独立性抽测（屏蔽 1-2 个页面验证其余正常）

### 每页迁移固定验证流程（吸取因子库重构 5 处 import 丢失的教训）

1. 迁移前：OpenAPI 导出该页路由清单存档
2. 迁移后：路由集合比对零差异
3. AST 未解析名静态检查（拦跨文件迁移漏 import/漏全局定义）
4. 手动冒烟：页面加载 + 主请求 + SSE/轮询 + 图表 + page-settings 持久化

***

## 七、保留清单（明确不动的东西）

| 项                                         | 原因                      |
| ----------------------------------------- | ----------------------- |
| 全部 API 路径与响应结构                            | 前后端分离契约（第三节）            |
| lib/factor\_\* 全家（含 quantgplearn\_local/） | 刚按"完全复刻零改动"约束定制，有专项文档约束 |
| 外部 CASE 目录 4 个数据准备工程 + .env 路径契约          | 独立数据工程（第 4.3 节）         |
| agent/ 子系统结构                              | 自洽子系统，仅收编前端外壳           |
| scheduler.py / preprocess.py              | 独立进程/脚本，与页面重构无交集        |
| chat.html（Gradio iframe）                  | Gradio 自成体系，统一成本大于收益    |
| 数据库 schema                                | 跨 CASE 契约               |
| routes/page\_settings.py                  | 已是通用层                   |

***

## 八、新功能接入模板（后续统一结构）

新增一个页面/子功能时，按"四件套"接入：

```
routes/<page>/__init__.py      # router 组装（prefix 由 app.py 统一给 /api/<page>）
routes/<page>/<sub>.py         # 子域端点（薄）
services/<page>/<sub>.py       # 业务逻辑（页面专属）
templates/<page>/index.html    # 页面壳（继承 base.html，x-data="<page>App()"）
templates/<page>/<sub>.html    # 子块模板
static/js/<page>/app.js        # window.<page>App（展开合并进根组件）
```

规则：

1. 路由文件 ≤200 行，禁止 import 其他页面路由；跨页复用一律走 lib/
2. 被 ≥2 页调用的 API 视为契约，实现放共享层
3. 前端一律用 common.js 的 App.http/App.sse/App.toast/App.chart/App.state，不新造轮子
4. 页面状态接 /api/page-settings/<namespace>
5. 上线前过一遍固定验证流程（第六节）

***

## 九、风险与对策

| 风险                                   | 对策                                             |
| ------------------------------------ | ---------------------------------------------- |
| 迁移漏 import/漏全局定义（因子库页已发生 5 处）        | 固定验证流程第 3 步 AST 检查，运行前拦截                       |
| 后端长期运行状态（SIM\_RUNNER 单例）搬迁后行为漂移      | 单例移 lib 时保持同一对象身份，搬迁后用 /api/live/state 对比前后快照  |
| rotation 合并时 sector/concept 行为差异被平均掉 | 先 diff 两个子包全部函数，差异点显式列成配置项，不静默合并               |
| 外部脚本路径契约破坏                           | data\_collection 重构不改 jobs 定义表中的脚本路径与 env 解析逻辑 |
| 前端条件加载导致 AI 侧栏在部分页失效                 | Stage 4 逐页验证侧栏打开/对话/接管功能                       |

```
```

