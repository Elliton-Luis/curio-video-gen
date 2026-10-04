"""Fluxo standby de ponta a ponta (rede mockada).

1) Sem imagens em lugar nenhum -> MediaStandby + README + metadata stub.
2) Com 1 foto manual -> a etapa de mídia passa (TTS mockado prova).
"""

import json
import os
from unittest.mock import patch

from curio.config import CurioConfig
from curio.pipeline import run_pipeline
from curio.pipeline_media import MediaStandby, manual_media_dir
from curio.stages.research import ResearchResult, ResearchSource
from curio.stages.entity import TargetEntity
from curio.stages.scenes import Chapter


def _seed_project(out_dir, slug="teste-standby"):
    root = os.path.join(out_dir, slug)
    os.makedirs(os.path.join(root, "script"), exist_ok=True)
    with open(os.path.join(root, "script", "script.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("Primeira cena do vídeo. Segunda cena do vídeo.")
    with open(os.path.join(root, "script", "title.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("Título de teste?")
    chapters = [Chapter(id=1, narration="Primeira cena do vídeo.",
                        duration_estimate=5.0),
                Chapter(id=2, narration="Segunda cena do vídeo.",
                        duration_estimate=5.0)]
    with open(os.path.join(root, "script", "chapters.json"), "w",
              encoding="utf-8") as fh:
        json.dump([c.to_dict() for c in chapters], fh)
    return root


def _empty_media(chapters, cfg, max_images, metrics=None, genre=""):
    scenes = [{"chapter_id": c.id, "asset": None, "assets": [],
               "reused_from": None} for c in chapters]
    return scenes, ["cena sem mídia (mock)"]


def test_standby_sem_imagens(tmp_path):
    out_dir = str(tmp_path / "output")
    root = _seed_project(out_dir)
    cfg = CurioConfig()
    cfg.out_dir = out_dir
    with patch("curio.stages.visual.fetch_media_multi",
               side_effect=_empty_media):
        try:
            run_pipeline("ideia teste", cfg, slug="teste-standby",
                         max_images=3)
            raise AssertionError("deveria entrar em standby")
        except MediaStandby as exc:
            assert exc.slug == "teste-standby"
            assert exc.n_scenes == 2
    manual = manual_media_dir(type("P", (), {"root": root})())
    assert os.path.isdir(manual)
    assert os.path.isfile(os.path.join(manual, "COMO_USAR.txt"))
    meta = json.load(open(os.path.join(root, "metadata.json"),
                          encoding="utf-8"))
    assert meta["status"] == "standby-no-media"
    assert meta["manual_dir"] == manual
    # nada de áudio/vídeo produzido
    assert not os.path.isfile(os.path.join(root, "render", "final.mp4"))


def test_resume_com_foto_manual(tmp_path):
    out_dir = str(tmp_path / "output")
    root = _seed_project(out_dir)
    cfg = CurioConfig()
    cfg.out_dir = out_dir
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
           b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
           b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd84"
           b"\x00\x00\x00\x00IEND\xaeB`\x82")
    manual = os.path.join(root, "assets", "manual")
    os.makedirs(manual)
    with open(os.path.join(manual, "01-foto.png"), "wb") as fh:
        fh.write(png)

    def _boom(*a, **k):
        raise RuntimeError("CHEGOU_NO_TTS")

    def _fonte(*a, **k):
        return ResearchResult(
            TargetEntity(name="Teste"),
            [ResearchSource(title="Teste", url="https://exemplo.org/t",
                            snippet="trecho de teste", origin="mock")])

    # A pesquisa também vai para a rede: stubada para o teste não depender
    # da Wikipedia (429 intermitente deixava a suíte instável).
    with patch("curio.stages.visual.fetch_media_multi",
               side_effect=AssertionError("não deve buscar: há foto manual")), \
         patch("curio.stages.research.research_topic", side_effect=_fonte), \
         patch("curio.stages.tts.synthesize", side_effect=_boom):
        try:
            run_pipeline("ideia teste", cfg, slug="teste-standby",
                         max_images=3)
            raise AssertionError("deveria chegar ao TTS")
        except RuntimeError as exc:
            assert str(exc) == "CHEGOU_NO_TTS"
    media = json.load(open(os.path.join(root, "media", "media.json"),
                           encoding="utf-8"))
    assert all(s["asset"] and s["asset"]["provider"] == "manual"
               for s in media)
