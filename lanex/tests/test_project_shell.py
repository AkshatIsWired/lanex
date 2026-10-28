"""Project switcher server support: default projects folder, Windows files root,
and revealing a design folder only when the server already knows it."""

from __future__ import annotations

import platform
from pathlib import Path

from lanex.controller import platform_env
from lanex.server import routes


class _CapturingHandler:
    def __init__(self, path: str = "/", body=None) -> None:
        self.path = path
        self._body = body or {}
        self.payload = None
        self.status = None

    def _send_json(self, obj, status: int = 200) -> None:
        self.payload = obj
        self.status = status


def test_projects_dir_prefers_the_windows_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_env, "wsl_windows_home", lambda: str(tmp_path))
    assert platform_env.projects_dir() == tmp_path / "LanEx-Projects"


def test_projects_dir_avoids_paths_with_spaces(monkeypatch):
    # LibreLane splits file lists on whitespace, so a profile path with a space
    # would break every run; those fall back to the Linux home.
    monkeypatch.setattr(platform_env, "wsl_windows_home", lambda: "/mnt/c/Users/Jane Doe")
    assert platform_env.projects_dir() == Path.home() / "lanex-projects"
    # The wizard says why; only this case is "your user name has a space".
    assert platform_env.projects_dir_info()[1] == "space"


def test_projects_dir_off_wsl_is_the_home_folder(monkeypatch):
    monkeypatch.setattr(platform_env, "wsl_windows_home", lambda: None)
    assert platform_env.projects_dir() == Path.home() / "lanex-projects"
    assert platform_env.projects_dir_info()[1] == "no_windows"


def test_windows_paths_pass_through_off_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    assert platform_env.to_host_path("C:/Users/x/chip") == "C:/Users/x/chip"
    assert platform_env.to_host_path("/home/x/chip") == "/home/x/chip"


def test_delete_refuses_folders_outside_the_projects_dir(monkeypatch, tmp_path):
    root = tmp_path / "LanEx-Projects"
    (root / "keep").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(platform_env, "projects_dir", lambda: root)
    h = _CapturingHandler(body={"design_dir": str(other), "confirm_name": "elsewhere"})
    routes.h_project_delete(h)
    assert h.status == 403 and other.is_dir()


def test_delete_needs_the_typed_name_and_not_the_open_project(monkeypatch, tmp_path):
    root = tmp_path / "LanEx-Projects"
    victim = root / "old"
    victim.mkdir(parents=True)
    monkeypatch.setattr(platform_env, "projects_dir", lambda: root)
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: None)
    h = _CapturingHandler(body={"design_dir": str(victim), "confirm_name": "wrong"})
    routes.h_project_delete(h)
    assert h.status == 400 and victim.is_dir()
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(victim))
    h = _CapturingHandler(body={"design_dir": str(victim), "confirm_name": "old"})
    routes.h_project_delete(h)
    assert h.status == 409 and victim.is_dir()
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: None)
    h = _CapturingHandler(body={"design_dir": str(victim), "confirm_name": "old"})
    routes.h_project_delete(h)
    assert h.status == 200 and not victim.exists()


def test_project_defaults_reports_the_projects_dir():
    h = _CapturingHandler()
    routes.h_project_defaults(h)
    data = h.payload["data"]
    assert data["projects_dir"] == str(platform_env.projects_dir())
    assert isinstance(data["exists"], bool)
    assert isinstance(data["wsl"], bool)


def test_fs_roots_offer_windows_files_on_wsl(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform_env, "wsl_windows_home", lambda: str(tmp_path))
    h = _CapturingHandler()
    routes.h_fs_roots(h)
    roots = h.payload["data"]["roots"]
    assert {"label": "Windows files", "path": str(tmp_path)} in roots
    labels = [r["label"] for r in roots]
    assert labels[0] == "Home"                  # home first, filesystem root after
    assert labels.index("Windows files") < labels.index("/ (root)")


def test_fs_roots_skip_windows_files_off_wsl(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform_env, "wsl_windows_home", lambda: None)
    h = _CapturingHandler()
    routes.h_fs_roots(h)
    assert "Windows files" not in [r["label"] for r in h.payload["data"]["roots"]]


def test_reveal_refuses_a_folder_the_server_does_not_know(monkeypatch, tmp_path):
    from lanex.controller import designs
    monkeypatch.setattr(designs, "list_designs", lambda: [])
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: None)
    opened = []
    monkeypatch.setattr(routes, "_reveal_in_file_manager", lambda p: opened.append(p) or (True, str(p)))
    h = _CapturingHandler(body={"design_dir": str(tmp_path)})
    routes.h_reveal(h)
    assert h.status == 404
    assert opened == []


def test_reveal_opens_a_known_design_folder(monkeypatch, tmp_path):
    from lanex.controller import designs
    monkeypatch.setattr(designs, "list_designs", lambda: [str(tmp_path)])
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: None)
    opened = []
    monkeypatch.setattr(routes, "_reveal_in_file_manager", lambda p: opened.append(p) or (True, str(p)))
    h = _CapturingHandler(body={"design_dir": str(tmp_path)})
    routes.h_reveal(h)
    assert h.status == 200
    assert opened == [tmp_path]
