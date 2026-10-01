"""POST 端点(FR-G3):任何会话/脚本把废料 POST 进来即完成接入,等下一次 collect 入梦。

仅标准库;默认只绑 127.0.0.1(隐私:废料不出本机)。可选令牌:设置环境变量
DREAM_DROP_TOKEN 后,请求须带 X-Dream-Token 头,否则 401。
请求体:单个 JSON 对象、JSON 数组或 JSONL 行,合法条目追加写入
<drop_dir>/incoming-<时间戳>-<随机>.jsonl,由 DropCollector 在 collect 时读入。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_ENV = "DREAM_DROP_TOKEN"
MAX_BODY_BYTES = 8 * 1024 * 1024  # 单次投递上限 8MB,防误用


def parse_body(body: bytes) -> tuple[list[dict], int]:
    """解析请求体 -> (合法条目, 坏行数)。支持 JSON 对象 / 数组 / JSONL 行。"""
    text = body.decode("utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        return [], 0
    obj = None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, dict):
        return [obj], 0
    if isinstance(obj, list):
        items = [o for o in obj if isinstance(o, dict)]
        return items, len(obj) - len(items)
    items, bad = [], 0
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(o, dict):
            items.append(o)
        else:
            bad += 1
    return items, bad


def make_handler(drop_dir: Path, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802(基类命名)
            self._send(200, {"endpoint": "dream drop", "POST": "/drop"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") not in ("/drop", "/collect"):
                self._send(404, {"error": "not found"})
                return
            if token and self.headers.get("X-Dream-Token") != token:
                self._send(401, {"error": "bad token"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(400, {"error": "bad length"})
                return
            items, bad = parse_body(self.rfile.read(length))
            if not items:
                self._send(400, {"error": "no valid items", "bad": bad})
                return
            drop_dir.mkdir(parents=True, exist_ok=True)
            name = f"incoming-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.jsonl"
            (drop_dir / name).write_text(
                "\n".join(json.dumps(it, ensure_ascii=False) for it in items) + "\n",
                encoding="utf-8",
            )
            self._send(200, {"saved": len(items), "bad": bad, "file": name})

        def log_message(self, *args):  # 静默默认访问日志(常驻输出干净)
            pass

    return Handler


def serve(drop_dir, host: str = "127.0.0.1", port: int = 8787,
          token_env: str = TOKEN_ENV) -> None:
    """阻塞式启动(常驻);令牌从环境变量读,不落盘(FR-H4 同款纪律)。"""
    handler = make_handler(Path(drop_dir), os.environ.get(token_env) or None)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"[dreamlayer] drop endpoint listening on http://{host}:{port}/drop "
          f"(dir={drop_dir}, token={'on' if os.environ.get(token_env) else 'off'})", flush=True)
    httpd.serve_forever()
