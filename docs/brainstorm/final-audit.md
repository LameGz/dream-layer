# Dream Layer 终审审计报告(红蓝裁决改动落地批次)

> 日期:2026-10-01 · 审计员:独立终审(agent 会话) · 依据:[verdict.md](verdict.md)三/四/六节
> 范围:C1-C5、D1/D3/D4、metrics 增强、privacy/README/test_no_semantics 共 11 条

---

## 【总体结论】**有条件通过**

11 条全部存在且主行为与描述一致,pytest 179 全绿,未发现红线级破坏(配对默认路径仍零语义、G6 素材唯一性在 anchor_mix 下保持)。但发现 1 条中等问题(quiet_cycle 与 A/B 交替共用日期序数奇偶,静默期实验分组系统性偏斜)与若干小问题,建议修完中等问题再进主干,小问题可随下一批带走。

---

## 【逐条核对表】

| # | 条目 | 结论 | 证据 |
|---|---|---|---|
| C1 | numbers() 要求 ≥4 位或含小数点 | ✅ | waker.py:96 `if "." in n or len(n) >= 4`;test_waker.py:84 断言 `"2"`/`"10"`/`"3"` 被滤、`"2.4"`/`"2026"` 保留 |
| C2 | 稀有锚点钉死 2 ≤ count ≤ max(2, ceil(0.05·N));强弱分级;Lane B 强锚点优先 | ✅ | waker.py:119-120 `_rare_cap`;:156 `2 <= df <= cap`;:160 `strong = bool(nums or proper)`;:281-287 Lane B 排序 `not anchor["strong"]` 在前 |
| C3 | IMPERATIVE_MARKS 补英文集;小写匹配 | ✅ | waker.py:42-46 补 7 个英文标记;:223 `q.lower()`;test_waker.py:116-117 断言 "You should"/"Next step" 被拦 |
| D1 | privacy.mode + config 校验 + build_engine local_only 拒非本机 | ✅ | privacy.yaml:34;config.py:141-143 校验枚举;scheduler.py:49-57 host ∉ {localhost,127.0.0.1,::1} 即 RuntimeError;fake 在 :46-47 提前放行 |
| D3 | 晨报条目豁免行 + 底部 review --batch | ✅ | sink.py:40 豁免行"不当真也没关系";:61 拼 `dreamlayer review --batch "id:verdict,..."` |
| C4 | trend 写 due(+14 天)/ reviewed;pending_trend_reviews | ✅ | reflux.py:73-77;metrics.py:217-232 `due <= today 且未 reviewed`;test_verdict_changes.py:126-151 覆盖到期/已对账 |
| C5 | anchor_mix 旁路 + 日期序数交替 + arm 进 night meta + ab_stats | ✅ | pool.py:206-279;scheduler.py:179-181、206-207;metrics.py:235-251 dream_id 日期 → dreams jsonl night meta.experiment |
| metrics 增强 | 诚实阀门/Lane B 配额/lane 分组回流接入 report_text | ✅ | metrics.py:181-214 dream_stats;:273-275 三行接入;另有 ab_stats/到期对账区块 :278-290 |
| bearer 形态 | redact_patterns 补 bearer | ✅ | privacy.yaml:21 `(?i)bearer\s+[A-Za-z0-9._-]{20,}` |
| 静态审计 | test_no_semantics.py 禁语义符号 | ✅ | tests/test_no_semantics.py:12-29 剥注释/docstring 后扫 similar/cosine/embedding/distance/semantic,并断言 lane_b_anchor 存在 |
| README | 隐私(说在前面)/ kill switch / 对照实验说明 | ✅ | README.md:133-137 默认云端明示 + local_only 指引;:139-141 90 天 <3 条归档;:149 对照实验说明 |

---

## 【新发现问题】(按严重度排序)

### 中

1. **quiet_cycle 与 A/B 交替共用日期序数奇偶,静默期实验分组系统性偏斜**
   - 位置:reflux.py:135(`today.toordinal() % 2 == 1` 跳过)× scheduler.py:180(序数奇 → arm B)
   - 问题:连续 idle 天触发隔日梦时,被跳过的恰好全是奇序数日 = B 夜(anchor_mix)。静默期越久,B 组样本越被系统性抽空,ab_stats 的"两组相当/谁更高"结论会被污染——这恰恰是 C5 实验要回答的问题。
   - 建议修法:arm 交替改用"已实际做梦的夜数"奇偶(读 journal 计数)而非日历序数;或 quiet_skip 跳过日不打乱交替序列(跳过的夜不占 arm 名额)。取其一即可,改动都在 10 行内。

### 低

2. **`_anchor_pairs` docstring 声称"软约束照常计数",实际传空列表不计数**
   - 位置:pool.py:255(docstring)vs :278 `_count_relaxed(a, b, [], today, stats)`
   - 影响:anchor_mix 夜的 origin_relaxed/time_relaxed 被少计,journal 健康信号轻微失真;文档与代码自相矛盾。
   - 建议:`_count_relaxed(a, b, soft, ...)` 传入真实 soft 列表,或改 docstring 说明刻意不计。

3. **配对期与醒来期的"稀有"口径不一致(分母不同)**
   - 位置:pool.py:259 `_doc_counts(candidates)`(仅当夜候选)vs waker.py:258 `_doc_counts(materials.values())`(全池)
   - 影响:同一 token 在配对侧被认定稀有、在 Lane B 侧可能不稀有(或反之),B 夜配出的锚点对醒来时不一定能走 Lane B。不是 bug,但 C5 的"锚点对"定义在两侧不对称,解读 8 周数据时需知悉。
   - 建议:在 pool._anchor_pairs docstring 里明说"稀有锚点的分母是当夜候选集",或统一为全池口径(后者要传 pool 引用,改动更大,建议前者)。

4. **test_verdict_changes.py docstring 声称覆盖"D3 豁免行",实际无断言**
   - 位置:tests/test_verdict_changes.py:1(docstring 列了 D3)——全文无 `不当真` 断言
   - 影响:豁免行回归无保护,sink.py:40 被误删时测试不会红。
   - 建议:test_sink.py 的 render_entry 测试里补一行 `assert "不当真也没关系" in text`。

5. **README 测试用例数未随本批改动更新**
   - 位置:README.md:94、:130 写"160 个用例",实际 pytest 收集 179
   - 建议:改为 179,或写"≥170"避免以后每批都要同步。

### 观察项(不是问题,记录在案)

- **anchor_mix 奇数 target**:anchor_n = target // 2(pool.py:238),随机循环补足到 target(:244),总对数不偏离;仅锚点占比略低于 50%(target=5 时 40%)。可接受,不建议改。
- **YAML `ab: yes` 不构成校验绕过**:PyYAML 将 `yes` 解析为真 bool True,config.py:175 的 isinstance 校验接受的是合法真值,语义无扭曲;加引号的 `"yes"` 字符串会被拦(test_verdict_changes.py:116-121 已覆盖)。审计假设的绕过路径不存在。
- **_doc_counts 签名变更后所有调用点一致**:waker.py:258、pool.py:259 均解包 (df, total);lane_b_anchor/grounding_ok 的新签名在 wake() 内(:273、:330)传递一致,测试同口径。
- **sink 豁免行未破坏既有断言**:test_sink.py 全部通过(含行数敏感的 `text.count("dreamlayer confirm") == 2`,豁免行不含该前缀)。
- **wake_phase 重写 dreams 保留 experiment 键**:scheduler.py:240 `dict(night_meta or {})` 整体保留,:265 原样回写,ab_stats 分组依据不丢。

---

## 【测试状态】

```
cd dream-layer && .venv/Scripts/python.exe -m pytest -q
179 passed in 7.68s
```

与审计预期的 179 全绿一致,零失败、零跳过。新增用例集中在 test_verdict_changes.py(11 个,D1×5 / C5×4 / C4×2)。

---

## 【与 verdict 的偏差】

**verdict 说了但代码没做:**

1. **晨报打开率观测(D2 的"加一个观测"、最终裁决"跑起来后"第 7 条)未实现**。verdict 明确"metrics 里记晨报打开率(用 review 命令的调用时间近似)",但 __main__.py `_cmd_review` 不留下任何时间戳,metrics.py 无打开率字段。审计清单第 8 条把它摘掉了(只要求 dream_stats 三项),但作为与 verdict 的对照必须点名:这是 verdict 明文、本批未交付的一项。因其归属"跑起来后(8 周数据期)"阶段而非"本周(开跑前)"安全带,不构成阻塞,建议补登 backlog。

**代码做了但 verdict 没说(超范围改动):**

2. **pool.py:325 注释自称"终审顺手修"**:`_form_pair` 硬约束无解的重试路径改为同样走 `_pick_b`(尽力满足软约束),旧行为推测是随机接受。方向正确、有测试背书,但属于 verdict 范围外的行为变更,按纪律应单独成行记录——此处仅注释提及,建议在本审计报告中追认(本行即追认)。

其余改动均在 verdict 处方清单内,无其他超范围行为变更。

---

## 【终审签字】

这批改动忠实执行了裁决:三条安全带(D1 硬开关、C5 对照旁路、D4 kill switch)全部系上,C1-C3 三个闸的修补精确到行,红线(默认随机配对零语义、G6 素材唯一性、confirm 不回注)在 anchor_mix 旁路下无一被破坏,179 测试全绿。**结论:可以进主干**,附带一个条件——问题 1(quiet_cycle 与 A/B 序数耦合)必须在实验数据被解读之前修掉,否则 8 周后 ab_stats 的分组确认率可能回答一个被偏斜污染的问题;四个低危问题与"晨报打开率"欠项建议登记 backlog 随下一批处理。裁决说的"改完语法,这周就寄"——语法已改完,可以寄。
