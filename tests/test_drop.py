"""drop 采集与 POST 端点单测(FR-G3),含 Skill 接入的命令面(dreamlayer drop)。"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from dreamlayer.__main__ import main
from dreamlayer.collectors.drop import DropCollector
from dreamlayer.drop_server import make_handler, parse_body

GLOBS = ["**/*secret*", "**/*token*"]


# ---------- parse_body ----------

def test_parse_body_shapes():
    obj, bad = parse_body(b'{"content": "a", "time": "2026-10-01"}')
    assert len(obj) == 1 and bad == 0
    obj, bad = parse_body(b'[{"content": "a"}, {"content": "b"}, "junk"]')
    assert len(obj) == 2 and bad == 1
    obj, bad = parse_body(b'{"content": "a"}\nnot json\n{"content": "b"}\n')
    assert len(obj) == 2 and bad == 1
    assert parse_body(b"") == ([], 0)


# ---------- DropCollector ----------

def test_drop_collector_reads_and_excludes(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "a.jsonl").write_text(
        json.dumps({"content": "会话废料一", "time": "2026-10-01T10:00:00", "tag": "discarded"},
                   ensure_ascii=False) + "\n" +
        json.dumps({"content": "会话废料二", "time": "2026-10-01T11:00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (drop / "secret_token.jsonl").write_text(
        json.dumps({"content": "NEVER-READ-MARKER", "time": "2026-10-01T12:00:00"},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    c = DropCollector({"name": "dev-tools", "origin": "dev-tools", "path": str(drop)},
                      exclude_globs=GLOBS)
    items = c.collect()
    assert len(items) == 2
    assert all(it["origin"] == "dev-tools" for it in items)
    assert items[0]["tag"] == "discarded" and items[1]["tag"] == "unknown"  # default_tag
    assert all("NEVER-READ-MARKER" not in it["content"] for it in items)


def test_drop_collector_missing_path_returns_empty(tmp_path):
    c = DropCollector({"path": str(tmp_path / "nope")}, exclude_globs=[])
    assert c.collect() == []


# ---------- Skill 接入的命令面 ----------

def test_drop_cli_appends_and_collector_reads(tmp_path):
    """SKILL 的入口:python -m dreamlayer drop "..." → drop 目录 → DropCollector 读出。"""
    dd = str(tmp_path)
    assert main(["drop", "废弃方案:把 waker 挂进 cron", "--tag", "discarded",
                 "--origin", "zcode", "--data-dir", dd]) == 0
    assert main(["drop", "第二条碎片", "--data-dir", dd]) == 0  # 默认 tag/origin
    lines = (tmp_path / "drop" / "incoming.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tag"] == "discarded" and first["origin"] == "zcode"
    assert "waker" in first["content"]
    # 端到端:CLI 写下的文件立刻能被采集器读出
    items = DropCollector({"origin": "dev-tools", "path": str(tmp_path / "drop")},
                          exclude_globs=[]).collect()
    assert len(items) == 2
    assert items[0]["origin"] == "zcode"  # 透传,不被采集器默认值覆盖
    assert items[1]["origin"] == "agent" and items[1]["tag"] == "discarded"


# ---------- POST 端点 ----------

def _serve(tmp_path, token=None):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "drop", token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(url, body: bytes, headers=None):
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_post_endpoint_saves_jsonl(tmp_path):
    srv = _serve(tmp_path)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/drop"
        code, payload = _post(url, json.dumps(
            {"content": "废料一", "time": "2026-10-01T10:00:00"}, ensure_ascii=False).encode("utf-8"))
        assert code == 200 and payload["saved"] == 1
        code, payload = _post(url, json.dumps(
            [{"content": "废料二", "time": "2026-10-01T10:01:00"}] * 2, ensure_ascii=False).encode("utf-8"))
        assert code == 200 and payload["saved"] == 2
        files = list((tmp_path / "drop").glob("incoming-*.jsonl"))
        assert len(files) == 2
        all_text = "\n".join(f.read_text(encoding="utf-8") for f in files)
        assert "废料一" in all_text  # 同秒投递的文件名带 uuid,不按文件名猜内容归属
        # 端到端:端点写下的文件立刻能被 DropCollector 读出
        items = DropCollector({"origin": "dev-tools", "path": str(tmp_path / "drop")},
                              exclude_globs=[]).collect()
        assert len(items) == 3
    finally:
        srv.shutdown()


def test_post_endpoint_token_and_404(tmp_path):
    srv = _serve(tmp_path, token="topsecret")
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        code, _ = _post(f"{base}/drop", b'{"content": "x", "time": "2026-10-01"}')
        assert code == 401
        code, _ = _post(f"{base}/drop", b'{"content": "x", "time": "2026-10-01"}',
                        {"X-Dream-Token": "topsecret"})
        assert code == 200
        code, _ = _post(f"{base}/other", b"{}")
        assert code == 404
    finally:
        srv.shutdown()
