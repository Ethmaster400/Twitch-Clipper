from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import captions, config, pipeline, render


def main(argv: list[str] | None = None) -> None:
    # Windows consoles default to cp1252, which can't print emoji in clip titles.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(prog="claud", description=__doc__)
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Find, render and post clips once")
    p_run.add_argument("--dry-run", action="store_true", help="Render but don't upload")

    p_loop = sub.add_parser("loop", help="Run forever on an interval")
    p_loop.add_argument("--every", type=int, default=60, help="Minutes between runs")

    p_auth = sub.add_parser("auth", help="One-time OAuth for an upload platform")
    p_auth.add_argument("platform", choices=("youtube", "tiktok"))

    p_render = sub.add_parser("render", help="Render a local video file to vertical (for testing)")
    p_render.add_argument("src", type=Path)
    p_render.add_argument("dst", type=Path)
    p_render.add_argument("--layout", default="auto", choices=("auto",) + render.LAYOUTS)
    p_render.add_argument("--facecam", type=render.Rect.parse, metavar="X,Y,W,H",
                          help="Facecam region as fractions of the frame, e.g. 0.75,0,0.25,0.3")
    p_render.add_argument("--gameplay", type=render.Rect.parse, metavar="X,Y,W,H")
    p_render.add_argument("--facecam-height", type=float, default=0.35,
                          help="Share of the vertical frame given to the facecam")
    p_render.add_argument("--gameplay-mode", default="crop", choices=("crop", "fit"),
                          help="Split layout: crop = zoom into the gameplay, fit = whole frame on blur")
    p_render.add_argument("--type", default="gaming", choices=("gaming", "irl"),
                          help="Stream type, as the pipeline labels it: gaming or irl (full-screen camera)")
    p_render.add_argument("--captions", action="store_true")

    p_snap = sub.add_parser("snapshot", help="Save a frame from a clip URL or file, to find the facecam")
    p_snap.add_argument("src", help="Twitch clip URL or local video file")
    p_snap.add_argument("dst", type=Path, help="Output image, e.g. frame.png")
    p_snap.add_argument("--at", type=float, default=1.0, help="Timestamp in seconds")

    p_detect = sub.add_parser("detect", help="Auto-detect the facecam in a clip URL or file")
    p_detect.add_argument("src", help="Twitch clip URL or local video file")
    p_detect.add_argument("--preview", type=Path, help="Save a frame with the detected box drawn on it")

    sub.add_parser("history", help="Show recent posts")
    sub.add_parser("profiles", help="Check the Upload-Post API key and list your Upload-Post profiles")
    p_status = sub.add_parser("status", help="Ask Upload-Post how recent uploads went on each platform")
    p_status.add_argument("--last", type=int, default=5, help="How many recent uploads to check")
    sub.add_parser("retry", help="Clear failed attempts so those clips are tried again on the next run")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.cmd == "render":
        layout, region = args.layout, args.facecam
        if layout in ("auto", "split", "face"):
            from .pipeline import resolve_layout
            streamer = config.Streamer("cli", "cli", layout=None if layout == "auto" else layout, facecam=region)
            layout, region = resolve_layout({}, streamer, args.src, stream_type=args.type)
            print(f"Layout: {layout}" + (f", region {region}" if region else ""))
        subs = None
        if args.captions:
            words = captions.transcribe(args.src)
            center_y = args.facecam_height if layout == "split" else 0.7
            subs = captions.write_ass(
                captions.group_words(words, 3), args.dst.with_suffix(".ass"), center_y=center_y
            )
        render.render_vertical(
            args.src, args.dst, layout=layout, subtitles=subs,
            facecam=region if layout == "split" else None, window=region if layout == "face" else None,
            gameplay=args.gameplay, facecam_ratio=args.facecam_height,
            gameplay_mode=args.gameplay_mode,
        )
        print(f"Wrote {args.dst}")
        return

    if args.cmd in ("snapshot", "detect"):
        src = Path(args.src)
        if args.src.startswith(("http://", "https://")):
            from .twitch import download_url
            src = download_url(args.src, Path("data/raw") / (args.src.rstrip("/").rsplit("/", 1)[-1] + ".mp4"))
        if args.cmd == "snapshot":
            render.snapshot(src, args.dst, args.at)
            print(f"Wrote {args.dst}")
            return
        from . import facecam
        rect = facecam.detect(src)
        if rect is None:
            print("No facecam found; this clip would use the blur layout.")
        else:
            print(f"facecam: [{rect.x}, {rect.y}, {rect.w}, {rect.h}]")
        if args.preview:
            facecam.save_preview(src, rect, args.preview)
            print(f"Wrote {args.preview}")
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
    elif args.cmd == "status":
        import json as _json

        from .db import DB
        from .uploaders import uploadpost
        rows = [r for r in DB(cfg.data_dir / "claud.db").history(200)
                if r["platform"] == "uploadpost"][: args.last]
        if not rows:
            print("No Upload-Post uploads recorded yet (check `claud history`).")
        for row in rows:
            print(f"\n== {row['updated_at']}  {row['streamer']}: {row['title'][:50]}")
            if row["status"] != "posted":
                print(f"   Claud couldn't send it: {row['error']}")
            elif not str(row["remote_id"]).startswith(("req", "job")) and len(str(row["remote_id"])) < 8:
                print(f"   Sent, but Upload-Post gave no request ID ({row['remote_id']}); check the dashboard.")
            else:
                try:
                    print(_json.dumps(uploadpost.status(row["remote_id"]), indent=2)[:2000])
                except Exception as e:
                    print(f"   Couldn't fetch status: {e}")
    elif args.cmd == "profiles":
        from .uploaders import uploadpost
        names = uploadpost.list_profiles()
        print("Upload-Post API key works. Profiles: " + (", ".join(names) or "(none yet)"))
        wanted = cfg.platform("uploadpost").get("profile")
        if wanted and wanted not in names:
            print(f"Warning: config.yaml uses profile {wanted!r}, which isn't in that list.")
    elif args.cmd == "retry":
        from .db import DB
        count = DB(cfg.data_dir / "claud.db").reset_failed()
        print(f"Cleared {count} failed attempt(s); they'll be retried on the next `claud run`.")
    elif args.cmd == "history":
        from .db import DB
        for row in DB(cfg.data_dir / "claud.db").history():
            status = row["remote_id"] if row["status"] == "posted" else f"FAILED: {row['error']}"
            print(f"{row['updated_at']}  {row['platform']:<8} {row['streamer']:<16} {row['title'][:40]:<40}  {status}")


if __name__ == "__main__":
    main()
