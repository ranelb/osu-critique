"""Mod canonicalisation for the optional stars/pp blocks (no rosu-pp needed)."""
from __future__ import annotations

from osu_critique.metrics import difficulty as D


def test_sr_mods_collapse_nc_to_dt_and_drop_non_sr_mods():
    assert D.effective_sr_mods("NCDT") == "DT"
    assert D.effective_sr_mods("DT,NC") == "DT"
    assert D.effective_sr_mods("HDHR") == "HR"      # HD does not change SR
    assert D.effective_sr_mods("DTHR") == "DT,HR"   # canonical order
    assert D.effective_sr_mods("") == ""
    assert D.effective_sr_mods(None) == ""


def test_pp_mods_strip_relax_and_autopilot_but_keep_ranked():
    assert D.pp_mods("RXDT") == "DT"                # unranked, rosu-pp rejects it
    assert D.pp_mods("APHDHR") == "HD,HR"
    assert D.pp_mods("NFHT") == "NF,HT"
    assert D.pp_mods("NC") == "DT"                  # canonicalised
    assert D.pp_mods("") == ""


def test_collect_needed_always_includes_nm():
    rows = [{"beatmap_md5": "a" * 32, "mod_string": "DTHR"},
            {"beatmap_md5": "a" * 32, "mod_string": "DT"},
            {"beatmap_md5": "b" * 32, "mod_string": ""}]
    need = D.collect_needed(rows)
    assert need["a" * 32] == {"DT,HR", "DT", ""}
    assert need["b" * 32] == {""}
