# 2026-08-27 ThesisTrace 高性价比云服务器候选

资料截止日期：2026-08-27。本文只使用厂商官网价格页、规格页和官方文档；无法从第一方页面同时确认当前价格、规格与购买条件的产品，不进入最终排名。

## 结论

如果欧洲时延可接受，首选 **netcup RS 2000 G12**：8 个专用 AMD EPYC 核、16 GB 内存、512 GB NVMe，按 12 个月购买为 €21.43/月（含页面所示 19% VAT），这是本轮唯一在低价位明确给出专用 CPU 核的候选。建议先选 1 个月合同（€25.72/月）完成持续 CPU、磁盘和网络验收，再决定是否改买长约。

如果必须放在亚洲，首选 **OVHcloud Singapore VPS-4**：8 vCore、24 GB、200 GB NVMe，官网入口价 S$30/月（未含 GST），但该价格链接明确选择了 12 个月预付，且新加坡每月 3 TB 后会降至 10 Mbps。它比欧洲候选更靠近中国和东亚用户，但 CPU 是否能长期满载没有公开保证。

如果只想低成本试运行，选 **netcup VPS 2000 G12 OpenClaw Special**：€22.15/月、按小时计费、无最低合同期，配置为 8 个共享 vCore、16 GB、512 GB NVMe。它适合一个月验收，不应把共享 vCore 当成 8 个专用核。

**不建议直接购买淘宝“8 核 16 GB、峰值 20 Mbps、80 GB、¥21/月”的长约。** 这个价格并不能证明欺诈，但卖家没有说明底层厂商、CPU 是否共享、持续 CPU 限速、独立 IPv4、月流量、续费价和账号归属之前，无法与正规 VPS 作同类比较。80 GB 还要同时容纳系统、镜像、PostgreSQL、RustFS、日志和数据，对单机 ThesisTrace 也偏紧。

## 为什么以 8 vCPU / 16 GiB 为付费起点

当前 [`deploy/core/compose.yaml`](../../deploy/core/compose.yaml) 同时定义 research、batch-research、tracking 三个 Worker；每个默认限制为 2 CPU、2 GiB 内存，其中执行预算为 1.5 GiB。仅三个 Worker 的资源上限合计就是 6 CPU、6 GiB，此外还需运行 PostgreSQL、RustFS、API、Web、初始化任务、内核页缓存和 Docker。

因此：

- 8 vCPU / 16 GiB 是单机部署的合理起点，不是富余配置；
- 4 vCPU / 8 GiB 只适合减少并发、停掉部分 Worker 的开发或小规模试运行；
- 8 vCPU 如果是共享、突发或有持续利用率限速，不能等同于 8 个专用核；
- 80 GB 系统盘在没有实测数据集、结果和日志增长之前，不宜承诺足够。

## 最终候选

| 排名 | 产品与定位 | 区域 | CPU / 内存 / 磁盘 | 网络与 IP | 当前可核价格与合同 | 主要限制 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | netcup RS 2000 G12，持续计算首选 | 欧洲自动分配：奥地利、德国或荷兰 | 8 个专用 AMD EPYC 9645 核；16 GB DDR5 ECC；512 GB NVMe | 2.5 Gbps；流量不限量；过去 24 小时超过 3 TB 时临时降至 300 Mbps；公共 IPv4 + /64 IPv6 包含 | 12 个月 €21.43/月，合计 €257.16；1 个月合同加 €4.29，即 €25.72/月；均为页面所示含 19% VAT | 欧洲到中国时延；位置自动分配；产品页提示部分位置可能缺货或延迟交付；没有确认包含异地自动备份 |
| 2 | OVHcloud Singapore VPS-4，亚洲首选 | 新加坡 | 8 vCore；24 GB；200 GB NVMe | 3 Gbps；每月 3 TB 后降至 10 Mbps；独立 IPv4 和 IPv6 包含 | S$30/月起、未含 GST；配置器为 12 个月预付，折算年度 S$360 未含 GST | 仅称 CPU“虚拟隔离”，未承诺专用物理核或公布持续 CPU 阈值；公开页未显示续费价；备份仍在同一数据中心 |
| 3 | netcup VPS 2000 G12 OpenClaw Special，灵活验收首选 | 欧洲自动分配：纽伦堡、维也纳或阿姆斯特丹 | 8 个共享 vCore，KVM；16 GB DDR5 ECC；512 GB NVMe | 2.5 Gbps；过去 24 小时平均超过 2 TB 时临时降至 200 Mbps；公共 IPv4 + /64 IPv6 包含 | €22.15/月（页面所示含 19% VAT）；按小时计费；0 个月最低合同期；€0 设置费 | 限量特价、售完即止；CPU 核不专用，厂商给 VPS 的最低可用性为 99.6%，低于 Root Server 的 99.9% |
| 4 | 腾讯云轻量应用服务器 4 核 8 GB 免费试用，仅用于中国内地验收 | 具体可选地域以申领页库存为准 | 4 核 Intel Xeon；8 GB；180 GB SSD | 12 Mbps；2,000 GB/月；每台轻量服务器默认 1 个独立公网 IP | 1 个月免费；每日限量、先到先得 | 不满足完整 8c16g 基线；试用页未公布持续满载 CPU 政策；试用后不能把其他规格的续费折扣套用到本产品；备份点另计费；中国内地上线公网网站还涉及备案 |
| 5 | Oracle OCI Always Free A1，仅用于 Arm 开发/轻量服务 | 账号 Home Region；资源受区域容量影响 | 合计 2 OCPU、12 GB，Ampere Arm；200 GB 启动盘与块存储总额 | 每月 10 TB 出站；可在公共子网分配公共 IP | $0，账号存续期间的 Always Free 配额 | 不是旧资料常写的 4 OCPU / 24 GB；可能无容量；连续 7 天同时满足低 CPU、低网络、低内存会被回收；Arm 镜像必须先通过生产镜像 Smoke Test；不足以原样跑当前完整 Compose |

> 税费提示：netcup 页面按德国 19% VAT 展示，并说明会依客户居住国变化；OVHcloud 新加坡页明确未含 GST。本文不使用临时汇率把不同币种强行换算成人民币，最终应比较结算页总额、银行卡汇率和税费。

## 候选详情

### 1. netcup RS 2000 G12

官方产品页当前列出 [8 个专用 AMD EPYC 9645 核、16 GB DDR5 ECC、512 GB NVMe、2.5 Gbps 接口、流量不限量和 Copy-On-Write 快照](https://www.netcup.com/en/server/root-server/rs-2000-g12-ip-iv-12m)（检索日期：2026-08-27）。同页给出：

- 12 个月合同与账期，€21.43/月，页面总价可按 €21.43 × 12 = €257.16 计算；
- 1 个月合同加 €4.29，即 €25.72/月；
- “No preference Europe”不加价，由奥地利、德国或荷兰自动分配；新加坡加 €27.37/月，导致同规格达到 €48.80/月，不再有价格优势；
- 公共 IPv4 与 /64 IPv6 不加价；只要 IPv6 可减 €0.60/月；
- 过去 24 小时流量超过 3 TB 时暂时降至 300 Mbps；
- 首次订单有 30 天满意保证，产品页也提示高需求可能延迟交付、部分位置可能暂时不可用。

netcup 官方的[服务器类型对比](https://www.netcup.com/en/helpcenter/documentation/server)（检索日期：2026-08-27）明确区分：Root Server 提供专用 CPU 核，VPS 不提供；最低年可用性分别为 99.9% 与 99.6%。这使 RS 2000 G12 比同价共享 VPS 更适合研究计算和批处理。

风险与购买建议：

- 官网没有把 €21.43 标注为“首期特价后跳价”，但也不应据此假设未来续费永不调价；下单时保存订单价格、合同期和自动续费条款；
- Copy-On-Write 快照是回滚能力，不等于独立异地备份；PostgreSQL、RustFS 和 canonical data 仍需定期备份到另一家对象存储；
- 先购买 1 个月，连续压测 CPU 至少数小时并运行真实研究作业；通过后，12 个月相对月付约节省 16.7%。

### 2. OVHcloud Singapore VPS-4

OVHcloud [新加坡 VPS-4 官方页](https://www.ovhcloud.com/en-sg/vps/vps-singapore/)（检索日期：2026-08-27）列出 8 vCore、24 GB RAM、200 GB NVMe、3 Gbps 公网带宽、每日备份和 S$30/月起（未含 GST）。其“Configure”链接生成的[官方配置器](https://www.ovhcloud.com/en-sg/vps/configurator/?brick=VPS%2BModel%2B4&planCode=vps-2027-model4&pricing=upfront12&processor=+&storage=200__SSD__NVMe&vcore=8__vCore)带有 `pricing=upfront12`，所以 S$30 是 12 个月预付的月均价，年度基础价为 S$360，不能当作随时取消的月付价。

网络页面虽然写“Unlimited traffic”，但同页脚注明亚太区限制：新加坡、孟买、悉尼的 VPS-4 每月配额为 3 TB，超过后带宽降至 10 Mbps。3 Gbps 是端口上限，不是保证持续吞吐。

OVHcloud [全球 VPS 功能页](https://www.ovhcloud.com/en/vps/)（检索日期：2026-08-27）还确认：

- 独立 IPv4、IPv6、Anti-DDoS、KVM 控制台和 99.9% SLA 包含；
- 标准备份每天执行，不包括附加磁盘，滚动 7 天，并在**同一数据中心**复制三份；
- CPU 描述为“virtually isolated”，没有公开说明是专用物理核，也没有给出可长期 100% 使用的阈值。

风险与购买建议：

- 公开价格页没有展示 1 个月价格、到期续费价或续约期限；下单前必须在新加坡站结算页逐项截图确认；
- 同机房三副本不能覆盖数据中心级故障、账号冻结或误删，应保留异地应用级备份；
- 如果主要用户在中国内地，先从目标运营商实测新加坡方向的晚高峰时延、丢包和回程，不能只看“3 Gbps”。

### 3. netcup VPS 2000 G12 OpenClaw Special

[官方特价页](https://www.netcup.com/en/server/vps/vps-2000-g12-iv-hourly-based-openclaw-special)（检索日期：2026-08-27）确认：8 vCore、16 GB DDR5 ECC、512 GB NVMe、KVM、欧洲自动分配、€22.15/月（页面所示含 19% VAT）、按小时计费、无最低合同期、无设置费，并包含公共 IPv4 + /64 IPv6。

它适合作为付费验收环境，原因是可以快速删除止损；但不适合作为“8 个稳定计算核”的纸面承诺：netcup 官方对比表明确 VPS 的 CPU 核不专用，产品页也没有给出可持续满载的最低性能保证。网络有明确公平使用边界，过去 24 小时平均流量超过 2 TB 时会暂时降至 200 Mbps。

该产品写明“only while supplies last”，不能作为长期容量规划中必然仍可增购的规格。快照和控制台虽包含，仍需另做数据库与对象数据异地备份。

### 4. 腾讯云免费试用与付费价锚点

腾讯云[免费体验馆](https://cloud.tencent.com/act/pro/free?productSlug=trabbit)（检索日期：2026-08-27）列出 4 核 8 GB、12 Mbps、180 GB SSD、2,000 GB 流量包的轻量应用服务器，试用 1 个月，每日限量、先到先得。官方[基本概念](https://cloud.tencent.com/document/product/1207/79254)说明每台轻量应用服务器创建后默认分配 1 个独立公网 IP。

这适合完成 x86 生产镜像启动、Compose 配置、数据恢复和基本用户闭环验收，但 CPU 与内存都低于完整部署起点。试用页面没有给这项 4c8g 产品承诺具体续费价，也没有公开说明可持续满载 CPU 的阈值，不能把同页其他规格的“续费 1 年 3.5 折”推断到它。

作为付费价锚点，腾讯云[轻量应用服务器价格总览](https://cloud.tencent.com/document/product/1207/73452/)（检索日期：2026-08-27）当前给出：

- 中国内地通用型 8c16g、270 GB SSD、18 Mbps、3,500 GB/月为 ¥500/月；12 个月及以上新购和续费均为 85 折，即 ¥5,100/年、月均 ¥425；
- 海外通用型 8c16g、300 GB SSD、45 Mbps、7,168 GB/月为 ¥530/月；
- 香港通用型 8c16g、300 GB SSD、40 Mbps、7,168 GB/月为 ¥650/月；
- 中国内地、海外和香港的备份点配额分别为 ¥0.10/GB/月、¥0.11/GB/月；套餐外流量另计费。

这些正式刊例价远高于欧洲候选，因此付费腾讯云只有在中国内地网络、备案、人民币付款和国内支持的价值明显高于计算成本时才合理，不进入付费性价比前三。

### 5. Oracle OCI Always Free

Oracle 的 2026 年官方文档已经把 Ampere A1 Always Free 改为每月 1,500 OCPU 小时和 9,000 GB 小时，等价于**合计 2 OCPU、12 GB 内存**，不是大量旧文章仍写的 4 OCPU、24 GB。[Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)（检索日期：2026-08-27）同时确认：

- 必须在账号 Home Region 创建，最多拆成两台，总额仍为 2 OCPU / 12 GB；
- A1 是 Arm 架构；200 GB 为启动盘与块存储合计，并包含最多 5 个卷备份；
- 每月包含 10 TB 出站流量；
- 资源不足会出现 `out of host capacity`；
- 若连续 7 天 CPU P95、网络和 A1 内存利用率都低于 20%，实例可能被 Oracle 回收。

Oracle [Free Tier 文档](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm)还说明免费试用结束后，应把 A1 总量降至 2 OCPU / 12 GB，否则超额实例会被禁用并在 30 天后删除。

因此 OCI 只适合低成本 Arm 兼容性测试、静态站或辅助服务。当前完整 ThesisTrace Compose 需要更多 CPU，而且 RustFS、PostgreSQL、Python/Rust 依赖和最终生产镜像都必须先在 Arm 上做 Production Image Smoke Test，不能直接假设兼容。

## 不进入最终排名的产品

### Hetzner Cloud

Hetzner 的 8 vCPU / 16 GB `CX43` 和 Arm `CAX31` 原本很有价格竞争力，但[当前 Cost-Optimized 官方页](https://www.hetzner.com/cloud/cost-optimized/)（检索日期：2026-08-27）对所有该档实例显示 `not available`，并说明这类旧硬件资源数量有限，只适合低到中等 CPU、能接受波动的测试负载。既然当前不能可靠创建，就不列入“仍可购买”的排名。

2026-06-15 调价后的常规 CPX 8c16g 价格显著上升；[官方调价文档](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)也明确新订单已执行新价格。不能再引用调价前博客或历史价作为当前报价。

### Contabo

Contabo 的[当前服务器组合说明](https://help.contabo.com/en/support/solutions/articles/103000408463-can-i-get-more-information-about-contabo-s-server-portfolio-)（检索日期：2026-08-27）已经使用 Core VPS / Performance VPS 新命名，而可抓取的公开价格信息仍混有旧 Cloud VPS 组合，无法把当前规格、地区附加费和结算总价可靠对应。官方[流量政策](https://help.contabo.com/en/support/solutions/articles/103000271195-are-there-any-bandwidth-or-traffic-limits-at-contabo-)又保留按公平使用自行限速的权利，未给固定阈值。按本文规则，不把无法闭环核价的产品列入排名。

### Hostinger

Hostinger [VPS 价格页](https://www.hostinger.com/vps-hosting?lang=en)（检索日期：2026-08-27）显示 KVM 4 为 4c16g、200 GB、16 TB，优惠折算 $12.99/月，续费为 2 年 $28.99/月；KVM 8 为 8c32g、400 GB、32 TB，优惠折算 $25.99/月，续费为 2 年 $49.99/月。页面明确所有方案预付、月价只是总价除以月数，但静态页没有明确优惠首期对应多少个月，因此无法严谨计算首期应付总额。

更重要的是，Hostinger 的[官方 CPU 政策](https://www.hostinger.com/support/6899741-what-is-the-cpu-use-limit-for-vps-at-hostinger/)（检索日期：2026-08-27）说明持续高 CPU 会触发自动限速，每小时减少 25% CPU 容量，且用户每周只能自行解除一次；页面没有公布具体触发时长。对于长时间研究计算，这个风险高于纸面核数的吸引力。

其[备份文档](https://www.hostinger.com/support/1583232-how-to-back-up-or-restore-a-vps-at-hostinger/)确认默认每周备份、最多保留 4 份；手动快照只能有 1 份且 1 天过期。综合首期合同不透明、续费跳价和持续 CPU 限速，不进入最终前三。

此外，[官方机房列表](https://www.hostinger.com/support/1583267-where-are-hostinger-servers-located/)（检索日期：2026-08-27）当前把亚洲 VPS 位置列为印度、印度尼西亚和马来西亚，没有列新加坡；购买时不能依据旧评测假设仍可选新加坡。

### 阿里云

阿里云活动页的当前 8c16g 活动价、适用身份和续费价需要登录购买控制台才能确认，公开静态页面无法完成同口径核价。[轻量应用服务器计费 FAQ](https://help.aliyun.com/zh/simple-application-server/product-overview/billing-faq)（检索日期：2026-08-27）能确认包年包月、流量和快照规则，但不能证明某个当前 8c16g 活动价；[ECS 价格页](https://ecs-buy.aliyun.com/price)也不能替代具体地区、实例族、系统盘和带宽的结算价。因此不把第三方宣传的“新客价”纳入排名。

### 淘宝 ¥21/月 8c16g 套餐

这不是可由厂商第一方验证的产品，不能排名。即使能正常开机，也可能是：共享 CPU 高超售、促销实例转租、NAT IPv4、峰值而非保证带宽、短期首月价、只给面板子账号、卖家可随时收回账号，或违反上游转售条款。任何一种都可能让“8c16g”失去可比性。

## 淘宝卖家必须回答的问题

购买前要求卖家把答案写在聊天记录或订单备注中，并提供上游控制台截图；不能只接受“稳定”“独享”“不限流量”这类形容词。

1. **上游与所有权**：上游厂商、产品全名、机房城市、实例 ID；买家是否拥有上游主账号，还是只有卖家面板；卖家停业后能否直接续费和找上游支持。
2. **CPU**：具体 CPU 型号；8 核是专用物理核、专用 vCPU、共享 vCPU 还是突发核；虚拟化类型；可否持续 100% 使用；公平使用阈值、限速方式、CPU steal 和超售比例。
3. **内存**：16 GB 是否硬保证；是否 balloon、突发内存或依赖 swap；超限后是 OOM、限速还是停机。
4. **磁盘**：80 GB 是 NVMe、SSD 还是机械盘；是否本地盘；可用容量、IOPS/吞吐限制、RAID/多副本、磁盘故障责任、能否扩容。要求提供 `fio` 规则允许范围，而不是只看一次跑分。
5. **网络**：20 Mbps 是入站、出站还是双向；保证值还是共享端口峰值；每月流量包、超量单价和限速值；中国内地回程线路、晚高峰丢包；提供测试 IP 或 Looking Glass。
6. **公网 IP**：是否独立、固定、可直接入站的 IPv4；是否 NAT、共享端口或需另付费；IPv6；IP 被封、被墙或黑名单时能否免费更换；25、80、443 等端口限制。
7. **价格与合同**：¥21 是首月、首年折算还是长期月付；最低预付期、设置费、续费价、涨价规则、退款窗口、缺货替换规则；是否能开票。
8. **系统权限**：完整 root、重装系统、救援模式、VNC/KVM、反向 DNS、自定义 ISO、Docker 和 TUN/TAP 是否可用。
9. **备份与恢复**：快照数量、频率、保留期、是否异地、是否额外收费；卖家删机或上游封号后如何导出数据；恢复时长与责任边界。
10. **合规与支持**：SLA、故障赔偿、工单响应；禁止的应用；DDoS 触发后的处理；中国内地机房的备案条件；账号实名认证和数据访问主体。

如果卖家拒绝回答第 1、2、5、6、7、9 项，或只能让买家一次性付一年，不应购买。

## 购买与验收顺序

1. 优先购买可按小时或 1 个月取消的实例；不要先为纸面折扣支付一年或两年。
2. 用最终 Production Image 做启动、健康检查、API、三个 Worker、PostgreSQL 和 RustFS 的完整 Smoke Test；Arm 候选必须单独通过，不能用 x86 结果代替。
3. 在厂商允许范围内连续运行 CPU 和磁盘测试，并运行至少一次真实数据更新、研究和 tracking；同时记录 `steal`、CPU 频率、RSS、磁盘延迟、错误和任务总时长。
4. 从目标用户网络在工作日晚高峰测试时延、丢包、上下载和跨境稳定性；“峰值 20 Mbps”或“3 Gbps 端口”都不能替代实测。
5. 验证公网 IPv4、DNS、TLS、80/443 入站、SMTP 限制、防火墙、重装和救援控制台。
6. 做一次 PostgreSQL、RustFS 和 canonical data 的异地备份与空机恢复演练；厂商快照不能成为唯一副本。
7. 验收通过后再决定长约；保存首期总价、税费、续费价、自动续期、取消截止日和资源公平使用政策的截图。

## 最终决策

- **欧洲可接受、研究计算为主**：买 netcup RS 2000 G12 的 1 个月合同；验收通过后再考虑 12 个月。
- **亚洲低时延优先**：在 OVHcloud 新加坡结算页确认 S$360 未含 GST 的 12 个月总价和续费条款，再买 VPS-4。
- **只做一个月、需要 8c16g 纸面规格**：netcup VPS 2000 G12 Special，但用真实作业验证共享 CPU，不把它当专用核。
- **只想先验证部署**：有资格就申领腾讯云 4c8g 一个月试用；Oracle A1 只用于 Arm 兼容性和轻量服务，不承载完整生产单机。
- **淘宝 ¥21 套餐**：只有在卖家完整回答清单、允许月付、给独立上游账号，并通过与正规候选同一套验收后，才可把它当临时测试机；仍不应保存唯一数据副本。

## netcup 产品线补充核对：ARM、VPS、VPS Lite 与 Root Server

补充核对日期：2026-08-28。本节 netcup 的价格、规格、合同、网络和可售状态均来自 netcup 官方产品页或官方文档；页面价格按德国 19% VAT 展示，实际税额仍以购买者地区和结算页为准。

### 先澄清产品名称与虚拟化边界

- netcup 当前的 x86 产品分为 **VPS Lite G12s**、**常规 VPS G12** 和 **Root Server G12**。当前 [VPS Lite G12s](https://www.netcup.com/en/server/vps-lite)、[VPS G12](https://www.netcup.com/en/server/vps) 和 [Root Server G12](https://www.netcup.com/en/server/root-server) 都是 KVM 虚拟机，不是裸金属服务器（检索日期：2026-08-28）。
- “Root Server”在 netcup 的语境里仍运行在与其他虚拟机共享的宿主机上，但其预订的 CPU 核与 RAM 有保证；VPS 的 CPU 核不专用。netcup 的[官方服务器对比](https://www.netcup.com/en/helpcenter/documentation/server)还给出 VPS 99.6%、Root Server 99.9% 的最低年可用性（检索日期：2026-08-28）。因此不能把 8 个 VPS vCore 当作 8 个可持续占满的专用核，也不能把 Root Server 当作独占整台物理机。
- netcup 当前 ARM 目录仍是 **VPS ARM G11**，不是 ARM G12。官方 [ARM 产品页](https://www.netcup.com/en/server/arm-server)明确显示全部 ARM VPS 当前已售罄；目录价格只能作历史/产品口径参考，不能作为“现在可以买”的候选（检索日期：2026-08-28）。
- netcup 禁用 SVM 等嵌套虚拟化，但[官方文档](https://www.netcup.com/en/helpcenter/documentation/server)明确推荐 Docker 或 Podman。ThesisTrace 使用 Docker Compose，不依赖在云主机里再运行 KVM，因此这一限制不影响当前部署方式（检索日期：2026-08-28）。

### 当前 G12 产品梯级

- [VPS Lite G12s](https://www.netcup.com/en/server/vps-lite) 共四档：Lite 1 为 2c4g/80 GB SSD、€4.88/月；Lite 2 为 4c8g/160 GB SSD、€7.92/月；Lite 3 为 8c16g/320 GB SSD、€13.89/月；Lite 4 为 16c32g/640 GB SSD、€25.72/月（检索日期：2026-08-28）。它们是成本优化的 x86 VPS，位置由纽伦堡、维也纳或阿姆斯特丹自动分配。
- [常规 VPS G12](https://www.netcup.com/en/server/vps) 共五档：VPS 500 为 2c4g/128 GB NVMe、€5.91/月起；VPS 1000 为 4c8g/256 GB、€10.37/月起；VPS 2000 为 8c16g/512 GB、€19.25/月起；VPS 4000 为 12c32g/1 TB、€32.41/月起；VPS 8000 为 16c64g/2 TB、€47.95/月起（检索日期：2026-08-28）。这些均为共享 x86 vCore，并可选按小时计费。
- [Root Server G12](https://www.netcup.com/en/server/root-server) 共四档：RS 1000 为 4 个专用核/8 GB/256 GB NVMe、€12.79/月起；RS 2000 为 8 个专用核/16 GB/512 GB、€21.43/月起；RS 4000 为 12 个专用核/32 GB/1 TB、€39.92/月起；RS 8000 为 16 个专用核/64 GB/2 TB、€71.36/月起（检索日期：2026-08-28）。G12 Root Server 使用 AMD EPYC 9645、DDR5 ECC、NVMe 和 KVM。

### 8c16g 同档逐项对比

| 产品 | 架构、CPU 与虚拟化 | 内存与系统盘 | 网络公平使用边界 | 合同与当前价格 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| [VPS Lite 3 G12s](https://www.netcup.com/en/server/vps/vps-lite-3-g12s-iv-2m) | x86；8 个共享 vCore；KVM | 16 GB；320 GB SSD | 1 Gbps 接口；过去 24 小时平均超过 100 Mbps 时临时限制为 100 Mbps | €13.89/月；最低合同期和账期均为 2 个月，最低基础支出 €27.78；IPv4 + /64 IPv6 不加价 | 可加入购物车；欧洲位置自动分配；不能用代金券 |
| [VPS 2000 G12](https://www.netcup.com/en/server/vps/vps-2000-g12-iv-12m) | x86；8 个共享 vCore；KVM | 16 GB DDR5 ECC；512 GB NVMe | 2.5 Gbps；过去 24 小时超过 2 TB 时临时限制为 200 Mbps | 12 个月配置页为 €19.24/月、合计 €230.88；无最低期的按小时方案加 €2.91/月，即 €22.15/月上限；IPv4 + /64 IPv6 不加价 | 当前可下单，但页面提示高需求可能延迟，部分指定位置暂时不可用 |
| [VPS 2000 G12 OpenClaw Special](https://www.netcup.com/en/server/vps/vps-2000-g12-iv-hourly-based-openclaw-special) | 与常规 VPS 2000 相同：x86、8 个共享 vCore、KVM | 16 GB DDR5 ECC；512 GB NVMe | 2.5 Gbps；过去 24 小时超过 2 TB 时临时限制为 200 Mbps | €22.15/月；按实际使用小时结算；0 个月最低合同期、€0 设置费；IPv4 + /64 IPv6 不加价 | 限量特价，售完即止；不能与代金券叠加 |
| [RS 2000 G12](https://www.netcup.com/en/server/root-server/rs-2000-g12-ip-iv-12m) | x86；8 个专用 AMD EPYC 9645 核；KVM | 16 GB DDR5 ECC；512 GB NVMe | 2.5 Gbps；过去 24 小时超过 3 TB 时临时限制为 300 Mbps | 12 个月 €21.43/月、合计 €257.16；1 个月为 €25.72；IPv4 + /64 IPv6 不加价 | 当前可下单，但页面提示高需求可能延迟，部分指定位置暂时不可用；首次订单有 30 天满意保证 |
| [VPS 2000 ARM G11](https://www.netcup.com/en/server/arm-server/vps-2000-arm-g11-iv-mnz) | ARM64/AArch64；10 个共享 Ampere vCore；KVM | 16 GB；512 GB NVMe | 2.5 Gbps；过去 24 小时超过 2 TB 时临时限制为 200 Mbps | 目录价 €13.41/月；1 个月最低合同期与账期 | **官方显示 sold out，不能下单**；不是 G12 产品 |

常规 VPS 总览页把 VPS 2000 的“起价”显示为 €19.25/月，而具体 12 个月配置页显示 €19.24/月；上表按更接近结算的具体配置页记录。netcup 的[计费 FAQ](https://www.netcup.com/en/server/vps)说明按小时方案每月预付，取消时按实际小时结算，没有最低合同期和通知期。Root Server 则可选 1 或 12 个月；[官方 FAQ](https://www.netcup.com/en/server/root-server)允许同代向更大规格或更长最低合同期升级，但不能从 VPS 原位升级成 Root Server（检索日期：2026-08-28）。

三条 G12 产品线都可在下单时选择 IPv4 + IPv6、仅 IPv6 或仅 Cloud vLAN；[官方网络文档](https://www.netcup.com/en/helpcenter/documentation/server/network-configuration)说明默认 IPv4 + IPv6 会得到 1 个静态 IPv4 和 /64 IPv6，且网络配置在实例创建后不能切换。ThesisTrace 对公网 Web/API 使用场景应保留默认 IPv4 + IPv6，不能为每月 €0.60 的减免选择之后无法补回 IPv4 的配置（检索日期：2026-08-28）。

### 对当前 ThesisTrace Compose 的选型结论

当前 [`deploy/core/compose.yaml`](../../deploy/core/compose.yaml) 同时运行 PostgreSQL、RustFS、API、Web、research worker、batch-research worker 和 tracking worker；三个 Worker 的默认上限分别都是 2 CPU、2 GiB，合计已预留 6 CPU、6 GiB，且还没有计入数据库、对象存储、API、Web、操作系统与页缓存。因此：

1. **生产单机首选 RS 2000 G12 x86。** 8 个专用核能让三个计算 Worker 的持续吞吐更可预测；16 GB 是当前默认并发的起步容量而非宽裕容量。其 12 个月价只比常规 VPS 2000 的具体配置页贵 €2.19/月、约 11.4%，却把 CPU 从共享变成专用，并把年最低可用性从 99.6% 提高到 99.9%，这笔差价对研究计算值得。
2. **先买 RS 2000 的 1 个月合同做生产镜像验收。** 验收真实数据更新、三类 Worker 并发、PostgreSQL/RustFS 恢复、RSS、CPU steal、I/O 延迟和任务时长；通过后再把同代合同升级到 12 个月。若更新与批量研究需要长期并行，或实测内存逼近 16 GB，再升到 RS 4000 G12 的 12c32g，不应仅凭纸面预先购买。
3. **VPS Lite 3 只适合低预算开发/低占空比试运行。** 它的 8c16g 与 €13.89 很便宜，但 CPU 是共享 vCore，磁盘由 NVMe 降为 SSD，接口降为 1 Gbps，且最低要付两个月；持续研究任务最在意的正是 CPU 和存储尾延迟，不能只按核数比较。
4. **常规 VPS 2000 的价值主要是无最低期验收，不是长期生产性价比。** 按小时的 €22.15/月比 RS 2000 月付低 €3.57，但共享 CPU；12 个月方案虽比 Root 便宜 €2.19/月，却同时锁定一年且没有专用 CPU。OpenClaw Special 与常规按小时档的核心规格和当前月价相同，也不构成更好的长期容量承诺。
5. **RS 1000 G12 的 4c8g 不适合原样运行完整 Compose。** 三个 Worker 默认 CPU 上限之和已经是 6 CPU；即使依靠调度器勉强启动，也没有给 PostgreSQL、RustFS、API 和 Web 留出合理 CPU/内存余量。它只适合明确停掉部分 Worker 或降低并发的开发环境。
6. **当前不要选择 ARM。** 除了 netcup ARM G11 已售罄，仓库的 [`pyproject.toml`](../../pyproject.toml) 固定了 `akshare==1.18.94`；[`uv.lock`](../../uv.lock) 又在 Linux 条件下拉取 `py-mini-racer==0.6.0`，锁文件只列出 `manylinux1_x86_64` wheel，没有 Linux ARM64 wheel。Compose 没有 `platform` 固定并不等于 ARM 已兼容。即使 ARM 日后补货，也必须先修正这条依赖路径，并用最终 `linux/arm64` Production Image 完成全栈启动、健康检查、真实研究、更新、tracking 与恢复 Smoke Test，才可重新评估。

最后，netcup 的 Copy-On-Write 快照和 Local Block Storage 都不等于异地备份。[官方 Local Block Storage 文档](https://www.netcup.com/en/helpcenter/documentation/server/local-block-storage)明确说明它与服务器本地相连，不适合在服务器故障时快速切换或恢复；PostgreSQL、RustFS 与 canonical data 仍必须备份到另一故障域或另一厂商（检索日期：2026-08-28）。

## 中国内地与韩国双区域访问：亚洲节点补充核对

补充核对日期：2026-08-28。本节只采用厂商官网、官方文档和公开产品 API；价格均保留厂商结算币种，不用波动汇率折成人民币。所谓“当前可买”仅表示官方页面、公开 API 或支持地域文档在检索时仍提供该节点与规格，不代表下单瞬间一定有库存。

### 先给结论：单机部署的明确排序

没有任何一家厂商的“东京”“首尔”“香港”位置或端口峰值，能证明中国电信、联通、移动与韩国各运营商的实际跨网质量。跨境路由会随运营商、时段和拥塞变化；腾讯云自己的[地域与网络连通性文档](https://cloud.tencent.com/document/product/1207/50103/)也明确警告，中国内地访问境外轻量实例可能出现较大延迟和丢包。因此以下是**值得进入同一套实测的购买顺序**，不是未经测试的线路承诺：

1. **腾讯云轻量应用服务器首尔 8c16g：生产首测首选。** 月付 ¥530，300 GB SSD、45 Mbps 峰值带宽、每月 7,168 GB 出流量，公网 IPv4；一次性购买 12 个月按官方 85 折为 ¥5,406，折合 ¥450.50/月，且新购与续费都适用时长折扣。[官方价格表](https://cloud.tencent.com/document/product/1207/73452/)与[支持地域表](https://cloud.tencent.com/document/product/1207/50103/)同时列出首尔和东京，首尔一区、二区仍支持新购（检索日期：2026-08-28）。在没有真实三网数据前，先按官方“选择最靠近目标客户的地域”原则从首尔开始，再把东京作为路由实测备选；300 GB 足以先做 ThesisTrace 全栈验收。CPU 是否专用、具体 ISA 和持续占用边界没有在该套餐价格页形成承诺，且 CPU 可能在 Intel/AMD 间变化，必须实机确认 `uname -m`、CPU steal 和长任务吞吐。[官方退费规则](https://cloud.tencent.com/document/product/1207/44582)还允许每个实名认证主体、每个实例套餐类型的首台新购实例在发货后 5 天内享受一次无理由全额退还；所有地域共享这一次机会，优惠券不退，购买前仍需确认账号是否尚有资格。
2. **Vultr High Performance AMD 首尔、东京或大阪 8c16g：最适合按小时做多运营商验收。** 官方公开 [Plans API](https://api.vultr.com/v2/plans?per_page=500) 的 `vhp-8c-16gb-amd` 为 8 个 AMD vCPU thread、16,384 MB RAM、350 GB NVMe、8,192 GB 流量，$0.132/小时、每月上限 $96；首尔 `icn`、东京 `nrt`、大阪 `itm` 和新加坡 `sgp` 都在该方案 locations 中，且 `deploy_ondemand=true`（检索日期：2026-08-28）。[官方部署文档](https://docs.vultr.com/products/compute/instances/cloud-compute/provisioning)明确把 High Performance 放在 Shared CPU 类别，公网 IPv4 默认分配。它比腾讯贵，但可用首尔与东京各跑几天晚高峰 A/B 测试后再保留较好的节点。
3. **LightNode 首尔或东京 8c16g：最低成本的亚洲线路探针，不直接作为当前生产答案。** [官方首尔 VPS 页](https://go.lightnode.com/korea-vps)与[东京 VPS 页](https://go.lightnode.com/japan-vps)都显示 8 vCPU、16 GB DDR4、50 GB NVMe、4 TB 流量为 $52.70/月，并可进入控制台购买；[官方计费文档](https://doc.lightnode.com/Financial/resourcebilling.html)说明按小时计费、每月最多计 672 小时，停机但未释放仍收费（检索日期：2026-08-28）。50 GB 明显不足以同时长期保存 PostgreSQL、RustFS、镜像和 canonical data；附加数据盘价格只在登录控制台可见，无法用公开一方来源闭环总成本。普通 VPS 页面也没有承诺 CPU 专用或 ISA；真正的[东京专用 CPU VDS](https://go.lightnode.com/tokyo-vds)同档为 $158.70/月，不能把 $52.70 的 VPS 写成专用核。
4. **OVHcloud 新加坡 VPS-4：大厂中纸面算力/价格最好，但地理与合约弱于首尔/东京。** [新加坡官方价格页](https://www.ovhcloud.com/en-sg/vps/)当前以 `upfront12` 配置给出 S$30/月、12 个月预付 S$360，未含 GST；规格为 8 vCore、24 GB RAM、200 GB NVMe、最高 3 Gbps、3 TB 月流量，超量后限至 10 Mbps，含 IPv4/IPv6 和同数据中心保留 7 天的每日备份（检索日期：2026-08-28）。[VPS Cloud 页面](https://www.ovhcloud.com/en-sg/vps/vps-cloud/)说明使用新一代 Intel 架构；它仍是隔离虚拟机，不是独占物理 CPU。新加坡对韩国的地理距离明显大于首尔/东京，且必须先付一年，只应在线路实测已合格、结算页确认续费价后采用。
5. **Akamai Cloud/Linode 东京或大阪：持续计算最清楚，但价格最高。** 官方 [Dedicated 8c16g 类型 API](https://api.linode.com/v4/linode/types/g6-dedicated-8)给出 8 个专用 x86 vCPU、16 GB RAM、320 GB SSD、6 TB 流量、6 Gbps 出站端口，$0.216/小时、$144/月；[东京与大阪 Region API](https://api.linode.com/v4/regions)及各区 availability API 在检索时均返回该类型 `available=true`。官方 [CPU 选择文档](https://techdocs.akamai.com/cloud-computing/docs/choosing-between-shared-and-dedicated-cpus)允许 dedicated 实例持续使用 100% CPU，而 shared 实例建议最高持续 80%。如果真实 Worker 基准证明共享 CPU 抖动不可接受，它是亚洲节点里最清晰的持续 CPU 方案；否则为单机 ThesisTrace 支付 $144/月不划算。

这五项的排序按“当前 ThesisTrace 能否部署 + 中韩位置平衡 + 可先短付验证 + 总成本”综合确定。首尔只是按距离与厂商选区原则得到的第一试点，不是对中国三网质量的承诺；如果晚高峰实测显示东京更稳定，就应以实测结果改选东京。若只按纸面算力单价，OVHcloud 会更靠前，但新加坡的地理位置与年付锁定都不符合本题的首测目标。

### 最终候选逐项对照

| 排名与方案 | 区域、架构与 CPU | RAM / 系统盘 | 月价、合同与续费 | IPv4、网络与流量 | 快照、备份与主要风险 |
| --- | --- | --- | --- | --- | --- |
| 1. [腾讯轻量首尔](https://cloud.tencent.com/document/product/1207/73452/) | 首尔；Linux 实机需确认 ISA；官方不承诺专用 CPU，Intel/AMD 型号可能变化 | 16 GB / 300 GB SSD | ¥530 月付；12 个月新购/续费均 85 折，¥5,406/年 | 公网 IPv4；45 Mbps 峰值；7,168 GB/月，仅统计出流量，超额 ¥0.8/GB | 备份点与额外 SSD 另计；跨境延迟/丢包无保证；实例创建后不能换地域 |
| 2. [Vultr High Performance AMD](https://api.vultr.com/v2/plans?per_page=500) | 首尔、东京、大阪、新加坡当前在方案 locations；AMD x86；8 个共享 vCPU thread | 16 GB / 350 GB NVMe | $0.132/小时，672 小时封顶 $96/月；无长约续费折扣 | 公网 IPv4 默认分配，可选 IPv6；8 TB 出流量，超量 $0.01/GB；官方未给该档固定端口保证 | 自动备份加收实例费 20%，仅保留最近 2 份；快照 $0.05/GB/月；共享 CPU 会抖动 |
| 3. [LightNode 首尔 VPS](https://go.lightnode.com/korea-vps) | 首尔（东京同价可作 A/B）；KVM；普通 VPS 的 ISA、CPU 型号和专用状态未在公开页承诺 | 16 GB / 50 GB NVMe | $52.70/月等值；按小时，672 小时封顶；释放才停止计费；FAQ 称不收 VAT/销售税 | 1 个公网 IPv4、无 IPv6；4 TB/月；公开页未给端口 Mbps；流量耗尽后官方文档称限至 10 Kbps | 仅 1 个手工快照，且释放主机或系统盘时会一并删除；50 GB 不足，附加盘公开价格缺失 |
| 4. [OVHcloud VPS-4](https://www.ovhcloud.com/en-sg/vps/) | 新加坡；新一代 Intel x86；8 个虚拟核，不承诺独占物理 CPU | 24 GB / 200 GB NVMe | S$30/月等值、S$360 预付 12 个月，未含 GST；续费以结算页为准 | IPv4 + IPv6；最高 3 Gbps；3 TB/月，随后限 10 Mbps | 含每日备份、同机房保留 7 天；年付锁定，新加坡到韩国的路线需验证 |
| 5. [Akamai Dedicated 8c16g](https://api.linode.com/v4/linode/types/g6-dedicated-8) | 东京/大阪当前 API 可用；x86；8 个专用 vCPU，可持续 100% | 16 GB / 320 GB SSD | $0.216/小时，$144/月封顶；无预付续费折扣 | 公网 IPv4 与 IPv6；6 Gbps 出站；6 TB/月，核心机房超量 $0.005/GB | 备份服务另付费、同数据中心、最多 4 个备份槽；持续性能明确但价格高 |

Vultr 的备份与计费边界分别见[自动备份文档](https://docs.vultr.com/vps-automatic-backups)、[快照计费说明](https://docs.vultr.com/support/platform/billing/does-vultr-charge-for-stored-snapshots)和[服务器计费说明](https://docs.vultr.com/support/platform/billing/how-am-i-billed-for-my-servers)。Akamai 的公网地址、流量和备份边界分别见[Compute Instance 文档](https://techdocs.akamai.com/cloud-computing/docs/compute-instance)、[Network Transfer 文档](https://techdocs.akamai.com/cloud-computing/docs/network-transfer-usage-and-costs)及[Backup Service 文档](https://techdocs.akamai.com/cloud-computing/docs/backup-service)（均检索于 2026-08-28）。所有厂商本地快照/同机房备份都不能替代 PostgreSQL、RustFS 与 canonical data 的异地恢复副本。

### 同一厂商的区域取舍

#### 腾讯云轻量

[官方 8c16g Linux 价格表](https://cloud.tencent.com/document/product/1207/73452/)与[当前支持新购地域](https://cloud.tencent.com/document/product/1207/50103/)给出如下选择（检索日期：2026-08-28）：

| 区域 | 8c16g 规格 | 月付 | 12 个月 85 折总价 / 月均 | 中韩双访问判断 |
| --- | --- | --- | --- | --- |
| 首尔 / 东京 / 新加坡 | 300 GB SSD、45 Mbps 峰值、7,168 GB/月 | ¥530 | ¥5,406 / ¥450.50 | 首尔先测、东京作路由备选；新加坡更远，不作为第一选择 |
| 中国香港 | 300 GB SSD、40 Mbps 峰值、7,168 GB/月 | ¥650 | ¥6,630 / ¥552.50 | 偏中国内地但不保证跨境质量，且韩国路径需实测 |
| 中国内地 | 270 GB SSD、18 Mbps、3,500 GB/月 | ¥500 | ¥5,100 / ¥425 | 偏中国内地；韩国用户跨境，且公开网站绑定域名需 ICP 备案 |

这里的 85 折不是“仅首年活动价”：官方表写明中国内地、香港及海外符合规格的实例在**新购和续费** 12 个月及以上时均享受 85 折。但套餐中的 Mbps 是峰值/套餐带宽，不是中国内地到境外的优化线路保证。

#### LightNode

- [东京](https://go.lightnode.com/japan-vps)和[首尔](https://go.lightnode.com/korea-vps)普通 VPS 的 8c16g 都是 50 GB NVMe、4 TB、$52.70/月；[香港 BGP](https://go.lightnode.com/hong-kong-vps)同规格为 $74.31/月（检索日期：2026-08-28）。三个页面都提供购买入口，可作为当前可买处理。
- 官方测速地址可用于首轮探测：东京 `38.54.50.202`、首尔 `156.244.19.242`、香港 BGP `38.54.23.45`，分别来自[东京测速页](https://www.lightnode.com/en-US/speed/jp-tokyo-1)、[首尔测速页](https://www.lightnode.com/en-US/speed/kr-seoul-1)和[香港 BGP 测速页](https://www.lightnode.com/zh-CN/speed/cn-hongkong-3-bgp)（检索日期：2026-08-28）。香港 CNCN 测速接口在本次核对时返回 HTTP 503，恢复前不能把它当可验证的中国优化线路证据。
- [官方实例部署文档](https://doc.lightnode.com/Instance/Deployinstance.html)说明每个实例含一个 IPv4，目前不提供 IPv6；[流量与 FAQ](https://doc.lightnode.com/FAQ/FAQ.html)说明超额后限至 10 Kbps、无额外流量账单。这个限速会让生产服务近似不可用，应监控累计出流量。

#### Vultr 与 Akamai/Linode

- Vultr 同一个 `vhp-8c-16gb-amd` 可在东京、首尔、大阪和新加坡按小时创建，因此最适合做地域 A/B。若只想先验证部署，公开 API 的 `vc2-4c-8gb` 是 4c8g/160 GB/4 TB、$0.055/小时、$40/月，但它同样是共享 CPU，且必须降低或串行化三个 Worker；不能把它当完整默认 Compose 的等价容量。若要求专用 CPU，官方 `voc-c-8c-16gb-150s-amd` 为 8c16g/150 GB/7 TB、$0.219/小时、$160/月，在这些亚洲节点均可部署（[Plans API](https://api.vultr.com/v2/plans?per_page=500)，检索日期：2026-08-28）。
- Akamai 的更便宜降档是 [Shared 6c16g `g6-standard-6`](https://api.linode.com/v4/linode/types/g6-standard-6)：320 GB SSD、8 TB、6 Gbps 出站，$0.144/小时、$96/月；东京、大阪和新加坡当前 availability API 均为可用。它比 8c16g dedicated 少两核，且官方持续 CPU 上限建议为 80%，因此优先级低于 Vultr 同价 8c16g shared，也不应替代默认并发的生产容量。

### 已核对但不进入最终排名

#### AWS Lightsail：节点齐全但同档太贵，降档又是突发 CPU

- [官方区域文档](https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-regions-and-availability-zones-in-amazon-lightsail.html)提供香港、首尔、新加坡与东京，但没有大阪；香港属于需手动启用的 opt-in Region（检索日期：2026-08-28）。
- 真正的 Linux 8c16g 是 [Compute-optimized 2Xlarge](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html)，含公网 IPv4、640 GB SSD、7 TB，按需小时计费到 $168/月上限，没有年付/续费折扣。较合理的降档是 General Purpose 4c16g/320 GB/6 TB、$84/月，但 [CPU baseline 文档](https://docs.aws.amazon.com/lightsail/latest/userguide/baseline-cpu-performance.html)给该档每 vCPU 40% 基线，依赖突发容量，不适合三个 Worker 的持续计算。
- 流量包同时统计入站和出站，超额只对出站收费；香港、首尔、新加坡、东京分别为 $0.09、$0.13、$0.12、$0.14/GB（[官方流量 FAQ](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-data-transfer-allowance.html)）。快照 $0.05/GB/月，自动快照最多保留最近 7 份（[官方快照 FAQ](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-snapshots.html)）。公开 bundle 表未对该计划作 ISA 合同承诺，仍需在 blueprint 与实例内确认。价格明显高于同区域候选，因此排除。

#### Hetzner：亚洲只有新加坡，涨价后不再是本题的低价方案

- [官方位置文档](https://docs.hetzner.com/cloud/general/locations/)显示亚洲仅新加坡，没有香港、东京、大阪或首尔；新加坡的 Shared AMD CPX42 是 8c16g/320 GB NVMe。2026-06-15 生效的[官方新价格表](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)为 €0.1498/小时、€93.49/月，均未含 VAT 与 IPv4；主 IPv4 另加 €0.50/月，因此税前至少 €93.99/月（检索日期：2026-08-28）。
- [Regular Performance 页面](https://www.hetzner.com/cloud/regular-performance/)将其定位为低到中等 CPU 使用、性能可变的共享方案；新加坡仅含 0.5 TB 流量，超额 €7.40/TB。官方说明宿主 10 Gbps 共享、通常可达约 300–500 Mbps但不保证。地理与流量都弱于前列候选，排除。

#### Alibaba Cloud Simple Application Server：规格很合适，但公开价格和实时库存无法闭环

- [官方实例家族表](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/instance-families/)列出 CPU-optimized `swas.d.c8m16s300b1.linux`：8c16g、300 GB、最高 200 Mbps、1 个公网 IPv4、Free 流量；可用地域包含香港、新加坡、东京和首尔，并说明 CPU-optimized 实例完整占用每个 hyper-thread、提供一致性能（检索日期：2026-08-28）。
- 但[官方创建文档](https://www.alibabacloud.com/help/en/simple-application-server/user-guide/create-a-server)将最终可购计划与价格放在登录后的购买页或 `ListPlans` API；公开静态页面不能确认各区当前价格和该 plan 的实时库存。[区域与连通性文档](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/regions-and-network-connectivity)也明确警告境外实例从中国内地访问可能有高延迟和丢包、普通公网带宽不保证。
- 计费为 1/3/6 个月或 1/2/3 年订阅，默认启用自动续费（[官方计费概述](https://www.alibabacloud.com/help/en/simple-application-server/product-overview/overview)）；公开规格表也未明确 ISA。由于无法用未登录的一方来源闭环“当前价格 + 当前可售”，按本文规则不排名，不能把控制台临时活动价当长期续费价。

#### netcup 新加坡：价格可算，但当前库存提示无法映射到新加坡

[RS 2000 G12 官方配置页](https://www.netcup.com/en/server/root-server/rs-2000-g12-ip-iv-12m)给新加坡加价 €27.37；以年付基础 €21.43/月计为 €48.80/月（页面含德国 19% VAT），1 个月合同再加 €4.29，为 €53.09/月。若可买，它仍是 8 个专用 EPYC 核、16 GB、512 GB NVMe、2.5 Gbps、24 小时超过 3 TB 后限 300 Mbps、含 IPv4。但本次官方页面同时显示“该产品当前在此位置不可用”的提示，页面又没有可靠地把提示映射到某个具体 location；因此无法确认新加坡当前库存，不列入“当前可买”排名。只有结算页明确允许选择 Singapore 后才重新考虑。

### 实际购买与验收动作

1. **先买首尔，不先买年付。** 第一轮优先开腾讯首尔 1 个月，并先确认账号仍有该套餐类型的 5 天无理由退还资格；若希望把地域变量也测掉，则并行短开 Vultr 首尔与东京各 48–72 小时。LightNode 首尔/东京只作为低成本网络探针，除非控制台附加盘总价明确且完整 Production Image 通过。
2. **覆盖真实用户网络与时段。** 中国内地至少分别从电信、联通、移动取样，韩国至少从目标用户实际 ISP 取样；在北京时间/韩国时间工作日晚 20:00–23:00 测 TCP 建连、TLS 首字节、下载、上传、丢包与路由，每个节点连续多天。禁止只看机房到公共测速站的单次 ping。
3. **用当前全栈负载判定 CPU。** 在最终 x86 Production Image 上并发运行 PostgreSQL、RustFS、API、Web、research、batch-research 和 tracking Worker，记录 CPU steal、频率、RSS、I/O P95、真实数据更新/研究/tracking 时长与错误。当前三个 Worker 默认上限合计已经是 6 CPU/6 GiB，因此 4c8g 降档只能在明确串行 Worker 后用于开发验证。
4. **做存储与恢复门槛。** 生产候选系统盘至少按 200–300 GB 起步；完成 PostgreSQL、RustFS 和 canonical data 到另一厂商/故障域的备份与空机恢复。LightNode 50 GB 和任何同机房自动快照都不能单独过关。
5. **验收后才锁年付。** 若腾讯首尔同时满足中韩路由、任务时长和恢复目标，再转 12 个月 85 折；若东京线路更好则迁到东京后重新验收。若共享 CPU 长任务波动明显，按同一数据集比较 Akamai dedicated 或 Vultr dedicated，不能只比较标称 vCPU 数。

## 回答“这么贵吗”：当前预算阶梯

补充核对日期：2026-08-28。结论是：**不是所有 8c16g 都要 ¥500/月，但“亚洲节点、真正月付、磁盘够用、公开可买”同时成立时，价格确实比欧洲高。** 便宜方案都要接受降到 4c8g、预付一年、50 GB 小盘，或欧洲高延迟中的至少一项。

为便于理解，本节人民币近似值只按[中国银行 2026-08-27 23:35 外汇牌价](https://www.boc.cn/sourcedb/whpj/index.html)的现汇卖出价计算：美元 ¥6.7371、新加坡元 ¥5.3081、欧元 ¥7.8605；实际信用卡汇率、境外交易费和税费另算，厂商原币价格才是合同价格。

| 预算阶梯 | 当前官方可买方案 | 价格 | 得到什么 | 必须接受的代价 |
| --- | --- | --- | --- | --- |
| 约 ¥109–202/月，最低算力价 | [netcup VPS Lite 3](https://www.netcup.com/en/server/vps/vps-lite-3-g12s-iv-2m) 或 [RS 2000 G12](https://www.netcup.com/en/server/root-server/rs-2000-g12-ip-iv-12m) | Lite 3 8c16/320 GB SSD 为 €13.89/月，最低付 2 个月，约 ¥109/月；RS 2000 8 个专用核/16 GB/512 GB NVMe 为年付 €21.43/月，约 ¥168，或月付 €25.72，约 ¥202；这些页面数值含德国 19% VAT，实际税率随购买者地区变化 | 欧洲市场仍能用很低价格买到 8c16，RS 的 CPU 还是专用核 | 机房在欧洲；对中国内地和韩国都绕远，不能满足低时延目标。Lite 还是共享 CPU |
| 约 ¥159/月等值，亚洲纸面性价比最高 | [OVHcloud 新加坡 VPS-4](https://www.ovhcloud.com/en-sg/vps/) | 8c24/200 GB NVMe 为 S$30/月等值，约 ¥159；但配置按钮实际进入带 `pricing=upfront12` 的[官方配置器](https://www.ovhcloud.com/en-sg/vps/configurator/?brick=VPS%2BModel%2B4&planCode=vps-2027-model4&pricing=upfront12&processor=+&storage=200__SSD__NVMe&vcore=8__vCore)，必须预付 S$360，约 ¥1,911，且未含 GST | 规格超过 8c16，磁盘达到最低可用线，含 IPv4/IPv6 与每日备份 | S$30 不是可随时取消的真实月付价；先锁一年，新加坡到中韩两侧的线路仍须实测 |
| 约 ¥183–250/月，亚洲降档 | [腾讯云海外轻量 4c8](https://cloud.tencent.com/document/product/1207/73452/) | 入门型 120 GB/30 Mbps/3,584 GB 为 ¥215 月付；12 个月 85 折共 ¥2,193，月均 ¥182.75。通用型 180 GB/35 Mbps/5,120 GB 为 ¥250 月付；12 个月共 ¥2,550，月均 ¥212.50 | 首尔、东京、新加坡当前支持新购；价格、续费折扣、IPv4 和流量都能公开闭环 | 4c8 无法按当前默认配置并发跑三个 Worker；120/180 GB 也低于建议的 200–300 GB，必须串行 Worker 并严控数据量 |
| 约 ¥187/月，最灵活的亚洲 4c8 | [LightNode 首尔](https://go.lightnode.com/ko/korea-vps)或[东京](https://go.lightnode.com/tokyo-vps) 4c8 | 4c8/50 GB NVMe/3 TB 为 $27.70/月，约 ¥187；按小时计费、672 小时封顶。若全年持续运行是 $332.40，官方未给年付折扣 | 可先开几天比较首尔与东京，不必预付一年 | 50 GB 远远不够 ThesisTrace；附加数据盘价格只在登录控制台可见，所以 $27.70 不是可验证的生产总成本；CPU 专用性也未承诺 |
| 约 ¥355/月，最低基础价的亚洲 8c16 | [LightNode 首尔](https://go.lightnode.com/ko/korea-vps)或[东京](https://go.lightnode.com/tokyo-vps) 8c16 | 8c16/50 GB NVMe/4 TB 为 $52.70/月，约 ¥355；按小时计费。全年持续运行是 $632.40，无公开年付折扣 | 在已核厂商中，真正按小时开通的亚洲 8c16 基础价最低 | 仍只有 50 GB；补足磁盘后的总价无法从公开页面核实，不能直接当生产候选 |
| ¥450.50–530/月，省事的完整亚洲档 | [腾讯云海外轻量 8c16](https://cloud.tencent.com/document/product/1207/73452/) | 300 GB SSD、45 Mbps、7,168 GB 为 ¥530 月付；12 个月 85 折共 ¥5,406，月均 ¥450.50 | 磁盘与流量无需额外拼装，首尔/东京均可选 | 这是便利性与公开闭环的价格，不是最低算力价；共享/持续 CPU 边界仍需实测 |

### ¥300/月以内到底有没有亚洲 8c16

- **若“8c16”表示至少 8 核、至少 16 GB，并接受一年预付：有。** OVHcloud 新加坡 VPS-4 是 8c24，S$30/月等值、S$360 一次预付；按上述中国银行牌价约 ¥159/月、约 ¥1,911/年，税费另算。它是本轮唯一能从公开一方页面闭环、同时达到该算力和磁盘下限的约 ¥300/月内亚洲候选。
- **若要求恰好/至少 8c16、磁盘够用且可真实月付：没有。** LightNode 的 $52.70 约 ¥355/月且只有 50 GB；腾讯是 ¥530/月；OVH 的 S$30 展示价绑定 12 个月预付；netcup 新加坡库存又无法确认。
- **若能降到 4c8：有多项。** 最稳妥的预算方案是先月付腾讯海外入门型 ¥215，在首尔与东京中选择一个做实测，并把三个 Worker 串行化；线路和容量通过后，才考虑 12 个月月均 ¥182.75。LightNode $27.70 更灵活，但 50 GB 使其更像网络/部署试验机。

因此，对用户的直接回答应是：**现在不是“服务器都这么贵”，而是亚洲跨境位置、足够磁盘和公开可续费会显著抬价。预算压在 ¥200 左右，应选 4c8 降并发或接受 OVH 新加坡年付；坚持亚洲 8c16 真月付和 200 GB 以上磁盘，准备约 ¥350–530/月才现实。淘宝 ¥21/月的 8c16 与这些公开成本不在同一市场层级，仍必须按前述上游所有权、CPU、IPv4、流量和续费清单核验。**

## OVHcloud 亚洲机房即时价格与库存更正

复核日期：2026-08-28。本节以 OVHcloud 官方动态配置器的即时可选状态为准，**取代本文前面所有把 OVHcloud VPS-4 新加坡写成“当前可买”或“当前可闭环购买”的判断**。产品页的 `From` 价格是公开标价，不等于对应亚太机房当下有库存。

### 直接结论

- **若“亚洲”严格按地理区域计算，当前最便宜且唯一可下单的是新加坡 VPS-1。** [OVHcloud Asia 官方 VPS-1 配置器](https://www.ovhcloud.com/asia/vps/configurator/?brick=VPS%2BModel%2B1&planCode=vps-2027-model1&pricing=upfront12&processor=+&storage=40__SSD__NVMe&vcore=2__vCore)当前显示新加坡 `Available now`：2 vCore、4 GB RAM、40 GB NVMe。无合约为 **US$5.35/月（税前）**；12 个月方案一次预付 **US$54.48（税前）**，只是折合 **US$4.54/月**，不是逐月付款。
- OVH 配置器把新加坡、悉尼和孟买放在同一个 `Asia/Oceania` 标签下。悉尼 VPS-1 与新加坡完全同价且当前可买，但悉尼属于大洋洲；孟买 VPS-1 当前 `Out of stock`。因此若沿用 OVH 的“亚洲/大洋洲”分类，**新加坡与悉尼并列最低**；若用户服务中国和韩国，应优先测试新加坡，而不是因为同价选择距离更远的悉尼。
- 同一资源在不同销售站点以不同币种结算，不代表机房价格高低。[新加坡站 VPS-1 配置器](https://www.ovhcloud.com/en-sg/vps/configurator/?brick=VPS%2BModel%2B1&planCode=vps-2027-model1&pricing=upfront12&processor=+&storage=40__SSD__NVMe&vcore=2__vCore)显示无合约 **S$6.80/月（税前）**，或一次预付 **S$69.36/12 个月（税前）**、折合 **S$5.78/月**。中国或韩国购买者最终能使用哪个销售站点、币种和税额取决于开户与账单国家；官方配置器在未进入结算前只给 `ex. taxes`，所以这里不臆算税后价。

### ThesisTrace 所需大规格：有标价，但目前没有亚洲库存

[OVHcloud Asia VPS 产品页](https://www.ovhcloud.com/asia/vps/)给 VPS-4 标注 8 vCore、24 GB RAM、200 GB NVMe，`From US$23.37 ex. GST/month`；但配置按钮默认进入 12 个月方案，[VPS-4 官方配置器](https://www.ovhcloud.com/asia/vps/configurator/?brick=VPS%2BModel%2B4&planCode=vps-2027-model4&pricing=upfront12&processor=+&storage=200__SSD__NVMe&vcore=8__vCore)显示总额为 **US$280.44（税前）/12 个月**。新加坡销售站对应公开标价为 S$30/月等值、一次预付 S$360（税前）。这些都只是年付标价，不是当前能在亚洲下单的实例。

即时库存如下：

| 2027 套餐 | 新加坡 SGP | 悉尼 SYD | 孟买 YNM | 当前判断 |
| --- | --- | --- | --- | --- |
| VPS-1，2c4g/40 GB | Available now | Available now | Out of stock | 只有这一档在亚太可下单；新加坡与悉尼同价 |
| [VPS-2，4c8g/75 GB](https://www.ovhcloud.com/asia/vps/configurator/?brick=VPS%2BModel%2B2&planCode=vps-2027-model2&pricing=upfront12&processor=+&storage=75__SSD__NVMe&vcore=4__vCore) | Out of stock | Out of stock | Out of stock | 亚太暂不可买 |
| [VPS-3，6c12g/100 GB](https://www.ovhcloud.com/asia/vps/configurator/?brick=VPS%2BModel%2B3&planCode=vps-2027-model3&pricing=upfront12&processor=+&storage=100__SSD__NVMe&vcore=6__vCore) | Out of stock | Out of stock | Out of stock | 亚太暂不可买 |
| [VPS-4，8c24g/200 GB](https://www.ovhcloud.com/asia/vps/configurator/?brick=VPS%2BModel%2B4&planCode=vps-2027-model4&pricing=upfront12&processor=+&storage=200__SSD__NVMe&vcore=8__vCore) | Out of stock | Out of stock | Out of stock | 满足 ThesisTrace 纸面容量，但当前亚太无法下单 |

亚太 VPS 还有流量限制：[官方 VPS 页面](https://www.ovhcloud.com/en-sg/vps/)注明 VPS-1 每月 500 GB、VPS-2/3 每月 1 TB、VPS-4 每月 3 TB，超过后带宽降至 10 Mbps。因此最终购买结论是：**只想买 OVH 最便宜的亚洲试验机，可买新加坡 VPS-1；要运行完整 ThesisTrace，则 OVH 亚太当前没有可买的大规格答案，不能再把 VPS-4 的 US$23.37 或 S$30 年付标价列为现货方案。库存恢复后仍需重新核对价格、合约和中韩线路。**

## OVH 大规格售罄后的亚洲现货替代

复核日期：2026-08-29。本节取代前文仍把 OVH VPS-4 列入候选的旧排序；只保留能由厂商官方配置器、产品 API 或当前地域可用表闭环“规格、价格、节点和可部署状态”的候选。x86-64 是 ThesisTrace 的验收门槛；厂商没有把 ISA 写入公开合同时，表中会明确标出需实机确认。价格为厂商原币，税费随账单国家变化。

### 直接推荐排序

1. **成本优先的新发现：Contabo 东京 Cloud VPS 8。** 当前官方配置器可直接选择 Asia (Japan)、Ubuntu、1 个免费 IPv4 并进入下一步，8 vCPU、24 GB、300 GB SSD、600 Mbit/s、无限流量但受公平使用政策约束；真实 1 个月结算摘要为 **€22.00**，12 个月一次预付 **€238.80**、月均 €19.90。新加坡同规格为 €21.85/月或 €237.00/年。它是本轮纸面性价比最高的完整容量候选，但属于 Core VPS：处理器按开通时资源可用性分配，官方把其定位为标准负载，并明确在性能随时段变化或需要 dedicated resources 时升级。因此应先月付跑 7–14 天完整负载与晚高峰线路，不应凭 8 核标称直接替换生产机。
2. **生产首测仍选腾讯云轻量首尔/东京 8c16。** 300 GB SSD、45 Mbps 峰值、7,168 GB/月，¥530 月付或 ¥5,406/年；首尔、东京、新加坡和曼谷都在当前支持新购地域中。它比 Contabo 贵很多，但套餐、流量、续费折扣与区域支持的公开闭环最完整。对韩国用户先测首尔，对中国内地三网仍必须实测；官方不承诺跨境低丢包，也没有专用核承诺。
3. **需要按小时比较节点：Vultr High Performance AMD。** 首尔、东京、大阪、新加坡均在 `vhp-8c-16gb-amd` 的当前 locations 中且 `deploy_ondemand=true`；8c16、350 GB NVMe、8 TB，$0.132/小时、672 小时封顶 $96/月。它是共享 CPU，但最适合把地域变量快速 A/B 后销毁实例。
4. **只做便宜线路探针：LightNode 首尔/东京。** 8c16、50 GB NVMe、4 TB 为 $52.70/月封顶并按小时计费，官方购买链接的 `type=CPU_SHARE` 明确是共享 CPU；50 GB 仍不足以部署完整 ThesisTrace，附加盘公开总价也无法闭环，所以不列为生产机。
5. **共享 CPU 抖动无法接受才买 Akamai/Linode Dedicated。** 东京/大阪 availability API 当前对 `g6-dedicated-8` 返回 `available=true`；8 个专用 x86 vCPU、16 GB、320 GB SSD、6 TB，$0.216/小时、$144/月。持续 CPU 合同最清楚，但不符合本次低价优先目标。

这里的“东京优先”只是面向韩国的地理起点，不是面向中国内地的优化线路保证。香港和曼谷没有出现更便宜且同时满足 200–300 GB 存储的现货：腾讯曼谷与首尔/东京同价；LightNode 香港 8c16 更贵且仍只有 50 GB。

### 同口径现货表

| 方案与当前可用证据 | 4c8 降档 | 至少 8c16 / 最接近 | CPU、IPv4 与流量 | 对 ThesisTrace 的定位 |
| --- | --- | --- | --- | --- |
| [Contabo Cloud VPS 4](https://contabo.com/en-us/vps/cloud-vps-core-4) / [Cloud VPS 8](https://contabo.com/en-us/vps/cloud-vps-core-8)：配置器当前可选东京、新加坡并给出 `Due Today` 与 `Next` | 东京：4c8/100 GB SSD/200 Mbps，€8.05 月付；12 个月预付 €86.70、月均 €7.23。新加坡：€8.00 月付；年付 €86.10、月均 €7.18 | 东京：8c24/300 GB SSD/600 Mbps，€22.00 月付；年付 €238.80、月均 €19.90。新加坡：€21.85 月付；年付 €237.00、月均 €19.75 | x86-64；Core VPS 不承诺专用核，处理器按开通时可用性分配；1 IPv4 免费；出入流量不限量但有 FUP；停止服务不能按小时省钱，最低期 1 个月 | **价格冠军、先验收后可转生产。** 4c8 只做串行 Worker/开发；8c24 才进入完整全栈测试。CPU steal、磁盘 P95、恢复和中韩晚高峰连续通过后再年付 |
| [腾讯云轻量价格表](https://cloud.tencent.com/document/product/1207/73452/) + [新购地域表](https://cloud.tencent.com/document/product/1207/50103/)：首尔/东京/新加坡/曼谷当前支持新购 | 海外通用型 4c8/180 GB SSD/35 Mbps/5,120 GB，¥250 月付；年付 ¥2,550、月均 ¥212.50 | 8c16/300 GB SSD/45 Mbps/7,168 GB，¥530 月付；年付 ¥5,406、月均 ¥450.50 | 公网 IPv4；只计出流量；CPU 型号随机，价格页没有 dedicated-core/ISA 合同；境外节点从中国内地访问可能高延迟、丢包 | **生产首测。** 套餐最完整；先买一个月测首尔，再以东京作备选，验收后才年付 |
| [Vultr Plans API](https://api.vultr.com/v2/plans?per_page=500) + [Regions API](https://api.vultr.com/v2/regions?per_page=500)：`icn/nrt/itm/sgp` 均在方案 locations，按需部署开启 | `vc2-4c-8gb`：4c8/160 GB/4 TB，$0.055/小时、$40/月封顶；持续一年等值 $480，无年付折扣 | `vhp-8c-16gb-amd`：8c16/350 GB NVMe/8 TB，$0.132/小时、$96/月封顶；持续一年等值 $1,152 | x86 AMD；Shared CPU；公网 IPv4 默认分配；超额 $0.01/GB；关机仍计费，销毁才停止 | **最佳多节点 A/B。** 共享核长任务仍需实测，不因 High Performance 名称推断为专用核 |
| [LightNode 首尔](https://go.lightnode.com/korea-vps) / [东京](https://go.lightnode.com/japan-vps)：两种规格均有当前创建入口 | 4c8/50 GB NVMe/3 TB，$27.70/月封顶；持续一年 $332.40，无年付折扣 | 8c16/50 GB NVMe/4 TB，$52.70/月封顶；持续一年 $632.40 | x86 ISA 未写入公开合同；购买链接明确 `CPU_SHARE`；1 IPv4、无 IPv6；流量耗尽限至 10 Kbps | **只作路由/部署探针。** 50 GB 直接淘汰为生产盘；释放实例才停止计费 |
| [Akamai/Linode Types API](https://api.linode.com/v4/linode/types) + [大阪 availability](https://api.linode.com/v4/regions/jp-osa/availability) / [东京 3](https://api.linode.com/v4/regions/jp-tyo-3/availability) / [东京 2](https://api.linode.com/v4/regions/ap-northeast/availability)：逐类型当前为 true | Shared `g6-standard-4`：4c8/160 GB/5 TB，$0.072/小时、$48/月；持续一年 $576 | Dedicated `g6-dedicated-8`：8c16/320 GB/6 TB，$0.216/小时、$144/月；持续一年 $1,728。Shared 6c16 则为 $96/月 | x86；Dedicated 档 8 核保留且可持续 100%；公网 IPv4/IPv6 包含；关机仍计费 | **确定性 CPU 备选。** 只有共享方案实测失败且长任务价值覆盖差价时采用 |

Contabo 的架构与资源边界来自[官方自定义镜像要求](https://help.contabo.com/en/support/solutions/articles/103000274171-can-i-use-custom-images-on-my-server-)（仅支持 x86-64/amd64）和[官方产品组合说明](https://help.contabo.com/en/support/solutions/articles/103000408463-can-i-get-more-information-about-contabo-s-server-portfolio-)：Core VPS 4/8 分别是 4c8/100 GB 与 8c24/300 GB，且处理器按 provisioning 时库存分配。上述 Contabo 结算是在 EUR、Ubuntu 24.04、不加备份/监控/额外磁盘的配置下读取；购买者账单国家可能增加税费，必须以下单页最终 `Due Today` 为准。

### 为什么没把其他大厂排进前五

- **DigitalOcean 新加坡当前能部署，但被 Vultr 同价压住。** [官方价格表](https://www.digitalocean.com/pricing/droplets)的 Basic 4c8 为 160 GB SSD、5 TB、$48/月，8c16 为 320 GB、6 TB、$96/月；[官方可用表](https://docs.digitalocean.com/products/droplets/details/availability/)当前列出 SGP1，Basic 属共享 CPU。它没有首尔/东京/大阪，8c16 与 Vultr 同为 $96，却少 30 GB 磁盘和 2 TB 流量，因此只作账户或生态偏好备选。
- **Hetzner 新加坡涨价后不再便宜。** [2026-06-15 官方价格表](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)的 Shared CPX32 4c8 是 €48.99/月、CPX42 8c16 是 €93.49/月，主 IPv4 还要 €0.50/月；新加坡仅含 0.5 TB 出流量。它的成熟度不能抵消相对 Contabo 与 Vultr 的价格/流量劣势。

### 实际购买决策

- **只想花最低成本确认能跑：** 买 Contabo 东京 Cloud VPS 4 一个月（€8.05），串行 Worker，验证 x86 Production Image、DNS/TLS、三网与韩国晚高峰；它不是完整生产容量。
- **想测哪个亚洲节点线路最好：** 用 Vultr 在首尔、东京、大阪和新加坡各开 24–72 小时，因为按小时且销毁即止费；不要用 Contabo 配置器显示的单一延迟代替真实用户网络。
- **要完整 ThesisTrace 且预算非常紧：** 先月付 Contabo 东京 Cloud VPS 8（€22）跑 7–14 天；只有 CPU steal、三类 Worker 并发、PostgreSQL/RustFS I/O、备份恢复和中韩晚高峰都过关，才转年付 €238.80。
- **要少冒险地先上线：** 仍先买腾讯首尔/东京 8c16 月付；若共享 CPU 抖动成为实际瓶颈，再比较 Akamai dedicated，而不是仅按标称核数升级。
