# Dream Layer

**把白天留下的碎片随机配对，生成值得人再看一眼的观察与问题。**

[English](README.md) · [Agent 接入说明](skills/dream/SKILL.md) · [设计与评审记录](docs/brainstorm/) · [CI](https://github.com/LameGz/dream-layer/actions/workflows/test.yml)

Dream Layer 为智能体工作流提供实验性的 REM 层：收集入选、被拒、犹豫或废弃的素材，随机配对并调用模型联想，再筛出晨报候选。默认晨报最多 3 条，只给观察和问题。是否有用由人确认，系统不据此执行任务，也不把梦话重新投入素材池。

## 先跑一夜模拟

需要 Python 3.11+；CI 使用 Python 3.12。以下命令从源码运行，运行时依赖为 PyYAML 和 OpenAI SDK。

```bash
git clone https://github.com/LameGz/dream-layer.git
cd dream-layer
python -m venv .venv
```

激活环境：Windows PowerShell 用 `.venvScriptsActivate.ps1`，macOS/Linux 用 `source .venv/bin/activate`，然后安装：

```bash
python -m pip install -e ".[dev]"
```

先在 `config/rhythm.local.yaml` 写入以下本机配置，使用仓库演示种子和手动 drop，不扫描示例中的个人目录，也不推送 webhook。该文件已被 Git 忽略；`collectors` 会整体覆盖默认采集器配置。

```yaml
collectors:
  demo: {}
  drop:
    - name: manual
      path: data/drop
  read_disk: []
webhook_url_env: ""
quiet_cycle: { mode: "off" }
```

```bash
python -m dreamlayer run --once --fake
```

这会执行采集、配对、模拟生成和筛选，并在 `data/` 写日志、梦境和晨报。素材不足时写出原因。`--fake` 只替换模型引擎，仍然按配置读取素材和写盘；它的产物用于验证流程。

## 从投料到人工确认

```text
drop / 读盘素材
    → 隐私过滤与保留期 → 素材池 → 随机配对
    → 模型碰撞 → 醒来筛选 → 晨报
    → 人工确认 → 确认日志与指标
```

```bash
python -m dreamlayer drop "废弃方案：把全部模块放到同一个进程" --tag discarded --origin manual
python -m dreamlayer run --once --fake
python -m dreamlayer review
python -m dreamlayer metrics
```

素材标签为 `selected`、`rejected`、`hesitated`、`discarded`、`unknown`；权重由 `config/weights.yaml` 配置。配对考虑标签、来源、时间桶和覆盖次数，不使用语义相似度选对。同一素材在一夜中最多参与一对。

审核时只确认你判断有用的内容。可用结论为 `recall`、`trend`、`cross_time`；也可以跳过。按晨报中的实际编号直接确认：

```bash
python -m dreamlayer confirm 2026-10-16-abcdef012345-01 cross_time
```

上面的编号仅为格式示例，请替换为实际 `dream_id`。Agent 可使用 `review --batch "实际编号:cross_time"` 登记用户已经表达的判断，不能代替用户判定。

## 运行时间与记录身份

`python -m dreamlayer run` 启动常驻进程，默认本地时间 02:30 采集、03:00 入梦、05:00 筛选；进程需要保持运行。`run --once` 立即执行完整一轮。启动时具备补跑判定，长时间没有确认时可按 `quiet_cycle` 降为隔日运行。

凌晨的近期素材窗口覆盖前一日与当日已采入素材，历史抽样另计。入池与清理使用相同的保留期截止日，避免刚清掉的旧来源重新回池。

每次运行有独立的 12 位 `attempt_id`。新编号为 `YYYY-MM-DD-<attempt_id>-NN`；同日重跑不会复用编号或覆盖上一轮原始梦境。旧 `YYYY-MM-DD-NN` 编号继续可查询、确认。

| 路径 | 内容 |
|---|---|
| `data/drop/`、`data/pool/` | 待采素材与素材池 |
| `data/dreams/attempts/<日期>/` | 各次运行的梦境、元数据与确认状态 |
| `data/dreams/<日期>.jsonl` | 最近一次运行的兼容视图 |
| `data/journal/attempts/<日期>/` | 新运行的逐次 Markdown 日志 |
| `data/journal/<日期>.md`、`data/morning/<日期>.md` | 当日展示日志与晨报，后续运行可更新 |
| `data/reflux_log.jsonl`、`data/report/` | 人工确认日志、指标与图表 |

旧梦境可按编号确认；`review --date` 读取该日期的最新候选视图。保留期控制素材池，不等于自动删除日志与归档。

## 配置与真实模型

| 文件 | 内容 |
|---|---|
| `config/weights.yaml` | 标签权重、历史采样与覆盖权重 |
| `config/rhythm.yaml` | 时间、水位、配对约束、采集器、晨报上限 |
| `config/rhythm.local.yaml` | 本机顶层覆盖；嵌套字段整体替换 |
| `config/privacy.yaml` | 路径排除、脱敏、来源开关、保留期、隐私模式 |
| `config/engine.yaml` | OpenAI 兼容端点、模型、密钥环境变量名 |

仓库 `rhythm.yaml` 含示例本地采集路径；接入实际数据前应换成自己选择的来源。默认 `privacy.mode: open`，真实模型会收到素材内容；默认引擎端点见 `engine.yaml`。通过环境变量 `DREAM_LLM_API_KEY` 提供密钥，再去掉 `--fake` 运行。

使用本地模型时，将 `privacy.mode` 改为 `local_only`，同时把 `engine.base_url` 指向本机；非本机引擎地址会被拒绝。若需要完全本地运行，也要关闭或核对 webhook：模型模式并不代替推送配置。

可选的 `listen` 提供默认绑定 `127.0.0.1:8787` 的 `/drop` 接口，令牌使用 `DREAM_DROP_TOKEN`；晨报推送 URL 使用 `DREAM_WEBHOOK_URL`。详细参数可用 `python -m dreamlayer <子命令> --help` 查看。

## 与另外两个项目协作

- [agent-tree](https://github.com/LameGz/agent-tree) 记录执行事件，可显式把失败、打回、犹豫片段投给 Dream，并读取晨报；它不会因此自动启动 Dream 的常驻调度。
- [Synapse Graph Skills](https://github.com/LameGz/synapse-graph-skills) 保存工程记忆。Dream 的观察不自动写成 Synapse 事实；需要人工判断后再按记忆提案流程处理。

## 验证与实验边界

```bash
python -m pytest tests -q
```

2026-10-16 的 Ubuntu、Windows CI 均为 **197 passed**。回归覆盖跨日素材、同日重跑身份、旧编号确认、自测用假引擎、过期素材和未闭合 frontmatter。测试通过说明这些流程符合断言，不能证明生成的观察有用。

随机碰撞的价值仍是待验证假设。“95% 是噪声”是设计预期，不是测量结果。历史评审与退出设想见 [docs/brainstorm/](docs/brainstorm/)；没有自动归档项目的机制。指标多使用按日期的最新视图，不能当作所有运行归档的完整统计；A/B 分组对新运行编号的统计仍有限制，不据此宣称实验结论。

真实模型质量、长期收益、推送服务与宿主端到端行为需独立验证。

## 许可

[MIT License](LICENSE)。
