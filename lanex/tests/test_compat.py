# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Canary tests for the librelane compatibility layer (H4/I2).

These fail on the exact librelane release that breaks a private-API touchpoint
LanEx relies on (FlowProgressBar patch, Flow.factory, variable introspection),
pointing at the seam BEFORE a user hits a cryptic mid-run failure. They run
against the *installed* librelane, so CI's version matrix exercises them for
real."""
from __future__ import annotations

from lanex.controller import compat


def test_version_and_availability() -> None:
    assert compat.is_available()
    assert compat.get_version() not in ("", "unknown")


def test_probe_passes_on_the_installed_librelane() -> None:
    probe = compat.probe_compat()
    # If this fails, one of LanEx's private-API assumptions broke against the
    # installed librelane — the message names which touchpoint.
    assert probe["ok"], probe["issues"]
    assert probe["version"] == compat.get_version()


def test_version_range_boundaries() -> None:
    assert compat._version_in_range("3.0.4") is True
    assert compat._version_in_range("3.0.99") is True
    assert compat._version_in_range("3.0.3") is False   # below floor
    assert compat._version_in_range("3.1.0") is False   # at exclusive ceiling
    assert compat._version_in_range("4.0.0") is False


def test_probe_shape() -> None:
    probe = compat.probe_compat()
    for key in ("ok", "version", "known_good", "range", "issues"):
        assert key in probe
    assert isinstance(probe["issues"], list)
