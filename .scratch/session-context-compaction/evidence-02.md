# Issue 02 验证记录

状态：complete。实现已独立提交，验证与复审闭合。

## 代码审查

- 初始快照 `/tmp/thesistrace-ticket02-review`：Standards 0项；Spec 1项P1，provenance hypothesis 无界。
- 修复快照 `/tmp/thesistrace-ticket02-review-fixed`：Standards 0项；Spec复审仍发现最坏JSON转义公式+2048字符备注超预算。另确认catalog最大完整字段在转义后也可超过单页32KiB。
- 已在仓库外复现两个catalog最坏形状，`/tmp/test_catalog_bound.py` 两项预期失败。待本次固定版本集成结束后收紧当前契约并补入正式测试，再复审。

## 快速验证

- 分页/目录/MCP/轨迹：58 passed（初始修复版）。
- 新增备注与provenance测试连同MCP：47 passed；该结果只覆盖当时用例，不覆盖随后发现的公式控制字符边界。
- Alpha语言、ResearchKind、Batch契约：63 passed。
- Agent safe-result与Scripted工具：97 passed；MCP适配/传输边界：9 passed。
- Web安全投影/时间线：18 passed；ResearchWorkspace输入：21 passed；Web typecheck通过。
- Python `ruff check src tests` 通过；工作区 `git diff --check` 通过。

## 隔离集成

1. `20260906t174732z-31865-ad178069`：418 passed、4 failed、8 deselected，629.90s。三处旧回执断言未同步，一处测试复用已关闭连接池。已修复；不是通过结果。
2. `20260906t180554z-39276-4d5eee5c`：412 passed、10 failed，577.125s。运行期间修复长字段时引入过临时循环import，被本轮构建产物捕获；Worker/stdio子进程启动失败。循环import已去除，不能把这轮作为当前稳定代码结论。
3. `20260906t181657z-46438-10307ff4`：422 passed、8 deselected（648.92s），随后6项数据库/RustFS重启测试全部通过，runner最终exit0并清理所属资源。该运行覆盖长备注初版；随后仅收紧文本上限，追加针对性验证如下。

以上均使用 `./scripts/test-runtime integration` 的独立 Compose 项目。前两轮已由runner清理所属容器/卷/网络；未重置或删除dev容器数据和Dataset Head。

## 当时尚待（现已完成）

- 合法可编译公式的6字节JSON转义组合、最大Catalog Field/Builtin完整记录回归与修复。
- 修复后的需求复审、实际存储/HTTP/Worker验收结果。
- 本票独立提交与tracker完成；未开始03。


## 最后边界修复与验证

- notes最终上限1024字符；Catalog说明文字384字符。没有截断内容或修改数值；最大合法编译公式的注释控制字符也纳入JSON字节核算。
- Run/Track完整provenance最坏文本组合：31645B /31684B；最大Catalog Field/Builtin及分页元数据：29751B /27965B，均不超过32768B。
- 最终分页/MCP/轨迹62项通过；Alpha/ResearchKind/Batch及边界70项通过（两组有重叠，不将其相加）。Web表单/时间线/安全投影39项通过，Webtypecheck和Pythonruff通过。
- 固定ingress重新测量4 passed /38 deselected；pytest0.91s、wall1.29s、峰值RSS157057024B。最终契约SHA256 e00ef7bf365b978fbe071083e2e09428e64f0309bd2907d547dca0fa09b89979，146969B。
- 最终快照 `/tmp/thesistrace-ticket02-review-final` Standards复审0项；Spec复审0项，provenance P1与Catalog边界均已关闭。
- 真实浏览器产品闭环与最终全量check/image smoke仍属于06，本票仅验证相关前端组件与输入行为，未声称浏览器验收完成。
