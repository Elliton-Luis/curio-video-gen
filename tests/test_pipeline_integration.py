"""Integração: o pipeline inteiro com rede, LLM e TTS mockados.

O que este arquivo garante é a COSTURA, não cada peça (cada uma tem teste
próprio): que a inserção esparsa chega ao render, que a pasta de informações
recebe fontes E imagens, que a conferência anti-invenção aparece no
metadata, e que nenhuma legenda é mexida.
"""

import json
import os
import subprocess
from unittest.mock import patch

from curio.config import CurioConfig
from curio.pipeline import run_pipeline
from curio.project_paths import video_paths
from curio.media.selection_result import MediaStageResult
from curio.stages.research import ResearchResult, ResearchSource
from curio.stages.entity import TargetEntity
from curio.stages.script import ScriptArtifact, TitleArtifact
from curio.stages.scene_projection import Chapter
from curio.stages.scene_contract import ScenePlanResult
from curio.stages.scene_contract import SemanticScene
from curio.stages.tts import TTSResult
from tests.media_test_support import with_selection

SCRIPT = (
    "Marte leva 687 dias para dar uma volta completa no Sol. "
    "São 687 dias, sempre, sem atalho. "
    "O planeta tem duas luas pequenas. "
    "A atmosfera é fina e cheia de poeira. "
    "Por isso o céu fica vermelho ao meio-dia. "
    "E você já parou pra pensar nisso?"
)


def _sources():
    return [ResearchSource(
        title="Marte", url="https://pt.wikipedia.org/wiki/Marte",
        snippet="Marte leva 687 dias para completar sua órbita. "
                "Possui duas luas: Fobos e Deimos.",
        origin="wikipedia")]


# Assunto declarado por cena: a inserção só entra se for mais precisa sobre
# o tema que o fundo (regra de `order_for_insertion`).
SCENE_QUERIES = ["mars craters surface", "mars moons telescope",
                 "mars dust atmosphere", "red sky dust",
                 "mars sunset horizon", "mars surface rocks"]


def _chapters():
    parts = [p.strip() + "." for p in SCRIPT.split(".") if p.strip()]
    out, t = [], 0.0
    for i, p in enumerate(parts, 1):
        dur = 6.0
        ch = Chapter(id=i, narration=p, duration_estimate=dur,
                     start=t, end=t + dur)
        ch.set_visual_queries([SCENE_QUERIES[i - 1]], source="test_fixture")
        ch.subject = f"mars {i}"
        ch.visual_entities = ["crater", "surface"]
        out.append(ch)
        t += dur
    return out


def _real_images(tmp_path):
    """Imagens REAIS (o Ken Burns do ffmpeg não digere arquivo falso)."""
    paths = []
    for k, color in enumerate(("0x224466", "0x88aacc", "0x667788")):
        p = str(tmp_path / f"fundo{k}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"color=c={color}:s=480x854",
                        "-frames:v", "1", p], check=True)
        paths.append(p)
    return paths


def _media(chapters, paths):
    """3 candidatos por cena com licença livre.

    O fundo é genérico (não fala de Marte) e um dos complementares é o
    preciso — é o que tem de acabar como inserção.
    """
    titles = ["red dunes generic", "mars craters closeup",
              "mars planet surface"]
    def asset(k):
        return {"provider": "pixabay", "asset_id": f"a{k}",
                "title": titles[k], "author": "Alguem",
                "license": "Pixabay License", "license_url": "https://p.io/l",
                "source_url": f"https://p.io/{k}",
                "download_url": f"https://p.io/{k}.jpg",
                "width": 2000, "height": 2000, "kind": "image",
                "local_path": paths[k], "rights_status": "clear"}
    return [with_selection({"chapter_id": c.id, "asset": asset(0),
             "assets": [{"asset": asset(k), "query": f"q{k}", "order": k}
                        for k in range(3)],
             "reused_from": None}) for c in chapters]


def _run(tmp_path, narration="ai", scene_error=None, **over):
    out_dir = str(tmp_path / "output")
    cfg = CurioConfig()
    cfg.out_dir = out_dir
    cfg.render_backend = "cpu"
    cfg.width, cfg.height, cfg.fps = 160, 284, 12
    images = _real_images(tmp_path)
    for key, val in over.items():
        setattr(cfg, key, val)

    chapters = _chapters()
    plan = ScenePlanResult(
        semantic_scenes=tuple(ch.semantic_scene("mock") for ch in chapters),
        timeline_spans=tuple(ch.timeline_span() for ch in chapters), source="mock")
    scene_builder = (patch("curio.stages.scenes.build_semantic_scenes",
                           side_effect=scene_error) if scene_error else
                     patch("curio.stages.scenes.build_semantic_scenes",
                           return_value=plan))

    def acquire_media(scenes, _cfg, _max_images, metrics=None, genre=""):
        assert all(isinstance(scene, SemanticScene) for scene in scenes)
        return MediaStageResult.from_rows(
            _media(scenes, images), "provider")

    patches = [
        patch("curio.stages.research.research_topic", return_value=ResearchResult(
            TargetEntity(name="Marte"), _sources(), tried_queries=["Marte"])),
        patch("curio.stages.script.generate_script",
              return_value=ScriptArtifact(SCRIPT, "mock")),
        patch("curio.stages.script.generate_title",
              return_value=TitleArtifact("Por que Marte é vermelho?", "mock")),
        scene_builder,
        patch("curio.stages.visual.fetch_media_multi",
              side_effect=acquire_media),
        patch("curio.stages.tts.synthesize", side_effect=_fake_tts),
    ]
    for p in patches:
        p.start()
    try:
        return run_pipeline("por que marte e vermelho", cfg,
                            slug="teste-integracao", max_images=3,
                            narration=narration), out_dir
    finally:
        for p in patches:
            p.stop()


def _fake_tts(text, wav_path, provider, voice, speed, duration_target,
              words_path=None, metrics=None, language="pt-BR"):
    """TTS stub: um 'word' por palavra, com tempo linear (0.5 s/palavra)."""
    import wave
    words, t = [], 0.0
    for w in text.split():
        words.append({"text": w, "start": round(t, 3),
                      "end": round(t + 0.5, 3)})
        t += 0.5
    total = round(t, 3)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * int(16000 * total))
    if words_path:
        with open(words_path, "w", encoding="utf-8") as fh:
            json.dump(words, fh)
    return TTSResult(path=wav_path, duration=total, words=words,
                     provider=provider, voice=voice, speed=speed)


def test_integracao_completa(tmp_path):
    meta, out_dir = _run(tmp_path)
    root = os.path.join(out_dir, "teste-integracao")
    paths = video_paths(out_dir, "teste-integracao")
    assert meta["scene_context_enrichment"]["source"] == "mock"
    assert meta["scene_context_enrichment"]["changed"] is True
    assert meta["media_resolution_source"] == "provider"
    assert os.path.isfile(paths.media_manifest_json)
    assert os.path.isfile(paths.script_manifest_json)
    assert meta["artifacts"]["script_manifest"] == paths.script_manifest_json
    run_log = meta["execution_log"]
    assert os.path.isfile(run_log)
    events = [json.loads(line) for line in open(run_log, encoding="utf-8")]
    assert events[0]["event"] == "run_started"
    assert events[-1]["event"] == "run_completed"
    assert {e["stage"] for e in events if e["event"] == "stage_started"} >= {
        "research", "script", "scenes", "media", "tts", "subs", "render"}
    assert not any("prompt" in e.get("details", {}) for e in events)

    # 1) inserções esparsas chegaram à timeline e ao metadata
    assert meta["visual"]["insert_budget"] == 2
    assert meta["visual"]["insertions"] == 2, meta["visual"]
    assert meta["visual"]["insert_style"] == "drop_in"
    vt = json.load(open(paths.visual_json, encoding="utf-8"))
    ins = [im for t in vt for im in t["images"] if im["order"] > 0]
    assert len(ins) == 2
    assert all(im["transition"] == "drop_in" for im in ins)
    assert all(im["sfx"] for im in ins), "inserção sem som"

    # 2) a pasta de informações tem fontes E imagens
    assert os.path.isfile(paths.sources_json)
    assert os.path.isfile(paths.sources_report), "FONTES.md não foi gerado"
    report = open(paths.sources_report, encoding="utf-8").read()
    assert "Marte" in report
    assert "Pixabay License" in report
    assert "https://p.io/l" in report          # link da licença
    assert "anti-invenção" in report

    # 3) anti-invenção conferiu e o número bate com a fonte
    grounding = meta["research"]["grounding"]
    assert grounding["checked"] > 0
    assert "687" in grounding["grounded"]
    assert grounding["unverified"] == [], grounding

    # 4) direitos autorais registrados como livres, uma entrada por imagem
    #    distinta (o registro deduplica a mesma foto usada em várias cenas)
    assert meta["sources"]["blocked_media"] == 0
    assert meta["sources"]["media"] == 3  # 3 fotos distintas no vídeo
    reg = json.load(open(paths.sources_json, encoding="utf-8"))
    assert all(m["rights_status"] == "clear" for m in reg["media"])
    assert all(m["license"] == "Pixabay License" for m in reg["media"])
    assert all(m["local_path"] for m in reg["media"])

    # 5) as legendas não foram tocadas pelo caminho novo
    assert os.path.isfile(paths.subs_srt) and os.path.isfile(paths.subs_ass)
    assert meta["subtitle_cues"] > 0
    srt = open(paths.subs_srt, encoding="utf-8").read()
    assert "687" in srt


def test_falha_no_chain_de_cenas_em_ideia_cai_para_divisao_local(tmp_path):
    from curio.project_paths import video_paths
    from curio.stages.nvidia import NvidiaError
    from curio.stages.scenes import _norm

    error = NvidiaError("LLM indisponível após 6/6 rodadas")
    meta, out_dir = _run(tmp_path, scene_error=error)
    assert meta["scenes_source"] == "local"
    assert any("cenas locais (chain LLM indisponível" in warning
               for warning in meta["warnings"])
    paths = video_paths(out_dir, "teste-integracao")
    chapters = json.load(open(paths.chapters_json, encoding="utf-8"))
    assert _norm(" ".join(ch["narration"] for ch in chapters)) == _norm(SCRIPT)


def test_insercoes_desligadas_nao_quebram_o_video(tmp_path):
    meta, out_dir = _run(tmp_path, visual_insertions=0)
    root = os.path.join(out_dir, "teste-integracao")
    paths = video_paths(out_dir, "teste-integracao")
    assert meta["visual"]["insertions"] == 0
    vt = json.load(open(paths.visual_json, encoding="utf-8"))
    assert not [im for t in vt for im in t["images"] if im["order"] > 0]
    assert os.path.isfile(paths.final_mp4)


def test_sfx_desligado_mantem_a_insercao(tmp_path):
    meta, out_dir = _run(tmp_path, visual_sfx=False)
    paths = video_paths(out_dir, "teste-integracao")
    vt = json.load(open(paths.visual_json, encoding="utf-8"))
    ins = [im for t in vt for im in t["images"] if im["order"] > 0]
    assert len(ins) == 2, "sem SFX a foto ainda entra"
    assert all(im["sfx"] is None for im in ins)
    assert meta["visual"]["sfx"] is False


def test_musica_manual_e_transicoes_de_genero_chegam_ao_video(tmp_path):
    """Mix real com trilha fornecida pelo usuário; sem download no render."""
    music = tmp_path / "user-theme.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=220:duration=30", "-c:a", "pcm_s16le", str(music)],
        check=True)
    meta, _out_dir = _run(
        tmp_path, genre="people", music_mode="manual", music_file=str(music),
        visual_sfx=False)
    assert meta["audio"]["music"]["mode"] == "manual"
    assert meta["audio"]["music"]["track"]["path"] == str(music)
    assert meta["audio"]["music"]["ducking"] is True
    assert meta["visual_transitions"]["genre"] == "people"
    assert meta["artifacts"]["music"] == str(music)
    assert os.path.isfile(meta["artifacts"]["video"])


def test_auto_usa_trilhas_locais_especificas_por_genero(tmp_path):
    """Dois renders FFmpeg reais escolhem assets locais de pastas distintas."""
    library = tmp_path / "assets" / "library" / "music"
    fixture_styles = {
        "people": (220, "violin classical ambient people", ["classical"]),
        "science": (880, "calm minimal ambient science", ["minimal"]),
    }
    for genre, (freq, title, mood) in fixture_styles.items():
        folder = library / genre
        folder.mkdir(parents=True)
        track = folder / "fixture.wav"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"sine=frequency={freq}:duration=30", "-c:a", "pcm_s16le",
            str(track)], check=True)
        (folder / "fixture.json").write_text(json.dumps({
            "asset_id": f"fixture:{genre}", "source_asset_id": genre,
            "title": title, "author": "Curio test fixture",
            "source": "manual", "source_url": "", "license": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "downloaded_at": "test", "genres": [genre], "mood": mood,
            "duration": 30, "filename": track.name, "use_count": 0,
        }), encoding="utf-8")

    outputs = {}
    for genre in ("people", "science"):
        case = tmp_path / f"case-{genre}"
        case.mkdir()
        meta, _ = _run(case, genre=genre, music_mode="auto",
                       audio_enabled=True,
                       music_auto_fill=False, sfx_auto_fill=False,
                       audio_library_dir=str(tmp_path / "assets" / "library"))
        outputs[genre] = meta
    people = outputs["people"]["audio"]["music"]["track"]
    science = outputs["science"]["audio"]["music"]["track"]
    assert people["title"] == "violin classical ambient people"
    assert science["title"] == "calm minimal ambient science"
    assert people["path"] != science["path"]
    assert os.path.isfile(outputs["people"]["artifacts"]["video"])
    assert os.path.isfile(outputs["science"]["artifacts"]["video"])


def test_fluxo_humano_guarda_audio_request_para_finalize(tmp_path):
    music = tmp_path / "human-theme.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=330:duration=30", "-c:a", "pcm_s16le", str(music)],
        check=True)
    meta, out_dir = _run(tmp_path, narration="human", genre="people",
                         audio_enabled=True, music_mode="manual",
                         music_file=str(music), visual_sfx=False)
    assert meta["narration"] == "human-pending"
    assert meta["audio_request"]["music"]["mode"] == "manual"
    assert meta["audio_request"]["music"]["track"]["path"] == str(music)
    assert "audio" not in meta  # trilha ainda não foi mixada até finalize
    assert meta["visual_report"]["cenas"] == len(meta["chapters"])
    assert "provider_downloads" in meta
    assert meta["scene_context_enrichment"]["source"] == "mock"
    assert meta["media_resolution_source"] == "provider"
    from curio.project_paths import video_paths
    paths = video_paths(out_dir, "teste-integracao", "people")
    assert os.path.isfile(paths.sources_json)
    assert os.path.isfile(paths.sources_report)
    assert meta["sources"]["media"] == 3
    source_registry = json.load(open(paths.sources_json, encoding="utf-8"))
    assert len(source_registry["media"]) == meta["sources"]["media"]
    assert meta["scene_context_enrichment"]["scene_ids"] == [
        chapter["id"] for chapter in meta["chapters"]
    ]


def test_finalize_humano_aplica_trilha_salva_no_audio_request(tmp_path, monkeypatch):
    from curio.pipeline import finalize_project
    from curio.project_paths import video_paths
    from curio.stages import transcribe as transcribe_stage

    music = tmp_path / "human-final-theme.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=330:duration=30", "-c:a", "pcm_s16le", str(music)],
        check=True)
    meta, out_dir = _run(tmp_path, narration="human", genre="people",
                         audio_enabled=True, music_mode="manual",
                         music_file=str(music), visual_sfx=False)
    paths = video_paths(out_dir, "teste-integracao", "people")
    duration = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", paths.silent_mp4],
        check=True, capture_output=True, text=True)
    seconds = float(duration.stdout.strip())
    voice = tmp_path / "human.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"sine=frequency=440:duration={max(3.0, seconds - 0.05):.3f}",
        "-c:a", "pcm_s16le", str(voice)], check=True)
    monkeypatch.setattr(transcribe_stage, "transcribe", lambda *a, **k: [
        {"text": "voz", "start": 0.2, "end": 0.8}])
    final = finalize_project("teste-integracao", str(voice),
                            CurioConfig(out_dir=out_dir,
                                        render_backend="cpu",
                                        audio_library_dir=str(tmp_path / "assets/library")))
    assert final["audio"]["music"]["mode"] == "manual"
    assert final["audio"]["music"]["track"]["path"] == str(music)
    assert final["artifacts"]["music"] == str(music)
    assert os.path.isfile(final["artifacts"]["video"])
