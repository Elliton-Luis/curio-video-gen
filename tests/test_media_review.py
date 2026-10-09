import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.media_review import CandidateExporter, load_reviewed_media, MediaReviewPending
from curio.stages.scene_contract import SemanticScene, VisualRepresentation
from curio.stages.media_contracts import Candidate
from curio.stages.visual_contracts import SearchQuery
from curio.stages import media_acquisition
from curio.pipeline_visual import resolve_media
from curio.project_artifacts import write_json


def setup(tmp_path, monkeypatch, mode='review'):
    scenes = [SemanticScene(1, 'Aristóteles pensava.'), SemanticScene(2, 'Ele ensinava.')]
    config = CurioConfig(cache_dir=str(tmp_path / 'cache'), genre='people')
    image = tmp_path / 'download.jpg'
    Image.new('RGB', (800, 900), 'blue').save(image)
    def download(asset, *_args):
        asset.local_path = str(image)
        asset.width, asset.height = 800, 900
        return SimpleNamespace(asset=asset)
    monkeypatch.setattr(media_acquisition, 'download_media', download)
    exporter = CandidateExporter(tmp_path, scenes, config, mode)
    for scene in scenes:
        for index in (1, 2):
            asset = MediaAsset('wikimedia', str(index), title=f'Aristotle {index}',
                license='CC BY 4.0', source_url=f'https://commons.wikimedia.org/{index}')
            candidate = Candidate(asset, SearchQuery('Aristotle', 'topic_contextual'), str(index))
            exporter.record(scene.id, candidate, reason='no topic evidence', score=10 * index)
    exporter.summary['status'] = 'awaiting_review'
    exporter.flush()
    return scenes, config, exporter


def test_deleted_rejected_candidates_are_not_restored_and_retained_override_gate(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    for folder in exporter.root.glob('scene_*'):
        next(folder.glob('002_*.jpg')).unlink()
    monkeypatch.setattr(media_acquisition, 'download_media', lambda *args: pytest.fail('resume must not download'))
    result = load_reviewed_media(tmp_path, scenes, config)
    assert [row.asset.asset_id for row in result.scenes] == ['1', '1']
    assert all(row.assets[0].query_source == 'manual_review' for row in result.scenes)
    summary = json.loads((exporter.root / 'review_summary.json').read_text())
    assert all(state['remaining'] == 1 and len(state['used']) == 1 for state in summary['scenes'].values())
    assert not list(exporter.root.glob('scene_*/002_*.jpg'))


def test_best_remaining_is_used_and_all_remaining_are_reported(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    result = load_reviewed_media(tmp_path, scenes, config)
    assert all(row.asset.asset_id == '2' for row in result.scenes)
    summary = json.loads((exporter.root / 'review_summary.json').read_text())
    assert summary['scenes']['1']['remaining'] == 2
    assert len(summary['scenes']['1']['used']) == 1
    assert summary['scenes']['1']['selection_policy'].startswith('best_remaining')


def test_empty_scene_gets_explicit_fallback_without_using_neighbor(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    for path in (exporter.root / 'scene_01').glob('*.jpg'):
        path.unlink()
    result = load_reviewed_media(tmp_path, scenes, config)
    assert result.scenes[0].asset.provider == 'synth'
    assert result.scenes[1].asset.provider != 'synth'
    summary = json.loads((exporter.root / 'review_summary.json').read_text())
    assert summary['scenes']['1']['remaining'] == 0
    assert summary['scenes']['1']['synthetic_fallback']
    assert summary['scenes']['1']['empty_reason']


def test_review_scene_identity_mismatch_and_dump_are_not_silently_ignored(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='cenas mudaram'):
        load_reviewed_media(tmp_path, [SemanticScene(1, 'Changed')], config)
    exporter.summary['mode'] = 'dump'
    exporter.flush()
    with pytest.raises(ValueError, match='dump'):
        load_reviewed_media(tmp_path, scenes, config)


def test_corrupt_retained_image_blocks_resume_instead_of_replacing_it(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    next((exporter.root / 'scene_01').glob('*.jpg')).write_bytes(b'broken')
    with pytest.raises(ValueError, match='arquivos inválidos'):
        load_reviewed_media(tmp_path, scenes, config)


def test_existing_review_never_refills_deleted_files(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    config.review_media = True
    paths = SimpleNamespace(root=str(tmp_path))
    with pytest.raises(MediaReviewPending):
        resolve_media(scenes, config, paths, 2, 'people', None, False, write_json)


def test_config_switches_are_opt_in(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = CurioConfig.load()
    assert not config.review_media and not config.dump_media_candidates
    monkeypatch.setenv('REVIEW_MEDIA', '1')
    monkeypatch.setenv('DUMP_MEDIA_CANDIDATES', '1')
    config = CurioConfig.load()
    assert config.review_media and config.dump_media_candidates


def test_empty_search_initializes_manifests_for_every_scene(tmp_path):
    config = CurioConfig(cache_dir=str(tmp_path / 'cache'))
    scenes = [SemanticScene(1, 'Nothing available')]
    exporter = CandidateExporter(tmp_path, scenes, config, 'review')
    manifest = json.loads((exporter.root / 'scene_01/manifest.json').read_text())
    assert manifest['candidates'] == []
    exporter.summary['status'] = 'awaiting_review'
    exporter.flush()
    assert load_reviewed_media(tmp_path, scenes, config).scenes[0].asset.provider == 'synth'


def test_interrupted_export_reuses_manifest_without_restoring_deleted_files(tmp_path, monkeypatch):
    scenes, config, exporter = setup(tmp_path, monkeypatch)
    row = next(iter(exporter.records[1].values()))
    deleted = exporter.root / 'scene_01' / row['filename']
    deleted.unlink()
    exporter.summary['status'] = 'collecting'
    exporter.flush()
    resumed = CandidateExporter(tmp_path, scenes, config, 'review')
    asset = MediaAsset.from_dict(row['asset'])
    candidate = Candidate(asset, SearchQuery('Aristotle', 'topic_contextual'), row['identity'])
    resumed.record(1, candidate, score=99)
    assert not deleted.exists()
    assert resumed.records[1][candidate.identity]['score'] == 99


def test_cli_flags_and_resume_command_are_wired(monkeypatch, tmp_path):
    from curio import cli
    monkeypatch.chdir(tmp_path)
    seen = []
    monkeypatch.setattr(cli, 'cmd_generate', lambda args, cfg: seen.append((cfg.review_media, cfg.dump_media_candidates)) or 0)
    assert cli.main(['generate', 'Aristóteles', '--media-review']) == 0
    assert seen == [(True, False)]
    assert cli.main(['generate', 'Aristóteles', '--media-dump']) == 0
    assert seen[-1] == (False, True)
    monkeypatch.setattr(cli, 'cmd_resume_media_review', lambda args, cfg: seen.append(args.slug) or 0)
    assert cli.main(['resume-media-review', '--slug', 'saved']) == 0
    assert seen[-1] == 'saved'


def test_resume_before_tts_uses_saved_stages_without_network(tmp_path):
    from contextlib import ExitStack
    from unittest.mock import patch
    import shutil
    from tests.test_pipeline_integration import _run, _fake_tts
    from curio.pipeline import run_pipeline
    from curio.pipeline_input import PipelineInput
    from curio.project_paths import video_paths
    with pytest.raises(MediaReviewPending):
        _run(tmp_path, review_media=True)
    paths = video_paths(str(tmp_path / 'output'), 'teste-integracao')
    review = Path(paths.root) / 'media_review'
    context = json.loads((review / 'resume_context.json').read_text())
    for folder in review.glob('scene_*'):
        shutil.copy2(tmp_path / 'fundo0.png', folder / 'user_choice.png')
    cfg = CurioConfig(out_dir=str(tmp_path / 'output'), resume_media_review=True,
                      render_backend='cpu', width=160, height=284, fps=12)
    def forbidden(*args, **kwargs):
        pytest.fail('resume must not research, plan or search again')
    with ExitStack() as stack:
        for method in ['curio.stages.research.research_topic', 'curio.stages.script.generate_script',
                       'curio.stages.script.generate_title', 'curio.stages.scenes.build_semantic_scenes',
                       'curio.stages.visual.fetch_media_multi']:
            stack.enter_context(patch(method, side_effect=forbidden))
        stack.enter_context(patch('curio.stages.tts.synthesize', side_effect=_fake_tts))
        result = run_pipeline(PipelineInput(context['topic'], Path(paths.script_txt).read_text(),
                                          Path(paths.title_txt).read_text()), cfg,
                              slug='teste-integracao')
    assert Path(result['artifacts']['video']).is_file()
    rows = json.loads(Path(paths.media_json).read_text())
    assert all(row['asset']['provider'] == 'manual' for row in rows)


def test_dump_keeps_normal_selection_and_exports_semantic_rejections(tmp_path, monkeypatch):
    from curio.stages import visual
    from curio.stages.visual_planning import build_visual_plan
    from curio.stages.search_planning import build_search_plan
    cfg = CurioConfig(cache_dir=str(tmp_path / 'cache'), dump_media_candidates=True,
                      media_providers='wikimedia')
    scene = SemanticScene(1, 'Mars planet', subject='Mars planet',
                          representations=(VisualRepresentation('Mars planet'),))
    image = tmp_path / 'real.jpg'
    Image.new('RGB', (1200, 1600), 'red').save(image)
    def download(asset, *_args, **_kwargs):
        asset.local_path, asset.width, asset.height = str(image), 1200, 1600
        return asset
    monkeypatch.setattr(media_acquisition, 'download_asset', download)
    good = MediaAsset('wikimedia', '1', title='Mars planet surface', license='CC BY 4.0',
        width=1200, height=1600, download_url='https://example.test/1.jpg')
    bad = MediaAsset('wikimedia', '2', title='Unrelated dog', license='CC BY 4.0',
        width=1200, height=1600, download_url='https://example.test/2.jpg')
    class Provider:
        name = 'wikimedia'
        def search(self, *args, **kwargs): return [good, bad]
    plan = build_visual_plan(scene)
    search = build_search_plan(plan)
    normal, _ = visual._search_scene_with_shortcircuit(scene, plan, search, [Provider()], cfg, 1, None, cfg.cache_dir)
    exporter = CandidateExporter(tmp_path, [scene], cfg, 'dump')
    cfg._media_review_exporter = exporter
    dumped, _ = visual._search_scene_with_shortcircuit(scene, plan, search, [Provider()], cfg, 1, None, cfg.cache_dir)
    assert normal.asset.asset_id == dumped.asset.asset_id == '1'
    assert len(list((exporter.root / 'scene_01').glob('*.jpg'))) == 2
    records = list(exporter.records[1].values())
    assert next(row for row in records if row['asset']['asset_id'] == '2')['initial_decision'] == 'rejected'


def test_dump_preserves_existing_manual_selection(tmp_path, monkeypatch):
    from curio import pipeline_visual
    from curio.project_paths import video_paths
    from curio.media.selection_result import MediaStageResult
    from tests.media_test_support import with_selection
    cfg = CurioConfig(out_dir=str(tmp_path), dump_media_candidates=True)
    paths = video_paths(str(tmp_path), 'project')
    manual = Path(paths.root) / 'assets/manual'
    manual.mkdir(parents=True)
    Image.new('RGB', (1200, 1600), 'blue').save(manual / 'user.png')
    scene = SemanticScene(1, 'User selected image')
    monkeypatch.setattr(pipeline_visual, 'get_providers', lambda cfg: [])
    automatic = MediaStageResult.from_rows([with_selection({'chapter_id': 1, 'asset': None, 'assets': []})], 'provider')
    monkeypatch.setattr(pipeline_visual.visual_stage, 'fetch_media_multi', lambda *args, **kwargs: automatic)
    result = resolve_media([scene], cfg, paths, 1, '', None, False, write_json)
    assert result.scenes[0].asset.provider == 'manual'
    assert result.scenes[0].asset.local_path.endswith('user.png')
    summary = json.loads((Path(paths.root) / 'media_review/review_summary.json').read_text())
    assert summary['status'] == 'dump_completed'


def test_review_pause_preserves_audio_controls(tmp_path):
    from tests.test_pipeline_integration import _run
    with pytest.raises(MediaReviewPending):
        _run(tmp_path, review_media=True, music_mode='manual', music_file='/local/track.mp3',
             music_gain_db=-17, music_ducking=False, tts_voice='pt-br')
    context = json.loads((tmp_path / 'output/teste-integracao/media_review/resume_context.json').read_text())
    saved = context['review_config']
    assert saved['music_mode'] == 'manual'
    assert saved['music_file'] == '/local/track.mp3'
    assert saved['music_gain_db'] == -17 and not saved['music_ducking']
    assert saved['tts_voice'] == 'pt-br'
