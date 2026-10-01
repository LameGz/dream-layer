---
name: dream
description: Dream Layer 的 agent 接入(丢废料入梦池/做一夜梦/读晨报/确认有效回流)。当用户说"丢进梦里""做个梦""看看晨报""昨晚梦到什么""这个梦有用/没用"或想记录一段被废弃的想法、失败的尝试、犹豫不决的判断时使用。
---

# Dream Layer:agent 工作流的 REM 层

Dream Layer 在夜里把白天流经系统的碎片(包括被拒的、犹豫的、废弃的)随机配对、高温碰撞,
早上产出 ≤3 条「观察 + 问题」。它只观察与提问,不执行、不建议;梦不立项,由人拍板。

## 使用时机

- 用户说"把这个丢进梦里 / 记下来今晚做梦用";
- 会话中出现**被废弃的方案、失败的尝试、犹豫未决的判断**——这些是梦最值钱的原料,主动提议投递;
- 用户说"做个梦 / 跑一夜 / 看看晨报 / 昨晚梦到什么"。

## 命令(在 Dream Layer 工作目录下执行;`--data-dir` 默认 ./data)

### 1. 丢一条碎片进梦池

```bash
python -m dreamlayer drop "被废弃的方案:把 waker 挂进 cron——违背节律而非指令" \
  --tag discarded --origin zcode
```

- `--tag` 五值:`selected / rejected / hesitated / discarded / unknown`(语义:这条碎片当时的命运)
- `--origin` 用你的名字(如 zcode / hermes),来源不同会增加梦的意外度
- 幂等:相同内容重复投递无害;写进 `data/drop/incoming.jsonl`,等下一次 collect

### 2. 做一夜梦(完整一夜:采集→配对→微型梦→醒来→晨报)

```bash
python -m dreamlayer run --once          # 真实模式,需要环境变量 DREAM_LLM_API_KEY
python -m dreamlayer run --once --fake   # FakeEngine:零网络零花费,冒烟用
```

产出:`data/journal/<日期>.md`(人读)+ `data/dreams/<日期>.jsonl`(机器读)+ `data/morning/<日期>.md`(晨报)。
水位:当日素材 < min_pool 时只记"太累但没东西可梦",不是错误。

### 3. 读晨报

打开 `data/morning/<今天>.md`,把每条「观察 / 问题」转述给用户;条目里带 confirm 提示。

### 4. 陪用户过审(登记有效回流)

- **用户在终端**:直接跑 `python -m dreamlayer review`——逐条展示观察/问题,按 1=recall / 2=trend / 3=cross_time 确认,s 跳过,q 结束;
- **用户在对话里口头确认**(如"第一条有用,是跨时关联"):agent 用批量登记,转述结果:

```bash
python -m dreamlayer review --batch "2026-10-01-12:cross_time,2026-10-01-06:trend"
```

确认写入 `data/reflux_log.jsonl`,是全部指标与降频的依据。**只登记用户明确认可的条目,不要代判**;
登记越少,它越安静(quiet_cycle 隔日梦)——这是特性,不是缺陷。

## 红线(不可违反)

- 梦话**永不回注**素材池:不要把晨报内容再 drop 回去——那是在喂镜子;
- 不为提高命中率调整任何随机性/权重/约束;
- drop 的原料是"流经系统的碎片",不是任务清单、不是待办;
- 梦不立项:观察与问题留给用户,不要替用户决定行动。
