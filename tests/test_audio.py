import sys
import time
import wave

from theempire import audio
from theempire.game import Event, Game
from theempire.ui import pick_sound
from theempire.world import load_world


def test_generate_every_sound(tmp_path):
    audio.generate(tmp_path)
    for name in audio._SFX_NAMES + audio._MUSIC_NAMES:
        with wave.open(str(tmp_path / f"{name}.wav")) as w:
            assert w.getframerate() == audio.RATE and w.getnframes() > audio.RATE // 4


def fake_player(tmp_path):
    log = tmp_path / "played.txt"
    script = tmp_path / "player.py"
    script.write_text("import sys, time\n"
                      f"open({str(log)!r}, 'a').write(sys.argv[-1].rsplit('/', 1)[-1] + '\\n')\n"
                      "time.sleep(0.2)\n")
    return [sys.executable, str(script)], log


def wait_for(check, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.1)
    return False


def test_effects_and_looping_music(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "SETTINGS", tmp_path / "settings.json")
    player, log = fake_player(tmp_path)
    a = audio.Audio(mode="all", cache=tmp_path / "snd")
    a.player = player
    assert a.ready.wait(30)
    a.sfx("battle")
    a.music("war")
    # The march loops: it is started again after it ends.
    assert wait_for(lambda: log.exists() and log.read_text().count("war.wav") >= 2)
    assert "battle.wav" in log.read_text()
    a.select_music("off")
    played = log.read_text().count("war.wav")
    time.sleep(0.8)
    assert log.read_text().count("war.wav") == played  # music stopped
    a.toggle_effects()  # effects off
    a.sfx("nuke")
    time.sleep(0.4)
    assert "nuke.wav" not in log.read_text()
    a.close()


def test_cossack_loops_when_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "SETTINGS", tmp_path / "settings.json")
    player, log = fake_player(tmp_path)
    a = audio.Audio(mode="all", cache=tmp_path / "snd")
    a.player = player
    assert a.ready.wait(30)
    a.select_music("cossack")
    assert wait_for(lambda: log.exists() and log.read_text().count("cossack.wav") >= 2)
    a.close()


def test_music_choice_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "SETTINGS", tmp_path / "settings.json")
    a = audio.Audio(cache=tmp_path / "snd")
    a.select_music("cossack")
    assert audio.load_music() == "cossack"
    a.toggle_effects()
    assert audio.load_effects() is False
    a.close()


def test_legacy_audio_mode_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "SETTINGS", tmp_path / "settings.json")
    audio.SETTINGS.write_text('{"audio": "sfx"}')
    assert audio.load_music() == "off"
    assert audio.load_effects() is True
    audio.SETTINGS.write_text('{"audio": "off"}')
    assert audio.load_music() == "off"
    assert audio.load_effects() is False
    audio.SETTINGS.write_text('{"audio": "all"}')
    assert audio.load_music() == "auto"
    assert audio.load_effects() is True


def test_bell_without_player(tmp_path):
    rings = []
    a = audio.Audio(mode="all", cache=tmp_path / "snd", bell=lambda: rings.append(1))
    a.player = None
    a.sfx("nuke")
    a.sfx("battle")      # minor events do not ring
    assert rings == [1]
    a.close()


def test_pick_sound_point_of_view():
    g = Game("coldwar", humans=("nato",), seed=1, world=load_world())
    nato, pact = g.factions[0].name, g.factions[1].name
    ours = Event(1, f"{nato} conquista Kiev (prima: {pact}).", None, "alert", "capture", 0)
    theirs = Event(1, f"{pact} conquista Berlin (prima: {nato}).", None, "alert", "capture", 1)
    far = Event(1, f"{pact} conquista Lagos (prima: Neutrali).", None, "info", "capture", 1)
    boom = Event(1, "☢ ...", None, "wmd", "nuke", 1)
    assert pick_sound(g, 0, [ours]) == "capture"
    assert pick_sound(g, 0, [theirs]) == "loss"
    assert pick_sound(g, 0, [far]) is None
    assert pick_sound(g, 0, [ours, boom, theirs]) == "nuke"
