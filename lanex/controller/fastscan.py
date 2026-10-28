# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tree walks that skip folders before entering them.

``Path.rglob("*")`` followed by a filter visits every file under ``runs/``
(hundreds per run, a thousand runs in a busy project) only to throw them away.
On a project kept on ``/mnt/c`` each visit is a round trip to Windows, so the
Setup page's design-info took tens of seconds. :func:`iter_entries` yields what
``rglob("*")`` would (files, folders and links, symlinked folders listed but not
entered, unreadable folders skipped) minus everything under a pruned folder.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterator, Tuple

# The folders every source scan skips: run results, VCS data, build output.
SOURCE_SKIP_DIRS = frozenset({".git", "runs", "tmp", "__pycache__", "build",
                              "node_modules", "sim_build", "obj_dir"})


def iter_entries(root: "str | Path",
                 prune: Callable[[Tuple[str, ...]], bool]) -> Iterator[Path]:
    """Every entry under *root*, like ``Path(root).rglob("*")``, without
    descending into a folder for which ``prune(rel_parts)`` is true.

    ``rel_parts`` are the folder's path components relative to *root*. The
    pruned folder itself is still yielded (``rglob`` lists it too); only its
    contents are skipped. Order is unspecified; callers sort, as they did the
    ``rglob`` output.
    """
    stack: list = [((), str(Path(root)))]
    while stack:
        rel, path = stack.pop()
        try:
            it = os.scandir(path)
        except OSError:
            continue
        with it:
            for entry in it:
                yield Path(entry.path)
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                if not is_dir:
                    continue
                crel = rel + (entry.name,)
                if prune(crel):
                    continue
                stack.append((crel, entry.path))


def iter_rel_entries(root: "str | Path") -> Iterator[Tuple[str, "os.DirEntry[str]"]]:
    """``(relative path, DirEntry)`` for every entry under *root*, like
    ``rglob("*")`` (symlinked folders listed, not entered). The DirEntry keeps
    the file type the directory read already returned, so callers need a stat
    only for sizes."""
    stack: list = [("", str(Path(root)))]
    while stack:
        prefix, path = stack.pop()
        try:
            it = os.scandir(path)
        except OSError:
            continue
        with it:
            for entry in it:
                rel = prefix + entry.name
                yield rel, entry
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((rel + os.sep, entry.path))
                except OSError:
                    continue


def prune_names(names: "frozenset[str] | set[str]") -> Callable[[Tuple[str, ...]], bool]:
    """A prune test that skips any folder whose own name is in *names*."""
    return lambda parts: parts[-1] in names
