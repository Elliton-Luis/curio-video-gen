#!/usr/bin/env bash
# Teste de fumaça offline: valida a lógica sem rede, sem API e sem custo.
# Rode antes de depurar qualquer falha do pipeline: ./scripts/smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
exec python3 - "$@" <<'EOF'
import sys

passed, failed = 0, []

def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"[OK] {name}")
    else:
        failed.append(name)
        print(f"[FALHA] {name}")

from curio.stages import nvidia as N
from curio.stages import scenes as S
from curio.stages import subs as subs
from curio.pipeline import _relevance
from curio.media.providers import MediaAsset

# 1. Extração de JSON tolerante (a causa do erro das cenas)
check("json puro", N._extract_json('{"a": 1}') == {"a": 1})
check("json com cercas", N._extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("json com preâmbulo/epílogo",
      N._extract_json('Claro! Aqui vai:\n{"a": [1, 2]}\nEspero que ajude.') == {"a": [1, 2]})
try:
    N._extract_json('{"a": 1,')
    check("json truncado rejeitado", False)
except ValueError:
    check("json truncado rejeitado", True)
try:
    N._extract_json('só texto, sem json')
    check("sem json rejeitado", False)
except ValueError:
    check("sem json rejeitado", True)

# 2. Cenas: contagem por duração + validação literal
check("3 cenas p/ 30s", S.scenes_for_duration(30) == 3)
check("5 cenas p/ 45s", S.scenes_for_duration(45) == 5)
check("7 cenas p/ 60s", S.scenes_for_duration(60) == 7)
ch = S._local_chapters("Primeira frase. Segunda frase! Terceira?", 2)
check("divisão local cobre o roteiro",
      " ".join(c.narration for c in ch) == "Primeira frase. Segunda frase! Terceira?")
check("estimativa minima 2.5s", all(c.duration_estimate >= 2.5 for c in ch))

# 3. Legendas a partir de timestamps reais
words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.4}
         for i, t in enumerate("o gato comeu o rato .".split())]
cues = subs.cues_from_words(words)
check("agrupa sem offset artificial", abs(cues[0][0] - 0.0) < 1e-9)
check("blocos curtos", all(len(c[2].split()) <= 5 for c in cues))

# 4. Gate de relevância da mídia
a = MediaAsset(provider="w", asset_id="1", title="USMC-050408 marine photo")
check("título sem nada da consulta zera", _relevance("worker salt wages", a) == 0)
b = MediaAsset(provider="w", asset_id="2", title="Ancient Roman salt coin")
check("título relevante pontua", _relevance("roman salt coin", b) >= 2)

# 5. Métricas (offline, em /tmp)
import tempfile
from curio.metrics import RunMetrics, backfill_from_metadata
tmp = tempfile.mkdtemp()
m = RunMetrics("slug-teste", "ideia", "ai")
m.nvidia("modelo-x", {"prompt_tokens": 10, "completion_tokens": 20})
m.tts("edge-tts", 100)
m.media_search("wikimedia")
m.media_download(500, False)
m.media_download(0, True)
m.whisper("base")
fake_meta = {"title": "T", "duration_target": 45, "duration_actual": 44.0,
             "audio_duration": 43.0, "width": 1080, "height": 1920,
             "script_source": "nvidia:x", "script_chars": 500,
             "scenes_source": "nvidia", "chapters": [{"a": 1}],
             "media": [{"asset": {"x": 1}}, {"asset": None, "reused_from": 1}],
             "subtitle_cues": 10, "subtitle_source": "wordboundary",
             "tts_provider": "edge-tts", "tts_voice": "v",
             "render_backend": "cpu", "render_encoder": "libx264",
             "warnings": [], "artifacts": {}}
path = m.save(fake_meta, {"tts": 1.0}, tmp)
import os as _os, re as _re, json as _json
check("métricas salvas timestamp_slug.json",
      bool(_re.match(r"\d{8}-\d{6}_slug-teste\.json", _os.path.basename(path))))
doc = _json.load(open(path))
check("consumo registrado",
      doc["consumption"]["nvidia"]["calls"] == 1
      and doc["consumption"]["nvidia"]["completion_tokens"] == 20
      and doc["consumption"]["media"]["cache_hits"] == 1
      and doc["consumption"]["whisper"] == {"calls": 1, "model": "base"})
bf = backfill_from_metadata("antigo", fake_meta, tmp)
bfdoc = _json.load(open(bf))
check("backfill marca consumo indisponível",
      bfdoc["source"].startswith("backfill")
      and bfdoc["consumption"]["nvidia"] is None)

# 6. Modo roteiro-pronto (offline: sem rede, sem API, sem ffmpeg)
from curio.stages import visual as V
import tempfile as _tf
with _tf.NamedTemporaryFile("w", suffix=".txt", delete=False,
                             encoding="utf-8") as fh:
    fh.write("  Primeira frase. Segunda frase!  \n")
script = V.read_script_file(fh.name)
check("roteiro lido verbatim (só aparas de borda)",
      script == "Primeira frase. Segunda frase!")
try:
    V.read_script_file(fh.name + ".inexistente")
    check("roteiro inexistente rejeitado", False)
except FileNotFoundError:
    check("roteiro inexistente rejeitado", True)
chapters = S._local_chapters(script, 2)
try:
    V.validate_preserved(script, chapters)
    check("divisão literal validada", True)
except ValueError:
    check("divisão literal validada", False)
import copy as _copy
bad = _copy.deepcopy(chapters)
bad[0].narration = "texto adulterado"
try:
    V.validate_preserved(script, bad)
    check("adulteração detectada", False)
except ValueError:
    check("adulteração detectada", True)
check("cenas p/ roteiro longo acompanham o texto",
      V.scenes_for_script("palavra " * 400, type("C", (), {"duration_target": 45})())
      > S.scenes_for_duration(45))
p1 = V.plan_scene_images(9.0, 1)
check("1 imagem = Ken Burns (plano vazio)", p1 == [])
p3 = V.plan_scene_images(9.0, 3)
check("3 imagens têm sobreposição",
      len(p3) == 3 and p3[1]["start"] < p3[0]["start"] + p3[0]["duration"])
check("transições variam sem repetir",
      [p["transition"] for p in p3] == ["base", "drop_in", "slide_left"])
check("base é tela cheia sem rotação",
      p3[0]["scale"] == 1.0 and p3[0]["rotation_deg"] == 0.0)
p5 = V.plan_scene_images(12.0, 5)
trs = [p["transition"] for p in p5[1:]]
check("4 estilos variados com 5 imagens",
      trs == ["drop_in", "slide_left", "slide_right", "fade"])
check("cena curta encurta a conta em vez de piscar",
      len(V.plan_scene_images(2.0, 5)) < 5)
from curio.stages.scenes import Chapter as _Ch
ch2 = [_Ch(id=1, narration="Olá mundo.", duration_estimate=3.0,
           visual_queries=["hello world"], start=0.0, end=3.0)]
vt = V.build_visual_timeline(ch2, [{"chapter_id": 1, "assets": [],
                                    "reused_from": None}])
check("sem mídia = fallback honesto",
      vt[0]["fallback"] and vt[0]["images"] == []
      and vt[0]["narration"] == "Olá mundo.")
rt = V.retime_visual_timeline(
    [{"chapter_id": 1, "start": 0.0, "end": 3.0, "narration": "x",
      "reused_from": None, "fallback": False,
      "images": [{"order": 0, "query": "q", "duration": 1.0, "start": 0.0,
                  "transition": "base"},
                 {"order": 1, "query": "q", "duration": 1.0, "start": 1.0,
                  "transition": "drop_in"}]}],
    [_Ch(id=1, narration="x", duration_estimate=5.0, start=0.0, end=5.0)])
check("retime preserva ordem/transição e estica tempos",
      rt[0]["end"] == 5.0 and rt[0]["images"][1]["transition"] == "drop_in"
      and rt[0]["images"][1]["query"] == "q")
lq = V.local_queries("As legiões na fronteira defendiam Roma dos bárbaros.")
check("consultas offline traduzem o contexto",
      any("roman" in q or "rome" in q for q in lq)
      and any("frontier" in q or "barbarian" in q for q in lq))
check("stopwords não viram consulta",
      all("para" not in q.split() and "como" not in q.split() for q in
          V.local_queries("Para como isso era muito sobre tudo.")))
lq2 = V.local_queries("Não foi um dia, nem uma batalha. Foi o império.")
check("início de frase não vira entidade",
      all("não" not in q.split() and "foi" not in q.split() for q in lq2))
one, used = V._spec_images([{"query": "rome", "asset": {"asset_id": "1",
                          "local_path": "/x.jpg"}}], 5.0)
check("1 imagem vira base (Ken Burns, sem fallback)",
      len(one) == 1 and one[0]["transition"] == "base"
      and one[0]["duration"] == 5.0 and used == 0
      and one[0]["sfx"] is None)
check("zero imagens = fallback",
      V._spec_images([], 5.0) == ([], 0))

# 8. Variedade global + SFX (sem repetição consecutiva, ~1/3 com som)
def _fake_media(n_chapters, per):
    chs, med = [], []
    for i in range(n_chapters):
        chs.append(_Ch(id=i + 1, narration=f"Trecho {i + 1} sobre Roma.",
                       duration_estimate=9.0, start=float(i * 9),
                       end=float((i + 1) * 9)))
        med.append({"chapter_id": i + 1, "reused_from": None,
                    "assets": [{"query": "rome",
                                "asset": {"asset_id": f"{i}-{k}",
                                          "local_path": f"/tmp/{i}-{k}.jpg"}}
                               for k in range(per)]})
    return chs, med

_chs8, _med8 = _fake_media(3, 3)
_vt8 = V.build_visual_timeline(_chs8, _med8, seed="slug-teste", sfx=True)
_seq8 = [i["transition"] for t in _vt8 for i in t["images"] if i["order"] > 0]
check("inserções consecutivas nunca repetem (3 cenas)",
      len(_seq8) == 6 and all(a != b for a, b in zip(_seq8, _seq8[1:])))
check("6 overlays cobrem os 6 estilos",
      set(_seq8) == set(V.ENTRY_STYLES))
_sfx8 = [(t["chapter_id"], i["sfx"]) for t in _vt8 for i in t["images"]
         if isinstance(i.get("sfx"), dict)]
check("SFX em algumas inserções, nunca em todas",
      0 < len(_sfx8) < len(_seq8))
check("SFX dentro da cena e tipos alternados",
      all(_vt8[c - 1]["start"] <= s["at"] <= _vt8[c - 1]["end"]
          for c, s in _sfx8)
      and [s["kind"] for _, s in _sfx8] == ["swish", "tap"])
check("base nunca tem SFX",
      all(i["sfx"] is None for t in _vt8 for i in t["images"]
          if i["order"] == 0))
_vt8_nosfx = V.build_visual_timeline(_chs8, _med8, seed="slug-teste",
                                     sfx=False)
check("sfx=False desliga tudo",
      all(i.get("sfx") is None for t in _vt8_nosfx for i in t["images"]))
_rt8 = V.retime_visual_timeline(
    _vt8, [_Ch(id=c.id, narration=c.narration, duration_estimate=12.0,
               start=c.start, end=c.start + 12.0) for c in _chs8])
_rt8_seq = [i["transition"] for t in _rt8 for i in t["images"]
            if i["order"] > 0]
_rt8_sfx = [(i["sfx"]["kind"], i["sfx"]["at"]) for t in _rt8
            for i in t["images"] if isinstance(i.get("sfx"), dict)]
_old_at = [s["at"] for _, s in _sfx8]
check("retime mantém transições e SFX (só move tempos)",
      _rt8_seq == _seq8
      and [k for k, _ in _rt8_sfx] == [s["kind"] for _, s in _sfx8]
      and all(at not in _old_at for _, at in _rt8_sfx)
      and all(0.0 <= at <= 36.0 for _, at in _rt8_sfx))

# 7. LLM: 5 tentativas + fallback OpenRouter (offline, urlopen simulado)
import io as _io
import socket as _sock
import urllib.error as _urlerr
import urllib.request as _urlreq
_real_urlopen, _real_sleep = _urlreq.urlopen, N.time.sleep
N.time.sleep = lambda s: None  # backoff sem espera no teste
_calls = {"n": 0}
_BEHAVIOR = {"mode": "ok-after-2"}


def _fake_urlopen(req, timeout=None):
    _calls["n"] += 1
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if _BEHAVIOR["mode"] == "timeout-always":
        raise _sock.timeout("timed out")
    if _BEHAVIOR["mode"] == "unauthorized":
        raise _urlerr.HTTPError(url, 401, "Unauthorized", {},
                                _io.BytesIO(b'{"error":"bad key"}'))
    if _BEHAVIOR["mode"] == "ok-after-2" and _calls["n"] < 3:
        raise _sock.timeout("timed out")
    if "openrouter" in url and _BEHAVIOR["mode"] == "nvidia-down":
        body = {"choices": [{"message": {"content": "roteiro via fallback"},
                             "finish_reason": "stop"}]}
        return _io.BytesIO(_json.dumps(body).encode())
    if "openrouter" not in url and _BEHAVIOR["mode"] == "nvidia-down":
        raise _sock.timeout("timed out")
    body = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    return _io.BytesIO(_json.dumps(body).encode())


_urlreq.urlopen = _fake_urlopen
_saved_env = {k: _os.environ.get(k) for k in
              ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "CURIO_LLM_ATTEMPTS")}
_os.environ["NVIDIA_API_KEY"] = "fake-nvidia"
_os.environ["OPENROUTER_API_KEY"] = "fake-or"
_os.environ["CURIO_LLM_ATTEMPTS"] = "5"
try:
    _calls["n"] = 0
    _BEHAVIOR["mode"] = "ok-after-2"
    N._post_with_retries([], "k", "m", "https://x", 5, 10, 0.1,
                         "NVIDIA", "NVIDIA_API_KEY")
    check("retry: 2 timeouts + sucesso na 3ª", _calls["n"] == 3)
    _calls["n"] = 0
    _BEHAVIOR["mode"] = "unauthorized"
    try:
        N._post_with_retries([], "k", "m", "https://x", 5, 10, 0.1,
                             "NVIDIA", "NVIDIA_API_KEY")
        check("401 não repete", False)
    except N.NvidiaError:
        check("401 não repete", _calls["n"] == 1)
    _calls["n"] = 0
    _BEHAVIOR["mode"] = "timeout-always"
    _os.environ["CURIO_LLM_ATTEMPTS"] = "3"
    try:
        N._post_with_retries([], "k", "m", "https://x", 5, 10, 0.1,
                             "NVIDIA", "NVIDIA_API_KEY")
        check("esgotamento levanta com contagem", False)
    except N.NvidiaError as exc:
        check("esgotamento levanta com contagem",
              _calls["n"] == 3 and "após 3 tentativas" in str(exc))
    _os.environ["CURIO_LLM_ATTEMPTS"] = "5"
    _calls["n"] = 0
    _BEHAVIOR["mode"] = "nvidia-down"
    body, label = N._chat([{"role": "user", "content": "oi"}], 50, 0.1,
                          "nv-model", "https://nv.local/v1", 5,
                          "or-model", "https://openrouter.local/api/v1")
    check("fallback OpenRouter assume após NVIDIA cair",
          label == "openrouter:or-model"
          and body["choices"][0]["message"]["content"] == "roteiro via fallback"
          and _calls["n"] == 5 + 1)
    del _os.environ["OPENROUTER_API_KEY"]
    _calls["n"] = 0
    try:
        N._chat([{"role": "user", "content": "oi"}], 50, 0.1,
                "nv-model", "https://nv.local/v1", 5)
        check("sem fallback: erro explica OPENROUTER_API_KEY", False)
    except N.NvidiaError as exc:
        check("sem fallback: erro explica OPENROUTER_API_KEY",
              "OPENROUTER_API_KEY" in str(exc) and "NVIDIA" in str(exc))
finally:
    _urlreq.urlopen = _real_urlopen
    N.time.sleep = _real_sleep
    for k, v in _saved_env.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v

print(f"\n{passed} passaram, {len(failed)} falharam.")
sys.exit(1 if failed else 0)
EOF
