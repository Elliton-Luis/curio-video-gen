"""Regressão do caso real: vídeo sobre papel térmico de recibo.

Este é o teste que documenta o defeito reportado. As 23 imagens do vídeo
original eram do Pixabay, e nenhuma era do fenômeno central: entrou usina
termelétrica para "térmico", Catrina (pessoa reconhecível), céu estrelado,
papéis de parede de montanha/rio/campo/deserto ("wallpaper", "4k", "hd"),
flor murcha como metáfora, e uma impressora de fita de transferência
térmica — outra tecnologia.

O que este arquivo garante é que a cena fica VAZIA de fotografia em vez de
errada. Uma cena sem imagem é resolvida por outra estratégia visual
(diagrama, cartão); uma cena com usina termelétrica é misinformation.
"""

import os
from types import SimpleNamespace

import pytest

from curio.media.providers import MediaAsset
from curio.metrics import RunMetrics
from curio.stages import media_rules, scoring
from curio.stages import visual as V
from curio.stages.scenes import Chapter


def _cena_thermal() -> Chapter:
    """A cena do problema: explica o mecanismo do papel térmico."""
    ch = Chapter(
        id=1,
        narration=("O papel térmico funciona assim: o calor da impressora "
                   "altera o corante e a imagem aparece na hora, sem tinta."),
        duration_estimate=8.0,
        visual_queries=["thermal paper receipt", "receipt paper roll"],
        visual_intent="thermal paper receipt",
        visual_type="mechanism",
        subject="thermal receipt paper",
        visual_entities=["receipt", "paper roll", "printed text"],
        context=["cash register"],
        forbidden=["power plant", "wallpaper", "steam", "heat wave"],
    )
    ch.global_visual_queries = list(ch.visual_queries)
    ch.start, ch.end = 0.0, 8.0
    return ch


def _asset(aid, title, provider="pixabay", lic="Licença Pixabay (uso livre)",
           w=1920, h=1280):
    return {"provider": provider, "asset_id": aid, "title": title,
            "license": lic, "license_url": "https://p.io/lic",
            "source_url": f"https://p.io/{aid}",
            "download_url": f"https://p.io/{aid}.jpg",
            "width": w, "height": h, "kind": "image", "local_path": ""}


# --- as imagens que NÃO podem entrar ----------------------------------

# Cada título aqui SAIU no vídeo real. Nenhum pode passar agora — mas cada
# um cai por um motivo diferente, e o motivo importa: é o que o autor lê
# para entender por que a cena ficou sem foto.
#
#   termo proibido da cena ("power plant", "wallpaper", "steam")
#   termo decorativo global ("background", "4k", "template")
#   nota abaixo do mínimo (não é proibido, é que não é do assunto)
_REJECTED_BY_TERM = [
    "power plant cooling towers steam",
    "mountain river wallpaper 4k hd",
    "desert field background 4k",
    "generic stock background template",
]
_REJECTED_BY_SCORE = [
    "thermal power station at dusk",
    "day of the dead catrina woman face",
    "starry night sky galaxy stars",
    "withered flower sunset metaphor",
    "thermal transfer ribbon printer",
]


@pytest.mark.parametrize("titulo", _REJECTED_BY_TERM)
def test_imagem_do_video_original_barrada_por_termo(titulo):
    ch = _cena_thermal()
    why = media_rules.rejection_reason(_asset("x", titulo),
                                       media_rules.scene_blocklist(ch))
    assert why, f"passou indevidamente: {titulo!r}"


@pytest.mark.parametrize("titulo", _REJECTED_BY_SCORE)
def test_imagem_do_video_original_barrada_por_nota(titulo):
    """Não é proibido — é que não fala do assunto. Cai no threshold."""
    ch = _cena_thermal()
    asset = _asset("x", titulo)
    assert media_rules.rejection_reason(asset,
                                        media_rules.scene_blocklist(ch)) == ""
    nota = scoring.base_score(asset, ch)["score"]
    ok, low = scoring.below_threshold([{"score": nota, "asset": asset}])
    assert not ok, f"nota {nota} deixou passar: {titulo!r}"


def test_a_fotografia_certa_da_nota_alta():
    ch = _cena_thermal()
    certo = _asset("ok", "thermal paper receipt roll closeup")
    errado = _asset("bad", "power plant cooling towers")
    assert scoring.base_score(certo, ch)["score"] > 0
    assert (scoring.base_score(certo, ch)["score"]
            > scoring.base_score(errado, ch)["score"])
    assert media_rules.rejection_reason(errado, media_rules.scene_blocklist(ch))


def test_impressora_de_fita_nao_e_o_fenomeno():
    """A fita de transferência é outra tecnologia: não pode ser a cena."""
    ch = _cena_thermal()
    fita = _asset("t", "thermal transfer ribbon printer machine")
    nota = scoring.base_score(fita, ch)["score"]
    ok, _low = scoring.below_threshold([{"score": nota, "asset": fita}])
    assert not ok, "a fita de transferência passou como papel térmico"


# --- a cena precisa de DIAGRAMA, não de foto --------------------------

def test_cena_e_mecanismo_entao_nao_deve_buscar_foto_generica():
    ch = _cena_thermal()
    assert ch.visual_type == "mechanism"
    # O tipo de visual implica bloqueio do "laboratório genérico" que a
    # cachoeira genéricaOffercia antes como último recurso.
    bloqueados = media_rules.scene_forbidden(ch)
    assert any("laborator" in b for b in bloqueados), bloqueados


def test_tipo_historico_bloqueia_foto_moderna():
    ch = Chapter(id=1, narration="São Francisco de Assis no século XIII.",
                 duration_estimate=8.0,
                 visual_type="historical_art", subject="saint francis",
                 visual_entities=["fresco", "monge"])
    bloqueados = media_rules.scene_forbidden(ch)
    assert "modern photo" in bloqueados
    assert "stock photo" in bloqueados
    why = media_rules.rejection_reason(
        _asset("h", "modern photo of a church"), bloqueados)
    assert why


def test_cena_tipografica_bloqueia_foto_de_fundo():
    ch = Chapter(id=1, narration="Salário vem do latim salarium.",
                 duration_estimate=8.0,
                 visual_type="typographic", subject="salarium")
    bloqueados = media_rules.scene_forbidden(ch)
    assert "wallpaper" in bloqueados


# --- decorativos são sempre errados, qualquer que seja a cena --------

@pytest.mark.parametrize("titulo", [
    "wallpaper mountains 4k", "background abstract hd", "4k nature scene",
    "mockup presentation", "logo design template", "banner header web",
    "desktop screensaver", "8k ultra hd photo",
])
def test_decorativo_e_bloqueado_em_qualquer_cena(titulo):
    ch = SimpleNamespace(forbidden=[], visual_type="literal",
                          subject="", visual_entities=[], context=[],
                          narration="", visual_queries=[])
    why = media_rules.rejection_reason(_asset("d", titulo),
                                       media_rules.scene_blocklist(ch))
    assert why, f"decorativo passou: {titulo!r}"


def test_termo_que_e_substring_nao_e_bloqueado():
    """Fronteira de palavra: '4k' não pode derrubar '4Kids' nem 'HDRI'."""
    ch = SimpleNamespace(forbidden=[], visual_type="literal",
                          subject="", visual_entities=[], context=[],
                          narration="", visual_queries=[])
    bloqueados = media_rules.scene_blocklist(ch)
    assert not media_rules.rejection_reason(_asset("k", "4kids cartoon"),
                                            bloqueados)
    assert not media_rules.rejection_reason(_asset("k", "hdri mountain"),
                                            bloqueados)


def test_texto_nao_e_bloqueado_por_si():
    """'text' não está na lista: um recibo, uma placa, um letreiro são
    conteúdo legítimo, e o próprio tema pode ser um texto."""
    ch = SimpleNamespace(forbidden=[], visual_type="literal",
                          subject="", visual_entities=[], context=[],
                          narration="", visual_queries=[])
    assert not media_rules.rejection_reason(
        _asset("t", "printed text on a receipt"), media_rules.scene_blocklist(ch))


def test_titulo_vazio_nao_e_rejeitado_por_filtro_tematico():
    """Sem título não dá para julgar tematicamente; decide o resto."""
    ch = _cena_thermal()
    assert media_rules.rejection_reason(_asset("v", ""),
                                        media_rules.scene_blocklist(ch)) == ""


# --- resolução mínima para 1080x1920 ----------------------------------

def test_resolucao_abaixo_do_piso_e_rejeitada():
    floor = media_rules.min_dimension()
    assert floor == 1080
    pequena = _asset("s", "thermal paper receipt", w=1000, h=2000)
    why = media_rules.passes_hard_filters(pequena,
                                         media_rules.scene_blocklist(_cena_thermal()))
    assert "resolução" in why
    grande = _asset("s", "thermal paper receipt", w=1600, h=2400)
    assert media_rules.passes_hard_filters(grande, []) == ""


def test_asset_com_dimensoes_desconhecidas_passa():
    """NASA não devolve dims; a conferência real é pós-download."""
    a = _asset("n", "thermal paper receipt", w=0, h=0)
    assert media_rules.passes_hard_filters(a, []) == ""


# --- o resultado visível: cena fica vazia, não errada -----------------

def test_cena_sem_foto_boa_recebe_diagrama(tmp_path, monkeypatch):
    """Fluxo completo com um acervo igual ao do vídeo original.

    O resultado NÃO é "cena vazia" nem "usina na tela": é um diagrama
    do mecanismo. A cena mostra o que precisa mostrar do outro jeito.
    """
    from tests.test_media_waterfall import _FakeProv  # noqa: E402
    acervo = [_asset("w1", "power plant cooling towers steam"),
              _asset("w2", "mountain river wallpaper 4k hd"),
              _asset("w3", "day of the dead catrina face"),
              _asset("w4", "starry night sky stars")]
    p1 = _FakeProv("pixabay", [MediaAsset(**a) for a in acervo])
    ch = _cena_thermal()
    m = RunMetrics("s", "idea", "narr")
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="pt-BR")
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [p1], cfg, 2, m, str(tmp_path))
    asset = scenes[0]["asset"]
    assert asset is not None, "a cena ficou sem visual nenhum"
    assert asset["provider"] == "synth", "entrou imagem de banco irrelevante"
    assert "Diagrama" in asset["title"]
    assert os.path.getsize(asset["local_path"]) > 10000
    # as 4 rejeições continuam registradas, com motivo
    assert scenes[0]["rejected"], "o motivo da rejeição não foi registrado"
    motivos = " ".join(r["reason"] for r in scenes[0]["rejected"])
    assert "termo bloqueado" in motivos
    # e as métricas contam a estratégia, sem chamar isso de falha
    assert m.media_visual_types.get("mechanism") == 1
    assert m.media_fallbacks.get("diagram") == 1
    assert m.media_rejections


def test_cena_com_boas_imagens_escolhe_a_mais_proxima(tmp_path, monkeypatch):
    from tests.test_media_waterfall import _FakeProv, _mock_download  # noqa: E402
    _mock_download(monkeypatch, tmp_path)
    acervo = [_asset("g1", "generic abstract background"),
              _asset("g2", "thermal paper receipt roll"),
              _asset("g3", "receipt paper roll closeup")]
    p1 = _FakeProv("pixabay", [MediaAsset(**a) for a in acervo])
    ch = _cena_thermal()
    cfg = SimpleNamespace(cache_dir=str(tmp_path), language="pt-BR")
    scenes, _ = V._search_scene_with_shortcircuit(ch, [p1], cfg, 2, None,
                                                 str(tmp_path))
    escolhidos = [e["asset"]["asset_id"] for e in scenes[0]["assets"]]
    assert "g1" not in escolhidos, "genérica não devia entrar no topo"
    assert "g2" in escolhidos or "g3" in escolhidos
    # e a pontuação é registrada para a folha de contato
    assert all("score" in e for e in scenes[0]["assets"])


# --- cena tipográfica não busca foto -----------------------------------

def test_cena_tipografica_nao_busca_foto(tmp_path, monkeypatch):
    """Critério de aceite 3: uma etimologia não vira fotografia.

    Verificado contra a API real antes deste teste: buscar "salarium"
    aprova "File:Clathurella salarium (MNHN-IM-2000-3235).jpeg" — um
    fungo — e "Navy - Medicine & Surgery - Hospital Ships". Não é falha
    de filtro nem de threshold: é a pergunta errada. A cena É uma palavra,
    então vai direto ao cartão.
    """
    from types import SimpleNamespace
    from curio.config import CurioConfig
    from curio.metrics import RunMetrics
    from curio.stages import visual as V

    ch = SimpleNamespace(
        id=3, narration="A palavra salário vem do latim salarium.",
        visual_queries=["salarium", "roman salt"],
        global_visual_queries=["salarium"],
        visual_type="typographic", subject="salarium",
        visual_entities=["sal", "romano"], context=[], forbidden=[])

    class _Explode:
        name = "nunca-chamado"

        def search(self, *a, **k):
            raise AssertionError("cena tipográfica não pode consultar a rede")

    cfg = CurioConfig()
    cfg.cache_dir = str(tmp_path)
    m = RunMetrics("s", "i", "n")
    scenes, warns = V._search_scene_with_shortcircuit(
        ch, [_Explode()], cfg, 2, m, cfg.cache_dir)

    asset = scenes[0]["asset"]
    assert asset["provider"] == "synth"
    assert "Card" in asset["title"]
    assert scenes[0]["strategy"] == "card"
    assert not warns
    assert m.media_visual_types.get("typographic") == 1
    assert m.media_fallbacks.get("card") == 1


def test_cartao_mostra_a_cadeia_da_etimologia(tmp_path):
    """A cadeia vem das ENTIDADES, não das consultas de busca.

    Repetir "salarium" em corpo pequeno logo abaixo de "SALARIUM" em
    corpo grande parece defeito, e as consultas são o que foi digitado no
    buscador — não a decomposição do sentido.
    """
    from curio.stages import visuals
    ch = Chapter(id=1, duration_estimate=8.0, visual_type="typographic",
                 narration="A palavra salário vem do latim salarium.",
                 subject="salarium", visual_entities=["sal", "romano"],
                 visual_queries=["salarium", "roman salt"], context=[],
                 forbidden=[])
    cadeia = visuals._card_chain(ch)
    assert cadeia == ["sal", "romano"]
    assert "salarium" not in cadeia
    a = visuals.render_card("salarium", ["salarium", "roman salt"],
                            ch.narration, str(tmp_path), "pt-BR", 3, ch=ch)
    assert os.path.getsize(a.local_path) > 10000
