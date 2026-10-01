"""回流器(sink)—— P1 已建(FR-D)。

原则:只观察与提问,不执行、不建议——梦没有执行权(FR-D3)。
  - render():morning.md(条目 = observation + open_question + evidence,人类打开即读);
  - push():webhook 推送(飞书/Slack 卡片:"昨夜梦境 top3");URL 走环境变量(FR-H4 同款纪律),
    失败只报状态,不让夜停摆(NFR5)。
有效回流定义:人工确认为 recall / trend / cross_time(confirm CLI + reflux_log.jsonl,FR-D4)。
频控:每日上限 = rhythm.max_reflux_per_day(默认 3);连续 idle_days 天无有效回流自动隔日梦
(quiet_cycle,实现见 reflux.quiet_skip)。
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

_WEBHOOK_TIMEOUT_S = 10
_PUSH_LIMIT = 3


def _fmt_evidence(info: list[dict]) -> str:
    parts = []
    for e in info or []:
        parts.append(f"{e.get('key', '?')}({e.get('tag', '?')} · {e.get('origin', '?')} {e.get('date', '?')})")
    return " × ".join(parts) if parts else "-"


def render_entry(i: int, r) -> str:
    """单条晨报条目:observation + open_question + evidence + confirm 提示 + 豁免行。"""
    return (
        f"## {i}. [{r.verdict} · surprise {r.surprise:.2f}] {r.dream_id}\n"
        f"\n"
        f"观察:{r.observation}\n"
        f"问题:{r.open_question}\n"
        f"证据:{_fmt_evidence(getattr(r, 'evidence_info', None))}\n"
        f"\n"
        f"确认有效:dreamlayer confirm {r.dream_id} {r.verdict}\n"
        f"不当真也没关系——这本来就可能是 95% 的那部分。\n"  # 红队 D3:豁免行,清心理债务
    )


def render(reflux_list, out_path=None, *, night_note: str | None = None,
           morning_of: date | None = None) -> Path | None:
    """渲染 morning.md。空夜也要写(晨报是每日仪式,存在感指标 FR-I1 的载体)。"""
    if out_path is None:
        return None
    out_path = Path(out_path)
    day = morning_of or (date.fromisoformat(out_path.stem) if out_path.stem.count("-") == 2 else date.today())
    lines = [f"# morning · {day.isoformat()}", ""]
    if night_note:
        lines += [f"note: {night_note}", ""]
    if reflux_list:
        lines.append(f"昨夜 {len(reflux_list)} 条值得看(上限 3,频控 FR-D4)。")
        lines.append("")
        for i, r in enumerate(reflux_list, 1):
            lines += render_entry(i, r).splitlines()
        # 蓝队加固:拼好可复制的批量过审命令,把 30 秒压到 10 秒
        batch = ",".join(f"{r.dream_id}:{r.verdict}" for r in reflux_list)
        lines += ["", f"一键全收(若条条都认):dreamlayer review --batch \"{batch}\"", ""]
    else:
        lines += ["昨夜无晨报条目。", ""]
    lines += ["---", "只观察与提问,不执行、不建议;梦不立项,由人决定。", ""]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def digest_text(reflux_list) -> str:
    """卡片/推送正文:"昨夜梦境 top3" 逐条一行。"""
    lines = [f"昨夜梦境 top{min(len(reflux_list), _PUSH_LIMIT)}"]
    for r in reflux_list[:_PUSH_LIMIT]:
        lines.append(f"[{r.verdict}] {r.observation} —— {r.open_question}({r.dream_id})")
    return "\n".join(lines)


def _payload_for(url: str, reflux_list) -> dict:
    """按端点风格构造卡片:feishu/larksuite -> interactive 卡片,其余按 Slack 文本。"""
    text = digest_text(reflux_list)
    if "feishu" in url or "larksuite" in url:
        return {
            "msg_type": "interactive",
            "card": {"config": {"wide_screen_mode": True},
                     "elements": [{"tag": "markdown", "content": text}]},
        }
    return {"text": text}


def push(reflux_list, webhook_url: str | None = None) -> tuple[bool, str]:
    """webhook 推送;未配置返回 (False, 'no webhook'),失败返回 (False, 原因),从不抛出。"""
    if not webhook_url:
        return False, "no webhook"
    if not reflux_list:
        return False, "nothing to push"
    payload = _payload_for(webhook_url, reflux_list)
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as resp:
            return True, f"HTTP {resp.status}"
    except Exception as e:  # 推送失败不影响 journal/morning 已落盘(NFR5)
        return False, str(e)
