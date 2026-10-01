"""CLI(C-9)。

    python -m dreamlayer run                       # 常驻,真实节律,真实引擎
    python -m dreamlayer run --once                # 即时完整一夜(collect+dream+wake),真实引擎
    python -m dreamlayer run --once --fake         # FakeEngine,零网络零花费
    python -m dreamlayer run --once --fake --config-dir <dir>   # 测试用自定义配置

    python -m dreamlayer confirm 2026-10-01-07 recall   # 人工确认有效回流(FR-D4/FR-I3)
    python -m dreamlayer metrics                        # 五指标 + 保底产物(FR-I1/I2)
    python -m dreamlayer listen                         # POST 端点:会话废料投递(FR-G3)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .reflux import REFLUX_VERDICTS
from .scheduler import build_collectors, build_engine, run_daemon, run_once


def _cmd_run(args) -> int:
    cfg = load_config(args.config_dir)
    data_dir = Path(args.data_dir)
    collectors = build_collectors(cfg, data_dir)
    engine = build_engine(cfg, fake=args.fake)

    if args.once:
        path = run_once(cfg, collectors, engine, data_dir=data_dir)
        print(f"journal: {path}")
        if path is not None:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("meta:"):
                    print(line)
                    break
        morning = data_dir / "morning" / f"{path.stem if path else ''}.md"
        if path is not None and morning.exists():
            print(f"morning: {morning}")
        return 0

    print(f"[dreamlayer] daemon started (config={args.config_dir}, data={data_dir})", flush=True)
    run_daemon(cfg, collectors=collectors, engine=engine, data_dir=data_dir)
    return 0


def _cmd_confirm(args) -> int:
    from . import reflux

    data_dir = Path(args.data_dir)
    if args.verdict not in REFLUX_VERDICTS:
        print(f"verdict 必须是 {REFLUX_VERDICTS} 之一(梦只观察与提问,没有 action)", file=sys.stderr)
        return 1
    dream = reflux.find_dream(data_dir, args.dream_id)
    if dream is None:
        print(f"找不到 dream_id={args.dream_id}(格式 YYYY-MM-DD-NN,见 morning.md 或 journal pair 序号)",
              file=sys.stderr)
        return 1
    log = reflux.load_log(data_dir)
    if reflux.already_confirmed(log, args.dream_id):
        print(f"{args.dream_id} 已确认过,不重复登记", file=sys.stderr)
        return 1
    reflux.append_confirm(data_dir, args.dream_id, args.verdict, dream)
    reflux.mark_confirmed(data_dir, args.dream_id)
    print(f"confirmed: {args.dream_id} -> {args.verdict} ({reflux.log_path(data_dir)})")
    return 0


def _cmd_review(args) -> int:
    """交互过审(FR-D4 的体验面):逐条过晨报候选;--batch 供 agent 从对话收集后批量落账。"""
    from datetime import date as _date

    from . import reflux

    data_dir = Path(args.data_dir)
    if args.batch:
        ok, warns = reflux.apply_batch(data_dir, args.batch.split(","))
        for w in warns:
            print(f"! {w}")
        print(f"batch: 登记 {ok} 条 -> {reflux.log_path(data_dir)}")
        return 0
    day = _date.fromisoformat(args.date) if args.date else _date.today()
    candidates = reflux.load_candidates(data_dir, day)
    registered = reflux.run_wizard(candidates, data_dir)
    if registered:
        print(f"reflux_log: {reflux.log_path(data_dir)}(梦产率与 quiet_cycle 读它)")
    return 0


def _cmd_drop(args) -> int:
    """FR-G3 的 CLI 面:agent/skill 一条命令投废料,等下一次 collect 入梦(幂等去重)。"""
    import json
    from datetime import datetime

    drop_dir = Path(args.data_dir) / "drop"
    drop_dir.mkdir(parents=True, exist_ok=True)
    item = {
        "content": args.content,
        "time": datetime.now().isoformat(timespec="seconds"),
        "tag": args.tag,
        "origin": args.origin,
    }
    target = drop_dir / "incoming.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"dropped -> {target}(等下一次 collect 入梦;python -m dreamlayer run --once 可立即做一夜)")
    return 0


def _cmd_metrics(args) -> int:
    from . import metrics

    data_dir = Path(args.data_dir)
    out_dir = metrics.write_report(data_dir)
    print(metrics.report_text(data_dir), end="")
    for name in ("drift.svg", "band.svg"):
        if (out_dir / name).exists():
            print(f"chart: {out_dir / name}")
    return 0


def _cmd_listen(args) -> int:
    from .drop_server import serve

    drop_dir = Path(args.drop_dir) if args.drop_dir else Path(args.data_dir) / "drop"
    serve(drop_dir, host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="dreamlayer",
        description="Dream Layer — agent 工作流的 REM 层(节律触发、强制随机配对、无目标自由联想)",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    runp = sub.add_parser("run", help="常驻节律;--once 即时完整一夜")
    runp.add_argument("--once", action="store_true", help="即时完整一夜(collect+dream+wake)后退出")
    runp.add_argument("--fake", action="store_true", help="FakeEngine:零网络零花费(开发/CI 用)")
    runp.add_argument("--config-dir", default="config", help="四份 yaml 所在目录(默认 ./config)")
    runp.add_argument("--data-dir", default="data", help="运行时产物目录(默认 ./data)")
    runp.set_defaults(func=_cmd_run)

    cp = sub.add_parser("confirm", help="人工确认有效回流:dream_id = journal pair 序号(YYYY-MM-DD-NN)")
    cp.add_argument("dream_id")
    cp.add_argument("verdict", help="有效回流三值:recall | trend | cross_time")
    cp.add_argument("--data-dir", default="data")
    cp.set_defaults(func=_cmd_confirm)

    rp = sub.add_parser("review", help="交互过审:逐条过晨报候选,登记有效回流(默认今天)")
    rp.add_argument("--date", default=None, help="过审哪一天的晨报(默认今天)")
    rp.add_argument("--batch", default=None,
                    help='非交互批量(agent 用):"dream_id:verdict,dream_id:verdict"')
    rp.add_argument("--data-dir", default="data")
    rp.set_defaults(func=_cmd_review)

    dp = sub.add_parser("drop", help="投递一条废料进 drop 目录(SKILL 接入的命令面)")
    dp.add_argument("content", help="碎片正文")
    dp.add_argument("--tag", default="discarded",
                    help="五值之一:selected | rejected | hesitated | discarded | unknown(默认 discarded)")
    dp.add_argument("--origin", default="agent", help="来源标识(默认 agent)")
    dp.add_argument("--data-dir", default="data")
    dp.set_defaults(func=_cmd_drop)

    mp = sub.add_parser("metrics", help="五指标报告 + 被拒池漂移图/邻近带曲线(保底产物)")
    mp.add_argument("--data-dir", default="data")
    mp.set_defaults(func=_cmd_metrics)

    lp = sub.add_parser("listen", help="POST 端点(默认 127.0.0.1:8787 /drop):会话废料投递 drop 目录")
    lp.add_argument("--host", default="127.0.0.1")
    lp.add_argument("--port", type=int, default=8787)
    lp.add_argument("--drop-dir", default=None, help="默认 <data-dir>/drop")
    lp.add_argument("--data-dir", default="data")
    lp.set_defaults(func=_cmd_listen)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
