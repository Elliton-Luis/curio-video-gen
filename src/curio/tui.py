"""TUI visual em terminal (stdlib, sem dependências).

Organizada por OBJETIVO, não por comando técnico:
- "Quero um vídeo pronto" → narração IA, sai com MP4 final.
- "Quero narrar eu mesmo" → assistente em 2 passos, deixando explícito que
  o vídeo final SÓ existe depois do passo 2 (finalize com sua voz).
- "Ajuda" explica os fluxos, arquivos e o que fazer em cada etapa.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import time

from . import verify as verify_mod
from .config import CurioConfig, parse_duration
from .pipeline import run_pipeline, video_paths
from .slug import slugify
from .stages import nvidia as nvidia_stage
from .media import providers as media_prov

QUICK_TEST_IDEA = "De onde veio a palavra salário?"
QUICK_TEST_SLUG = "teste-rapido"

LLM_PROVIDERS = ("nvidia", "openrouter", "gemini", "groq")
MEDIA_PROVIDERS = ("pixabay", "pexels", "wikimedia", "openverse")


class _TUIExit(Exception):
    pass


def _confirm_twice(prompt: str, confirm_text: str = "SIM") -> bool:
    """Confirmação dupla para ações destrutivas."""
    first = _ask(f"{prompt} [s/N]: ").strip().lower()
    if not first.startswith("s"):
        return False
    second = _ask(f"Tem certeza? Digite '{confirm_text}' para confirmar: ").strip()
    return second == confirm_text


def _colors() -> dict[str, str]:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return {k: "" for k in ("bold", "cyan", "green", "yellow", "red", "dim", "reset")}
    return {
        "bold": "\033[1m", "cyan": "\033[36m", "green": "\033[32m",
        "yellow": "\033[33m", "red": "\033[31m", "dim": "\033[2m",
        "reset": "\033[0m",
    }


def _clear() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def _banner(c: dict[str, str]) -> None:
    print(f"{c['bold']}{c['cyan']}"
          "  ____ _   _ ____  ___ ___  \n"
          " / ___| | | |  _ \\|_ _/ _ \\ \n"
          "| |   | | | | |_) || | | | |\n"
          "| |___| |_| |  _ < | | |_| |\n"
          " \\____|\\___/|_| \\_\\___\\___/ \n"
          f"{c['reset']}{c['dim']}Máquina de Conteúdo Educativo em Vídeo — v0.2{c['reset']}\n")


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise _TUIExit()


def _pause(c: dict[str, str]) -> None:
    _ask(f"\n{c['dim']}Enter para voltar ao menu...{c['reset']}")


def _ask_duration(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    """Meta de duração (nunca corta): auto ou segundos. Padrão: auto."""
    from .config import parse_duration
    raw = _ask("Duração [auto/30/45/60/90/120/180/outro Nºs, padrão auto]: ").strip()
    if not raw:
        print("Duração: automática (o conteúdo manda).")
        import dataclasses as _dc
        return _dc.replace(cfg, duration_target=0.0)
    if raw.strip().lower().startswith("person"):
        raw = _ask("Quantos segundos (5..600)? ").strip()
    try:
        seconds = parse_duration(raw)
    except ValueError as exc:
        print(f"{exc} — mantendo atual.")
        return cfg
    import dataclasses
    if seconds <= 0:
        print("Duração: automática (o conteúdo manda).")
    else:
        print(f"Duração-alvo: {seconds:.0f}s (meta, sem corte).")
    return dataclasses.replace(cfg, duration_target=seconds)


def _progress(idx: int, total: int, label: str, status: str) -> None:
    print(f"  [{idx}/{total}] {label}... {status}", flush=True)


def _show_verify(c: dict[str, str], mp4: str, srt: str, cfg: CurioConfig) -> bool:
    print(f"\n{c['bold']}Verificação do vídeo:{c['reset']}")
    rep = verify_mod.verify_video(mp4, srt, cfg.duration_target, cfg.width, cfg.height)
    for chk in rep.checks:
        mark = f"{c['green']}OK   {c['reset']}" if chk.ok else f"{c['red']}FALHA{c['reset']}"
        extra = f" {c['dim']}— {chk.detail}{c['reset']}" if chk.detail else ""
        print(f"[{mark}] {chk.label}{extra}")
    print(f"\n{c['bold']}{rep.passed}/{rep.total} verificações passaram.{c['reset']}")
    return rep.success


def _project_status(cfg: CurioConfig, slug: str) -> tuple[str, dict]:
    """Retorna (situação legível, metadata)."""
    meta_path = os.path.join(cfg.out_dir, slug, "metadata.json")
    if not os.path.isfile(meta_path):
        return "não encontrado", {}
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except json.JSONDecodeError:
        return "metadados corrompidos", {}
    mode = meta.get("narration", "ai")
    tag = " (roteiro pronto)" if meta.get("mode") == "script" else ""
    if mode == "human-pending":
        return "aguardando sua voz (sem vídeo final ainda)" + tag, meta
    if mode == "human":
        return "vídeo final com SUA voz" + tag, meta
    return "vídeo final pronto (voz de IA)" + tag, meta


# ------------------------------------------------------- configuração avançada
def _show_current_config(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}Configuração atual:{c['reset']}")
    print(f"  Diretório de saída: {cfg.out_dir}")
    print(f"  Cache: {cfg.cache_dir}")
    print(f"  LLM: {cfg.nvidia_model} (base: {cfg.nvidia_base_url})")
    print(f"  OpenRouter: {cfg.openrouter_model} (base: {cfg.openrouter_base_url})")
    print(f"  Gemini: {cfg.gemini_model} (base: {cfg.gemini_base_url})")
    print(f"  Groq: {cfg.groq_model} (base: {cfg.groq_base_url})")
    print(f"  TTS: {cfg.tts_provider} / {cfg.tts_voice} / speed {cfg.tts_speed}")
    print(f"  Render: {cfg.render_backend} / {cfg.render_encoder}")
    print(f"  Mídia providers: {cfg.media_providers}")
    print(f"  Imagens por cena: {cfg.visual_max_images}")
    print(f"  Overlap visual: {cfg.visual_overlap}")
    print(f"  SFX visual: {cfg.visual_sfx}")
    print(f"  Whisper: {cfg.whisper_model}")


def _provider_menu(c: dict[str, str], cfg: CurioConfig, providers: tuple[str, ...],
                   label: str, current: str, env_prefix: str) -> CurioConfig:
    print(f"\n{c['bold']}Selecionar {label} (provedores disponíveis: {', '.join(providers)}, none):{c['reset']}")
    print(f"  Atual: {current}")
    choice = _ask(f"  Novo ({'|'.join(providers)}/none, Enter=pula): ").strip().lower()
    if not choice:
        return cfg
    if choice == "none":
        new_val = "none"
    elif choice in providers:
        new_val = choice
    else:
        print(f"{c['red']}Inválido. Opções: {', '.join(providers)}, none{c['reset']}")
        return cfg
    return dataclasses.replace(cfg, **{f"{env_prefix}_providers": new_val})


def _ask_llm_provider(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    return _provider_menu(c, cfg, LLM_PROVIDERS, "LLM", cfg.nvidia_model, "nvidia_model")


def _ask_media_providers(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    # Para mídia, aceita CSV
    print(f"\n{c['bold']}Providers de mídia (CSV, ex.: pixabay,wikimedia,openverse):{c['reset']}")
    print(f"  Atual: {cfg.media_providers}")
    choice = _ask(f"  Novo (Enter=pula): ").strip().lower()
    if not choice:
        return cfg
    valid = set(MEDIA_PROVIDERS + ("none",))
    chosen = [p.strip() for p in choice.split(",") if p.strip()]
    if all(p in valid for p in chosen):
        return dataclasses.replace(cfg, media_providers=",".join(chosen))
    print(f"{c['red']}Inválido. Use: {', '.join(MEDIA_PROVIDERS)} ou none{c['reset']}")
    return cfg


def _ask_cache_dir(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Diretório de cache (atual: {cfg.cache_dir}):{c['reset']}")
    choice = _ask("  Novo caminho (Enter=pula): ").strip()
    if not choice:
        return cfg
    return dataclasses.replace(cfg, cache_dir=choice)


def _ask_output_dir(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Diretório de saída (atual: {cfg.out_dir}):{c['reset']}")
    choice = _ask("  Novo caminho (Enter=pula): ").strip()
    if not choice:
        return cfg
    return dataclasses.replace(cfg, out_dir=choice)


def _config_flow(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    while True:
        _clear()
        _banner(c)
        _show_current_config(c, cfg)
        print(f"\n{c['bold']}O que ajustar?{c['reset']}")
        print(f"  {c['bold']}1){c['reset']} Provider LLM")
        print(f"  {c['bold']}2){c['reset']} Providers de mídia")
        print(f"  {c['bold']}3){c['reset']} Diretório de cache")
        print(f"  {c['bold']}4){c['reset']} Diretório de saída")
        print(f"  {c['bold']}5){c['reset']} Duração-alvo")
        print(f"  {c['bold']}6){c['reset']} TTS (provider/voz/speed)")
        print(f"  {c['bold']}7){c['reset']} Render (backend/encoder)")
        print(f"  {c['bold']}8){c['reset']} Visual (max_images/overlap/SFX)")
        print(f"  {c['bold']}9){c['reset']} Voltar")
        choice = _ask(f"\n{c['bold']}Escolha [1-9]:{c['reset']} ").strip()
        if choice == "1":
            cfg = _ask_llm_provider(c, cfg)
        elif choice == "2":
            cfg = _ask_media_providers(c, cfg)
        elif choice == "3":
            cfg = _ask_cache_dir(c, cfg)
        elif choice == "4":
            cfg = _ask_output_dir(c, cfg)
        elif choice == "5":
            cfg = _ask_duration(c, cfg)
        elif choice == "6":
            cfg = _ask_tts(c, cfg)
        elif choice == "7":
            cfg = _ask_render(c, cfg)
        elif choice == "8":
            cfg = _ask_visual(c, cfg)
        elif choice == "9":
            return cfg
        else:
            print("Opção inválida.")
        _pause(c)
    return cfg


def _ask_tts(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração TTS:{c['reset']}")
    prov = _ask(f"  Provider [{cfg.tts_provider}]: ").strip()
    if prov:
        cfg = dataclasses.replace(cfg, tts_provider=prov)
    voice = _ask(f"  Voz [{cfg.tts_voice}]: ").strip()
    if voice:
        cfg = dataclasses.replace(cfg, tts_voice=voice)
    speed = _ask(f"  Speed [{cfg.tts_speed}]: ").strip()
    if speed:
        try:
            cfg = dataclasses.replace(cfg, tts_speed=float(speed))
        except ValueError:
            print(f"{c['red']}Speed inválido{c['reset']}")
    return cfg


def _ask_render(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração Render:{c['reset']}")
    backend = _ask(f"  Backend [{cfg.render_backend}] (auto/vaapi/qsv/cpu): ").strip()
    if backend:
        cfg = dataclasses.replace(cfg, render_backend=backend)
    encoder = _ask(f"  Encoder [{cfg.render_encoder}] (ex.: hevc,h264): ").strip()
    if encoder:
        cfg = dataclasses.replace(cfg, render_encoder=encoder)
    return cfg


def _ask_visual(c: dict[str, str], cfg: CurioConfig) -> CurioConfig:
    print(f"\n{c['bold']}Configuração Visual:{c['reset']}")
    mi = _ask(f"  Max images por cena [{cfg.visual_max_images}] (1-5): ").strip()
    if mi:
        try:
            cfg = dataclasses.replace(cfg, visual_max_images=max(1, min(5, int(mi))))
        except ValueError:
            print(f"{c['red']}Inválido{c['reset']}")
    ov = _ask(f"  Overlap cap [{cfg.visual_overlap}] (0-1): ").strip()
    if ov:
        try:
            cfg = dataclasses.replace(cfg, visual_overlap=float(ov))
        except ValueError:
            print(f"{c['red']}Inválido{c['reset']}")
    sfx = _ask(f"  SFX [{cfg.visual_sfx}] (s/n): ").strip().lower()
    if sfx in ("s", "sim", "y", "yes", "true"):
        cfg = dataclasses.replace(cfg, visual_sfx=True)
    elif sfx in ("n", "nao", "no", "false"):
        cfg = dataclasses.replace(cfg, visual_sfx=False)
    return cfg


# ------------------------------------------------------- limpeza
def _clear_cache(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}LIMPAR CACHE{c['reset']}")
    print(f"  Diretório: {cfg.cache_dir}")
    if not os.path.isdir(cfg.cache_dir):
        print(f"  {c['yellow']}Cache não existe.{c['reset']}")
        return
    # Mostra tamanho
    total = 0
    for root, dirs, files in os.walk(cfg.cache_dir):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    print(f"  Tamanho atual: {total / (1024*1024):.1f} MB")
    if _confirm_twice(f"Apagar TODO o cache em {cfg.cache_dir}?"):
        try:
            shutil.rmtree(cfg.cache_dir)
            print(f"{c['green']}Cache removido.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _clear_output(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}LIMPAR PASTA DE SAÍDA{c['reset']}")
    print(f"  Diretório: {cfg.out_dir}")
    if not os.path.isdir(cfg.out_dir):
        print(f"  {c['yellow']}Pasta não existe.{c['reset']}")
        return
    # Conta projetos
    projects = [d for d in os.listdir(cfg.out_dir)
                if os.path.isdir(os.path.join(cfg.out_dir, d))]
    print(f"  Projetos encontrados: {len(projects)}")
    for p in projects:
        print(f"    - {p}")
    if _confirm_twice(f"Apagar TODOS os {len(projects)} projetos em {cfg.out_dir}?", "APAGAR TUDO"):
        try:
            for p in projects:
                shutil.rmtree(os.path.join(cfg.out_dir, p))
            print(f"{c['green']}Pasta de saída limpa.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _clear_project(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    proj_path = os.path.join(cfg.out_dir, slug)
    if not os.path.isdir(proj_path):
        print(f"{c['red']}Projeto '{slug}' não encontrado.{c['reset']}")
        return
    status, meta = _project_status(cfg, slug)
    print(f"  {slug}: {status}")
    if _confirm_twice(f"Apagar projeto '{slug}'?", slug.upper()):
        try:
            shutil.rmtree(proj_path)
            print(f"{c['green']}Projeto removido.{c['reset']}")
        except Exception as exc:
            print(f"{c['red']}Erro: {exc}{c['reset']}")
    else:
        print("Cancelado.")


def _cleanup_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    while True:
        _clear()
        _banner(c)
        print(f"\n{c['bold']}LIMPEZA E MANUTENÇÃO{c['reset']}")
        print(f"  {c['bold']}1){c['reset']} Limpar cache (imagens, fontes)")
        print(f"  {c['bold']}2){c['reset']} Limpar projeto específico")
        red = c['red']
        reset = c['reset']
        print(f"  {c['bold']}3){c['reset']} LIMPAR TUDO (cache + output) — {red}IRREVERSÍVEL{reset}")
        print(f"  {c['bold']}4){c['reset']} Ver tamanho do cache e output")
        print(f"  {c['bold']}5){c['reset']} Voltar")
        choice = _ask(f"\n{c['bold']}Escolha [1-5]:{c['reset']} ").strip()
        if choice == "1":
            _clear_cache(c, cfg)
        elif choice == "2":
            _clear_project(c, cfg)
        elif choice == "3":
            if _confirm_twice(f"{c['red']}APAGAR CACHE + OUTPUT TODOS?{c['reset']}", "SIM APAGUE TUDO"):
                _clear_cache(c, cfg)
                _clear_output(c, cfg)
            else:
                print("Cancelado.")
        elif choice == "4":
            _show_sizes(c, cfg)
        elif choice == "5":
            return
        else:
            print("Opção inválida.")
        _pause(c)


def _show_sizes(c: dict[str, str], cfg: CurioConfig) -> None:
    def _size(path: str) -> float:
        if not os.path.isdir(path):
            return 0.0
        total = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total / (1024 * 1024)
    
    cache_mb = _size(cfg.cache_dir)
    output_mb = _size(cfg.out_dir)
    print(f"\n{c['bold']}Tamanhos:{c['reset']}")
    print(f"  Cache: {cache_mb:.1f} MB ({cfg.cache_dir})")
    print(f"  Output: {output_mb:.1f} MB ({cfg.out_dir})")
    print(f"  Total: {cache_mb + output_mb:.1f} MB")


# ------------------------------------------------------- fila de vídeos
def _queue_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    from .queue import VideoQueue, process_queue
    print(f"\n{c['bold']}FILA DE VÍDEOS — processa várias ideias sequencialmente{c['reset']}")
    print("Cada item vira um projeto independente com pipeline completo.")
    
    queue = VideoQueue()
    
    # Como adicionar itens
    print(f"\n  {c['bold']}1){c['reset']} Adicionar ideias agora (uma por linha, Enter vazio para terminar)")
    print(f"  {c['bold']}2){c['reset']} Carregar de arquivo (.txt, uma ideia por linha)")
    print(f"  {c['bold']}3){c['reset']} Voltar")
    choice = _ask(f"\n{c['bold']}Escolha [1-3]:{c['reset']} ").strip()
    
    if choice == "1":
        print("Digite as ideias (linha vazia = terminar):")
        while True:
            idea = _ask("  > ").strip()
            if not idea:
                break
            queue.add(idea)
        print(f"Adicionados {len(queue.items)} itens.")
    elif choice == "2":
        path = _ask("Caminho do arquivo .txt: ").strip()
        if path and os.path.isfile(path):
            queue.add_from_file(path)
            print(f"Carregados {len(queue.items)} itens.")
        else:
            print(f"{c['red']}Arquivo não encontrado.{c['reset']}")
            return
    else:
        return
    
    if not queue.items:
        print("Fila vazia.")
        return
    
    # Salva fila se quiser
    if _ask("Salvar fila em JSON para retomar depois? [s/N]: ").strip().lower().startswith("s"):
        save_path = _ask(f"Caminho [queue.json]: ").strip() or "queue.json"
        queue.queue_file = save_path
        queue.save(save_path)
        print(f"Fila salva em {save_path}")
    
    # Confirma processamento
    print(f"\n{c['bold']}Fila pronta:{c['reset']}")
    queue.print_status()
    
    if not _ask(f"\nIniciar processamento de {len(queue.items)} vídeos? [S/n]: ").strip().lower().startswith("n"):
        print(f"\nProcessando... (Ctrl+C pausa, itens concluídos são salvos)")
        process_queue(
            queue, cfg, cfg.out_dir,
            on_item_start=lambda item: print(f"\n▶ [{item.slug}] {item.idea}"),
            on_item_complete=lambda item, ok: print(
                f"\n{'✓' if ok else '✗'} [{item.slug}] "
                f"{'OK' if ok else f'ERRO: {item.error}'} ({item.duration_seconds:.1f}s)"
            ),
            on_progress=lambda q: q.print_status(),
        )
    
    print(f"\n{c['bold']}Resultado final:{c['reset']}")
    queue.print_status()


# ---------------------------------------------------------------- ajuda

HELP_TEXT = """\
COMO FUNCIONA — dois jeitos de produzir:

[A] VÍDEO PRONTO (voz de IA)
    Ideia → roteiro → cenas → fotos → narração de IA → legendas → MP4 final.
    Você sai daqui com o vídeo pronto para assistir e publicar.

[B] NARRAR EU MESMO (2 passos — não existe vídeo final no passo 1!)
    Passo 1 — preparar a base: ideia → roteiro → cenas → fotos →
              vídeo SILENCIOSO + TELEPROMPTER (texto grande para ler).
    Passo 2 — você grava sua voz assistindo ao teleprompter (qualquer
              gravador: celular, Audacity...), volta aqui e finaliza:
              a máquina transcreve SUA voz, sincroniza as legendas nela
              e entrega o MP4 final.
    Ou seja: narração humana sem vídeo? Nunca — o vídeo final nasce no
    passo 2, com a sua voz como fonte da sincronia.

ONDE FICAM AS COISAS (pasta output/<projeto>/):
    render/final.mp4          o vídeo final (só existe no fim do fluxo A ou B)
    render/silent.mp4         base silenciosa (passo 1 do fluxo B)
    teleprompter/teleprompter.mp4   o texto grande para você ler gravando
    timeline/visual_timeline.json   fotos por trecho (só no modo roteiro-pronto)
    audio/                    narração da IA ou a SUA voz + transcrição
    metadata.json             tudo sobre o projeto (capítulos, licenças, tempos)

[C] ROTEIRO PRONTO (opção 9 — sem reescrever nada)
    Você entrega o texto final; a máquina divide em trechos, busca fotos
    para cada um e monta a sequência em álbum (fotos entrando umas sobre
    as outras, nunca slides). A narração sai idêntica ao seu texto.

DICAS:
    - Reexecutar sem --force reaproveita o já pronto (rápido e sem custo).
    - Legendas vêm de timestamps reais (voz de IA ou transcrição da sua).
    - Sem internet: voz local simples; sem chave NVIDIA: roteiros locais.
"""


def _help_flow(c: dict[str, str]) -> None:
    print(f"\n{c['bold']}AJUDA{c['reset']}\n")
    print(HELP_TEXT)


# ------------------------------------------------------- fluxo A (IA)

def _ai_flow(c: dict[str, str], cfg: CurioConfig,
             idea: str | None = None, slug: str | None = None,
             force: bool = False) -> None:
    print(f"\n{c['bold']}VÍDEO PRONTO — voz de IA, você sai com o MP4 final.{c['reset']}")
    if idea is None:
        idea = _ask("Ideia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
        if not idea:
            print("Ideia vazia — voltando ao menu.")
            return
        slug = slugify(idea)
        print(f"Pasta do projeto: {cfg.out_dir}/{slug}/")
        cfg = _ask_duration(c, cfg)
        force = _ask("Refazer etapas já concluídas? [s/N]: ").strip().lower().startswith("s")
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=force,
                            narration="ai", on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"]["subtitles"], cfg)


def _quick_test_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    print(f"\n{c['bold']}Teste rápido:{c['reset']} gera o vídeo-exemplo "
          f"{c['yellow']}{QUICK_TEST_IDEA!r}{c['reset']} do zero e verifica tudo.")
    ok = _ask("Continuar? [S/n]: ").strip().lower()
    if ok not in ("", "s", "y", "sim"):
        return
    _ai_flow(c, cfg, idea=QUICK_TEST_IDEA, slug=QUICK_TEST_SLUG, force=True)


# ------------------------------------------------------- fluxo B (humano)

def _human_step1(c: dict[str, str], cfg: CurioConfig) -> str | None:
    print(f"\n{c['bold']}PASSO 1 de 2 — preparar a base (SEM vídeo final ainda).{c['reset']}")
    print("Isso gera: vídeo silencioso + teleprompter para você ler gravando.")
    idea = _ask("Ideia do vídeo (ex.: De onde veio a palavra salário?): ").strip()
    if not idea:
        print("Ideia vazia — voltando ao menu.")
        return None
    slug = slugify(idea)
    print(f"Pasta do projeto: {cfg.out_dir}/{slug}/")
    cfg = _ask_duration(c, cfg)
    try:
        meta = run_pipeline(idea, cfg, slug=slug, force=False,
                            narration="human", on_progress=_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return None
    print(f"\n{c['green']}Base pronta!{c['reset']} (repare: ainda NÃO há vídeo final)")
    print(f"  1. Assista e leia: {meta['artifacts']['teleprompter']}")
    print(f"  2. Grave sua voz (~{meta['duration_actual']}s) com qualquer gravador")
    print(f"  3. Volte aqui → opção 'Passo 2: finalizar com minha voz'")
    from .openers import open_after_teleprompter
    if _ask("\nAbrir a pasta do teleprompter + gravador agora? [S/n]: "
            ).strip().lower() in ("", "s", "y", "sim"):
        for msg in open_after_teleprompter(
                cfg, os.path.dirname(meta['artifacts']['teleprompter']),
                force=True):
            print(f"  {msg}")
    return slug


def _human_step2(c: dict[str, str], cfg: CurioConfig,
                 slug: str | None = None) -> None:
    from .cli import _final_progress
    from .pipeline import finalize_project
    print(f"\n{c['bold']}PASSO 2 de 2 — finalizar com a sua voz (gera o MP4 final).{c['reset']}")
    if slug is None:
        slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" not in status and "final" not in status:
        print(f"{c['red']}Projeto '{slug}': {status}.{c['reset']}")
        print("Rode o passo 1 antes (opção 'Passo 1: preparar a base').")
        return
    audio = _ask("Arquivo de áudio com sua voz (wav/mp3): ").strip()
    if not audio:
        return
    try:
        meta = finalize_project(slug, os.path.expanduser(audio), cfg,
                                on_progress=_final_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s)")
    for w in meta.get("finalize_warnings", []):
        print(f"{c['yellow']}AVISO: {w}{c['reset']}")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"].get(
        "subtitles", os.path.join(cfg.out_dir, slug, "subtitles", "subs.srt")),
        cfg)


def _human_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _human_step1(c, cfg)
    if slug is None:
        return
    if _ask("\nJá tem o áudio gravado e quer finalizar AGORA? [s/N]: "
            ).strip().lower().startswith("s"):
        _human_step2(c, cfg, slug=slug)
    else:
        print("Sem pressa: quando gravar, volte → 'Passo 2: finalizar com minha voz'.")


# ------------------------------------------------------- roteiro pronto

def _script_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    from .pipeline import run_script_pipeline
    from .stages import visual as visual_stage
    print(f"\n{c['bold']}ROTEIRO PRONTO — suas palavras, intocadas; só as fotos mudam."
          f"{c['reset']}")
    print("O texto é usado exatamente como está (narração + legendas).")
    path = _ask("Arquivo .txt com o roteiro: ").strip()
    if not path:
        return
    try:
        script_text = visual_stage.read_script_file(os.path.expanduser(path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"{c['red']}ERRO: {exc}{c['reset']}")
        return
    print(f"Roteiro: {len(script_text)} caracteres, "
          f"{len(script_text.split())} palavras (será preservado).")
    nar = _ask("Narração: [1] voz de IA (vídeo final) / [2] eu mesmo (2 passos)? [1]: "
               ).strip()
    narration = "human" if nar == "2" else "ai"
    cfg = _ask_duration(c, cfg)
    raw_max = _ask(f"Fotos por cena com sobreposição [1-5, padrão "
                   f"{cfg.visual_max_images}]: ").strip()
    if raw_max:
        try:
            import dataclasses
            cfg = dataclasses.replace(
                cfg, visual_max_images=max(1, min(5, int(raw_max))))
        except ValueError:
            print("Valor inválido — mantendo o padrão.")
    try:
        meta = run_script_pipeline(script_text, cfg, narration=narration,
                                   on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 — TUI exibe erro e volta ao menu
        print(f"\n{c['red']}ERRO: {exc}{c['reset']}")
        print("O que já estava pronto foi preservado — tente de novo.")
        return
    if narration == "human":
        print(f"\n{c['green']}Base pronta!{c['reset']} (repare: ainda NÃO há vídeo final)")
        print(f"  1. Assista e leia: {meta['artifacts']['teleprompter']}")
        print(f"  2. Grave sua voz (~{meta['duration_actual']}s) com qualquer gravador")
        print(f"  3. Volte aqui → opção 'Passo 2: finalizar com minha voz'")
        print("Sem pressa: quando gravar, volte → 'Passo 2: finalizar com minha voz'.")
        return
    print(f"\n{c['green']}Pronto!{c['reset']} Vídeo final: {meta['artifacts']['video']} "
          f"({meta['duration_actual']}s em {meta['processing_time_seconds']}s)")
    _show_verify(c, meta["artifacts"]["video"], meta["artifacts"]["subtitles"], cfg)


# ------------------------------------------------------- projetos

def _list_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    if not os.path.isdir(cfg.out_dir):
        print("Nenhum projeto ainda — comece pela opção 1 ou 2.")
        return
    rows = 0
    for entry in sorted(os.listdir(cfg.out_dir)):
        status, meta = _project_status(cfg, entry)
        if not meta and status == "não encontrado":
            continue
        rows += 1
        mark = (c["yellow"] + "○" if "aguardando" in status
                else c["green"] + "●")
        print(f"{mark}{c['reset']} {c['cyan']}{entry}{c['reset']}: {status}")
    if not rows:
        print("Nenhum projeto ainda — comece pela opção 1 ou 2.")


def _verify_flow(c: dict[str, str], cfg: CurioConfig) -> None:
    slug = _ask("Projeto (slug da pasta em output/): ").strip()
    if not slug:
        return
    status, _meta = _project_status(cfg, slug)
    if "aguardando sua voz" in status:
        print(f"'{slug}' ainda não tem vídeo final — finalize primeiro "
              f"(opção 'Passo 2: finalizar com minha voz').")
        return
    paths = video_paths(cfg.out_dir, slug)
    if not os.path.isfile(paths.final_mp4):
        print(f"{c['red']}Projeto '{slug}': {status}; sem MP4 final.{c['reset']}")
        return
    _show_verify(c, paths.final_mp4, paths.subs_srt, cfg)


# ------------------------------------------------------- menu

def run(cfg: CurioConfig | None = None) -> int:
    cfg = cfg or CurioConfig.load()
    c = _colors()
    try:
        while True:
            _clear()
            _banner(c)
            print(f"{c['dim']}O que você quer fazer?{c['reset']}")
            print(f"\n  {c['bold']}QUERO UM VÍDEO PRONTO (voz de IA){c['reset']}")
            print(f"  {c['bold']}1){c['reset']} Criar vídeo com voz de IA")
            print(f"\n  {c['bold']}QUERO NARRAR EU MESMO (2 passos){c['reset']}")
            print(f"  {c['bold']}2){c['reset']} Passo 1: preparar base (silencioso + teleprompter)")
            print(f"  {c['bold']}3){c['reset']} Passo 2: finalizar com minha voz")
            print(f"\n  {c['bold']}ROTEIRO PRONTO (suas palavras){c['reset']}")
            print(f"  {c['bold']}4){c['reset']} Criar vídeo de roteiro pronto (sem reescrever)")
            print(f"\n  {c['bold']}MEUS PROJETOS{c['reset']}")
            print(f"  {c['bold']}5){c['reset']} Listar projetos (com situação)")
            print(f"  {c['bold']}6){c['reset']} Verificar um vídeo")
            print(f"\n  {c['bold']}CONFIGURAÇÃO AVANÇADA{c['reset']}")
            print(f"  {c['bold']}7){c['reset']} Configurar (LLM, mídia, TTS, render, visual, paths)")
            print(f"\n  {c['bold']}LIMPEZA E MANUTENÇÃO{c['reset']}")
            print(f"  {c['bold']}8){c['reset']} Limpeza (cache, projeto, tudo, ver tamanhos)")
            print(f"\n  {c['bold']}FILA DE VÍDEOS{c['reset']}")
            print(f"  {c['bold']}9){c['reset']} Processar fila (várias ideias sequenciais)")
            print(f"\n  {c['bold']}AJUDA E SISTEMA{c['reset']}")
            print(f"  {c['bold']}10){c['reset']} Como funciona (ajuda)")
            print(f"  {c['bold']}11){c['reset']} Teste rápido (gera exemplo e verifica)")
            print(f"  {c['bold']}12){c['reset']} Checar ambiente (doctor)")
            print(f"  {c['bold']}13){c['reset']} Sair")
            choice = _ask(f"\n{c['bold']}Escolha [1-13]:{c['reset']} ").strip()
            if choice == "1":
                _ai_flow(c, cfg)
            elif choice == "2":
                _human_flow(c, cfg)
            elif choice == "3":
                _human_step2(c, cfg)
            elif choice == "4":
                _script_flow(c, cfg)
            elif choice == "5":
                _list_flow(c, cfg)
            elif choice == "6":
                _verify_flow(c, cfg)
            elif choice == "7":
                cfg = _config_flow(c, cfg)
            elif choice == "8":
                _cleanup_flow(c, cfg)
            elif choice == "9":
                _queue_flow(c, cfg)
            elif choice == "10":
                _help_flow(c)
            elif choice == "11":
                _quick_test_flow(c, cfg)
            elif choice == "12":
                from .cli import cmd_doctor
                cmd_doctor(argparse.Namespace(), cfg)
            elif choice == "13":
                print("Até logo!")
                return 0
            else:
                print("Opção inválida.")
            _pause(c)
    except _TUIExit:
        print("\nAté logo!")
        return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
