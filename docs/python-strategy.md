# Python 策略编写指南

当前协议为 `python-strategy/v5`。用户手写和其他客户端提交的程序使用同一接口：
提交 Python 源码，再设置研究日期、股票池、资金、费用与滑点。业务参数写在源码中，
没有额外的数据声明表。编辑器的「编写参考」可查看当前 SDK、字段约束和完整示例。

## 先选择需要的入口

| 需要表达的规则 | 写什么 | 返回什么 |
| --- | --- | --- |
| 根据行情直接生成各日目标组合 | `compute(data, state)` | `Targets` |
| 批量计算指标，再根据真实持仓、成交作决定 | `compute` 和 `decide(data, account, state)` | `Values`；`Decision` 或 `None` |
| 只依赖账户事件或少量当日观察 | 只有 `decide` | `Decision` 或 `None` |

不需要继承平台类、实现回测循环、写存储代码或返回状态协议包。
`compute` 中是普通 Python 和 NumPy，不会把代码翻译成公式。
批量计算不需要每日 Python 回调；平台仍按日期推进共享交易模拟器。

## 一个完整的批量策略

以下示例按 60 日动量选前 30 只股票，每 5 个研究交易日提交等权目标。
60、30、5 是作者的业务规则，不是平台固定参数。

```python
import numpy as np
from quantgrove import Targets


def compute(data, state):
    close = data.history("price.close.adjusted", lookback=60)
    now, before = close[:, 60:], close[:, :-60]
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    scores = np.full(now.shape, -np.inf)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1

    order = np.argsort(-scores, axis=0, kind="stable")[:30]
    selected = np.zeros(scores.shape, dtype=bool)
    np.put_along_axis(selected, order, True, axis=0)
    selected &= valid

    return Targets.equal_weight(
        selected,
        priority=scores,
        update=(data.session_index % 5 == 0) & selected.any(axis=0),
        reason="60-day momentum",
    )
```

`axis=0` 表示在同一日期内比较不同股票，稳定排序让同分股票按规范 ID 顺序选择。
`data.session_index` 从研究起点连续计数，不能用 `np.arange(T) % 5` 替代，
否则每个数据块都会重新启动调仓周期。

NumPy 不是强制要求。也可以用 Python 循环构造同样的矩阵，但平台不能自动把任意
逐元素循环变成向量化计算。以上示例同时处理股票和日期两个轴。

## 批量数据的轴与缺失值

设本块有 N 只股票、T 个输出日期：

| 属性或方法 | 含义 |
| --- | --- |
| `data.sessions` | T 个输出日期，按时间递增，ISO 字符串元组 |
| `data.instruments` | N 个规范股票 ID，稳定排序；不同块的股票轴可能改变 |
| `data.session_index` | T 个从研究起点开始的零基交易日序号，跟踪时继续累加 |
| `data.eligible` | N×T 的只读布尔候选资格；不保证下一开盘可成交 |
| `data.history(field_id, lookback=L)` | N×(L+T) 的只读 float64 矩阵 |
| `data.common(name, lookback=L, industry=None)` | L+T 的公共市场时间序列 |
| `data.rng(purpose, session=日期)` | 按源码、日期和用途定位的 NumPy 随机生成器 |

输出块最多 128 日；L 为 0–252。64 日输出加 60 日回看需要 124 列，
128 日输出加 60 日回看需要 188 列，这不表示输出块超限。
历史矩阵最后 T 列严格对应 `data.sessions`，前 L 列是首个输出日前的历史位置。
历史不足、尚未上市、缺失价格或财报值均用 NaN 表示；不足的前置位置不会伪造日期或填零。
批量历史的日期坐标可通过 `data.history_sessions("price.close.adjusted", lookback=L)` 读取，
与同一字段的 `history` 数组逐列对齐。不足的预热日期为 `None`；该调用复用相同的历史读取。
对输入作修改前使用 `.copy()`。

字段 ID 可从编辑器「浏览字段」查找；按入口选择「插入 compute 批量读取」或
「插入 decide 当日读取」。数据读取可由 Python 变量动态决定。
财务字段按每列对应日期的披露与修订可见性读取，不把批末财报回填到早期日期。
字段、数据版本、日期范围、股票范围和读取预算由宿主独立校验。

公共输入包括 `universe_return`、`universe_advancing_fraction`、`industry_return`、
`industry_advancing_fraction`。行业输入必须传规范 SW2021 一级行业代码。
公共序列与公式共用聚合实现，逐日采用基础股票池和历史行业成员；
不受 Framework 某个下游阶段缩小候选列表的影响。

## 目标与不更新

`Targets(weights, update=flags, priority=None, reason="...")` 的 weights 为 N×T，flags 为 T 个布尔值。
权重必须有限、非负，每个提交日期的总权重不超过 1；剩余权重留为现金。
没有列出的持仓退出。平台不自动归一化、裁剪或给超额权重留容差。
`priority` 可选，为 N×T 数值矩阵，已选股票的值必须有限；数值越大，买入顺序越靠前，
同值按规范股票 ID 排序。省略时按股票 ID 顺序买入。资金或交易单位受限时，顺序会影响
成交，因此要复现公式的按排名选股策略，应像上例传 `priority=scores`，只匹配权重还不够。
每日 `target_weights` 等辅助函数按传入映射的插入顺序表达同样的买入优先级。
等权组合优先使用 `Targets.equal_weight`，平台按被选股票数构造精确份额。

- `update[t] = False`：本日没有新目标，不重放上一个目标。
- `update[t] = True` 且整列为零：明确要求清仓。
- `update[t] = True` 且有正权重：提交新的完整组合。

收盘形成目标，下一交易日开盘尝试成交。停牌、涨跌停、交易单位、现金和费用都可能
使实际成交不同于目标。最终研究日的目标作为待执行目标保存，逐日跟踪继续处理。

## 需要真实账户反馈时

计算与账户决策必须分别表达。以下完整示例批量计算动量，只在每 5 日检查时，
将当前实际持仓与当日最优股票比较；相同持仓不重复提交目标。

```python
import numpy as np
from quantgrove import Values, target_weights


def compute(data, state):
    close = data.history("price.close.adjusted", lookback=60)
    now, before = close[:, 60:], close[:, :-60]
    valid = data.eligible & np.isfinite(now) & np.isfinite(before) & (before > 0)
    scores = np.full(now.shape, np.nan)
    np.divide(now, before, out=scores, where=valid)
    scores -= 1
    return Values({"momentum": scores, "rebalance": data.session_index % 5 == 0})


def decide(data, account, state):
    if not data.values["rebalance"].item():
        return None
    scores = data.values["momentum"]
    valid = np.isfinite(scores)
    if not valid.any():
        return None
    best = data.instruments[int(np.argmax(np.where(valid, scores, -np.inf)))]
    held = [position["instrument_id"] for position in account.positions]
    if held == [best]:
        return None
    state["changes"] = state.get("changes", 0) + 1
    return target_weights({best: 1.0})
```

有 `decide` 时，`compute` 必须返回 `Values`，不能同时提交 Targets。
Values 可包含命名的 N×T 股票矩阵或 T 元素时间向量；允许 NaN 表示缺失，禁止无穷值。
`decide` 的 `data.values` 只有当日列，股票值按其 `data.instruments` 排列；
该轴包含当日可见候选及实际持仓。决策实例与计算实例不共享作者对象或 ndarray 的底层缓冲。

`decide` 中还有 `data.session`、`completed_sessions`、`candidates`、`candidate_details`，
以及截至当前收盘的 `data.history(field_id, days, instruments=...)` / `close_prices(days)`。
这些每日读取返回 `History`，其 `.array` 为股票×实际返回日期，`.sessions`、`.instruments`
提供坐标；键控视图 `history[股票]` 的缺失值为 None。每日读取可能少于请求的天数。
每日显式股票列表只能来自当前候选和持仓，不能申请未来日期。

`account` 是只读的真实模拟账户，提供 `cash_cny`、`positions`、`fills`、`rejections`、
`post_open_net_nav_cny`、`close_risk_nav_cny`。持仓包括实际股数 `execution_shares`、
成本、收盘价格和 `holding_age`。金额和精确账务量用十进制字符串表示，算术可用 `Decimal`。

每日决策辅助函数均从 `quantgrove` 导入，只构造结果；最终返回的结果才被提交：

| 返回 | 行为 |
| --- | --- |
| `None` | 不更新 |
| `target_weights(weights)` | 整体组合目标；`{}` 明确清仓 |
| `increase_to_weights(weights)` | 只向目标加仓，不卖出其他持仓 |
| `reduce_exposure(maximum)` | 按比例降低现有持仓，不买入 |
| `limit_positions({股票: 股数})` | 限制指定实际持仓，其余不变 |
| `limit_exposure(maximum)` | 追加总仓位上限 |
| `with_limits(decision, maximum_shares=..., maximum_exposure=...)` | 与已有更严格的限制取交集 |

## 连续记忆、恢复和跟踪

修改平台传入的 `state` 映射，例如 `state["days"] = state.get("days", 0) + T`。
支持 JSON 标量、列表、字符串键字典，以及受限的数值/布尔 ndarray；不用 pickle。
JSON 数值必须有限，整数范围为 `-(2**53-1)` 至 `2**53-1`；更大的标识值可保存为字符串。
ndarray 保留数值 dtype，最多 4 个轴；对象数组和任意 Python 对象不接受。
不要通过 `state = {...}` 重新绑定局部变量来保存记忆，应使用索引赋值或 `state.update(...)`。

compute 和 decide 分别有独立 state。块末计算状态不会提前暴露给本块早期的账户决策。
影响将来输出的记忆必须放进 state；全局变量、闭包、生成器、文件句柄和进程现场不持久化。
数字数组的行号也不是永久股票身份：跨块保存按股票组织的数组时，同时保存对应 ID 并重新对齐。

程序的私有执行会话可复用已装载代码和缓存；检查点或恢复可能重新装载它。
平台在完成一个块后原子保存账户、待执行目标和程序状态；失败时丢弃未提交部分，
从上个检查点重算。因此不要依赖「源码只执行一次」或自行产生外部副作用。
每日跟踪追加一天就是同一接口的 T=1，使用同一数据口径、状态和交易模拟器。

## 因果性和可重复性

每个日期的输出只能使用截至该日期的观察和先前状态。多日原生 NumPy 能读取整个块，
所以只读属性不能阻止偷看未来。例如用 `close[:, -1]` 生成本块所有日期的选择，
或沿整个时间轴求均值后回填早期日期，都会产生未来信息偏差。
只给 decide 当日计算值也无法修正 compute 中已经混入的未来信息。

平台对每个多日计算块额外重算首日和中点前缀，并拒绝已发现的输出差异；验证调用不提交状态。
这增加少量计算开销，不能覆盖所有未来信息偏差。发布前还应扰动未来价格/成员，并比较 64、128、逐日追加与恢复的
规范目标、状态及账户轨迹。有限样本通过不等于任意 Python 程序的因果性证明。
「检查配置」校验语法、入口和装载，不执行全部动态分支，也不证明因果性。

随机策略使用 `data.rng("selection", session=日期)` 为每个日期取得独立、可重放的源。
批量入口必须明确日期；每日入口默认当前日期。用途名称应稳定且非空。
不要依赖全局 RNG 的批量消耗顺序，否则改变 T 会改变路径。
时钟固定在操作末日的模拟收盘，不能用当前时钟代替批量日期轴。

相同 Python 程序应不受切分影响。公式与 Python 的数学表达即使等价，浮点归约顺序、
缺失处理和并列排序不同仍可能改变临界排名；平台不会仅凭策略名称承诺两种源码逐项精确相等。

## 限制与错误

| 资源 | 当前限制 |
| --- | --- |
| 输出日期 / 额外回看位置 | 128 / 252 |
| compute 单次 / 累计读取数据格 | 2,097,152 / 4,194,304 |
| decide 单次 / 累计读取数据格 | 262,144 / 1,048,576 |
| 每调用读取次数 / 累计编码响应 | 64 / 32 MiB |
| 源码 / 诊断输出 | 各 64 KiB |
| 完整调用输入 / 输出 | 4 MiB / 16 MiB |
| 持久状态 | 编码后 256 KiB；计算与决策状态还受终端状态总预算约束 |
| 单 guest 线性内存 | 128 MiB |
| 初始化 / 用户执行时限 | 10 秒 / 3 秒 |
| 整个研究任务内存硬上限 | 2 GiB；监督进程另有更早的保护阈值 |

128 日不是内存保证。股票数量、字段数量、回看窗口、临时数组、输出和状态共同占用预算。
超限调用明确失败，已提交检查点保留；不要用无界全历史驻留换取速度。
可导入固定环境中的 NumPy 及支持的标准库；不支持网络、宿主文件、安装包、Pandas、子进程或 ctypes。
环境为 CPython 3.14.0 / NumPy 2.5.0 WASI / Wasmtime 49.0.0，无外部 BLAS。

错误尽量包含源码摘要、日期和作者行号。结果的「交易明细 → Python 数据读取」
记录已接受读取的字段、范围和字节数，并区分 compute 与 decide。

## Framework、版本和复用

Framework 的四个业务步骤都使用同一个函数协议，可选 compute 返回 Values，必需 decide：
选股返回 `select(...)`；信号返回 `signals(..., valid_for_sessions=...)`；组合返回目标辅助函数；
风控返回 `risk_limits(...)` 或 `replace(...)`。`replace(None)` 取消本次组合建议，None 放行。
`data.framework` 提供本步可见的选股、信号和组合建议；保留的旧建议仅供观察，不自动重放。
这四个步骤不决定底层 Python 的计算方式。

HTTP/MCP 使用 `program: {"source": "..."}`；Framework 槽位使用
`{"kind": "python", "program": {"source": "..."}}`。无需提交参数或数据声明对象。
Run 冻结源码、数据和环境身份，编辑或复制为草稿不会修改历史结果或已有跟踪。
新环境拒绝旧版 class/on_close 源码及旧冻结运行环境，不在运行时自动转换、清库或回退。
升级前应完成待处理任务并显式处理旧 DailyTrack，API 和 Worker 必须使用同一版本。
旧 Python 研究结果仍可查看；若其冻结环境已经过期，开始跟踪会明确拒绝，
提示先更新源码、运行新草稿，再基于新结果开始跟踪。

手动更新旧程序时，把 `on_close` 中依赖账户的逻辑移到模块级
`def decide(data, account, state)`；将 `self.target_weights(...)` 等调用改为导入同名函数，
将需要保存的 `self` 属性改为传入的 `state`。只做这一步仍是逐日决策；
要获得批量收益，应把与账户无关的历史计算移入 `compute`，返回多日 Targets，
或返回 Values 供 decide 读取。用新草稿检查并运行，保留旧研究结果作为对照。

实现决策见 [ADR-0258](adr/0258-batch-python-computation-and-account-decisions.md)。
验证入口和选择只维护在 [AGENTS.md](../AGENTS.md#testing)。
