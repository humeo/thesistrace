# TuShare 财务数据与 Point-in-Time 接入研究

> 状态：研究结论，不是已批准 ADR，也不表示已经实现。接口资料核对日期：2026-08-12。
>
> 证据范围：TuShare 官方接口文档与官方 Python SDK、Microsoft Qlib 官方文档/源码、Quantopian Zipline 官方开源源码，以及当前 ThesisTrace 源码和 ADR。未使用博客等二手资料。

## 结论

建议把新增数据分成两个独立家族，不能都叫“基本面”，也不能塞进现有 `prices`：

1. `equity.financial_pit`：季度报告和公告事件，稀疏、可修订、同时具有“报告期”和“何时可知”两条时间轴。覆盖 `income`、`balancesheet`、`cashflow`、`fina_indicator`、`fina_audit`、`forecast`、`express`、`disclosure_date`。
2. `equity.daily_valuation`：`daily_basic` 的交易日级估值、股本和市值数据，以 `(session, instrument_id)` 为粒度。它不是季度财务 PIT；其中 PE/PB/PS 等是 TuShare 派生值，分母的历史版本血缘并不透明，应标记为 vendor-derived。

两个家族仍由同一个 immutable Generation 根 Manifest 引用。行情刷新时复用未变化的财务 Manifest；财务修订时复用未变化的行情 Manifest。验证成功后只原子切换一个 `HEAD.json`，已 pin 旧 Generation 的 ResearchRun 不受影响，不需要复制所有历史对象。

财务事实的核心查询语义是：

```text
对每个回测 session，只选择 available_session <= session 的最后一个已知版本。
```

不能以报告期末作为可见日期，不能把今天看到的最终值回填到历史，也不能在公告日期缺失时猜 45/90 天。TuShare 这些接口目前只给日期时，继续执行 [ADR-0016](../adr/0016-apply-conservative-availability-to-date-only-financial-disclosures.md)：从公告日期后的下一个已完成上海/深圳 Research Session 才可用。

## 1. TuShare 官方接口事实

### 1.1 接口对照

| 接口 | 粒度与主要身份字段 | 公告/版本线索 | 官方权限与提取约束 | 建议归属 |
| --- | --- | --- | --- | --- |
| [`income`](https://tushare.pro/document/2?doc_id=33) | `ts_code`, `end_date`, `report_type`, `comp_type`, `end_type` | `ann_date`, `f_ann_date`, `update_flag` | 2000 积分；普通接口按单股历史；5000 积分的 `income_vip` 可按报告期取全市场 | `financial_pit` 数值事实 |
| [`balancesheet`](https://tushare.pro/document/2?doc_id=36) | 同上 | 输出有 `ann_date`, `f_ann_date`, `update_flag` | 2000 积分；普通接口按单股历史；5000 积分的 `balancesheet_vip` 可按报告期取全市场 | `financial_pit` 数值事实 |
| [`cashflow`](https://tushare.pro/document/2?doc_id=44) | 同上；另有 `is_calc` 输入 | `ann_date`, `f_ann_date`, `update_flag` | 2000 积分；普通接口按单股历史；5000 积分的 `cashflow_vip` 可按报告期取全市场 | `financial_pit` 数值事实 |
| [`fina_indicator`](https://tushare.pro/document/2?doc_id=79) | `ts_code`, `end_date` 和指标列 | `ann_date`, `update_flag`；无 `f_ann_date`/报表口径字段 | 2000 积分；单次最多 100 条；普通接口按单股；5000 积分的 `fina_indicator_vip` 可按报告期取全市场 | `financial_pit` 派生指标事实 |
| [`fina_audit`](https://tushare.pro/document/2?doc_id=80) | `ts_code`, `end_date`，审计结论/费用/机构/签字人 | `ann_date`；无 `update_flag` | 2000 积分；官方名称是 `fina_audit`，不是 `audit`；页面未承诺 VIP 路径或单次上限 | 独立审计事件表 |
| [`forecast`](https://tushare.pro/document/2?doc_id=45) | `ts_code`, `end_date`, `type`，区间值及文本 | 当前版本 `ann_date`，另保留 `first_ann_date` | 2000 积分；普通接口可按单股或精确公告日；单次最多 3500 条；5000 积分有 `forecast_vip`；官方注明每日约 20:00–21:00 更新 | 独立预告事件表 |
| [`express`](https://tushare.pro/document/2?doc_id=46) | `ts_code`, `end_date`，收入/利润/资产等快报值 | `ann_date`; `is_audit`, `remark`；无 `f_ann_date`/`update_flag` | 2000 积分；普通接口按单股历史；5000 积分有 `express_vip`；页面未公布稳定单次上限 | 独立快报事件表 |
| [`disclosure_date`](https://tushare.pro/document/2?doc_id=162) | `ts_code`, `end_date` | `pre_date`, `actual_date`, `modify_date`; `ann_date` 是最新披露计划公告日 | 2000 积分；单次最多 6000 条、总量不限 | 独立披露计划事件表 |
| [`daily_basic`](https://tushare.pro/document/2?doc_id=32) | `trade_date`, `ts_code` | 每个交易日一版，不是报告修订链 | 2000 积分；单次最多 6000 条；5000 积分无总量限制；交易日约 15:00–17:00 更新 | `daily_valuation` |

这里的“5000”在报表类接口文档中主要是 VIP 权限积分，不应误写成统一的 5000 行上限。TuShare 的[最低积分表](https://tushare.pro/document/1?doc_id=108)目前把上述财务接口和 `daily_basic` 都列为 2000 积分起；[积分与频次表](https://tushare.pro/document/1?doc_id=290)目前列出的平台级额度是：2000 积分以上每分钟 200 次、每天每个 API 100000 次，5000 积分以上每分钟 500 次且常规数据无每天总量上限。这是 2026-08-12 的官方页面状态，不是可以写死的永久接口合同；真实能力还会受账号积分、单独权限和接口自身行数上限影响。上线前必须用部署所用 token 做能力探针并保存结果，不能从其他接口的频率推断财务接口频率。

### 1.2 三大报表不是同一种数值语义

三大报表的 `report_type` 官方代码包括：`1` 最新合并、`2` 单季合并、`3` 调整单季、`4` 调整合并、`5` 调整前合并，以及 `6`–`12` 的母公司/母公司调整口径。`comp_type` 又以 `1`–`4` 区分一般工商、银行、保险、证券。设计上必须原样保留这些字段，不能只用 `(ts_code, end_date, field)` 去重，否则会吞掉不同口径或调整前版本。

- 利润表、现金流量表通常是年初至报告期的累计流量；不能把所有季度行直接当“单季度”。需要单季值时，优先用来源明确提供的单季 `report_type`，或者只在完全相同口径之间做差。
- 资产负债表是报告期末存量。
- `fina_indicator` 是 TuShare 已计算的指标，不等于原始报表字段；它缺少三大报表的完整口径字段，字段目录必须明确标记来源和定义。
- 财务报表多数字段单位为元，`forecast` 的净利润区间单位为万元，比例字段可能为百分比。单位必须逐字段进入 catalog，不能统一猜测，也不能把缺失值填零。

### 1.3 每个日期字段的含义

建议保留原始日期，不在采集阶段压成一个 `date`：

- 三大报表：优先以 `f_ann_date`（实际公告日期）作为 `source_published_date`，没有时才用 `ann_date`；两者都保留。
- `fina_indicator`、`fina_audit`、`express`：以各自 `ann_date` 为来源公告日。
- `forecast`：每次版本的 `ann_date` 决定该版本的可见性；`first_ann_date` 只说明该预告链首次出现的日期，不能替代当前版本日期。
- `disclosure_date.pre_date` 是计划日期，绝不代表财务数值已经可用。`actual_date` 可用于发现/完整性核对，但数值事实仍以对应数值接口自己的 `ann_date`/`f_ann_date` 为准。该接口的 `ann_date` 是最新披露计划公告日，也不是报表数值公告时间。

上述接口没有精确到时分秒的公告时间，因此 `source_published_date` 映射到 `available_session` 时使用 ADR-0016 的下一已完成 Research Session。若以后接入官方公告的可靠 `rec_time`，才可按交易日历和精确时间制定更细规则；不能用当天日期假装盘前已知。

### 1.4 `update_flag` 不是版本主键

`update_flag=1` 表示来源认为当前行较新，但它不是全局唯一版本 ID，也不能证明 TuShare 返回了完整历史修订链。实施时：

- 保留 `update_flag=0` 和调整前报表；不能先过滤到只有 `1`。
- 不用 `update_flag` 去重。
- 完全相同响应行按内容 hash 幂等；相同逻辑身份但内容不同必须成为另一个版本。
- 历史首次 bootstrap 可以按来源公告日期建立已返回版本，但必须披露：这只是 TuShare 当前能返回的来源版本集合，不代表所有曾经公开过的中间修订都存在。这与 [ADR-0018](../adr/0018-preserve-source-financial-versions-without-inventing-history.md) 一致。

若以后轮询发现“相同公告日期、相同口径，但 payload 变了”，且来源没有给出新的修订日期，不能把新值追溯回旧公告日。它应记录为 `revision_basis=observed_correction`，并从首次观察到该 payload 后的 session 才生效。只有来源明确给出新公告/修订日期的版本，才使用 `revision_basis=source_version`。

## 2. 分页、权限与完整抓取

### 2.1 不复用当前通用分页假设

TuShare 官方 SDK 的 [`DataApi.query`](https://github.com/waditu/tushare/blob/master/tushare/pro/client.py) 只是把 `api_name`、token、params 和 fields POST 给服务端；它不提供通用分页合同。当前 ThesisTrace [`query_paginated`](../../src/thesistrace/adapters/tushare_provider.py) 会自行加入 `limit/offset`，再用调用方 primary key 覆盖重复行。对财务数据直接复用会有两个风险：

1. 财务接口页面没有统一承诺 `limit/offset`；请求被接受不等于分页语义可靠。
2. 如果 primary key 没包含公告日期、报表口径和内容版本，不同修订会被 `rows_by_key[key] = row` 静默覆盖。

按照 [ADR-0180](../adr/0180-use-one-ordinary-per-instrument-tushare-financial-collector.md)，
首期财务 collector 固定按普通接口的 `endpoint × ts_code` 形成一个逻辑
shard，不实现 VIP 或通用分页器。按照
[ADR-0192](../adr/0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md)，
只有 `balancesheet` 使用已经现场验证的固定100行 `limit/offset` 分页，并在
adapter 内合并成完整逻辑响应；其他报表仍为一次物理请求。分页停滞、schema
变化、异常页长或无法证明完整都 fail closed，不切换日期分片，也不能把疑似
截断的响应当成完整历史。

### 2.2 上线前能力探针

使用真实部署 token 对 `income`、`balancesheet` 和 `cashflow` 普通接口
分别记录：

- 是否有普通接口权限及其错误码/响应；
- 文档字段是否实际返回，空值和重复行模式；
- `limit/offset` 是否真正受支持，不能只看请求未报错；
- 单股完整历史和公告日期范围分片能否覆盖同一基准样本；
- 实际限流响应和安全节流参数。

探针结果是部署环境能力，不写死成 TuShare 的永久事实。权限不足时应明确阻止该家族发布，不做接口 fallback 或悄悄降级成不完整数据。

### 2.3 Bootstrap

Bootstrap 固定按 `endpoint × ts_code` 拉取三大报表单股历史，并在每个
shard 完成后持久化 resumable checkpoint。所有 expected instrument 的三类
shard 完成并通过完整性验证后，才可发布候选 Generation；进程重启只恢复
未完成 shard，不重新接受或改写已验证批次。所有批次保存请求参数、响应
字段顺序、响应 payload hash、首末来源日期、行数、采集时间和 endpoint
合同版本。

当前 [`_compact_source_lineage`](../../src/thesistrace/adapters/tushare_data.py) 只把响应压成 row count，无法证明财务修订的原始内容。财务接入需要把 accepted raw response 作为 content-addressed JSON object 保存，并让财务表 Manifest 引用 batch hash；root provenance 可以保留摘要，不能只剩计数。

按照
[ADR-0184](../adr/0184-start-financial-coverage-in-2010-with-minimal-pre-start-seeds.md)，
Financial Coverage Start 固定为 2010 年首个 Research Session。Canonical
事实保留从该 session 起变得可用的所有来源版本，并为首日投影保留最少的
pre-start Financial Seed Facts。Bootstrap 优先由一次完整历史响应在本地选出
2010 范围与 seed，并把原响应完整保留为 Raw Financial Batch；Canonical
版本表不接收范围之外的其余旧行。能力探针必须先证明完整历史响应没有截断，
否则 fail closed。执行合同只有 `complete-history`，没有日期分片替代路径。
请求窗口和 raw batch 时间范围都不是 Financial Coverage。

### 2.4 Bootstrap 请求量与耗时模型

2026-08-12 本地 Dataset Head 的 `instruments` Manifest 包含 5,541 个历史
ordinary A-share Instrument Identity。Bootstrap 以历史集合而不是仅当前上市
集合为 expected instruments，避免幸存者偏差。若能力探针证明每个普通接口
的单股完整历史逻辑响应完整，则三张报表的逻辑 checkpoint 数为：

```text
Q = endpoint_count × instrument_count × logical_shards × average_attempts
  = 3 × 5,541 × 1 × 1
  = 16,623
```

每个 API 各有 5,541 个逻辑 shard。按照
[ADR-0192](../adr/0192-paginate-the-ordinary-balance-sheet-inside-one-logical-shard.md)，
`balancesheet` 每100行增加一个物理分页请求；2026-08-14 对
`000001.SZ` 的实测是100行加62行，因此完整历史逻辑响应为两次物理调用。
实际全市场物理请求数取决于各标的资产负债表行数，但不再乘以37个年度分片。

TuShare 2000 积分档当前公布 200 次/分钟、100,000 次/日/每个 API；分钟限额
未明确声明可按 endpoint 独立累加，因此 collector 应在三类接口间共享
limiter。忽略额外资产负债表页面时，按 200 次/分钟计算的16,623次逻辑请求
下限是83.1分钟。现有 adapter 的默认 `throttle_seconds=0.5` 相当于最多发出
120 次/分钟；若把每个标的的 `balancesheet` 暂按两个物理页面估算，则约为
22,164次物理请求，纯节流时间约184.7分钟。若平均 HTTP 与 JSON 解码时延是
0.2、0.5 或1.0秒，尚未计最终 Parquet、Manifest 和完整性验证时，墙钟约
4.3、6.2 或9.2小时。新股可能只有一页，长历史或多版本标的也可能超过两页，
因此这是容量规划模型，不是硬承诺。

上述数字只包含财务 family。当前本地 Head 的 Market Coverage 是
2026-07-03 至 2026-08-04，而首次 financial-capable Head 已决定从 2010 年
首个 Research Session 开始 Market Coverage。现有行情 Bootstrap 对每个
Research Session 至少调用 `daily`、`adj_factor`、`suspend_d` 和 `stk_limit`
四个 endpoint；2010 至 2026-08 约四千个 session，因此还需要约 16,000 次
基础行情请求，另加分页、calendar、instrument 和 industry 请求。若从当前
Mounted Canonical Data Store 首次构建完整 2010 可执行 Head，财务和行情合计
约 33,000 次以上逻辑请求；沿用同一串行节流与 0.2、0.5、1.0 秒平均 HTTP
时延模型，来源采集约 6.4、9.2、13.8 小时。加上 Canonical 映射、Parquet、
Manifest 和完整性验证，应给首次总构建预留 8–16 小时。若 Market Coverage
已预先回填到 2010，则财务部分按约4–10小时预算。准确 session 数和分页倍数
由 Phase 0 的 `trade_cal` 与 live probe 记录，不能把本估算当硬承诺。

同一 Head 中有 1,696 个 Instrument Identity 在 2010 年首个 Research
Session 已经上市且尚未退市。已否决的严格 raw-window 方案会把
2010 起始窗口和 pre-start seed 窗口分成两次来源请求，只需为这 1,696 个
首日标的增加三类 seed 请求：额外 5,088 次，总计约 21,711 次；不是让所有
后来上市的标的也多请求一次。该口径的 200 次/分钟理论下限为 108.6 分钟，
0.5 秒纯节流时间为 180.9 分钟。该方案增加请求但不提高 Canonical 正确性，
因此不采用。

三张普通报表仍由 live capability probe 用完整历史与年度集合比较。执行合同
只接受一个 `complete-history` 逻辑 shard；`balancesheet` 的100行分页是固定的
source contract，不是运行时 fallback。每 API 日限额应按物理分页和重试计算，
并用 per-instrument checkpoint 跨日恢复。

### 2.5 V1 Financial Refresh：每次完整重拉

按照
[ADR-0185](../adr/0185-rebuild-the-complete-financial-family-on-every-v1-refresh.md)，
V1 不实现近期公告热窗口、历史轮转对账或自动调度。每次手动 Financial
Refresh 都对当时完整的 historical ordinary A-share Instrument Identity 集合
重新请求 `income`、`balancesheet` 和 `cashflow` 全历史 shard。新增、退市和
暂停上市标的都进入同一个 expected shard 计算，不能只按当前 active 股票抓取。

刷新沿用 Bootstrap 的 checkpoint、共享 limiter 和完整性合同。Exact
duplicate Raw Financial Batch、Canonical row 和 Parquet object 通过内容寻址
幂等复用；候选 family 是既有已接受 Source Financial Versions 与本次新增或
修订版本的并集。来源后来不再返回某个旧版本不构成删除，旧版本及其 raw
evidence 继续被 Manifest 引用。任何 endpoint 截断、权限变化、shard 失败、
schema 漂移或跨 family 校验失败都不得移动 Dataset Head，部分成功不能发布。
当前 5,541 个标的的基线仍为16,623个逻辑 shard；物理请求还要加上
`balancesheet` 后续页，当前按约4–10小时串行墙钟时间做容量规划。标的集合
变化后先按 `3 × instrument_count` 计算逻辑 shard，再加入现场分页倍数。

## 3. 物理模型与版本身份

### 3.1 稀疏事实，而不是永久日频展开

研究阶段曾考虑统一 long-form；后续领域设计已在
[ADR-0175](../adr/0175-store-each-financial-statement-kind-as-a-wide-version-table.md)
决定采用按报表类型分开的宽版本表。推荐结构修正为：

```text
equity.financial_pit
  income_statement_versions            # 一行一个 income 来源版本
  balance_sheet_versions               # 一行一个 balancesheet 来源版本
  cash_flow_statement_versions         # 一行一个 cashflow 来源版本
  raw_tushare_financial_batches        # content-addressed JSON references

equity.daily_valuation
  daily_valuation                      # (session, instrument_id) 日频宽表
```

`fina_indicator` 若后续接入，使用独立宽版本表，因为它是 TuShare
派生指标且缺少三大报表的完整口径字段。`forecast`、`express`、`audit`
和披露计划具有不同的 grain 与事件语义，后续各自归入适合的 Dataset
Family，不放进三大报表表中。

三大报表的所有 `report_type` 都保留，但按照
[ADR-0178](../adr/0178-build-initial-financial-fields-only-from-latest-consolidated-statements.md)，
首批六个 Session-Aligned Financial Field 只读取 `report_type=1` 的最新
合并口径。单季、调整、调整前和母公司口径不作为缺失时的替代输入；以后若
开放，使用新的稳定 Field Identifier。

每张宽表都保留一组版本身份和可见性列：

```text
instrument_id
source_endpoint
report_period
report_type
company_type
end_type
ann_date?
f_ann_date?
source_published_date
first_observed_at
source_available_session
available_session
update_flag?        # nullable
revision_basis      # source_version | observed_correction
source_row_sha256
source_batch_sha256
<该报表来源合同中的全部财务列，均 nullable>
```

一个财务列的非空值在逻辑上形成一个 Financial Fact；来源返回的 null
仍保持 null，不生成零。宽表保存当前已接受来源合同的全部字段，原始 JSON
batch 保留最终审计能力。Session-Aligned Financial Field 只投影本次执行
需要的列，不把宽表永久展开成日频副本。

建议两个身份层次：

- **来源行身份**：`SHA256(endpoint + ts_code + report_period + report_type/comp_type/end_type + ann_date/f_ann_date + canonical source payload)`。完全相同响应幂等。
- **逻辑修订组**：`endpoint + instrument_id + report_period + report_type + company_type + end_type`。PIT 投影先在同一报表逻辑组内选择可见版本，再读取请求的列。

`forecast`、`express`、`audit` 和披露计划保留自己的结构，不能硬塞进只有单个 `value_decimal` 的表：预告是区间和文本，审计是分类/机构事件，披露计划不是财务事实。

### 3.2 可见时间

```text
source_available_session = next_completed_session(source_published_date)

source_version:
  available_session = source_available_session

observed_correction（来源没有新的可验证日期）:
  available_session = max(source_available_session, first_observed_session)
```

若公告日期缺失，记录进入 quarantine/raw evidence，不能进入 authorable PIT facts。若来源日期早于 ThesisTrace Coverage，可保留真实 `source_available_session`，执行层的首个可见点自然受研究 Coverage 限制；若日期晚于当前 calendar，则保持 pending，等 calendar 能解析后再发布。

### 3.3 Partition

宽版本表按 `available_session` 的 Research Session block 分区，沿用当前 64-session 重写边界；高密度公告 block 再按稳定的 instrument hash bucket 拆 object。这样新公告和新观察到的修订只重写尾部/对应 block，旧 Parquet object 可以复用。排序键至少包含：

```text
(available_session, instrument_id, report_period,
 report_type, company_type, end_type, source_row_sha256)
```

所有 Parquet object 继续 ZSTD、规范序列化和 SHA-256 content addressing。月度/季度 PIT checkpoint 可以在 benchmark 证明必要后加入，但只能是可删除、可重建的 derived object，不能替代版本事实。

`daily_valuation` 已经是日频数据，按现有 64-session block 和 `(session, instrument_id)` 排序即可。它不需要 `report_period` 或 revision chain；对历史同日 payload 的静默变化仍按新 Generation 保存 provenance，旧 Generation 保持可复现。

## 4. 与当前 Generation/Manifest 的结合

当前 [`TABLE_SPECS`](../../src/thesistrace/data/generation_schema.py) 固定为九张 `canonical-eod` 表，所有 Arrow 字段均 `nullable=False`；[`_normalize_canonical`](../../src/thesistrace/data/generation_store.py) 也要求精确表集合。因此新增财务并非“配置里多写一张表”，而是一次明确的 schema contract hard cut。项目禁止兼容层/迁移 fallback，建议新 bootstrap 到一个新 contract，例如 `canonical-research-v2`，旧 contract 不在运行时兼容。

新 root Manifest 仍保持一个 Head，但按数据家族引用子 Manifest：

```text
HEAD.json
  -> Generation root
       -> equity.market_eod manifest
       -> equity.financial_pit manifest -> raw source batch references
       -> equity.daily_valuation manifest（启用后）
       -> field_catalog manifest
```

按照
[ADR-0183](../adr/0183-give-each-dataset-family-its-own-coverage-declaration.md)，
Coverage 由各 Dataset Family Manifest 声明，root 聚合但不压成一个全局
日期交集：

- Market Coverage：`coverage_start` 与 `market_data_through_session`；
- Financial Coverage：complete expected shard set、`financial_observed_through`
  与各 endpoint reconciliation watermark；
- 财务源接口/字段合同版本和权限探针摘要；
- `financial_revision_coverage` 限制，明确“未伪造 TuShare 未提供的历史版本”；
- 各 family Manifest digest 和 authorable field set。

个别股票没有 Financial Fact 是合法稀疏数据，不等于 Financial Coverage
不完整。ResearchRun 不拥有 Coverage；执行只验证其 Field References 所需的
family 是否能够提供计算 slice。引用财务字段的 ResearchRun 结束 session 不得
晚于 `financial_observed_through`；引用财务字段的 DailyTrack 在第一个未覆盖
session 前进入 blocked，直到完整 Financial Refresh 推进该 cutoff。只引用行情
字段的 Run 和 Track 不受财务刷新进度影响。

按照
[ADR-0181](../adr/0181-refresh-market-and-financial-families-independently-under-one-head.md)，
Market Refresh 与 Financial Refresh 是两个独立 operator action，但共同发布到
一个 Dataset Head。每次只 materialize 目标 family/table partitions，root
复用未变化的 Manifest digest。若采集期间 Head 已被另一刷新移动，旧 root
不得发布；应把已验证的目标 family 与最新未变化 family 重新组装并复验
cross-family invariants。不要建立独立可变的“finance latest Head”并在运行时
与已 pin 的行情 Generation join，否则 ResearchRun 无法复现。

Worker claim 阶段只需要读取并 pin root Manifest/digest，不应打开所有 Parquet。执行阶段根据表达式所需字段选择性打开对应 family Manifest 和分区。当前 `open_generation` 会还原全部固定表；财务加入前应把“检查 root/pin”与“按字段解析所需对象”分开，避免重新制造全量加载性能问题。

## 5. Alpha 与 DailyTrack 的最小干净边界

仅完成 ingestion 并不会让财务字段可写。目前：

- [`fields.py`](../../src/thesistrace/data/fields.py) 的 authorable catalog 固定为六个行情字段；
- [`evaluate_alpha_matrix`](../../src/thesistrace/research_kernel/alpha.py) 直接读取 `canonical["prices"]`，并把这六个名字硬编码到价格列。

最小且长期干净的改动不是让 Kernel 查询 Parquet，而是在 Data/Execution 边界增加一个批量 field resolver：

```text
Pinned Generation + requested field IDs + sessions + instruments
  -> Data-owned FieldResolver
       market resolver
       financial PIT as-of resolver
       daily valuation resolver
  -> pure AlphaInputMatrix
       sessions
       instruments
       values_by_field[field][instrument][session] -> float | None
       universe / industry inputs
  -> pure Research Kernel evaluation
```

ResearchRun admission 先从表达式得到 requested field IDs；Execution 用已 pin Generation 一次性、向量化地解析这些字段；Kernel 只接收 caller-prepared `AlphaInputMatrix`，不认识 Head、Manifest、Parquet 或 PIT 存储。PIT resolver 对每个逻辑修订组做 `available_session <= cutoff` 的 as-of 选择，再只对本次 session、股票池、字段生成矩阵，禁止 Python 的“股票 × 日期 × 字段”逐格扫描。

行情与财务以同一个 Numeric Series grain 进入 Formula，因此可以形成
Composite Alpha，而不需要独立“多因子模型”资源。按照
[ADR-0189](../adr/0189-add-one-cross-sectional-rank-builtin-for-composite-alpha.md)，
首个财务切片同时加入显式 `cs_rank(x)`，用于在每个 session 的已选 Liquidity
Universe 内把异质量纲的子因子变成 0–1 横截面百分位。例如：

```text
0.6 * cs_rank(pct_change(close_adj, 20))
+ 0.4 * cs_rank(net_profit_parent_latest_fy / total_assets_latest_reported)
```

并列值取平均 rank，单一有效值为 0.5，missing 不进入分母并继续保持 missing。
需要“越低越好”的子因子时由 Formula 显式取负；Industry Neutralization 仍在
完整 Composite Alpha 之后执行。ResearchRun 与 DailyTrack 使用同一个
`cs_rank` Builtin Definition，不允许两套横截面口径。

字段目录至少增加 `family`、`time_semantics`、`unit`、`source_endpoint`、
`authorable` 和 `applicable_company_types`。按照
[ADR-0176](../adr/0176-ingest-all-financial-company-types-but-author-fields-with-explicit-applicability.md)，
四种 `comp_type` 的来源字段全部采集，但 Alpha Field 必须声明可比较的公司
类型。按照
[ADR-0186](../adr/0186-apply-the-initial-six-financial-fields-to-all-company-types.md)，
首批六个字段的 `applicable_company_types` 明确为 `{1, 2, 3, 4}`；这表示字段
合同适用，不保证来源非空，也不代表跨行业直接排名一定是合理策略。来源空值
仍产生 missing，不回退到其他报表口径、行业专属字段或零，也不隐式改变
Liquidity Universe。Phase 1 入库时财务字段全部 `authorable=false`；只有 PIT
测试和性能基准完成后才开放这六个跨公司字段，行业专属 Financial Facts 保留
到其适用范围与研究语义确定以后。DailyTrack 使用同一个投影边界，避免回测
与每日执行产生两套可见性语义。

`daily_basic` 字段走 daily valuation resolver。PE/PB/PS/股息率/总股本/流通股本/市值可以单独开放，但目录必须写明 `vendor_derived=true`；它们不能用来证明 ThesisTrace 自己从财务 PIT 构造的估值因子没有前视偏差。

## 6. Qlib 与 Zipline 的可借鉴模式

### 6.1 Qlib：采用语义，不照搬存储

Qlib [官方 PIT 文档](https://qlib.readthedocs.io/en/stable/advanced/PIT.html) 为每个字段保存 `(date, period, value, _next)`：`date` 是版本发布日期，`period` 是报告期，`_next` 把同一报告期修订串联。查询只沿链读取查询时点前最后版本；这验证了 ThesisTrace 必须分离报告期和知识时间。

但 Qlib 当前 [`LocalPITProvider`](https://github.com/microsoft/qlib/blob/main/qlib/data/data.py) 明确标注非线程安全，并在查询时通过 `np.fromfile` 读取整个字段文件；官方也承认 PIT 计算仍有较大优化空间。其 [`dump_pit.py`](https://github.com/microsoft/qlib/blob/main/scripts/dump_pit.py) 增量逻辑不是可直接采用的通用修订数据库。ThesisTrace 应使用自己的 immutable manifests、列式分区和批量 as-of resolver。

Qlib 样例 collector 在发布日期缺失时按季度末后 45 天/年末后 90 天补日期（见[官方 collector 源码](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/pit/collector.py)）。这只是样例 fallback，会伪造知识时间，ThesisTrace 明确不采用。

### 6.2 Zipline：修订事实与 checkpoint 分离

Quantopian Zipline 的 [Blaze loader 源码](https://github.com/quantopian/zipline/blob/master/zipline/pipeline/loaders/blaze/core.py) 分离 `asof_date` 与 `timestamp`，把修订放在 deltas，并用 checkpoints 加速从某个历史状态继续合并。适合借鉴的不变量是：

- 修订追加而不是覆盖；
- 查询显式接受 session cutoff；
- checkpoint 是可重建的性能层，不是权威事实。

Zipline 在缺少 timestamp 时允许复制 as-of date。对财务数据这会前视，ThesisTrace 不采用该默认；Quantopian 仓库也已归档，不引入其 Blaze 技术栈。

## 7. 分阶段落地建议

### Phase 0：Live contract 与权限证明

- 用部署 token 探测三大普通报表 endpoint 的权限、字段、边界、分片和限流。
- 保存固定的官方响应 fixtures 和重复/空值/多口径样本。
- 实测完整历史响应、共享 limiter、checkpoint 和全量刷新成本。
- 不新增 authorable field。

### Phase 1：证据层与 immutable 稀疏事实

- 将 Market Coverage 回填到 2010 年首个 Research Session，作为财务可执行
  Head 的同区间市场前提；当前仅一年开发 Bootstrap 不满足首次发布条件。
- 建立 raw accepted response objects、三张宽 Canonical version table 和新
  Generation contract。
- 实现日期到下一 Research Session、版本 identity、quarantine 和候选 family
  完整性校验。
- 实现 ordinary per-instrument Bootstrap 与手动全量 Financial Refresh。
- 所有财务字段 `authorable=false`；对象和 candidate Manifest 只能在 active
  store 旁构建、验证与回放，Phase 1 不移动 Dataset Head，也不在普通 authoring
  中暴露财务数据。

### Phase 2：可执行切片与首次发布

- 引入 caller-prepared `AlphaInputMatrix`，移除 Kernel 的 prices-only 输入假设。
- 按 [ADR-0179](../adr/0179-defer-ttm-and-start-flow-fields-from-latest-annual-reports.md)
  首先开放 `total_revenue_latest_fy`、`net_profit_parent_latest_fy`、
  `operating_cash_flow_latest_fy`、`total_assets_latest_reported`、
  `total_liabilities_latest_reported` 和 `equity_parent_latest_reported`；
  第一阶段不构造 TTM，其余完整保留的 Financial Facts 暂不自动获得
  Alpha Field Capability。
- 同一 resolver 接入 ResearchRun 与 DailyTrack。
- 实现 `cs_rank` 的完整 cross-section plan node，并用一个行情 + 财务 Composite
  Alpha 证明 ResearchRun 与 DailyTrack 一致。
- cold benchmark 达标后才决定是否需要 derived checkpoints。
- 按
  [ADR-0187](../adr/0187-publish-the-first-financial-generation-only-as-an-executable-slice.md)
  通过 ingestion、PIT、ResearchRun、DailyTrack 和性能 acceptance 后，才首次
  发布包含财务 family 的 Dataset Head，并将 Financial Research Readiness
  置为 ready；不存在 ingestion-only 的中间 Head。
- 按
  [ADR-0188](../adr/0188-expose-the-initial-financial-product-only-through-alpha-authoring-and-data-readiness.md)
  在 Alpha Editor 暴露六个字段，并在 Data Overview 展示 Financial Coverage
  与 Financial Research Readiness；首版不建设公司财报、raw batch 或任意
  Canonical 字段浏览器。

### Phase 3：事件因子与日频估值

- 分别开放 forecast/express/audit 的事件语义，不能把文本/区间强行当普通标量。
- 以独立 `equity.daily_valuation` 接入 `daily_basic`，明确 vendor-derived lineage。
- 继续按真实研究需求扩字段，而不是一次把 TuShare 数百列全部暴露给 Alpha。

## 8. 必须通过的测试与基准

- 同一报告期先发布 `100`、后修订为 `80`：修订可见前仍为 `100`，之后才为 `80`。
- 报告期 `2025-12-31`、公告 `2026-03-30`：2025 年任何 session 都不可见。
- 日期级公告跨周末/节假日时，只能从下一已完成 Research Session 可用。
- 同 payload 重抓幂等；同旧公告日 payload 静默变化从首次观察 session 生效，不回溯。
- `update_flag=1` 不得抹掉旧版本；不同 `report_type`/`comp_type` 不得互相覆盖。
- 缺失公告日期进入 quarantine，不能靠季度末 offset 补造。
- 响应达到 100/3500/6000 等上限时必须拆分或失败，禁止静默截断。
- checkpoint 与从完整事实重放的结果完全一致。
- 新 Head 发布时，已 pin 旧 Generation 的并发 ResearchRun 结果不变。
- ingestion 后但 resolver/catalog 未开放的字段不能通过 Definition admission。
- Phase 1 candidate 即使包含完整财务表，也不能移动 Dataset Head 或出现在
  Alpha Authoring Catalog；首次发布必须让六个字段同时通过 ResearchRun 与
  DailyTrack 端到端执行。
- `cs_rank` 覆盖升序、并列、全 missing、单一有效值、变化 Universe 和
  mixed market-financial Formula；同一输入的 ResearchRun 与 DailyTrack
  产生完全相同的横截面值。
- cold benchmark 覆盖全市场、多字段、长研究区间；断言没有逐 cell/逐股票文件扫描，并记录 P50/P95、读取 object 数、bytes、峰值内存。
- market-only 与 finance-only refresh 都证明未变化 family 的 Manifest/object digest 被复用。

## 9. 仍需实测确认的 caveat

1. TuShare 的普通接口权限、账号频率和实际响应边界不是跨账号稳定合同，必须以部署 token 的 live probe 为准。
2. TuShare 能保留哪些历史调整版本只能以真实响应证明；ADR-0018 禁止补造来源没有的修订链。
3. `update_flag`、重复行及相同公告日 payload 变化的真实分布需用 fixtures 验证，不能只依赖字段说明。
4. `fina_indicator` 和 `daily_basic` 是来源派生数据；若未来要求完全自有因子血缘，应从 PIT 原始报表和同期股本/价格自行计算，而不是混写两者语义。
5. TuShare [FAQ](https://tushare.pro/document/1?doc_id=122)要求公开网站或论文使用其数据时标注“数据来源：Tushare数据”。若 ThesisTrace 从本地研究工具走向公开或商业分发，上线前还应核对当时有效的服务协议和展示要求。
6. 这份研究确定了产品边界和实施顺序；最终 schema contract 标识、物理
   partition 阈值和安全 limiter 数值仍应在实现 issue 中依据探针和 benchmark
   定案，但不能改变已接受的来源、Coverage、字段语义和首次发布边界。
