# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
#      http://www.apache.org/licenses/LICENSE-2.0
"""Run times in the person's own time zone: the WSL distro's clock is UTC
while Windows shows local time, so the browser's offset names the runs and
every timestamp the UI formats carries its offset."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from lanex.controller import platform_env


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(platform_env, "_client_utc_offset_min", None)


def test_the_browsers_offset_names_the_run(tmp_path):
    platform_env.note_client_utc_offset("330")          # India, +05:30
    tag = platform_env.new_run_tag(tmp_path)
    assert re.fullmatch(r"glui-\d{8}-\d{6}", tag)
    want = datetime.now(timezone(timedelta(minutes=330)))
    got = datetime.strptime(tag[5:], "%Y%m%d-%H%M%S").replace(tzinfo=want.tzinfo)
    assert abs((want - got).total_seconds()) < 5


def test_a_taken_name_gets_a_suffix(tmp_path):
    first = platform_env.new_run_tag(tmp_path)
    (tmp_path / first).mkdir()
    second = platform_env.new_run_tag(tmp_path)
    assert second != first and second.startswith(first[:18])


@pytest.mark.parametrize("bad", ["", "abc", "100000", None, "-9999"])
def test_nonsense_offsets_are_ignored(bad):
    platform_env.note_client_utc_offset(bad)
    assert platform_env._client_utc_offset_min is None


def test_timestamps_carry_their_offset():
    s = platform_env.iso_from_epoch(1_700_000_000)
    d = datetime.fromisoformat(s)
    assert d.tzinfo is not None and d.timestamp() == 1_700_000_000
