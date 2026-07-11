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
"""Coverage for the previously-untested pure functions in installer / container_run
(H4): the image-ref composition and the privilege-escalation command builder.

No test touches the network or a real docker/sudo — the escalation builder is
asserted to *produce* the right argv without executing it, and platform probes
are monkeypatched. GOTCHA (round-25): installer imports platform_env lazily, so
monkeypatch the real ``platform_env`` module, not ``installer.platform_env``."""
from __future__ import annotations

from lanex.controller import container_run, installer, platform_env


# --------------------------------------------------------------------------- #
# image_ref() — the version-matched image the --dockerized path uses
# --------------------------------------------------------------------------- #
def test_image_ref_default_pins_to_installed_version() -> None:
    ref = container_run.image_ref()
    assert ref.startswith("ghcr.io/librelane/librelane:")
    # With librelane installed the tag is its version, never the loose "latest".
    from lanex.controller import compat
    assert ref.endswith(":" + compat.get_version())


def test_image_ref_honours_override(monkeypatch) -> None:
    monkeypatch.setenv("LIBRELANE_IMAGE_OVERRIDE", "my.registry/lanex:pinned")
    assert container_run.image_ref() == "my.registry/lanex:pinned"


def test_pull_argv_uses_image_ref(monkeypatch) -> None:
    monkeypatch.setenv("LIBRELANE_IMAGE_OVERRIDE", "reg/img:tag")
    assert container_run.pull_argv("podman") == ["podman", "pull", "reg/img:tag"]


# --------------------------------------------------------------------------- #
# _escalate_argv() — root-acquisition strategy selection (never executes)
# --------------------------------------------------------------------------- #
def test_escalate_prefers_controlling_tty(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: True)
    argv, inherit_tty = installer._escalate_argv(["sudo", "apt-get", "install", "-y", "dot"])
    assert argv == ["sudo", "apt-get", "install", "-y", "dot"]
    assert inherit_tty is True


def test_escalate_falls_back_to_pkexec(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: name == "pkexec")
    res = installer._escalate_argv(["sudo", "apt-get", "install", "-y", "graphviz"])
    assert res is not None
    argv, inherit_tty = res
    assert argv[0] == "pkexec"
    assert argv[1:] == ["apt-get", "install", "-y", "graphviz"]
    assert inherit_tty is False


def test_escalate_gives_up_without_tty_or_pkexec(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: False)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: False)
    assert installer._escalate_argv(["sudo", "apt-get", "install", "-y", "x"]) is None


def test_escalate_does_not_rewrite_shell_wrapped_sudo(monkeypatch) -> None:
    # ``sh -c "… sudo …"`` isn't a plain ``sudo <cmd>`` — pkexec can't wrap it.
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: name == "pkexec")
    assert installer._escalate_argv(["sh", "-c", "sudo apt-get install x"]) is None


# --------------------------------------------------------------------------- #
# _run_argv() — a sudo command with a controlling terminal MUST attach to the
# terminal, even when `sudo -n true` succeeds. Detaching (start_new_session) drops
# the controlling tty and sudo's tty_tickets cache goes with it → "sudo: A
# terminal is required to authenticate" (the GDS3D-deps failure the user hit).
# --------------------------------------------------------------------------- #
def _capture_tty(monkeypatch):
    seen = {}

    def fake_tty(argv, *, label, key, env_extra=None):
        seen["argv"] = list(argv)
        seen["label"] = label
        return {"ok": True, "rc": 0, "label": label}

    monkeypatch.setattr(installer, "_run_argv_on_tty", fake_tty)
    monkeypatch.setattr(installer, "_emit", lambda *a, **k: None)
    return seen


def test_run_argv_sudo_with_tty_uses_terminal_even_if_passwordless(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: True)
    monkeypatch.setattr(installer, "_can_sudo", lambda: True)  # `sudo -n true` OK
    seen = _capture_tty(monkeypatch)
    argv = ["sudo", "apt-get", "install", "-y", "libgl1-mesa-dev"]
    res = installer._run_argv(argv, label="gds3d deps", key="gds3d")
    assert res.get("ok") is True
    assert seen.get("argv") == argv  # ran on the tty, not detached


def test_run_argv_sudo_with_tty_no_ticket_prompts_on_terminal(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: True)
    monkeypatch.setattr(installer, "_can_sudo", lambda: False)  # needs a password
    events = []

    def fake_tty(argv, *, label, key, env_extra=None):
        return {"ok": True, "rc": 0, "label": label}

    monkeypatch.setattr(installer, "_run_argv_on_tty", fake_tty)
    monkeypatch.setattr(installer, "_emit", lambda name, payload: events.append((name, payload)))
    installer._run_argv(["sudo", "apt-get", "install", "-y", "x"], label="l", key="k")
    assert any(n == "installer_info" and p.get("needs_password") for n, p in events)
