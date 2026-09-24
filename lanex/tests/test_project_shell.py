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


def test_projects_dir_lives_in_home():
    assert platform_env.projects_dir() == Path.home() / "lanex-projects"


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
