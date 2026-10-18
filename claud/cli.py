from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from . import captions, config, pipeline, render


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="claud", description=__doc__)
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Find, render and post clips once")
    p_run.add_argument("--dry-run", action="store_true", help="Render but don't upload")

    p_loop = sub.add_parser("loop", help="Run forever on an interval")
    p_loop.add_argument("--every", type=int, default=60, help="Minutes between runs")

    p_auth = sub.add_parser("auth", help="One-time OAuth for an upload platform")
    p_auth.add_argument("platform", choices=pipeline.PLATFORMS)

    p_render = sub.add_parser("render", help="Render a local video file to vertical (for testing)")
    p_render.add_argument("src", type=Path)
    p_render.add_argument("dst", type=Path)
    p_render.add_argument("--layout", default="blur", choices=["blur", "crop"])
    p_render.add_argument("--captions", action="store_true")

    sub.add_parser("history", help="Show recent posts")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.cmd == "render":
        subs = None
        if args.captions:
            words = captions.transcribe(args.src)
            subs = captions.write_ass(captions.group_words(words, 3), args.dst.with_suffix(".ass"))
        render.render_vertical(args.src, args.dst, layout=args.layout, subtitles=subs)
        print(f"Wrote {args.dst}")
        return

    cfg = config.load(args.config)

    if args.cmd == "run":
        pipeline.run(cfg, dry_run=args.dry_run)
    elif args.cmd == "loop":
        while True:
            try:
                pipeline.run(cfg)
            except Exception:
                logging.exception("Run failed")
            time.sleep(args.every * 60)
    elif args.cmd == "auth":
        pcfg = cfg.platform(args.platform)
        if args.platform == "youtube":
            from .uploaders import youtube
            youtube.authorize(pcfg["client_secrets"], pcfg["token_file"])
        else:
            from .uploaders import tiktok
            tiktok.authorize(pcfg["token_file"])
    elif args.cmd == "history":
        from .db import DB
        for row in DB(cfg.data_dir / "claud.db").history():
            status = row["remote_id"] if row["status"] == "posted" else f"FAILED: {row['error']}"
            print(f"{row['updated_at']}  {row['platform']:<8} {row['streamer']:<16} {row['title'][:40]:<40}  {status}")


if __name__ == "__main__":
    main()
