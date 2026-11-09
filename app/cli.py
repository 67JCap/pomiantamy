"""CLI: bynews run --once | --loop | preview <json-файл с тестовыми данными>.

Тестовый режим `preview` позволяет гонять весь пайплайн на фейковом LLM
без GPU и интернета — проверка контрактов интерфейсов.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def main():
    p = argparse.ArgumentParser(prog="bynews")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="запуск пайплайна")
    run.add_argument("--config", default="config/settings.yaml")
    grp = run.add_mutually_exclusive_group(required=True)
    grp.add_argument("--once", action="store_true")
    grp.add_argument("--loop", action="store_true")

    prev = sub.add_parser("preview", help="прогон на фикстурах (offline, fake-LLM)")
    prev.add_argument("fixture", help="JSON: [{title,text,url,source_id}]")

    args = p.parse_args()

    if args.cmd == "run":
        from app.pipeline.dag import Config, Pipeline
        cfg = Config(args.config)
        pipe = Pipeline(cfg)
        if args.once:
            asyncio.run(pipe.run_cycle())
        else:
            async def forever():
                while True:
                    await pipe.run_cycle()
                    await asyncio.sleep(cfg.get("pipeline", "interval_minutes", default=10) * 60)
            asyncio.run(forever())

    elif args.cmd == "preview":
        from app.pipeline.preview import run_preview
        asyncio.run(run_preview(args.fixture))

    return 0


if __name__ == "__main__":
    sys.exit(main())
