"""Etapa 6 — revisão humana: contact sheet, dry-run, swap e rerender.

O requisito de fundo: revisar um vídeo tem que custar ~1 minuto, e trocar
uma imagem NÃO pode custar uma nova narração. Estes testes existem para
que essa segunda parte não se perca numa refatoração — o `rerender` é
tentador de refazer "tudo que for preciso", e "tudo" inclui a voz.
"""

import json
import os
import subprocess
import wave

import pytest

from curio.cli import main
from curio.config import CurioConfig
from curio.pipeline import video_paths
from curio.stages import review as review_stage
from curio.stages import scoring as scoring_stage
from curio.stages import research as research_stage
from curio.stages import script as script_stage
from curio.stages import tts as tts_stage
from curio.stages import visual as visual_stage, visual_timeline
from curio.stages.scenes import Chapter

pytest.importorskip("PIL")


def run(out_dir, *args):
    """Invoca a CLI com --out-dir na posição GLOBAL (antes do subcomando)."""
    return main(["--out-dir", out_dir, *args])


def _semantic(chapters):
    return tuple(chapter.semantic_scene("review_fixture") for chapter in chapters)


def test_review_rejects_chapter_instead_of_reinterpreting_it():
    chapter = Chapter(id=1, narration="Texto.", duration_estimate=4,
                      visual_type="literal")
    with pytest.raises(TypeError, match="SemanticScene"):
        review_stage.scene_rows((chapter,), [], ".")


def _mk(tmp_path, n_cenas=4):
    """Projeto completo o suficiente para review/swap/rerender."""
    out = str(tmp_path / "output")
    slug = "proj-review"
    root = os.path.join(out, slug)
    for sub in ("script", "audio", "media", "timeline", "subtitles", "render",
                "sources", "review"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    paths = video_paths(out, slug)

    chapters = []
    for i in range(1, n_cenas + 1):
        vtype = ("mechanism", "literal", "typographic", "historical_art")[i - 1]
        ch = Chapter(id=i, narration=f"Narração da cena {i}.", duration_estimate=4.0,
                     visual_queries=[f"assunto {i}"], visual_type=vtype,
                     subject=f"assunto {i}",
                     visual_entities=[f"entidade {i}a", f"entidade {i}b"],
                     context=[], forbidden=["wallpaper", "power plant"])
        ch.global_visual_queries = list(ch.visual_queries)
        ch.start, ch.end = (i - 1) * 4.0, i * 4.0
        chapters.append(ch)
    with open(paths.chapters_json, "w", encoding="utf-8") as fh:
        json.dump([c.to_dict() for c in chapters], fh, ensure_ascii=False)
    with open(paths.timeline_json, "w", encoding="utf-8") as fh:
        json.dump([c.to_dict() for c in chapters], fh, ensure_ascii=False)
    with open(paths.title_txt, "w", encoding="utf-8") as fh:
        fh.write("Uma pergunta?")

    # Áudio: um WAV marker. Se o rerender re-sintetizasse, este arquivo
    # mudaria — é assim que o teste prova que a voz NÃO foi refeita.
    with wave.open(paths.narration_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000 * (4 * n_cenas))
    with open(paths.subs_ass, "w", encoding="utf-8") as fh:
        fh.write("[Script Info]\n")

    # Imagens reais (o Ken Burns não digere arquivo falso)
    imgs = []
    for k, cor in enumerate(("0x224466", "0x88aacc", "0x667788")):
        p = os.path.join(root, "media", f"img{k}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c={cor}:s=480x854", "-frames:v", "1", p],
                       check=True)
        imgs.append(p)

    media = []
    for ch in chapters:
        entries = []
        for k in range(2):
            entries.append({
                "asset": {"provider": "wikimedia", "asset_id": f"a{k}",
                          "title": f"foto {k} de {ch.subject}",
                          "license": "CC BY-SA 4.0",
                          "license_url": "https://ex.org/lic",
                          "source_url": "https://ex.org/x", "author": "Alguém",
                          "local_path": imgs[k], "kind": "image",
                          "width": 480, "height": 854},
                "query": f"q{k}", "order": k, "score": 60 - k * 10,
                "strategy": "image"})
        media.append({"chapter_id": ch.id, "asset": entries[0]["asset"],
                      "assets": entries, "reused_from": None,
                      "rejected": [{"title": "power plant towers",
                                    "query": "q0", "provider": "pixabay",
                                    "reason": "título contém termo bloqueado: 'power plant'"},
                                   {"title": "mountain wallpaper 4k",
                                    "query": "q1", "provider": "pixabay",
                                    "reason": "título contém termo bloqueado: 'wallpaper'"}],
                      "visual_type": ch.visual_type, "strategy": "image"})
    with open(paths.media_json, "w", encoding="utf-8") as fh:
        json.dump(media, fh, ensure_ascii=False)

    cfg = CurioConfig()
    cfg.out_dir = out
    cfg.render_backend = "cpu"
    cfg.width, cfg.height, cfg.fps = 120, 213, 10
    return cfg, slug, paths, chapters, media, root


# --- folha de contato --------------------------------------------------

def test_contact_sheet_gera_html_com_uma_linha_por_cena(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    out = review_stage.write_contact_sheet(paths.contact_sheet, _semantic(chapters), media,
                                           root, slug,
                                           threshold=scoring_stage.threshold())
    assert os.path.isfile(out)
    html = open(out, encoding="utf-8").read()
    assert html.startswith("<!doctype html>")
    for ch in chapters:
        assert f"Cena {ch.id}" in html
    # o que o autor precisa para decidir
    assert "power plant towers" in html      # motivo da rejeição
    assert "termo bloqueado" in html
    assert "CC BY-SA 4.0" in html             # licença
    assert "nota" in html
    assert "mínimo de nota" in html


def test_contact_sheet_aponta_imagens_por_caminho_relativo(tmp_path):
    """A folha precisa abrir de qualquer diretório, não só do projeto."""
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    out = review_stage.write_contact_sheet(paths.contact_sheet, _semantic(chapters), media,
                                           root, slug)
    html = open(out, encoding="utf-8").read()
    # relativo ao diretório da folha (review/), não ao projeto
    assert "../media/img0.png" in html
    assert str(root) not in html, "caminho absoluto quebraria fora do projeto"


def test_contact_sheet_conta_cenas_sem_visual(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    media[1]["assets"] = []
    media[1]["asset"] = None
    out = review_stage.write_contact_sheet(paths.contact_sheet, _semantic(chapters), media,
                                           root, slug)
    html = open(out, encoding="utf-8").read()
    assert "sem visual" in html
    assert "1 cena(s) sem visual" in html


def test_contact_sheet_marca_visual_gerado_por_codigo(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    media[0]["assets"][0]["asset"].update(provider="synth", license="Original")
    media[0]["assets"][0]["strategy"] = "diagram"
    out = review_stage.write_contact_sheet(paths.contact_sheet, _semantic(chapters), media,
                                           root, slug)
    html = open(out, encoding="utf-8").read()
    assert "diagrama" in html
    assert "geradas por código" in html


# --- dry-run -----------------------------------------------------------

def test_dry_run_mostra_a_decisao_por_cena(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    txt = review_stage.dry_run_text(_semantic(chapters), media,
                                    threshold=scoring_stage.threshold())
    for ch in chapters:
        assert f"Cena {ch.id}" in txt
    assert "[mechanism]" in txt and "[typographic]" in txt
    assert "assunto 1" in txt
    assert "proibidos  : wallpaper, power plant" in txt
    assert "descartado" in txt
    assert "termo bloqueado" in txt
    assert "scoring    : base" in txt


def test_dry_run_diz_quando_nao_houve_escolha(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    for s in media:
        s["assets"], s["asset"] = [], None
    txt = review_stage.dry_run_text(_semantic(chapters), media)
    assert txt.count("escolhido  : NENHUM") == len(chapters)


def test_cli_review_gera_a_folha_e_o_dry_run(tmp_path, capsys):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    assert run(cfg.out_dir, "review", "--slug", slug) == 0
    assert os.path.isfile(paths.contact_sheet)
    assert run(cfg.out_dir, "review", "--slug", slug, "--dry-run") == 0
    assert "Cena 1" in capsys.readouterr().out


# --- swap --------------------------------------------------------------

def test_swap_troca_a_imagem_sem_tocar_no_resto(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    antes = json.load(open(paths.media_json, encoding="utf-8"))
    rc = run(cfg.out_dir, "swap", "--slug", slug, "--scene", "1", "--pick", "1")
    assert rc == 0
    depois = json.load(open(paths.media_json, encoding="utf-8"))
    cena = depois[0]
    assert cena["assets"][0]["asset"]["asset_id"] == "a1"
    assert cena["assets"][0]["order"] == 0
    # as outras cenas não foram tocadas
    assert depois[1:] == antes[1:]
    # e a troca ficou registrada
    assert cena.get("swapped_from") == "a0"


def test_swap_rejeita_pick_fora_da_faixa(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    assert run(cfg.out_dir, "swap", "--slug", slug, "--scene", "1", "--pick", "9") == 1


def test_swap_rejeita_cena_inexistente(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    assert run(cfg.out_dir, "swap", "--slug", slug, "--scene", "99", "--pick", "0") == 1


def test_swap_respeita_a_ordem_na_reconstrucao(tmp_path):
    """O swap não pode ser desfeito pelo replanejamento.

    Se o rerender re-executasse a escolha de papéis, a foto que o autor
    acabou de tirar voltaria para a frente — e a troca não teria efeito.
    """
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    run(cfg.out_dir, "swap", "--slug", slug, "--scene", "1", "--pick", "1")
    media = json.load(open(paths.media_json, encoding="utf-8"))
    vt = visual_timeline.rebuild_visual_timeline(
        _semantic(chapters), tuple(ch.timeline_span() for ch in chapters),
        media, cfg, seed=slug)
    ids = [im["asset_id"] for im in vt[0]["images"]]
    assert ids[0] == "a1", f"swap desfeito pelo replanejamento: {ids}"


# --- rerender: o ponto é NÃO refazer a narração ------------------------

def test_rerender_refaz_video_sem_tocar_na_narracao(tmp_path, monkeypatch):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    run(cfg.out_dir, "swap", "--slug", slug, "--scene", "1", "--pick", "1")

    def _boom(*a, **k):
        raise AssertionError("TTS NÃO pode rodar no rerender")

    monkeypatch.setattr(tts_stage, "synthesize", _boom)
    mtime_audio = os.path.getmtime(paths.narration_wav)

    rc = run(cfg.out_dir, "rerender", "--slug", slug)
    assert rc == 0
    assert os.path.isfile(paths.final_mp4)
    assert os.path.getmtime(paths.narration_wav) == mtime_audio
    # o vídeo de fato mudou (o silencioso foi refeito com a nova ordem)
    assert os.path.getsize(paths.silent_mp4) > 1000


def test_rerender_avisa_quando_o_projeto_esta_incompleto(tmp_path):
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)
    os.remove(paths.narration_wav)
    assert run(cfg.out_dir, "rerender", "--slug", slug) == 1


def test_rerender_nao_reexecuta_pesquisa_nem_roteiro(tmp_path, monkeypatch):
    """Nem LLM, nem pesquisa: as duas etapas mais caras ficam fora."""
    cfg, slug, paths, chapters, media, root = _mk(tmp_path)

    def _boom(*a, **k):
        raise AssertionError("pesquisa/roteiro NÃO podem rodar no rerender")

    monkeypatch.setattr(research_stage, "research_topic", _boom)
    monkeypatch.setattr(script_stage, "generate_script", _boom)
    assert run(cfg.out_dir, "rerender", "--slug", slug) == 0


def test_rerender_uses_timed_chapters_and_records_asset_usage(tmp_path, monkeypatch):
    from curio import cli
    cfg, slug, paths, chapters, media, root = _mk(tmp_path, n_cenas=1)
    untimed = [ch.to_dict() for ch in chapters]
    untimed[0]["start"] = untimed[0]["end"] = 0
    with open(paths.chapters_json, "w", encoding="utf-8") as stream:
        json.dump(untimed, stream)
    with open(paths.visual_json, "w", encoding="utf-8") as stream:
        from tests.test_support.visual_timeline import build_visual_timeline
        json.dump(build_visual_timeline(visual_stage, chapters, media, insertions=0), stream)
    captured = {}
    def build(scenes, spans, *args, **kwargs):
        captured["duration"] = spans[0].end - spans[0].start
    monkeypatch.setattr(cli.pipeline_render_stage, "build_silent_visual", build)
    monkeypatch.setattr(cli.ff, "probe_duration", lambda *args: 4.0)
    monkeypatch.setattr("curio.stages.render.burn_final", lambda *a, **kw: {
        "path": paths.final_mp4, "duration": 4.0, "backend": "cpu", "encoder": "libx264"})
    assert run(cfg.out_dir, "rerender", "--slug", slug) == 0
    assert captured["duration"] == 4.0
    meta = json.load(open(paths.metadata_json, encoding="utf-8"))
    report = json.load(open(meta["metrics_file"], encoding="utf-8"))
    assert report["pipeline"]["visual_assets_unique"] == 2
    assert report["pipeline"]["visual_asset_beat_counts"]
    assert report["consumption"]["media"]["available_by_acquisition"] == {"cache": 2}
