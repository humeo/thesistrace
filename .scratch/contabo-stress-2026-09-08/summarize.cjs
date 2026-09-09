const fs=require('node:fs'),path=require('node:path');const d=__dirname;const read=n=>fs.readFileSync(path.join(d,n),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
const initial=read('status-final.jsonl'),comparison=read('comparison-final.jsonl');const all=[...initial,...comparison];const batches=all.filter(x=>x.request.tool==='get_research_batch');const singles=all.filter(x=>x.request.tool==='get_research_run');const children=batches.flatMap(x=>x.result.items);if(!all.every(x=>x.result.status==='succeeded')||!children.every(x=>x.status==='succeeded'))throw Error('Non-success outcome');
const eq=read('equivalence.jsonl');const equal=eq.length===4&&eq.every(x=>JSON.stringify(x.result.factor)===JSON.stringify(eq[0].result.factor));if(!equal)throw Error('Sampled factor results differ');const checks=read('result-checks.jsonl');for(const h of ['1','5'])for(const m of ['ic','rank_ic'])if(Math.abs(checks[0].result.factor.horizons[h].summary[m].mean+checks[1].result.factor.horizons[h].summary[m].mean)>1e-12)throw Error('Negation failed');
const span=rows=>(Math.max(...rows.map(x=>Date.parse(x.result.execution_timing.finished_at)))-Math.min(...rows.map(x=>Date.parse(x.result.execution_timing.started_at))))/1000;const serial=span(comparison.slice(0,2)),parallel=span(comparison.slice(2));
const stats={minAvailableKB:Infinity,maxLoad1:0,workers:{}};for(const l of fs.readFileSync(path.join(d,'resources.log'),'utf8').split('\n')){let m=l.match(/^MemAvailable:\s+(\d+)/);if(m)stats.minAvailableKB=Math.min(stats.minAvailableKB,+m[1]);m=l.match(/^(\d+\.\d+) \d+\.\d+ \d+\.\d+/);if(m)stats.maxLoad1=Math.max(stats.maxLoad1,+m[1]);m=l.match(/^(thesistrace-\S+) ([\d.]+)% ([\d.]+)(MiB|GiB)/);if(m){const w=stats.workers[m[1]]||{maxCpu:0,maxMemoryMiB:0};w.maxCpu=Math.max(w.maxCpu,+m[2]);w.maxMemoryMiB=Math.max(w.maxMemoryMiB,+m[3]*(m[4]==='GiB'?1024:1));stats.workers[m[1]]=w;}}
const summary={researchRuns:children.length+singles.length,batches:batches.length,succeeded:children.length+singles.length,failed:0,serialSeconds:serial,parallelSeconds:parallel,speedup:serial/parallel,sampledFactorResultsIdentical:equal,negationIcPassed:true,resources:stats};fs.writeFileSync(path.join(d,'summary.json'),JSON.stringify(summary,null,2));
const table=batches.map(x=>`| ${x.result.id} | ${x.result.batch_kind} | ${x.result.scope.universe} | ${x.result.items.length} | ${x.result.execution_timing.elapsed_seconds.toFixed(3)} | succeeded |`).join('\n');
fs.writeFileSync(path.join(d,'report.md'),`# Contabo 6C12G Research 压力测试（2026-09-08）

实测创建 ${summary.researchRuns} 个 Research（${batches.length} 个 Batch、${children.length} 个批次子 Research，另有 ${singles.length} 个独立回测），全部 succeeded，失败 0。经 MCP 查询每个 Batch 的所有子项终态，未把 accepted 当作完成。

## Worker 扩容结果

当前运行 2 个 batch-research-worker 和 1 个 research-worker。每个容器上限 2 CPU / 2 GiB，执行预算 1.5 GiB，calculation threads=2。使用现有 production 配置加载器执行 Compose --scale，未编辑服务代码、部署分支或生产配置，未重建原有 Worker、API、数据卷或 Dataset Head。

**扩容是本次运行态设置。仓库 deploy/compose.yaml 仍为 replicas: 1；后续常规 prod up 可能恢复 1 个。**

同一工作负载：两批各 20 因子，top1000，2026-08-03 至 2026-08-27，neutralization=none，均为相同公式、同一 Data Head（截至 2026-08-27）。

| Batch Worker 数 | 40 个 Research 的处理窗口 | 吞吐 |
|---|---:|---:|
| 1 | ${serial.toFixed(3)} 秒 | ${(40*60/serial).toFixed(2)} Research/分钟 |
| 2 | ${parallel.toFixed(3)} 秒 | ${(40*60/parallel).toFixed(2)} Research/分钟 |

本次吞吐提升 ${(serial/parallel).toFixed(2)} 倍。窗口从第一批 started_at 到最后一批 finished_at，包含串行批次间的领取等待，排除首次入队等待与 MCP 客户端启动。两批在双 Worker 下分别开始于 ${comparison[2].result.execution_timing.started_at} 和 ${comparison[3].result.execution_timing.started_at}，存在实际计算重叠。单 Worker 单批分别 ${comparison[0].result.execution_timing.elapsed_seconds.toFixed(2)} / ${comparison[1].result.execution_timing.elapsed_seconds.toFixed(2)} 秒；双 Worker 单批分别 ${comparison[2].result.execution_timing.elapsed_seconds.toFixed(2)} / ${comparison[3].result.execution_timing.elapsed_seconds.toFixed(2)} 秒。

仅一次 1→2 对照，按顺序运行且文件缓存未清除，不代表所有规模均线性加速或已测得机器极限。原始长区间批次与短区间负载曾并行，不能用二者比较速度。

## 工作负载

首批 20 因子：2025-01-02 至 2026-08-27，top1000，运行 278.860 秒。短区间为 2026-08-03 至 2026-08-27（19 个研究交易日）。覆盖动量、反转、成交量、波动率，5/10/20/40/60 窗口；top300/top1000；none/industry 中性化；策略扫描持仓 5/10/20/50/100、调仓 1/5/10/20。另有 10 个独立回测并行通过独立 research-worker 处理。所有测试名称以 STRESS-6C12G 标识，保留结果供产品内检查。

| Batch | 类型 | Universe | Research 数 | 执行秒数 | 状态 |
|---|---|---|---:|---:|---|
${table}

## 资源和可靠性

服务器 vmi3564117，6 核，物理内存 11960 MiB，无 Swap。约每 12 秒采样（docker stats 本身也耗时）。采样最低 MemAvailable ${(stats.minAvailableKB/1024/1024).toFixed(2)} GiB，最高一分钟 load average ${stats.maxLoad1}。批量 Worker 观测内存最高 ${Math.max(...Object.entries(stats.workers).filter(([k])=>k.includes('batch-research')).map(([,v])=>v.maxMemoryMiB)).toFixed(1)} MiB；独立 Worker 最高 ${stats.workers['thesistrace-research-worker-1'].maxMemoryMiB} MiB。这是采样值，不是连续峰值；CPU 百分比以单核为 100%。

最终三个 Research Worker RestartCount=0、OOMKilled=false；API/Auth/Web/PostgreSQL/RustFS 健康检查通过，磁盘约 163 GB 可用。停止了本次临时采样进程。未执行数据刷新、DailyTrack 或真实模型研究，没有改动已有研究结果。

## 结果抽查及版本核验

四个对照批次的首个因子完整 factor 返回对象完全一致；另抽查正负公式的 1d/5d IC 和 Rank IC 反号一致，抽查一份策略汇总能读取。19 日短区间的 20d 指标为 null、valid_session_count=0，属于该区间没有足够远期标签，不是执行失败。未做全部 210 份 Result 的独立重算。

扩容新容器和旧容器 image ID 不同。进一步实测 /app/src 下全部 148 个 Python 源文件内容一致，SHA256=5d734a45fc5f469ce7b740f61dc0e5d57cc64c013a8db31758c62bf4b179a019；安装依赖名称/版本清单 SHA256=61ae085ecd36fa01bf437151d7b5a94725d2bacb83c020a156f61fcf1af3c1d9。不能声称镜像二进制完全一致，未为本轮测试部署新版本。

## 证据

本目录保存请求、MCP admission、终态、代表性结果、资源采样、Worker 日志和 final-host.txt。summary.json 为机器可读汇总；summarize.cjs 可重算汇总和抽查断言。
`);console.log(JSON.stringify(summary,null,2));
