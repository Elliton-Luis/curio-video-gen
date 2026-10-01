"""Costura FFmpeg de música baixa, ducking, SFX local e transições."""

import math
import shutil
import struct
import subprocess

import pytest

from curio.config import CurioConfig
from curio.stages import render as R


def test_burn_final_mixes_music_low_and_sidechains_voice(tmp_path, monkeypatch):
    silent = tmp_path / "silent.mp4"
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.mp3"
    for p in (silent, voice, music):
        p.write_bytes(b"fixture")
    commands = []
    monkeypatch.setattr(R.ff, "require_tools", lambda: None)
    monkeypatch.setattr(R, "_video_codec_args",
                        lambda _cfg: ("cpu", "libx264", ["-c:v", "libx264"]))
    monkeypatch.setattr(R.ff, "run", lambda cmd: (commands.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "", "")))
    monkeypatch.setattr(R.ff, "probe_duration", lambda _path: 5.0)
    out = tmp_path / "final.mp4"
    cfg = CurioConfig()
    cfg.render_backend = "cpu"
    R.burn_final(str(silent), None, str(voice), str(out), cfg, 5.0,
                 music_path=str(music), music_gain_db=-15,
                 music_ducking=True, final_fade=0.6)
    cmd = commands[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=-15.0dB" in graph
    assert "sidechaincompress=" in graph
    assert "release=1100" in graph
    assert "-shortest" in cmd
    assert "fade=t=out:st=4.400:d=0.600" in cmd[cmd.index("-vf") + 1]


def test_existing_voice_only_mix_keeps_padding_and_no_music_graph(tmp_path, monkeypatch):
    silent, voice = tmp_path / "silent.mp4", tmp_path / "voice.wav"
    silent.write_bytes(b"fixture")
    voice.write_bytes(b"fixture")
    commands = []
    monkeypatch.setattr(R.ff, "require_tools", lambda: None)
    monkeypatch.setattr(R, "_video_codec_args",
                        lambda _cfg: ("cpu", "libx264", ["-c:v", "libx264"]))
    monkeypatch.setattr(R.ff, "run", lambda cmd: (commands.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "", "")))
    monkeypatch.setattr(R.ff, "probe_duration", lambda _path: 5.0)
    R.burn_final(str(silent), None, str(voice), str(tmp_path / "out.mp4"),
                 CurioConfig(), 5.0)
    cmd = commands[0]
    assert "-filter_complex" not in cmd
    assert any("apad=whole_dur=5.0" in part for part in cmd)
    assert "-shortest" not in cmd


def test_build_sfx_track_uses_local_audio_asset(tmp_path, monkeypatch):
    asset = tmp_path / "paper.mp3"
    asset.write_bytes(b"fixture")
    commands = []
    monkeypatch.setattr(R.ff, "run", lambda cmd: (commands.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "", "")))
    result = R.build_sfx_track([{
        "kind": "swish", "at": 1.25, "duration": 0.4,
        "gain_db": -32, "path": str(asset),
    }], 4.0, str(tmp_path / "sfx.wav"))
    assert result.endswith("sfx.wav")
    cmd = commands[0]
    assert str(asset) in cmd
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=-32.0dB" in graph
    assert "adelay=1250|1250" in graph


def test_default_music_gain_is_audible_under_ducking():
    assert CurioConfig().music_gain_db == -15


def test_genre_transition_plan_distinguishes_genres_and_scene_roles():
    from curio.pipeline import _final_audio_fade, _genre_transitions
    from curio.stages.scenes import Chapter
    chapters = [
        Chapter(id=1, narration="context", duration_estimate=3),
        Chapter(id=2, narration="a quote", duration_estimate=3,
                text_role="quote", visual_type="typographic"),
        Chapter(id=3, narration="na verdade, revelou a descoberta", duration_estimate=3),
    ]
    people = _genre_transitions(chapters, "people")
    science = _genre_transitions(chapters, "science")
    assert people[0] > science[0]
    assert people[1] > people[0]
    assert _genre_transitions(chapters, "people", "none") == [0.0, 0.0]
    assert _final_audio_fade("people") > _final_audio_fade("science")


def test_genre_transition_kinds_vary_effect_without_changing_lengths():
    from curio.pipeline import _genre_transition_kinds
    from curio.stages.scenes import Chapter
    chapters = [Chapter(id=1, narration="a", duration_estimate=3),
                Chapter(id=2, narration="b", duration_estimate=3)]
    assert _genre_transition_kinds(chapters, "mystery") == ["fadeblack"]
    assert _genre_transition_kinds(chapters, "science") == ["slideright"]
    assert _genre_transition_kinds(chapters, "people") == ["fade"]
    assert _genre_transition_kinds(chapters, "people", "none") == ["fade"]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg/ffprobe ausentes")
def test_cross_dissolve_preserves_full_scene_duration(tmp_path):
    cfg = CurioConfig()
    cfg.render_backend = "cpu"
    cfg.width, cfg.height, cfg.fps = 96, 96, 10
    clips = []
    for idx, color in enumerate(("red", "blue")):
        path = tmp_path / f"{idx}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"color=c={color}:s=96x96:r=10:d=1", "-an", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(path)], check=True)
        clips.append(str(path))
    out = tmp_path / "joined.mp4"
    R.concat_with_transitions(clips, str(out), cfg, [0.2])
    assert R.ff.probe_duration(str(out)) == pytest.approx(2.0, abs=0.12)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg/ffprobe ausentes")
def test_ducking_reduces_music_during_voice_and_returns_in_pause(tmp_path):
    video, voice, music = (tmp_path / "silent.mp4", tmp_path / "voice.wav",
                           tmp_path / "music.wav")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=black:s=96x96:r=24:d=4", "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(video)], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=220:sample_rate=48000:duration=2",
        "-f", "lavfi", "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000:d=2",
        "-filter_complex", "[0:a]volume=0.8[v];[v][1:a]concat=n=2:v=0:a=1[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", str(voice)], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=48000:duration=4,volume=0.8",
        "-c:a", "pcm_s16le", str(music)], check=True)

    cfg = CurioConfig()
    cfg.render_backend = "cpu"
    outputs = {}
    for ducking in (True, False):
        target = tmp_path / f"duck-{ducking}.mp4"
        R.burn_final(str(video), None, str(voice), str(target), cfg, 4.0,
                     music_path=str(music), music_gain_db=-12,
                     music_ducking=ducking)
        raw = subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(target), "-map", "0:a:0",
            "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
            check=True, capture_output=True).stdout
        samples = struct.unpack(f"{len(raw) // 4}f", raw)

        def tone_amplitude(start, end, hz=880):
            values = samples[int(start * 48000):int(end * 48000)]
            real = sum(x * math.cos(2 * math.pi * hz * i / 48000)
                       for i, x in enumerate(values))
            imag = sum(x * math.sin(2 * math.pi * hz * i / 48000)
                       for i, x in enumerate(values))
            return 2 * (real * real + imag * imag) ** 0.5 / max(1, len(values))

        outputs[ducking] = (
            tone_amplitude(1.0, 1.8), tone_amplitude(2.5, 3.3),
            tone_amplitude(1.0, 1.8, 220))
    ducked_active, ducked_pause, voice_active = outputs[True]
    open_active, open_pause, _voice_open = outputs[False]
    assert ducked_active < ducked_pause * 0.8
    assert open_active == pytest.approx(open_pause, rel=0.15)
    assert voice_active > ducked_active
