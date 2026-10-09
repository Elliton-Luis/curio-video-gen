#!/usr/bin/env python3
"""Run real pipeline cases and save auditable media selection measurements."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--rerender", action="store_true",
                        help="Resume real render using previously produced project artifacts")
    args = parser.parse_args()
    if args.source_root:
        sys.path.insert(0, str(args.source_root.resolve()))
    env = Path(".env")
    if env.is_file():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                key = key.strip()
                if key.replace("_", "").isalnum():
                    os.environ.setdefault(key, value)
    from curio.config import CurioConfig
    from curio.pipeline import run_pipeline
    from curio.pipeline_input import PipelineInput
    from curio.media.identity import asset_identity

    cases = json.loads(args.cases.read_text())
    results = []
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        config = CurioConfig.load("config.toml")
        config.out_dir = str(args.out_dir.resolve())
        config.tts_provider, config.tts_voice = "espeak-ng", "pt-br"
        config.render_backend = "cpu"
        config.width, config.height, config.fps = 480, 854, 24
        config.sub_font_size, config.sub_margin_v = 40, 70
        config.audio_enabled, config.music_mode, config.auto_open = False, "none", False
        genre = case.get("genre", "")
        slug = case["slug"]
        print(f"CASE {slug}", flush=True)
        try:
            project = args.out_dir / genre / slug
            if args.rerender:
                from types import SimpleNamespace
                from curio.cli import cmd_rerender
                if cmd_rerender(SimpleNamespace(slug=slug), config):
                    raise RuntimeError("rerender failed")
                metadata = json.loads((project / "metadata.json").read_text())
            else:
                metadata = run_pipeline(
                    PipelineInput(case["topic"], case["script"], case["title"]),
                    config, slug=slug, genre=genre, max_images=2)
            rows = json.loads((project / "media/media.json").read_text())
            assets = [entry["asset"] for row in rows for entry in row.get("assets", [])]
            real = [asset for asset in assets if asset.get("provider") != "synth"]
            identities = [asset_identity(asset) for asset in real]
            result = {"slug": slug, "topic": case["topic"],
                      "project": str(project.resolve()), "scenes": len(rows),
                      "real_scenes": sum(bool(row.get("asset")) and row["asset"].get("provider") != "synth" for row in rows),
                      "synthetic_scenes": sum((row.get("asset") or {}).get("provider") == "synth" for row in rows),
                      "real_assets": len(real), "unique_real_assets": len(set(identities)),
                      "repeated_real_assets": len(real) - len(set(identities)),
                      "duration": metadata.get("duration_actual"),
                      "assets": [{key: asset.get(key) for key in ("title", "provider", "source_url", "local_path")} for asset in assets]}
        except Exception as error:
            result = {"slug": slug, "error": str(error)}
        results.append(result)
        (args.out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "assets"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
