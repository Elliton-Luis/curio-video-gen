"""CLI da biblioteca: update explícito, listagem offline e modos de geração."""

from curio.cli import build_parser, main
from curio.config import CurioConfig


def test_generate_accepts_audio_modes_and_manual_file():
    args = build_parser().parse_args([
        "generate", "test topic", "--music-mode", "manual",
        "--music-file", "theme.mp3",
    ])
    assert args.music_mode == "manual"
    assert args.music_file == "theme.mp3"


def test_music_update_is_explicit_and_reports_missing_freesound_key(
        tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "library")
    monkeypatch.setattr("curio.cli.CurioConfig.load", lambda _path=None: cfg)
    result = main(["music", "update", "--genre", "people"])
    assert result == 1
    assert "FREESOUND_API_KEY" in capsys.readouterr().err


def test_music_list_is_offline_and_empty_library_is_valid(tmp_path, monkeypatch,
                                                           capsys):
    cfg = CurioConfig()
    cfg.audio_library_dir = str(tmp_path / "library")
    monkeypatch.setattr("curio.cli.CurioConfig.load", lambda _path=None: cfg)
    assert main(["music", "list", "--genre", "people"]) == 0
    assert "people: música 0/10" in capsys.readouterr().out
    assert (tmp_path / "library/music/people").is_dir()
