"""Provider-neutral workflow invariants and its mandatory editorial loop."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from PIL import Image
from curio import agent_flow as flow
from curio.config import CurioConfig
from curio.stages.scene_contract import SemanticScene, TimelineSpan, ScenePlanResult
from curio.stages.scene_plan_artifact import plan_to_dict


def job(tmp_path):
    cfg = CurioConfig(out_dir=str(tmp_path / 'output'))
    paths = flow.initialize(cfg, 'job', 'Tema')
    folder = Path(paths.root) / 'agent_flow'
    plan = flow.read(folder / 'plan.json')
    plan.update(script='Texto factual.', title='Título', research={'sources': [
        {'title': 'Fonte', 'url': 'https://example.org/source', 'snippet': 'Evidência.'}]},
        scene_plan=plan_to_dict(ScenePlanResult((SemanticScene(1, 'Texto factual.', subject='Tema'),),
                    (TimelineSpan(1, 2),), 'external_agent')))
    plan['music'].update(intent='Trilha contemplativa instrumental.', reason='Silêncio preserva a narração.')
    flow.write(folder / 'plan.json', plan)
    return cfg, paths, folder, plan


def export(paths):
    scene = Path(paths.root) / 'media_review/scene_01'
    scene.mkdir(parents=True, exist_ok=True)
    for name in ('good.jpg', 'bad.jpg'):
        Image.new('RGB', (80, 100), 'blue').save(scene / name)
    flow.write(scene / 'manifest.json', {'candidates': []})
    return 3


def choose(folder, filename='good.jpg'):
    feedback = flow.read(folder / 'media-feedback.json')
    feedback['scenes'][0].update(filename=filename, reason='Representa o contexto narrado.',
                                rights_evidence='Domínio público, fonte verificada.', fallback_reason='Fontes esgotadas.')
    flow.write(folder / 'media-feedback.json', feedback)


def review_stub(paths, state, cfg):
    folder = Path(paths.root) / 'agent_flow'
    Path(paths.final_mp4).parent.mkdir(parents=True, exist_ok=True)
    Path(paths.final_mp4).write_bytes(b'video')
    flow.write(paths.timeline_json, [{'id': 1, 'start': 0, 'end': 2}])
    flow.write(paths.media_json, [])
    evidence = folder / f"evidence-{state['iteration']:03d}"
    evidence.mkdir()
    state.update(render_id=f"render-{state['iteration']}", evidence_dir=str(evidence))
    flow.write(evidence / 'fingerprint.json', flow._fingerprint(paths))
    flow.write(evidence / 'request.json', {'technical_passed': True, 'frames': [{'scene_id': 1}]})
    flow.write(folder / 'feedback.json', {'schema_version': 1, 'render_id': state['render_id'],
        'reviewer': 'any-agent', 'decision': 'approve', 'issues': [],
        'checks': {key: {'ok': True, 'evidence': 'Inspeção documentada.'} for key in flow.CHECKS},
        'scenes': [{'scene_id': 1, 'ok': True, 'evidence': 'Imagem pertinente.'}]})
    flow._save(folder, state, 'awaiting_render_review', 'Review')


def rendered_job(tmp_path, monkeypatch):
    cfg, paths, folder, plan = job(tmp_path)
    monkeypatch.setattr(flow, '_render_review', review_stub)
    assert flow.advance(paths, cfg, lambda: export(paths), lambda: 0) == 3
    choose(folder)
    assert flow.advance(paths, cfg, lambda: pytest.fail('must not search'), lambda: 0) == 3
    return cfg, paths, folder, plan


def test_external_contract_no_provider_and_mandatory_render_review(tmp_path, monkeypatch):
    cfg, paths, folder, plan = rendered_job(tmp_path, monkeypatch)
    assert flow.read(folder / 'state.json')['status'] == 'awaiting_render_review'
    assert not (Path(paths.root) / 'media_review/scene_01/bad.jpg').exists()
    assert (folder / 'discarded/0/scene_01/bad.jpg').exists()
    assert flow.advance(paths, cfg, None, None) == 0
    assert flow.read(folder / 'state.json')['status'] == 'approved'
    assert flow.advance(paths, cfg, None, None) == 0


@pytest.mark.parametrize('field', ['video', 'plan', 'candidate', 'asset'])
def test_changed_artifact_invalidates_approval(tmp_path, monkeypatch, field):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    flow.advance(paths, cfg, None, None)
    if field == 'video':
        Path(paths.final_mp4).write_bytes(b'changed')
    elif field == 'plan':
        plan = flow.read(folder / 'plan.json'); plan['title'] = 'Outro'; flow.write(folder / 'plan.json', plan)
    elif field == 'asset':
        local = tmp_path / 'external.jpg'; local.write_bytes(b'asset')
        flow.write(paths.media_json, [{'asset': {'local_path': str(local)}}])
    else:
        Image.new('RGB', (80, 100), 'red').save(Path(paths.root) / 'media_review/scene_01/good.jpg')
    with pytest.raises(ValueError, match='Artefatos mudaram'):
        flow.advance(paths, cfg, None, None)


@pytest.mark.parametrize('fault', ['render_id', 'checks', 'scenes', 'technical', 'issues'])
def test_incomplete_or_failed_review_cannot_approve(tmp_path, monkeypatch, fault):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    feedback = flow.read(folder / 'feedback.json')
    if fault == 'render_id': feedback['render_id'] = 'old'
    elif fault == 'checks': feedback['checks']['semantic_images']['ok'] = False
    elif fault == 'scenes': feedback['scenes'] = []
    elif fault == 'issues': feedback['issues'] = ['bad crop']
    else:
        state = flow.read(folder / 'state.json')
        flow.write(Path(state['evidence_dir']) / 'request.json', {'technical_passed': False})
    flow.write(folder / 'feedback.json', feedback)
    with pytest.raises(ValueError): flow.advance(paths, cfg, None, None)


def test_rejection_revision_render_returns_to_editor_again(tmp_path, monkeypatch):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    feedback = flow.read(folder / 'feedback.json')
    feedback.update(decision='revise', issues=['Melhorar enquadramento'])
    flow.write(folder / 'feedback.json', feedback)
    assert flow.advance(paths, cfg, None, None) == 3
    assert flow.read(folder / 'state.json')['status'] == 'needs_revision'
    flow.revise(paths)
    assert flow.advance(paths, cfg, None, lambda: 0) == 3
    assert flow.read(folder / 'state.json')['render_id'] == 'render-1'
    assert flow.read(folder / 'state.json')['status'] == 'awaiting_render_review'
    assert (folder / 'evidence-000/feedback.json').exists()


def test_plan_validation_no_automatic_music_and_literal_narration(tmp_path):
    cfg, paths, folder, plan = job(tmp_path)
    plan['music']['mode'] = 'auto'
    with pytest.raises(ValueError, match='auto'): flow.validate_plan(plan)
    plan['music']['mode'] = 'none'
    plan['script'] = 'Narrativa diferente.'
    with pytest.raises(ValueError, match='roteiro literal'): flow.validate_plan(plan)


def test_empty_scene_requires_explicit_fallback(tmp_path):
    cfg, paths, folder, plan = job(tmp_path)
    flow.advance(paths, cfg, lambda: export(paths), None)
    choose(folder, None)
    feedback = flow.read(folder / 'media-feedback.json')
    feedback['scenes'][0]['fallback_reason'] = ''
    flow.write(folder / 'media-feedback.json', feedback)
    with pytest.raises(ValueError, match='Fallback'): flow._select_media(paths, plan, 0)
    assert (Path(paths.root) / 'media_review/scene_01/good.jpg').exists()


def test_export_failure_keeps_job_retryable(tmp_path):
    cfg, paths, folder, _ = job(tmp_path)
    with pytest.raises(ValueError, match='Exportação'): flow.advance(paths, cfg, lambda: 1, None)
    assert flow.read(folder / 'state.json')['status'] == 'awaiting_plan'


def test_replan_archives_audio_and_searches_for_new_scene_plan(tmp_path, monkeypatch):
    cfg, paths, folder, plan = rendered_job(tmp_path, monkeypatch)
    Path(paths.narration_wav).parent.mkdir(exist_ok=True)
    Path(paths.narration_wav).write_bytes(b'old audio')
    plan['script'] = 'Texto novo.'
    plan['scene_plan']['semantic_scenes'][0]['narration'] = 'Texto novo.'
    flow.write(folder / 'plan.json', plan)
    flow.revise(paths, True)
    assert not Path(paths.narration_wav).exists()
    assert (folder / 'previous/1/audio/narration.wav').read_bytes() == b'old audio'
    assert flow.advance(paths, cfg, lambda: export(paths), None) == 3
    assert Path(paths.script_txt).read_text() == 'Texto novo.'


def test_cli_new_flow_is_opt_in_and_keeps_config_private(tmp_path, monkeypatch):
    from curio.cli import build_parser, cmd_agent_flow
    cfg = CurioConfig(out_dir=str(tmp_path / 'output'), auto_open=True)
    args = build_parser().parse_args(['agent-flow', 'init', '--slug', 'job', '--topic', 'Tema'])
    assert cmd_agent_flow(args, cfg) == 3
    assert cfg.auto_open is True
    assert build_parser().parse_args(['generate', 'Tema']).func.__name__ == 'cmd_generate'


def test_slug_cannot_escape_output(tmp_path):
    with pytest.raises(ValueError): flow.initialize(CurioConfig(out_dir=str(tmp_path)), '../escape')


def test_fresh_job_real_render_skips_internal_research_planning_and_llm(tmp_path, monkeypatch):
    """Only TTS and candidate acquisition are fixtures; timeline, selection and FFmpeg are real."""
    from argparse import Namespace
    from curio import cli, pipeline_research, pipeline_scenes, pipeline_script
    from curio.media_review import CandidateExporter
    from curio.stages import tts, nvidia, visual
    from curio.stages import media_acquisition
    from curio.media.providers import MediaAsset
    from curio.stages.media_contracts import Candidate
    from curio.stages.visual_contracts import SearchQuery
    from tests.test_pipeline_integration import _fake_tts
    cfg, paths, folder, plan = job(tmp_path)
    cfg.width, cfg.height, cfg.fps, cfg.render_backend = 180, 320, 12, 'cpu'
    text = 'Este roteiro factual usa imagem real escolhida por agente externo e revisão obrigatória.'
    plan['script'] = text
    plan['scene_plan']['semantic_scenes'][0]['narration'] = text
    flow.write(folder / 'plan.json', plan)
    image = tmp_path / 'source.jpg'
    Image.effect_noise((600, 900), 60).convert('RGB').save(image)
    def local_export():
        scenes = flow.validate_plan(plan).semantic_scenes
        monkeypatch.setattr(media_acquisition, 'download_media', lambda asset, *args: SimpleNamespace(
            asset=MediaAsset(asset.provider, asset.asset_id, license='Public domain',
                             local_path=str(image), width=600, height=900)))
        exporter = CandidateExporter(paths.root, scenes, cfg, 'review')
        exporter.record(1, Candidate(MediaAsset('wikimedia', 'fixture', title='Imagem', license='Public domain'),
                                       SearchQuery('context', 'topic_contextual'), 'fixture'))
        exporter.summary['status'] = 'awaiting_review'
        exporter.flush()
        return 3
    assert flow.advance(paths, cfg, local_export, None) == 3
    filename = next((Path(paths.root) / 'media_review/scene_01').glob('*.jpg')).name
    choose(folder, filename)
    monkeypatch.setattr(tts, 'synthesize', _fake_tts)
    def forbidden(*args, **kwargs): pytest.fail('internal research/LLM/search must not run')
    monkeypatch.setattr(pipeline_research.research_stage, 'research_topic', forbidden)
    monkeypatch.setattr(pipeline_scenes.scenes_stage, 'build_semantic_scenes', forbidden)
    monkeypatch.setattr(pipeline_script.script_stage, 'generate_script', forbidden)
    monkeypatch.setattr(nvidia, 'complete_json', forbidden)
    args = Namespace(slug='job')
    assert flow.advance(paths, cfg, None, lambda: cli.cmd_resume_media_review(args, cfg)) == 3
    request = flow.read(folder / 'request.json')
    assert request['status'] == 'awaiting_render_review'
    assert Path(request['frames'][0]['path']).is_file()
    assert Path(paths.final_mp4).stat().st_size > 0
    assert flow.read(paths.media_json)[0]['asset']['provider'] != 'synth'


def test_status_never_reports_valid_approval_after_asset_changes(tmp_path, monkeypatch):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    flow.advance(paths, cfg, None, None)
    Path(paths.final_mp4).write_bytes(b'changed')
    assert flow.current_state(paths)['status'] == 'needs_revision'


def test_selected_asset_outside_project_is_bound_to_approval(tmp_path, monkeypatch):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    local = tmp_path / 'selected.jpg'
    local.write_bytes(b'original')
    flow.write(paths.media_json, [{'asset': {'local_path': str(local)}}])
    state = flow.read(folder / 'state.json')
    flow.write(Path(state['evidence_dir']) / 'fingerprint.json', flow._fingerprint(paths))
    flow.advance(paths, cfg, None, None)
    local.write_bytes(b'changed')
    assert flow.current_state(paths)['status'] == 'needs_revision'


def test_deleted_video_invalidates_status(tmp_path, monkeypatch):
    cfg, paths, folder, _ = rendered_job(tmp_path, monkeypatch)
    flow.advance(paths, cfg, None, None)
    Path(paths.final_mp4).unlink()
    assert flow.current_state(paths)['status'] == 'needs_revision'


def test_manual_music_must_be_used_and_credit_preserved(tmp_path):
    cfg, paths, folder, plan = job(tmp_path)
    plan['music'].update(mode='manual', file=str(tmp_path / 'track.wav'),
                         source_url='https://example.org/music', license='CC BY',
                         license_url='https://creativecommons.org/licenses/by/4.0/')
    flow.write(paths.metadata_json, {'audio': {'music': {'track': None}}})
    with pytest.raises(ValueError, match='não foi usada'): flow._record_music(paths, plan)
    flow.write(paths.metadata_json, {'audio': {'music': {'track': {'path': plan['music']['file'], 'title': 'Music'}}}})
    flow._record_music(paths, plan)
    metadata = flow.read(paths.metadata_json)
    assert metadata['audio']['music']['track']['license'] == 'CC BY'
    assert metadata['audio']['music']['intent']['source'] == 'external_agent'
    assert metadata['audio']['credits']
