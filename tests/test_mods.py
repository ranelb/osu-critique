"""Mods that change geometry and judgement are applied, not ignored.

Hard Rock raises OD/AR (x1.4, cap 10) and CS (x1.3, cap 10) and reflects the
playfield vertically (lazer: OsuModHardRock -> ReflectVerticallyAlongPlayfield);
Easy halves OD/AR/CS. All of that changes both the hit windows and where the
player's cursor has to be.
"""
from osu_critique.io.beatmap import (PLAYFIELD_HEIGHT, build_objects,
                                     circle_radius, load_beatmap, od_windows,
                                     mod_string)
from osu_critique.report import analyze

MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"

_MOD_NAMES = frozenset({"double_time", "half_time", "hard_rock", "easy", "hidden",
                        "flashlight", "no_fail", "relax", "auto_pilot"})


class _ModReplay:
    """Delegating proxy: the fixture replay, seen with different mod flags."""

    def __init__(self, inner, **mods):
        object.__setattr__(self, "_inner", inner)
        for name in _MOD_NAMES:
            object.__setattr__(self, name, bool(mods.get(name, False)))

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name in _MOD_NAMES:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _mods(**overrides):
    base = dict(double_time=False, half_time=False, hidden=False, hard_rock=False,
                easy=False, flashlight=False, no_fail=False, relax=False,
                auto_pilot=False)
    base.update(overrides)
    return base


def test_hard_rock_reflects_the_playfield_vertically():
    bm = load_beatmap(MAP)
    plain = build_objects(bm, 1.0, hard_rock=False)
    hr = build_objects(bm, 1.0, hard_rock=True)
    assert len(plain) == len(hr) > 0
    assert [o["x"] for o in hr] == [o["x"] for o in plain]          # x untouched
    assert [o["y"] for o in hr] == [PLAYFIELD_HEIGHT - o["y"] for o in plain]
    assert [o["t"] for o in hr] == [o["t"] for o in plain]


def test_windows_and_radius_follow_the_mods():
    bm = load_beatmap(MAP)
    w300 = lambda od: od_windows(od, 1.0)[0]
    assert w300(bm.od(hard_rock=True)) < w300(bm.od()) < w300(bm.od(easy=True))
    assert (circle_radius(bm.cs(hard_rock=True)) < circle_radius(bm.cs())
            < circle_radius(bm.cs(easy=True)))


def test_mod_string():
    assert mod_string(_Stub(**_mods(double_time=True, hidden=True))) == "DT+HD"
    assert mod_string(_Stub(**_mods())) == "NM"
    assert mod_string(_Stub(**_mods(relax=True))) == "RX"


def test_hr_analysis_judges_against_the_reflected_map(monkeypatch, tmp_path):
    import osu_critique.report as report_mod
    from osu_critique.io.replay import load_replay as real_load

    plain = report_mod.analyze(REPLAY, MAP, tag="nm", outdir=str(tmp_path),
                               console=False)

    def hr_load(path):
        return _ModReplay(real_load(path), hard_rock=True)

    monkeypatch.setattr(report_mod, "load_replay", hr_load)
    hr = report_mod.analyze(REPLAY, MAP, tag="hr", outdir=str(tmp_path),
                            console=False)

    assert hr["mods"]["HR"] is True and hr["mod_string"] == "HR"
    assert hr["difficulty"]["OD"] > plain["difficulty"]["OD"]
    assert hr["difficulty"]["CS"] > plain["difficulty"]["CS"]
    assert hr["spacing_radius"] < plain["spacing_radius"]
    # tighter windows can only downgrade judgements, never upgrade them
    assert hr["counts_detected"]["300"] <= plain["counts_detected"]["300"]
    # the fixture's cursor never saw a reflected map, so aim error explodes --
    # which is the point: we now measure against the map the player saw
    assert hr["aim_px"]["mean_norm"] > plain["aim_px"]["mean_norm"]
