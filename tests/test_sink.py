"""sink 单测(FR-D):morning.md 渲染 / webhook payload / push 降级。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dreamlayer.sink import _payload_for, digest_text, push, render, render_entry
from dreamlayer.waker import Reflux


def _reflux(i=1, verdict="trend", dream_id=None):
    return Reflux(
        dream_id=dream_id or f"2026-10-01-{i:02d}", verdict=verdict, surprise=0.72, lane="A",
        fragment="梦话原文", evidence=["ka", "kb"],
        observation="两条被拒记录在说同一件事",
        open_question="ka 里的 2.4 后来怎么样了?",
        evidence_info=[
            {"key": "ka", "tag": "rejected", "origin": "daily-pipeline", "date": "09-28"},
            {"key": "kb", "tag": "hesitated", "origin": "zcode", "date": "10-01"},
        ],
    )


def test_render_entry_has_observation_question_evidence_and_confirm_hint():
    text = render_entry(1, _reflux())
    assert "[trend · surprise 0.72] 2026-10-01-01" in text
    assert "观察:两条被拒记录在说同一件事" in text
    assert "问题:ka 里的 2.4 后来怎么样了?" in text
    assert "ka(rejected · daily-pipeline 09-28) × kb(hesitated · zcode 10-01)" in text
    assert "dreamlayer confirm 2026-10-01-01 trend" in text
    assert "不当真也没关系" in text  # 红队 D3 豁免行(终审问题 4:回归保护)


def test_render_morning_md(tmp_path):
    out = tmp_path / "morning" / "2026-10-01.md"
    render([_reflux(1), _reflux(2, "cross_time", "2026-10-01-02")], out_path=out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# morning · 2026-10-01")
    assert "昨夜 2 条值得看" in text
    assert text.count("dreamlayer confirm") == 2
    assert "只观察与提问" in text  # FR-D3:不执行不建议的落款


def test_render_empty_night_with_note(tmp_path):
    out = tmp_path / "morning" / "2026-10-01.md"
    render([], out_path=out, night_note="今夜无梦")
    text = out.read_text(encoding="utf-8")
    assert "note: 今夜无梦" in text
    assert "昨夜无晨报条目" in text


def test_payload_for_feishu_vs_slack():
    rs = [_reflux()]
    feishu = _payload_for("https://open.feishu.cn/open-apis/bot/v2/hook/xxx", rs)
    assert feishu["msg_type"] == "interactive"
    slack = _payload_for("https://hooks.slack.com/services/xxx", rs)
    assert set(slack) == {"text"}
    assert "昨夜梦境 top1" in digest_text(rs)


def test_push_no_webhook_and_empty():
    assert push([], None) == (False, "no webhook")
    assert push([_reflux()], None) == (False, "no webhook")


def test_push_to_local_endpoint(tmp_path):
    received = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append(json.loads(body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ok, detail = push([_reflux()], f"http://127.0.0.1:{srv.server_address[1]}/hook")
        assert ok is True and detail == "HTTP 200"
        assert received and received[0]["text"].startswith("昨夜梦境 top1")
    finally:
        srv.shutdown()


def test_push_failure_never_raises():
    ok, detail = push([_reflux()], "http://127.0.0.1:1/nope")  # 端口 1,必失败
    assert ok is False and detail
