#!/usr/bin/env python3
"""Reacquire project images and render using its saved narration and scene plan."""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('slug')
    args = parser.parse_args()
    for line in Path('.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value)
    from curio.config import CurioConfig
    from curio.project_paths import paths_for_slug
    from curio.project_artifacts import write_json
    from curio.pipeline_visual import resolve_media
    from curio.stages.scene_contract import SemanticScene
    from curio.cli import cmd_rerender
    config = CurioConfig.load('config.toml')
    _, paths = paths_for_slug(config.out_dir, args.slug)
    genre = Path(paths.root).parent.name
    plan = json.loads(Path(paths.root, 'script/scene-plan.json').read_text())
    scenes = [SemanticScene.from_dict(row) for row in plan['semantic_scenes']]
    result = resolve_media(scenes, config, paths, 2, genre, None, True, write_json)
    rows = result.to_rows()
    print(json.dumps({'real_scenes': sum(row['asset']['provider'] != 'synth' for row in rows),
                      'scenes': len(rows)}, ensure_ascii=False), flush=True)
    if all(row['asset']['provider'] == 'synth' for row in rows):
        raise RuntimeError('No real media selected; render intentionally not started')
    config.render_backend = 'cpu'
    if cmd_rerender(SimpleNamespace(slug=args.slug), config):
        raise RuntimeError('Render failed')


if __name__ == '__main__':
    main()
