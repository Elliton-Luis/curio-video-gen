"""UX do seletor vertical de gênero, sem alterar os perfis editoriais."""

from curio import tui
from curio.config import CurioConfig
from curio.stages import editorial


def _colors():
    return {key: "" for key in ("dim", "bold", "cyan", "yellow", "reset")}


def test_seletor_de_genero_repassa_todos_os_nomes_e_metadados(monkeypatch):
    expected = editorial.choices()
    captured = {}

    def choose(_colors, title, options, **kwargs):
        captured.update(title=title, options=options, kwargs=kwargs)
        return len(options) - 1

    monkeypatch.setattr(tui, "select_option", choose)
    cfg = CurioConfig(genre="people")
    result = tui._ask_genre(_colors(), cfg)

    assert captured["title"] == "GÊNERO DO VÍDEO"
    assert captured["options"] == [label for _key, label in expected]
    assert captured["kwargs"]["selected"] == next(
        i for i, (key, _label) in enumerate(expected) if key == "people")
    assert captured["kwargs"]["fit_labels"] is True
    assert captured["kwargs"]["footer"] == "↑ ↓ selecionar   Enter confirmar   Esc voltar"
    details = captured["kwargs"]["details_for"]
    profile = editorial.get(expected[-1][0])
    assert details(len(expected) - 1) == [
        profile.description,
        f"ritmo {profile.pacing.target_scene_seconds:g}s/cena · "
        f"densidade {profile.pacing.information_density} · "
        f"legenda {profile.pacing.caption_max_words} palavras",
    ]
    assert result.genre == expected[-1][0]


def test_lista_vertical_atualiza_detalhes_com_up_down_e_enter(monkeypatch):
    options = [label for _key, label in editorial.choices()]
    details_seen = []
    selected_seen = []
    keys = iter(("down", "down", "up", "enter"))

    def fake_render(_c, _title, _options, selected, _status, details,
                    **_kwargs):
        selected_seen.append(selected)
        details_seen.append(details)

    monkeypatch.setattr(tui, "_interactive_supported", lambda: True)
    monkeypatch.setattr(tui, "_render_menu", fake_render)
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    result = tui.select_option(
        _colors(), "GÊNERO DO VÍDEO", options, selected=1,
        details_for=lambda i: [f"descrição {i}", f"ritmo {i}"])

    assert selected_seen == [1, 2, 3, 2]
    assert details_seen == [["descrição 1", "ritmo 1"],
                            ["descrição 2", "ritmo 2"],
                            ["descrição 3", "ritmo 3"],
                            ["descrição 2", "ritmo 2"]]
    assert result == 2


def test_lista_vertical_esc_volta_sem_confirmar(monkeypatch):
    monkeypatch.setattr(tui, "_interactive_supported", lambda: True)
    monkeypatch.setattr(tui, "_render_menu", lambda *_a, **_kw: None)
    monkeypatch.setattr(tui, "_read_key", lambda: "esc")
    assert tui.select_option(_colors(), "GÊNERO DO VÍDEO", ["people"]) is None


def test_lista_nao_trunca_nomes_nem_descricao(capsys, monkeypatch):
    monkeypatch.setattr(tui, "_clear", lambda: None)
    label = "Mitologia e folclore — tradições e narrativas antigas"
    description = "A trajetória de uma pessoa e por que a vida dela importa."
    tui._render_menu(
        _colors(), "GÊNERO DO VÍDEO", [label], 0,
        details=[description, "ritmo 13s/cena · densidade medium · legenda 6 palavras"],
        fit_labels=True, footer="↑ ↓ selecionar   Enter confirmar   Esc voltar")
    output = capsys.readouterr().out
    assert label in output
    metrics = "ritmo 13s/cena · densidade medium · legenda 6 palavras"
    width = max(46, len("GÊNERO DO VÍDEO") + 4, len(label) + 7,
                len("↑ ↓ selecionar   Enter confirmar   Esc voltar") + 2)
    assert all(line in output for line in tui._wrap_text(description, width - 4))
    assert all(line in output for line in tui._wrap_text(metrics, width - 4))
    assert "…" not in output
    assert "›" in output
