# QS28 — 三个既有 QS4 切换公式的独立计算核对

2026-09-10 01:40 UTC 完成。只核对冻结计划中的 d035 / d036 / d037；没有改动公式、阈值、符号、窗口、股票池、旧计划或账户配置。固定截面为 **2026-08-27**，本地历史区间 **2026-03-05—2026-08-27，共 121 个 Research Sessions**。三式共 **8,580 个最终评分**及 **20,637 个分支排名 / 状态值**与当前 DSL 完全一致；每项有效集合差异、评分差异、最大绝对误差均为 **0**。[机器结果](round28-switch-proof.json)

## 定义与状态含义

令 `r_n = close[t] / close[t−n] − 1`，`σ_n` 为最近 n 个逐日收益的总体标准差；`R(x)` 为当天该表达式有限输入的升序横截面排名。三式均为 `((1+s)A + (1−s)B)/2`：在所有输入有效时，s=+1 取 A，s=−1 取 B，s=0 时二者均权。

| 冻结定义 | 每只股票自己的状态 s | 正状态分支 A | 负状态分支 B |
|---|---|---|---|
| d035 | sign(MA20 / MA120 − 1) | R(close[t−20] / close[t−120] − 1) | 1 − R(σ20) |
| d036 | sign(MA20 / MA120 − 1) | 1 − R(mean(amount,20)) | 1 − R(σ20) |
| d037 | sign(σ20 / σ120 − 1.2) | 1 − R(σ20) | R(−abs(R(r5) − 0.3)) |

来源是冻结计划的 [d035](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/round28-plan.json:2530)、[d036](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/round28-plan.json:2599)、[d037](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/round28-plan.json:2669)。以上状态都在单只股票的历史序列上计算，并不包含指数、市场宽度、组合收益或统一的市场状态。同一天可以有部分股票走 A、其余走 B；不能把这三式称为已经识别了全市场牛熊并统一切换组合。[逐股票内置函数执行](../../apps/core/src/thesistrace/research_kernel/series_plan.py)、[sign 契约](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:89)

d037 的 0.3 是 **5 日收益横截面排名的位置**，不是跌幅 30%，也不是过去时间轴上的分位数。外层排名把更接近该位置的股票赋予更高分。`amount` 是人民币成交额；此处没有股本归一化的换手率。`close` 是当前数据契约的因果累计复权收盘价。[字段契约](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:94)

## 每个 rank 节点的样本口径

每个 `rank` 节点都独立取该日研究 Universe 中、该节点输入为有限数的股票。平均序号映射至 0—1，并列共享平均名次，单个有效值为 0.5；缺失值不进入分母。它不会先等待整个复合公式的有效集合，也不会只在对应正 / 负状态的股票中排名。[rank 定义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:359)、[当前执行](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:364)

本日数据读取器给出 **2,998 只**当日研究 Universe 成员。该集合来自已存 TOP3000 成员与当日有效原始开盘、复权开盘及正成交额的交集；本证明复用此读取器，没有独立重建 TOP3000 或交易资格。[Universe 读取契约](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/columnar_series.py:160)

| 被排名表达式 | 本日有效股票数 | 该节点需要的数据 |
|---|---:|---|
| d035 中期动量 | 2,965 | t−20、t−120 两个收盘值有效，t−120 非零；该排名本身不要求中间每个收盘值齐全 |
| d035 / d036 / d037 的 σ20 | 2,983 | 最近 21 个收盘价构成 20 个有效逐日收益 |
| d036 的 mean(amount,20) | 2,983 | 最近 20 个成交额齐全 |
| d037 内层 R(r5) | 2,993 | 当前与 t−5 收盘值有效，t−5 非零 |
| d037 外层 R(−abs(R(r5)−0.3)) | 2,993 | 继承内层有限排名；再对距离评分排名 |

三式的最终有效评分分别为 2,860 个。因此，d035 的动量排名仍包含 **105** 只未进入最终评分的股票，低波动排名包含 **123** 只；d036 的成交额和低波动排名分别包含 **123** 只；d037 的低波动排名包含 **123** 只，温和反转内外层排名分别包含 **133** 只。先把所有节点压到最终有效股票池再排名会改变这些定义，本次没有这样处理。[样本计数和逐节点比较](round28-switch-proof.json)

## 缺失值与零权重

`ts_mean` / `ts_std` 要求完整窗口；`ts_std` 使用总体标准差，分母为 n。MA120 要求 120 个收盘价；σ120 要求 120 个逐日收益，也就是 121 个收盘价。实际编译 lookback 分别为 d035=120、d036=119、d037=120。[窗口契约](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:410)、[编译结果](round28-switch-proof.json)

加减乘除要求两侧均有限，除法还要求分母非零；故 **0 × 缺失仍为缺失**，算术写法没有惰性分支短路。即使状态给某一分支零权重，该分支缺失仍可能使最终评分缺失。[二元运算执行](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:292)

独立的两行合成探针 `0 * close + 1` 给出：close=2 时结果为 1，close 缺失时结果仍缺失。实际 8 月 27 日截面中，“被选中分支有限、但未选中分支缺失而额外丢失评分”的情况三式均为 **0 例**；138 个无最终评分的成员均已无有效状态。因此不能把本日这 138 个覆盖损失归因为未选中分支的零乘传播。[探针与覆盖拆分](round28-switch-proof.json)

## 固定日期实测

| 定义 | 正状态 | 负状态 | 等于门槛 | 状态缺失 | 独立 / DSL 最终有效数 | 集合差异 | 最大评分误差 |
|---|---:|---:|---:|---:|---:|---:|---:|
| d035 | 777 | 2,083 | 0 | 138 | 2,860 / 2,860 | 0 | 0 |
| d036 | 777 | 2,083 | 0 | 138 | 2,860 / 2,860 | 0 | 0 |
| d037 | 322 | 2,538 | 0 | 138 | 2,860 / 2,860 | 0 | 0 |

状态正负的含义依上表公式：d037 正状态指 σ20/σ120 > 1.2。5 个排名节点加 2 个状态表达式的 **20,637 个值**全部逐值相同，且各自有效集合相同。事先比较容差为 1e−10，实测误差为严格 0；本日没有刚好等于门槛的样本，等值分支含义来自 sign 与算术定义。[全部比较输出](round28-switch-proof.json)

独立计算使用 `math.fsum` 求均值、先求均值再求离均差平方和的两遍总体标准差，以及排序后 `bisect_left` / `bisect_right` 计算并列平均名次；没有调用内核均值、标准差或排名辅助函数。数据读取与 DSL 对照使用当前 `MountedGenerationStore` / `evaluate_columnar_alpha_matrix`。最终评分在各自叶子节点完成排名之后才与状态、两分支有效集合取交集。[独立脚本](prove_round28_switch.py)

复查命令，在仓库根目录执行：

```sh
UV_CACHE_DIR=/private/tmp/thesistrace-qs-uv-cache uv run --project apps/core --no-sync --offline python .scratch/top3000-sharpe-search-20260910/prove_round28_switch.py
```

本次命令退出码 **0**。核对使用的 checkout HEAD 为 `ad16ea9bd8e369c20270d187499cb089b7b7069e`；JSON 另存实际读取的 6 个源码文件 SHA256，避免只凭 HEAD 假定工作区源码未变。冻结计划 SHA256 为 `8f1ac92d21efb746cbbe58aa890127bae91d42b208c9c1d9c2c90a49d4370b4c`。已授权本地 manifest 内容 SHA256 为 `4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f`，与读取的 generation 标识一致。[执行证据](round28-switch-proof.json)

## 证明边界

这只证明一个预先固定日期的信号算术、排序和覆盖契约。没有独立审计原始行情、Universe 构建或读取器；没有证明所有日期、运行分块、未来收益、100,000 元交易、佣金 / 滑点或板块权限。截止 2026-08-27 的本地 generation 与截止 2026-09-09 的生产回测 generation 不同，不能把本次状态计数当成最新市场状态，也不能从评分完全一致推断账户盈利或 Sharpe 达标。未传输最新行情，未调用 MCP 提交或修改接口，未启动 / 修改容器，未编辑产品源码。
