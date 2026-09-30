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
from curio.pipeline import run_pipeline, video_paths
from curio.stages.research import ResearchSource
from curio.stages.scenes import Chapter

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
        ch.visual_queries = [SCENE_QUERIES[i - 1]]
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
    return [{"chapter_id": c.id, "asset": asset(0),
             "assets": [{"asset": asset(k), "query": f"q{k}", "order": k}
                        for k in range(3)],
             "reused_from": None} for c in chapters]


def _run(tmp_path, **over):
    out_dir = str(tmp_path / "output")
    cfg = CurioConfig()
    cfg.out_dir = out_dir
    cfg.render_backend = "cpu"
    cfg.width, cfg.height, cfg.fps = 160, 284, 12
    images = _real_images(tmp_path)
    for key, val in over.items():
        setattr(cfg, key, val)

    chapters = _chapters()
    patches = [
        patch("curio.stages.research.research_topic", return_value=_sources()),
        patch("curio.stages.script.generate_script", return_value=(SCRIPT, "mock")),
        patch("curio.stages.script.generate_title",
              return_value=("Por que Marte é vermelho?", "mock")),
        patch("curio.stages.scenes.build_chapters",
              return_value=(chapters, "mock")),
        patch("curio.stages.visual.fetch_media_multi",
              side_effect=lambda chs, c, mx, metrics=None, genre="": (
                  _media(chs, images), [])),
        patch("curio.stages.tts.synthesize", side_effect=_fake_tts),
    ]
    for p in patches:
        p.start()
    try:
        return run_pipeline("por que marte e vermelho", cfg,
                            slug="teste-integracao", max_images=3), out_dir
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
    return type("Res", (), {"duration": total, "words": words,
                            "provider": provider, "voice": voice,
                            "speed": speed})()


def test_integracao_completa(tmp_path):
    meta, out_dir = _run(tmp_path)
    root = os.path.join(out_dir, "teste-integracao")
    paths = video_paths(out_dir, "teste-integracao")

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
