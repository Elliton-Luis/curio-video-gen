"""Provider-neutral editorial workflow. JSON artifacts are its public contract."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import ffmpeg as ff
from .project_paths import video_paths, paths_for_slug
from .stages.scene_contract import SemanticScene, TimelineSpan, ScenePlanResult
from .stages.scene_plan_artifact import plan_from_dict, plan_to_dict
from .stages.scene_projection import Chapter
from .stages.script_input import validate_preserved
from .verify import verify_video

VERSION = 1
CHECKS = ('factual_accuracy', 'semantic_images', 'visual_variety',
          'framing_subtitles', 'pacing', 'audio_music', 'publication_rights')
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _run_checked(command):
    result = ff.run(command)
    if result.returncode:
        raise ff.FFMpegError(result.stderr[-1500:])


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label}: texto obrigatório')
    return value


def initialize(cfg, slug, topic='', genre=''):
    """Create a job, optionally seeding editorial input from an existing video."""
    if not slug or any(c in slug for c in ('/', '\\')) or slug in ('.', '..'):
        raise ValueError('Use --slug sem separadores de diretório')
    if genre and (any(c in genre for c in ('/', '\\')) or genre in ('.', '..')):
        raise ValueError('Gênero inválido')
    try:
        _, paths = paths_for_slug(cfg.out_dir, slug)
    except FileNotFoundError:
        paths = video_paths(cfg.out_dir, slug, genre)
    folder = Path(paths.root) / 'agent_flow'
    if (folder / 'state.json').exists():
        return paths
    folder.mkdir(parents=True, exist_ok=True)
    script = Path(paths.script_txt).read_text() if Path(paths.script_txt).exists() else ''
    research = read(paths.research_json) if Path(paths.research_json).exists() else {'idea': topic, 'sources': []}
    scene_plan = read(paths.scene_plan_json) if Path(paths.scene_plan_json).exists() else plan_to_dict(
        ScenePlanResult((SemanticScene(1, 'PREENCHA A NARRAÇÃO', subject=topic or 'tema'),),
                        (TimelineSpan(1, 10),), 'external_agent'))
    plan = {'schema_version': VERSION, 'topic': topic or research.get('idea', ''),
            'genre': genre or (Path(paths.root).parent.name if Path(paths.root).parent != Path(cfg.out_dir) else ''),
            'title': Path(paths.title_txt).read_text() if Path(paths.title_txt).exists() else '',
            'script': script, 'research': research, 'scene_plan': scene_plan,
            'music': {'mode': 'none', 'intent': '', 'reason': '', 'file': '',
                      'source_url': '', 'license': '', 'license_url': '', 'instrumental': True}}
    write(folder / 'plan.json', plan)
    state = {'schema_version': VERSION, 'status': 'awaiting_plan', 'iteration': 0,
             'history': [], 'project_root': str(Path(paths.root).resolve())}
    _save(folder, state, 'awaiting_plan', 'Preencha plan.json; depois execute advance.')
    (folder / 'AGENT.md').write_text(
        '# Contrato editorial do Curio\n\n'
        'Qualquer agente pode operar este projeto por arquivos JSON e CLI.\n'
        'Não há SDK, modelo, credencial ou provedor de agente obrigatório.\n'
        'Preencha plan.json com pesquisa, roteiro preservado pelas cenas e intenção musical.\n'
        'Use advance até a próxima pausa. Leia request.json em cada pausa.\n'
        'Na mídia, inspecione os arquivos e preencha media-feedback.json com um arquivo por cena,\n'
        'justificativa semântica e direitos. Busque alternativas se necessário.\n'
        'No render, examine o vídeo, frames, legendas e áudio; preencha feedback.json.\n'
        'Use revise para corrigir mídia e renderizar novamente; use replan para mudar roteiro/cenas.\n'
        'Nunca aprove somente porque o render terminou. Não invente evidências de inspeção.\n', encoding='utf-8')
    return paths


def _save(folder, state, status, instruction):
    state['status'] = status
    state['history'].append({'status': status, 'iteration': state['iteration']})
    write(folder / 'state.json', state)
    write(folder / 'request.json', {'schema_version': VERSION, 'status': status,
          'iteration': state['iteration'], 'instruction': instruction,
          'project_root': state['project_root']})


def validate_plan(plan):
    if plan.get('schema_version') != VERSION:
        raise ValueError('Versão do contrato não suportada')
    for field in ('topic', 'title', 'script'):
        _text(plan.get(field), field)
    scenes = plan_from_dict(plan['scene_plan'])
    validate_preserved(plan['script'], scenes.semantic_scenes)
    sources = plan['research'].get('sources', [])
    if not sources:
        raise ValueError('Pesquisa deve conter fontes verificáveis')
    for source in sources:
        for field in ('title', 'url', 'snippet'):
            _text(source.get(field), f'fonte.{field}')
        if not source['url'].startswith(('https://', 'http://')):
            raise ValueError('Fonte deve ter URL HTTP(S)')
    music = plan['music']
    _text(music.get('intent'), 'music.intent')
    _text(music.get('reason'), 'music.reason')
    if music.get('mode') not in ('none', 'manual'):
        raise ValueError('Agente deve escolher trilha local ou justificar ausência; auto não permitido')
    if music['mode'] == 'manual':
        for field in ('file', 'source_url', 'license', 'license_url'):
            _text(music.get(field), 'music.' + field)
        if music.get('instrumental') is not True:
            raise ValueError('Neste fluxo, trilha deve ser instrumental')
        if not Path(music['file']).is_file():
            raise ValueError('Trilha escolhida não existe')
        from .media.providers import classify_rights
        if classify_rights(music['license']) != 'clear':
            raise ValueError('Licença da trilha bloqueada')
        ff.probe_duration(music['file'])
    return scenes


def _persist_plan(paths, plan, cfg):
    scenes = validate_plan(plan)
    expected_genre = Path(paths.root).parent.name if Path(paths.root).parent != Path(cfg.out_dir) else ''
    if plan.get('genre') != expected_genre:
        raise ValueError('Gênero deve corresponder à pasta do projeto')
    changed = (Path(paths.script_txt).exists() and Path(paths.script_txt).read_text() != plan['script'])
    changed = changed or (Path(paths.scene_plan_json).exists() and read(paths.scene_plan_json) != plan['scene_plan'])
    if changed:
        archive = Path(paths.root) / 'agent_flow' / 'import-previous'
        index = 1
        while (archive / str(index)).exists():
            index += 1
        _archive(paths, archive / str(index))
    for path, text in ((paths.script_txt, plan['script']), (paths.title_txt, plan['title'])):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding='utf-8')
    write(paths.research_json, dict(plan['research'], idea=plan['topic']))
    write(paths.scene_plan_json, plan['scene_plan'])
    write(paths.chapters_json, [Chapter.from_semantic_scene(scene, timing=span).to_dict()
          for scene, span in zip(scenes.semantic_scenes, scenes.timeline_spans)])
    from .media_review import REVIEW_CONFIG_FIELDS
    cfg.music_mode, cfg.music_file = plan['music']['mode'], plan['music'].get('file', '')
    cfg.music_auto_fill = cfg.sfx_auto_fill = False
    write(Path(paths.root) / 'media_review/resume_context.json', {
        'topic': plan['topic'], 'genre': plan['genre'], 'narration': 'ai', 'max_images': 1,
        'grounding': {}, 'script_source': 'external_agent', 'title_source': 'external_agent',
        'review_config': {name: getattr(cfg, name) for name in REVIEW_CONFIG_FIELDS}})


def _media_template(paths, plan):
    rows = [{'scene_id': row['id'], 'filename': None, 'reason': '',
             'rights_evidence': '', 'fallback_reason': ''} for row in plan['scene_plan']['semantic_scenes']]
    write(Path(paths.root) / 'agent_flow/media-feedback.json', {'schema_version': VERSION, 'scenes': rows})


def _select_media(paths, plan, iteration):
    folder = Path(paths.root) / 'agent_flow'
    feedback = read(folder / 'media-feedback.json')
    ids = [s['id'] for s in plan['scene_plan']['semantic_scenes']]
    rows = feedback.get('scenes', [])
    if feedback.get('schema_version') != VERSION or [r.get('scene_id') for r in rows] != ids:
        raise ValueError('Revisão deve cobrir todas as cenas, em ordem')
    # Validate the whole decision before moving any candidate.
    moves = []
    for row in rows:
        _text(row.get('reason'), 'Justificativa semântica da cena')
        scene = Path(paths.root) / 'media_review' / f"scene_{row['scene_id']:02d}"
        filename = row.get('filename')
        files = [p for p in scene.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()]
        if filename is not None:
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise ValueError('Nome de imagem inválido')
            chosen = scene / filename
            if chosen not in files or chosen.is_symlink():
                raise ValueError(f'Imagem escolhida ausente: {filename}')
            _text(row.get('rights_evidence'), 'Direitos da imagem')
        else:
            _text(row.get('fallback_reason'), 'Fallback exige justificativa explícita')
        moves.extend((path, folder / 'discarded' / str(iteration) / scene.name / path.name)
                     for path in files if path.name != filename)
    for source, dest in moves:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise ValueError(f'Arquivo já arquivado: {dest}')
        shutil.move(str(source), str(dest))
    write(folder / f'media-approved-{iteration}.json', feedback)


def _fingerprint(paths):
    root = Path(paths.root)
    # Include editorial, audio, timeline, actual selected assets and remaining candidates.
    files = []
    for dirname in ('script', 'sources', 'audio', 'timeline', 'subtitles', 'media', 'media_review'):
        directory = root / dirname
        if directory.exists():
            files.extend(p for p in directory.rglob('*') if p.is_file())
    files += [Path(paths.final_mp4), root / 'agent_flow/plan.json']
    if Path(paths.metadata_json).exists():
        files.append(Path(paths.metadata_json))
    plan = read(root / 'agent_flow/plan.json')
    if plan['music']['mode'] == 'manual':
        files.append(Path(plan['music']['file']))
    for row in read(paths.media_json):
        for image in [row.get('asset', {})] + row.get('assets', []):
            asset = image.get('asset', image)
            if asset.get('local_path'):
                files.append(Path(asset['local_path']))
    return {str(p.resolve()): digest(p) for p in sorted(set(files))}


def _render_review(paths, state, cfg):
    folder = Path(paths.root) / 'agent_flow'
    evidence = folder / f"evidence-{state['iteration']:03d}"
    evidence.mkdir(parents=True, exist_ok=True)
    frames = []
    for row in read(paths.timeline_json):
        start, end = float(row.get('start', 0)), float(row.get('end', 0))
        frame = evidence / f"scene-{row['id']:02d}.jpg"
        _run_checked([ff.FFMPEG, '-y', '-ss', str((start + end) / 2), '-i', paths.final_mp4,
                        '-frames:v', '1', '-vf', 'scale=360:-2', str(frame)])
        if not frame.is_file():
            raise ValueError('Render não contém frame da cena')
        frames.append({'scene_id': row['id'], 'timestamp': (start + end) / 2, 'path': str(frame)})
    report = verify_video(paths.final_mp4, paths.subs_srt, 0, cfg.width, cfg.height)
    _run_checked([ff.FFMPEG, '-v', 'error', '-xerror', '-i', paths.final_mp4, '-f', 'null', '-'])
    snapshot = _fingerprint(paths)
    render_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    request = {'schema_version': VERSION, 'status': 'awaiting_render_review',
        'iteration': state['iteration'], 'render_id': render_id, 'video': paths.final_mp4,
        'frames': frames, 'technical_passed': report.success,
        'technical_checks': [vars(check) for check in report.checks],
        'media': read(paths.media_json), 'music': read(folder / 'plan.json')['music'],
        'instruction': 'Inspecione vídeo, frames e áudio. Preencha feedback.json. Aprovar ou revisar.'}
    write(evidence / 'request.json', request)
    write(evidence / 'fingerprint.json', snapshot)
    write(folder / 'feedback.json', {'schema_version': VERSION, 'render_id': render_id,
        'decision': 'revise', 'reviewer': '', 'checks': {key: {'ok': False, 'evidence': ''} for key in CHECKS},
        'scenes': [{'scene_id': row['scene_id'], 'ok': False, 'evidence': ''} for row in frames], 'issues': []})
    state['render_id'], state['evidence_dir'] = render_id, str(evidence)
    _save(folder, state, 'awaiting_render_review', request['instruction'])
    write(folder / 'request.json', request)


def _record_music(paths, plan):
    """Check that the chosen track was actually mixed and retain its attribution."""
    music = plan['music']
    if not Path(paths.metadata_json).exists():
        if music['mode'] == 'manual':
            raise ValueError('Faltam metadados da trilha renderizada')
        return
    metadata = read(paths.metadata_json)
    actual = metadata.get('audio', {}).get('music', {})
    track = actual.get('track') or {}
    if music['mode'] == 'manual':
        if not track.get('path') or Path(track['path']).resolve() != Path(music['file']).resolve():
            raise ValueError('Trilha escolhida não foi usada; corrija antes da revisão')
        track.update(source_url=music['source_url'], license=music['license'], license_url=music['license_url'])
        actual['intent'] = {'intent': music['intent'], 'instrumental': True, 'source': 'external_agent'}
        metadata['audio'].setdefault('credits', []).append(
            f"{track.get('title', '')}: {music['source_url']} ({music['license']}; {music['license_url']})")
    elif track:
        raise ValueError('Render usou música apesar da escolha de silêncio')
    write(paths.metadata_json, metadata)


def current_state(paths):
    """An approval is usable only while its reviewed inputs remain unchanged."""
    folder = Path(paths.root) / 'agent_flow'
    state = read(folder / 'state.json')
    if state.get('schema_version') != VERSION:
        raise ValueError('Versão do estado não suportada')
    if state['status'] == 'approved':
        if not _unchanged(paths, state):
            _save(folder, state, 'needs_revision', 'Artefatos mudaram; execute revise ou replan.')
    return state


def _unchanged(paths, state):
    try:
        return _fingerprint(paths) == read(Path(state['evidence_dir']) / 'fingerprint.json')
    except OSError:
        return False


def advance(paths, cfg, export, render):
    """One deterministic step; callbacks reuse the normal acquisition and render pipeline."""
    folder = Path(paths.root) / 'agent_flow'
    state, plan = read(folder / 'state.json'), read(folder / 'plan.json')
    if state.get('schema_version') != VERSION:
        raise ValueError('Versão do estado não suportada')
    status = state['status']
    if status == 'awaiting_plan':
        _persist_plan(paths, plan, cfg)
        result = export()
        if result != 3:
            raise ValueError('Exportação não terminou na pausa editorial; tente novamente')
        state['plan_digest'] = digest(folder / 'plan.json')
        write(folder / f"accepted-plan-{state['iteration']}.json", plan)
        _media_template(paths, plan)
        _save(folder, state, 'awaiting_media', 'Inspecione candidatos e preencha media-feedback.json; advance renderiza.')
    elif status == 'awaiting_media':
        if digest(folder / 'plan.json') != state['plan_digest']:
            raise ValueError('Plano mudou. Execute replan antes de continuar')
        _select_media(paths, plan, state['iteration'])
        cfg._agent_audio_request = plan['music']
        result = render()
        if result:
            raise ValueError('Render falhou; escolhas preservadas, execute advance novamente')
        _record_music(paths, plan)
        _render_review(paths, state, cfg)
    elif status in ('awaiting_render_review', 'approved'):
        evidence = Path(state['evidence_dir'])
        if not _unchanged(paths, state):
            _save(folder, state, 'needs_revision', 'Artefatos mudaram; execute revise ou replan.')
            raise ValueError('Artefatos mudaram. Execute revise ou replan; aprovação anterior inválida')
        if status == 'approved':
            return 0
        feedback = read(folder / 'feedback.json')
        if feedback.get('schema_version') != VERSION or feedback.get('render_id') != state['render_id']:
            raise ValueError('Revisão não corresponde ao render atual')
        _text(feedback.get('reviewer'), 'reviewer')
        if feedback.get('decision') == 'revise':
            if not feedback.get('issues'):
                raise ValueError('Revisão deve registrar problemas encontrados')
            write(evidence / 'feedback.json', feedback)
            _save(folder, state, 'needs_revision', 'Corrija mídia e execute revise; para roteiro/cenas, execute replan.')
        elif feedback.get('decision') == 'approve':
            request = read(evidence / 'request.json')
            if not request['technical_passed'] or feedback.get('issues'):
                raise ValueError('Problemas técnicos/editoriais impedem aprovação')
            for key in CHECKS:
                check = feedback.get('checks', {}).get(key, {})
                if check.get('ok') is not True:
                    raise ValueError(f'Revisão pendente: {key}')
                _text(check.get('evidence'), key)
            rows = feedback.get('scenes', [])
            if [r.get('scene_id') for r in rows] != [s['scene_id'] for s in request['frames']]:
                raise ValueError('Revisão deve cobrir todas as cenas')
            for row in rows:
                if row.get('ok') is not True:
                    raise ValueError('Cena não aprovada')
                _text(row.get('evidence'), 'Evidência da cena')
            write(evidence / 'feedback.json', feedback)
            _save(folder, state, 'approved', 'Vídeo aprovado pelo agente; evidências preservadas.')
            return 0
        else:
            raise ValueError('decision deve ser approve ou revise')
    return 3


def revise(paths, replan=False):
    folder = Path(paths.root) / 'agent_flow'
    state = read(folder / 'state.json')
    if state['status'] == 'awaiting_plan' and not replan:
        raise ValueError('Ainda não há mídia para revisar; execute advance')
    if (folder / 'feedback.json').exists() and state.get('evidence_dir'):
        write(Path(state['evidence_dir']) / 'feedback.json', read(folder / 'feedback.json'))
    state['iteration'] += 1
    if replan:
        validate_plan(read(folder / 'plan.json'))
        archive = folder / 'previous' / str(state['iteration'])
        _archive(paths, archive)
        _save(folder, state, 'awaiting_plan', 'Plano alterado; advance importa e exporta nova mídia.')
    else:
        if digest(folder / 'plan.json') != state.get('plan_digest'):
            raise ValueError('Plano mudou; execute replan')
        _save(folder, state, 'awaiting_media', 'Corrija media-feedback.json; advance renderiza e exige nova revisão.')


def _archive(paths, archive):
    """Preserve derived artifacts before editorial changes invalidate their caches."""
    for name in ('script', 'sources', 'media_review', 'media', 'audio', 'timeline', 'render', 'subtitles'):
        source = Path(paths.root) / name
        if source.exists():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(archive / name))
    metadata = Path(paths.metadata_json)
    if metadata.exists():
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(metadata), str(archive / metadata.name))
