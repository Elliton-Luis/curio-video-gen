"""Optional folder-based editorial review, independent of semantic selection."""
from pathlib import Path
import csv
import hashlib
import json
import shutil

from .pipeline_media import MediaStandby
from .media.selection_result import MediaStageResult
from .media.providers import MediaAsset, MediaError, classify_rights
from .stages import media_acquisition
from . import textnorm

REVIEW_CONFIG_FIELDS = ('audio_enabled', 'music_mode', 'music_file', 'music_gain_db',
    'music_ducking', 'music_transitions', 'tts_provider', 'tts_voice', 'tts_speed',
    'language', 'width', 'height', 'fps', 'sub_font_size', 'sub_margin_v')


class MediaReviewPending(MediaStandby):
    def __init__(self, slug, directory, n_scenes):
        super().__init__(slug, str(directory), n_scenes)
        self.args = (f"Revisão de mídia em {directory}. Apague as imagens irrelevantes e rode "
                     f"video-gen resume-media-review --slug {slug}",)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def scenes_signature(scenes):
    return hashlib.sha256(json.dumps([s.to_dict() for s in scenes],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class CandidateExporter:
    def __init__(self, root, scenes, config, mode):
        self.root, self.config = Path(root) / 'media_review', config
        self.records = {s.id: {} for s in scenes}
        self.summary = {'schema_version': 1, 'mode': mode, 'status': 'collecting',
                        'scene_signature': scenes_signature(scenes), 'scenes': {}}
        previous = self.root / 'review_summary.json'
        if previous.exists():
            stored = json.loads(previous.read_text())
            if stored['scene_signature'] != self.summary['scene_signature']:
                raise ValueError('As cenas mudaram desde a exportação de mídia.')
            if stored['mode'] != mode:
                raise ValueError('A pasta já pertence a outro modo de revisão/dump.')
            self.summary = stored
            self.summary['status'] = 'collecting'
            for scene in scenes:
                manifest = self.root / f'scene_{scene.id:02d}/manifest.json'
                if manifest.exists():
                    self.records[scene.id] = {row['identity']: row for row in
                        json.loads(manifest.read_text())['candidates']}
        for scene in scenes:
            (self.root / f'scene_{scene.id:02d}').mkdir(parents=True, exist_ok=True)
            self.flush_scene(scene.id)
        self.flush()

    def record(self, scene_id, candidate, reason='', score=None, stage='acquisition'):
        records = self.records[scene_id]
        identity = candidate.identity
        if identity in records:
            row = records[identity]
            row.update(score=score, initial_decision='rejected' if reason else 'accepted',
                       reason=reason, decision_stage=stage)
            self.flush_scene(scene_id)
            return
        asset = candidate.asset.to_dict()
        row = {'identity': identity, 'provider': asset['provider'],
               'query': candidate.search_query.query, 'title': asset['title'],
               'original_url': asset['source_url'], 'score': score, 'reason': reason,
               'initial_decision': 'rejected' if reason else 'pending',
               'decision_stage': stage, 'filename': None, 'asset': asset}
        records[identity] = row
        if classify_rights(asset['license'], asset['provider']) == 'blocked':
            row['export_error'] = 'license blocked'
        else:
            try:
                downloaded = media_acquisition.download_media(MediaAsset.from_dict(asset), self.config.cache_dir)
                downloaded_asset = downloaded.asset
                if not media_acquisition.downloaded_dimensions_valid(downloaded_asset):
                    raise ValueError('downloaded image dimensions invalid')
                local = Path(downloaded_asset.local_path)
                label = '-'.join(textnorm.tokens(asset['title']))[:75] or 'image'
                filename = f'{len(records):03d}_{asset["provider"]}_{label}{local.suffix.lower()}'
                folder = self.root / f'scene_{scene_id:02d}'
                shutil.copy2(local, folder / filename)
                row.update(filename=filename, asset=downloaded_asset.to_dict())
            except (MediaError, OSError, ValueError) as exc:
                row['export_error'] = str(exc)
        self.flush_scene(scene_id)

    def flush_scene(self, scene_id):
        rows = list(self.records[scene_id].values())
        folder = self.root / f'scene_{scene_id:02d}'
        _write(folder / 'manifest.json', {'scene_id': scene_id, 'candidates': rows})
        fields = ['filename', 'provider', 'query', 'title', 'original_url', 'score',
                  'initial_decision', 'reason', 'decision_stage', 'export_error']
        with (folder / 'manifest.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        self.summary['scenes'][str(scene_id)] = {'found': len(rows),
            'exported': sum(bool(row['filename']) for row in rows), 'remaining': None, 'used': []}
        self.flush()

    def flush(self):
        _write(self.root / 'review_summary.json', self.summary)

    def finish(self, result):
        self.summary['status'] = 'awaiting_review' if self.summary['mode'] == 'review' else 'dump_completed'
        for scene in result.scenes:
            state = self.summary['scenes'][str(scene.scene_id)]
            state['automatic_used'] = [
                entry.asset.source_url or entry.asset.local_path for entry in scene.assets]
            audit = scene.visual_audit.to_dict()
            state['queries'] = audit.get('queries', [])
            state['results_received'] = sum(query.get('results', 0) for query in state['queries'])
        self.flush()


def load_reviewed_media(root, scenes, config):
    """Deleted files stay deleted. Retained files override semantic rejection."""
    folder = Path(root) / 'media_review'
    summary = json.loads((folder / 'review_summary.json').read_text())
    if summary['mode'] != 'review':
        raise ValueError('Esta pasta é um dump de auditoria, não uma revisão editorial.')
    if summary['status'] == 'collecting':
        raise ValueError('A exportação foi interrompida. Rode media-review novamente para completá-la.')
    if summary['scene_signature'] != scenes_signature(scenes):
        raise ValueError('As cenas mudaram desde a revisão. Exporte uma nova revisão em outro projeto.')
    rows = []
    selected_root = folder / 'selected'
    selected_root.mkdir(exist_ok=True)
    for scene in scenes:
        scene_folder = folder / f'scene_{scene.id:02d}'
        manifest = json.loads((scene_folder / 'manifest.json').read_text())
        retained, invalid = [], []
        known = {row['filename']: row for row in manifest['candidates'] if row.get('filename')}
        # A scene folder may contain user-added images, whose metadata is manual.
        for path in sorted(scene_folder.iterdir()):
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'} or not path.is_file():
                continue
            if path.is_symlink():
                raise ValueError(f'Imagem de revisão deve ser um arquivo local: {path}')
            from PIL import Image
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    width, height = image.size
            except (OSError, ValueError, SyntaxError) as exc:
                invalid.append({'filename': path.name, 'error': str(exc)})
                continue
            original = known.get(path.name, {})
            asset = dict(original.get('asset') or MediaAsset('manual', path.stem,
                title=path.stem, license='manual do usuário').to_dict())
            if classify_rights(asset['license'], asset['provider']) == 'blocked':
                invalid.append({'filename': path.name, 'error': 'license blocked'})
                continue
            asset.update(local_path=str(path), width=width, height=height,
                         size_bytes=path.stat().st_size, used_in=f'cena {scene.id}')
            retained.append({'asset': asset, 'query': original.get('query', 'manual review'),
                'query_source': 'manual_review', 'relevance': 100, 'score': 100,
                'order': len(retained), 'strategy': 'manual_review',
                'review_original_score': original.get('score')})
        state = summary['scenes'][str(scene.id)]
        retained.sort(key=lambda entry: (-(entry['review_original_score'] or 0), entry['order']))
        state.update(remaining=len(retained), invalid_files=invalid,
                     retained_files=[entry['asset']['local_path'] for entry in retained],
                     selection_policy='best_remaining_by_original_score_then_filename',
                     used=[entry['asset']['local_path'] for entry in retained[:1]],
                     empty_reason='no images remained after review' if not retained else '')
        if invalid:
            _write(folder / 'review_summary.json', summary)
            raise ValueError(f'Cena {scene.id}: arquivos inválidos na revisão; veja review_summary.json.')
        if not retained:
            from .stages.visual_planning import build_visual_plan
            from .stages.visual_fallback_planning import build_visual_fallback_plan
            from .stages import visuals
            plan = build_visual_fallback_plan(build_visual_plan(scene), scene.narration,
                                              config.genre, None)
            asset = visuals.render_fallback_plan(plan, config.cache_dir, config.language, config.genre)
            if asset is None:
                raise ValueError(f'Cena {scene.id}: nenhum arquivo restou e fallback falhou.')
            retained = [{'asset': asset.to_dict(), 'query': 'empty reviewed scene',
                         'relevance': 0, 'score': 0, 'order': 0, 'strategy': 'synth'}]
            state['synthetic_fallback'] = True
        else:
            state['synthetic_fallback'] = False
            retained = retained[:1]
            retained[0]['order'] = 0
            chosen = Path(retained[0]['asset']['local_path'])
            destination = selected_root / f'scene_{scene.id:02d}_{chosen.name}'
            shutil.copy2(chosen, destination)
            retained[0]['asset']['local_path'] = str(destination)
            state['used'] = [str(destination)]
        from .stages.media_selection import SelectionDecision
        selection = SelectionDecision(scene_id=scene.id,
            status='synthetic' if state['synthetic_fallback'] else 'real',
            asset_id=retained[0]['asset']['asset_id'], provider=retained[0]['asset']['provider'],
            query_source='manual_review', fallback_level='manual_review',
            reason=state['empty_reason'] or 'user retained local files after review')
        rows.append({'chapter_id': scene.id, 'asset': retained[0]['asset'], 'assets': retained,
                     'reused_from': None, 'rejected': [], 'visual_decision': {
                         'selection': selection.to_dict(),
                         'selected': {'title': retained[0]['asset']['title'],
                                      'provider': retained[0]['asset']['provider'],
                                      'reason': state['empty_reason'] or 'user retained local files after review'},
                         'fallback_level': 'manual_review' if not state['synthetic_fallback'] else 'empty_reviewed_scene'}})
    summary['status'] = 'selected'
    _write(folder / 'review_summary.json', summary)
    return MediaStageResult.from_rows(rows, 'manual_review')


def record_review_render(root):
    folder = Path(root) / 'media_review'
    summary = json.loads((folder / 'review_summary.json').read_text())
    rows = json.loads((Path(root) / 'media/media.json').read_text())
    for row in rows:
        state = summary['scenes'][str(row['chapter_id'])]
        state['render_used'] = [entry['asset']['local_path'] for entry in row['assets']]
    summary['status'] = 'rendered'
    summary['render_output'] = str(Path(root) / 'render/final.mp4')
    _write(folder / 'review_summary.json', summary)
