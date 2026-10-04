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
"""Change a few top-level keys in a design's own config file, safely.

The project's config file is the project: what the Setup page shows for the
top module, the clock and the source list is what LibreLane reads, so a run
from LanEx and a run from a terminal build the same chip. This module is the
only place LanEx writes that file, and it is deliberately narrow:

* only top-level keys are set or removed; ``pdk::``/``scl::`` sections,
  comments, key order, quoting and line endings elsewhere are left exactly
  as they were (YAML is edited line by line, never re-dumped);
* after building the new text it parses old and new and refuses to write
  unless the ONLY difference is the requested keys, so a bad edit can't
  corrupt anything else;
* a copy of the previous file is kept outside the project, and the write is
  atomic (temp file + rename);
* Tcl configs are never edited.

Stdlib + PyYAML (already a LibreLane dependency).
"""
from __future__ import annotations

import copy
import fnmatch
import glob
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

CONFIG_NAMES = ("config.json", "config.yaml", "config.yml", "config.tcl")
_KEY_RX = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SCOPE_PREFIXES = ("pdk::", "scl::")
_BACKUPS_KEPT = 10


class ConfigEditError(Exception):
    """A refusal with a message fit to show the person."""


# ------------------------------------------------------------------ discovery

def find_config(design_dir: str | Path) -> Optional[Path]:
    d = Path(design_dir)
    for name in CONFIG_NAMES:
        p = d / name
        if p.is_file():
            return p
    return None


def _load(path: Path, text: str) -> Dict[str, Any]:
    if path.suffix == ".json":
        data = json.loads(text) if text.strip() else {}
    else:
        import yaml
        data = yaml.safe_load(text) if text.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigEditError(f"{path.name} doesn't hold a key/value mapping at the top level.")
    return data


def read_config(design_dir: str | Path) -> Dict[str, Any]:
    """``{path, name, format, editable, data, reason}`` for the design's config.
    ``data`` is the parsed file ({} for Tcl or when missing)."""
    path = find_config(design_dir)
    if path is None:
        return {"path": None, "name": None, "format": None, "editable": False,
                "data": {}, "reason": "This project has no config file yet."}
    fmt = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".tcl": "tcl"}[path.suffix]
    if fmt == "tcl":
        return {"path": str(path), "name": path.name, "format": fmt, "editable": False,
                "data": {}, "reason": "LanEx doesn't edit Tcl configs. Change it in the file."}
    try:
        data = _load(path, path.read_text(encoding="utf-8"))
    except ConfigEditError as ex:
        return {"path": str(path), "name": path.name, "format": fmt, "editable": False,
                "data": {}, "reason": str(ex)}
    except Exception as ex:
        return {"path": str(path), "name": path.name, "format": fmt, "editable": False,
                "data": {}, "reason": f"{path.name} can't be read: {ex}"}
    return {"path": str(path), "name": path.name, "format": fmt, "editable": True,
            "data": data, "reason": None}


# ------------------------------------------------------------------ scoped values

def scoped_values(data: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Every ``pdk::``/``scl::`` section (nested too) that also sets *key*, as
    ``{"scope": "pdk::sky130* / scl::sky130_fd_sc_hs", "pdk": pat|None,
    "scl": pat|None, "value": v}``."""
    out: List[Dict[str, Any]] = []

    def walk(section: Dict[str, Any], trail: List[str], pdk: Optional[str], scl: Optional[str]) -> None:
        for k, v in section.items():
            if not isinstance(k, str) or not k.startswith(_SCOPE_PREFIXES) or not isinstance(v, dict):
                continue
            kind, pat = k.split("::", 1)
            p2 = pat if kind == "pdk" else pdk
            s2 = pat if kind == "scl" else scl
            t2 = trail + [k]
            if key in v:
                out.append({"scope": " / ".join(t2), "pdk": p2, "scl": s2, "value": v[key]})
            walk(v, t2, p2, s2)

    walk(data, [], None, None)
    return out


def applies(entry: Dict[str, Any], pdk: Optional[str], scl: Optional[str]) -> Optional[bool]:
    """Whether a scoped entry applies to this PDK/SCL (None when unknown)."""
    if entry.get("pdk") and not pdk:
        return None
    if entry.get("scl") and not scl:
        return None
    ok = True
    if entry.get("pdk"):
        ok = ok and fnmatch.fnmatchcase(pdk, entry["pdk"])
    if entry.get("scl"):
        ok = ok and fnmatch.fnmatchcase(scl, entry["scl"])
    return ok


# ------------------------------------------------------------------ YAML text editing

_YAML_PLAIN_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_./:\-*+]*$")
_YAML_WORDS = {"true", "false", "yes", "no", "on", "off", "null", "y", "n", "~"}


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    s = str(v)
    if _YAML_PLAIN_RX.match(s) and s.lower() not in _YAML_WORDS and ": " not in s and " #" not in s:
        return s
    return json.dumps(s, ensure_ascii=False)   # a JSON string is a valid YAML double-quoted scalar


def _yaml_block(key: str, v: Any, comment: str = "") -> List[str]:
    if isinstance(v, (list, tuple)):
        if not v:
            return [f"{key}: []" + comment]
        return [f"{key}:" + comment] + [f"  - {_yaml_scalar(x)}" for x in v]
    if isinstance(v, dict):
        raise ConfigEditError(f"{key}: LanEx only writes plain values and lists.")
    return [f"{key}: {_yaml_scalar(v)}" + comment]


def _top_key(line: str) -> Optional[str]:
    """The key a column-0 ``KEY:`` line defines (quotes stripped), else None."""
    if not line or line[0] in " \t#-":
        return None
    m = re.match(r"""^(["']?)(.+?)\1\s*:(\s|$)""", line)
    return m.group(2) if m else None


def _blocks(lines: List[str]) -> List[Tuple[str, int, int]]:
    """``(key, start, end)`` spans of every top-level key; ``end`` excludes
    trailing blank lines and column-0 comments that follow the block."""
    starts = [(i, _top_key(ln)) for i, ln in enumerate(lines)]
    starts = [(i, k) for i, k in starts if k is not None]
    out = []
    for n, (i, k) in enumerate(starts):
        j = i + 1
        limit = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        last = i
        while j < limit:
            ln = lines[j]
            if ln.strip() == "":
                j += 1
                continue
            if ln[0] in " \t" or ln.lstrip().startswith("- ") and ln[0] == "-":
                last = j
                j += 1
                continue
            break   # column-0 comment or other content ends the block
        out.append((k, i, last + 1))
    return out


def _inline_comment(line: str) -> str:
    """A trailing ``  # comment`` on a ``KEY: value`` line, when the value is
    unquoted (quoted values are left without trying)."""
    head, _, rest = line.partition(":")
    val = rest.strip()
    if not val or val[0] in "\"'[{":
        return ""
    m = re.search(r"\s+#.*$", rest)
    return m.group(0) if m else ""


def _edit_yaml(text: str, sets: Dict[str, Any], removes: Iterable[str]) -> str:
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    removes = [k for k in removes if k not in sets]
    for key in list(sets) + list(removes):
        blocks = _blocks(lines)
        spans = [(s, e) for k, s, e in blocks if k == key]
        if len(spans) > 1:
            raise ConfigEditError(f"{key} appears more than once at the top level; fix the file by hand.")
        if spans:
            s, e = spans[0]
            if key in sets:
                comment = _inline_comment(lines[s]) if e - s == 1 else ""
                lines[s:e] = _yaml_block(key, sets[key], comment)
            else:
                lines[s:e] = []
        elif key in sets:
            new = _yaml_block(key, sets[key])
            # New keys go above the first pdk::/scl:: section (and the comment
            # lines heading it), so they read as project-wide settings.
            scoped = [s for k, s, _ in blocks if k.startswith(_SCOPE_PREFIXES)]
            if scoped:
                at = scoped[0]
                while at > 0 and lines[at - 1].startswith("#"):
                    at -= 1
                block = new + [""]
                if at > 0 and lines[at - 1].strip():
                    block = [""] + block
                lines[at:at] = block
            else:
                while lines and lines[-1].strip() == "":
                    lines.pop()
                lines.extend(new)
    return nl.join(lines) + nl


# ------------------------------------------------------------------ JSON editing

def _edit_json(text: str, data: Dict[str, Any], sets: Dict[str, Any], removes: Iterable[str]) -> str:
    m = re.search(r"\n([ \t]+)\"", text)
    indent: Any = (m.group(1) if m else "    ")
    if isinstance(indent, str) and indent.strip(" ") == "":
        indent = len(indent)
    out: Dict[str, Any] = {}
    pending = {k: v for k, v in sets.items() if k not in data}
    for k, v in data.items():
        if k in removes and k not in sets:
            continue
        if pending and isinstance(k, str) and k.startswith(_SCOPE_PREFIXES):
            out.update(pending)
            pending = {}
        out[k] = sets.get(k, v) if k in sets else v
    out.update(pending)
    nl = "\r\n" if "\r\n" in text else "\n"
    body = json.dumps(out, indent=indent, ensure_ascii=False)
    return body.replace("\n", nl) + nl


# ------------------------------------------------------------------ write

def _backup(path: Path, text: str) -> None:
    try:
        from . import platform_env
        tag = hashlib.sha1(str(path.parent.resolve()).encode()).hexdigest()[:10]
        bdir = platform_env.home() / "config-backups" / f"{path.parent.name}-{tag}"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / f"{time.strftime('%Y%m%d-%H%M%S')}-{path.name}").write_text(text, encoding="utf-8")
        old = sorted(bdir.iterdir())
        for f in old[:-_BACKUPS_KEPT]:
            f.unlink(missing_ok=True)
    except Exception:
        pass   # a backup is a courtesy; the validation below is the real guard


def set_keys(design_dir: str | Path, sets: Optional[Dict[str, Any]] = None,
             removes: Optional[Iterable[str]] = None, *, dry_run: bool = False) -> Dict[str, Any]:
    """Set and/or remove top-level keys in the design's config file.

    Returns ``{path, name, changed: [keys], scoped: {key: [entries]}, text}``.
    Raises :class:`ConfigEditError` with a readable reason on any refusal;
    the file is untouched in that case.
    """
    sets = dict(sets or {})
    removes = [k for k in (removes or []) if k not in sets]
    for k in list(sets) + removes:
        if not isinstance(k, str) or not _KEY_RX.match(k):
            raise ConfigEditError(f"'{k}' isn't a LibreLane variable name.")
    info = read_config(design_dir)
    if not info["path"]:
        raise ConfigEditError(info["reason"])
    if not info["editable"]:
        raise ConfigEditError(info["reason"])
    path = Path(info["path"])
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if text.startswith("﻿"):
        raise ConfigEditError(f"{path.name} starts with a byte-order mark; save it as plain UTF-8 first.")
    old = _load(path, text)

    expected = copy.deepcopy(old)
    changed = []
    for k, v in sets.items():
        if old.get(k, object()) != v:
            changed.append(k)
        expected[k] = v
    for k in removes:
        if k in expected:
            changed.append(k)
            del expected[k]
    scoped = {k: scoped_values(old, k) for k in list(sets) + removes}
    scoped = {k: v for k, v in scoped.items() if v}
    if not changed:
        return {"path": str(path), "name": path.name, "changed": [], "scoped": scoped, "text": text}

    new_text = _edit_json(text, old, sets, removes) if path.suffix == ".json" else _edit_yaml(text, sets, removes)
    try:
        got = _load(path, new_text)
    except Exception as ex:
        raise ConfigEditError(f"LanEx's edit of {path.name} didn't parse ({ex}); nothing was written.")
    if got != expected:
        raise ConfigEditError(f"LanEx couldn't change {', '.join(changed)} in {path.name} without touching "
                              "anything else, so nothing was written. Edit the file by hand.")
    if dry_run:
        return {"path": str(path), "name": path.name, "changed": changed, "scoped": scoped, "text": new_text}

    _backup(path, text)
    tmp = path.with_name(f".{path.name}.lanex-tmp")
    tmp.write_bytes(new_text.encode("utf-8"))
    try:
        os.chmod(tmp, path.stat().st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    return {"path": str(path), "name": path.name, "changed": changed, "scoped": scoped, "text": new_text}


# ------------------------------------------------------------------ VERILOG_FILES

_HDL_EXTS = (".v", ".sv")


def resolve_sources(design_dir: str | Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """What the config's ``VERILOG_FILES`` resolves to, the way LibreLane's
    preprocessor does it for the common forms (``dir::`` relative to the
    design dir with globbing, absolute paths, plain design-relative paths).

    ``{"mode": "none"|"list"|"unknown", "entries": [...], "files": [abs...],
    "globbed": bool, "reason": str|None}``. ``unknown`` (``ref::``/``expr::``/
    ``pdk_dir::`` or a scoped VERILOG_FILES) means LanEx shows it but won't
    rewrite it.
    """
    d = Path(design_dir).resolve()
    vf = data.get("VERILOG_FILES")
    if scoped_values(data, "VERILOG_FILES"):
        return {"mode": "unknown", "entries": [], "files": [], "globbed": False,
                "reason": "VERILOG_FILES is set inside a pdk::/scl:: section."}
    if vf is None:
        return {"mode": "none", "entries": [], "files": [], "globbed": False, "reason": None}
    entries = [str(x) for x in vf] if isinstance(vf, list) else str(vf).split()
    files: List[str] = []
    globbed = False
    for e in entries:
        if e.startswith(("ref::", "refg::", "expr::", "pdk_dir::")):
            return {"mode": "unknown", "entries": entries, "files": [], "globbed": False,
                    "reason": f"VERILOG_FILES uses '{e.split('::')[0]}::', which LanEx doesn't rewrite."}
        s = e[len("dir::"):] if e.startswith("dir::") else e
        p = s if os.path.isabs(s) else str(d / s)
        if os.path.isfile(p):
            files.append(str(Path(p).resolve()))
        elif any(ch in s for ch in "*?["):
            globbed = True
            files.extend(str(Path(m).resolve()) for m in sorted(glob.glob(p, recursive=True)) if os.path.isfile(m))
        else:
            files.append(str(Path(p).resolve()))   # missing file: keep it visible
    seen: List[str] = []
    for f in files:
        if f not in seen:
            seen.append(f)
    return {"mode": "list", "entries": entries, "files": seen, "globbed": globbed, "reason": None}


def sources_entries(design_dir: str | Path, files: Iterable[str]) -> List[str]:
    """``dir::``-relative entries for files inside the design dir, absolute
    otherwise (LibreLane reads both)."""
    d = Path(design_dir).resolve()
    out = []
    for f in files:
        p = Path(f).resolve()
        try:
            out.append("dir::" + p.relative_to(d).as_posix())
        except ValueError:
            out.append(str(p))
    return out


def set_sources(design_dir: str | Path, files: List[str]) -> Dict[str, Any]:
    """Make ``VERILOG_FILES`` resolve to exactly *files*. A glob that already
    resolves to that set is kept as it is; otherwise the list is written out
    file by file. Returns :func:`set_keys`' result plus ``"kept_glob"``."""
    info = read_config(design_dir)
    if not info["editable"]:
        raise ConfigEditError(info["reason"])
    cur = resolve_sources(design_dir, info["data"])
    if cur["mode"] == "unknown":
        raise ConfigEditError(cur["reason"])
    want = [str(Path(f).resolve()) for f in files]
    if cur["mode"] == "list" and sorted(cur["files"]) == sorted(want):
        return {"path": info["path"], "name": info["name"], "changed": [], "scoped": {}, "kept_glob": cur["globbed"]}
    # Keep the config's order for files that stay, new ones after.
    ordered = [f for f in cur["files"] if f in want] + [f for f in want if f not in cur["files"]]
    res = set_keys(design_dir, {"VERILOG_FILES": sources_entries(design_dir, ordered)})
    res["kept_glob"] = False
    return res


def follow_rename(design_dir: str | Path, old_abs: str, new_abs: str,
                  before: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Point the config at a file that was just renamed.

    Every top-level string (or list of strings) that names the old file, as
    ``dir::<rel>``, ``<rel>``, ``./<rel>`` or its absolute path, is rewritten to
    the new name (PNR_SDC_FILE, IO_PIN_ORDER_CFG, an explicit VERILOG_FILES …).
    *before* is :func:`resolve_sources` taken before the rename: a design file
    the build included through a glob that no longer matches it (``.v`` renamed
    to ``.sv`` under ``dir::src/*.v``) is listed explicitly so it stays in.
    Returns :func:`set_keys`' result; raises :class:`ConfigEditError`.
    """
    d = Path(design_dir).resolve()
    old_p, new_p = Path(old_abs).resolve(), Path(new_abs).resolve()
    try:
        old_rel, new_rel = old_p.relative_to(d).as_posix(), new_p.relative_to(d).as_posix()
    except ValueError:
        raise ConfigEditError("The file isn't inside the project folder.")
    info = read_config(design_dir)
    if not info["path"]:
        return {"changed": [], "name": None}
    if not info["editable"]:
        # Only a problem if that file actually names the renamed one.
        try:
            named = old_rel in Path(info["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            named = True
        if named:
            raise ConfigEditError(info["reason"])
        return {"changed": [], "name": info["name"]}
    forms = {"dir::" + old_rel: "dir::" + new_rel, old_rel: new_rel,
             "./" + old_rel: "./" + new_rel, str(old_p): str(new_p)}
    data = info["data"]
    sets: Dict[str, Any] = {}
    for k, v in data.items():
        if not _KEY_RX.match(str(k)):
            continue
        if isinstance(v, str) and v in forms:
            sets[k] = forms[v]
        elif isinstance(v, list) and all(isinstance(x, str) for x in v) and any(x in forms for x in v):
            sets[k] = [forms.get(x, x) for x in v]
    if before and before.get("mode") == "list" and str(old_p) in before.get("files", []):
        after = resolve_sources(design_dir, {**data, **sets})
        if after["mode"] == "list" and str(new_p) not in after["files"]:
            files = [str(new_p) if f == str(old_p) else f for f in before["files"]]
            sets["VERILOG_FILES"] = sources_entries(design_dir, files)
    if not sets:
        return {"changed": [], "name": info["name"]}
    res = set_keys(design_dir, sets)
    res.pop("text", None)
    return res
