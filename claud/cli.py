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
    p_render.add_argument("--layout", default="blur", choices=render.LAYOUTS)
    p_render.add_argument("--facecam", type=render.Rect.parse, metavar="X,Y,W,H",
                          help="Facecam region as fractions of the frame, e.g. 0.75,0,0.25,0.3")
    p_render.add_argument("--gameplay", type=render.Rect.parse, metavar="X,Y,W,H")
    p_render.add_argument("--facecam-height", type=float, default=0.35,
                          help="Share of the vertical frame given to the facecam")
    p_render.add_argument("--captions", action="store_true")

    p_snap = sub.add_parser("snapshot", help="Save a frame from a clip URL or file, to find the facecam")
    p_snap.add_argument("src", help="Twitch clip URL or local video file")
    p_snap.add_argument("dst", type=Path, help="Output image, e.g. frame.png")
    p_snap.add_argument("--at", type=float, default=1.0, help="Timestamp in seconds")

    sub.add_parser("history", help="Show recent posts")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.cmd == "render":
        if args.layout == "split" and not args.facecam:
            parser.error("--layout split needs --facecam X,Y,W,H")
        subs = None
        if args.captions:
            words = captions.transcribe(args.src)
            center_y = args.facecam_height if args.layout == "split" else 0.7
            subs = captions.write_ass(
                captions.group_words(words, 3), args.dst.with_suffix(".ass"), center_y=center_y
            )
        render.render_vertical(
            args.src, args.dst, layout=args.layout, subtitles=subs,
            facecam=args.facecam, gameplay=args.gameplay, facecam_ratio=args.facecam_height,
        )
        print(f"Wrote {args.dst}")
        return

    if args.cmd == "snapshot":
        src = Path(args.src)
        if args.src.startswith(("http://", "https://")):
            from .twitch import download_url
            src = download_url(args.src, args.dst.with_suffix(".mp4"))
        render.snapshot(src, args.dst, args.at)
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
