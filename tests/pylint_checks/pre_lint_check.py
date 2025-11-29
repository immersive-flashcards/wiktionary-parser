"""
Pylint plugin: require __init__.py in any directory that (directly or indirectly)
contains Python files. Honors .gitignore and lets you exclude top-level dirs.

Needs to be enabled in pyproject.toml
"""

from __future__ import annotations

import os
from typing import Iterable, Set

import pathspec
from pylint.checkers import BaseChecker
from pylint.lint import PyLinter


class RequireInitChecker(BaseChecker):
    """Filesystem-level check run at start of linting."""
    priority = -1
    name = "require_init_in_python_dirs"

    # Custom Message
    msgs = {
        "E0420": (  # just picking an unused code from the Imports Checker category (400s)
            "Directory missing __init__.py but contains Python files: %s",
            "missing-init-in-py-bearing-dir",
            "Any directory that (directly or indirectly) contains .py files must include an __init__.py.",
            {"scope": "module"},
        ),
    }

    # Configurable options (surfaced in pyproject.toml under [tool.pylint])
    options = (
        (
            "require-init-exclude-dirs",
            {
                "default": ("tests",),
                "type": "csv",
                "metavar": "<dirs>",
                "help": "Top-level directories to exclude (CSV). Default: tests",
            },
        ),
        (
            "require-init-root-dir",
            {
                "default": ".",
                "type": "string",
                "metavar": "<path>",
                "help": "Project root to scan. Defaults to current working directory.",
            },
        ),
        (
            "require-init-respect-gitignore",
            {
                "default": True,
                "type": "yn",
                "metavar": "y/n",
                "help": "Honor .gitignore when walking (requires pathspec). Default: y",
            },
        ),
    )

    # lifecycle hook: run once up-front
    def open(self) -> None:  # pylint: disable=arguments-differ
        project_root = os.path.abspath(self._root_dir())
        ignore = self._load_gitignore(project_root)
        excluded = set(self._exclude_dirs())

        dirs_with_py = self._collect_dirs_with_python(project_root, ignore, excluded)
        missing = self._missing_init(project_root, dirs_with_py)

        for rel in sorted(missing):
            # Indicate the path with the missing __init__.py
            init_path = os.path.join(project_root, rel, "__init__.py")
            self.add_message(
                "missing-init-in-py-bearing-dir",
                line=1,
                args=(f"{rel}/",)
            )

    # helpers
    def _root_dir(self) -> str:
        cfg = getattr(self.linter, "config", None)
        cfg_val = getattr(cfg, "require_init_root_dir", "..") if cfg else "."
        return cfg_val or "."

    def _exclude_dirs(self) -> Iterable[str]:
        cfg = getattr(self.linter, "config", None)
        val = getattr(cfg, "require_init_exclude_dirs", ("tests",)) if cfg else ("tests",)
        # normalize and keep only top-level names
        return [d.strip("/").split(os.sep)[0] for d in val]

    def _respect_gitignore(self) -> bool:
        cfg = getattr(self.linter, "config", None)
        val = getattr(cfg, "require_init_respect_gitignore", True) if cfg else True
        return bool(val)

    def _load_gitignore(self, directory: str):
        if not (self._respect_gitignore() and pathspec is not None):
            return None
        gitignore_path = os.path.join(directory, ".gitignore")
        if os.path.isfile(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            return pathspec.PathSpec.from_lines("gitwildmatch", lines)
        return pathspec.PathSpec([])

    def _collect_dirs_with_python(
        self, root: str, ignore, exclude_top: Set[str]
    ) -> Set[str]:
        """All dirs (and their ancestors up to root) that contain .py files."""
        found: Set[str] = set()
        for current_root, dirs, files in os.walk(root):
            rel_root = os.path.relpath(current_root, root)
            first = rel_root.split(os.sep)[0]

            # skip excluded top-level dirs
            if first in exclude_top:
                dirs[:] = []  # don’t descend
                continue

            # skip ignored directories
            if ignore and rel_root != "." and ignore.match_file(rel_root):
                dirs[:] = []
                continue

            # filter subdirs before descending
            dirs[:] = [
                d
                for d in dirs
                if d not in exclude_top
                and not (ignore and ignore.match_file(os.path.join(rel_root, d)))
            ]

            # collect if any .py file here (not ignored)
            py_files = [
                f
                for f in files
                if f.endswith(".py")
                and not (ignore and ignore.match_file(os.path.join(rel_root, f)))
            ]
            if py_files:
                current = current_root
                while True:
                    if current == root:
                        break
                    found.add(current)
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
        return found

    def _missing_init(self, root: str, dirs_with_py: Set[str]) -> Set[str]:
        missing = set()
        for abs_dir in dirs_with_py:
            init_file = os.path.join(abs_dir, "__init__.py")
            if not os.path.isfile(init_file):
                rel = os.path.relpath(abs_dir, root)
                #if rel == ".": # Optional: skip checking for __init__.py at project root
                #    continue
                missing.add(rel)
        return missing


def register(linter: PyLinter) -> None:
    """Ensures this pre-lint check runs first"""
    linter.register_checker(RequireInitChecker(linter))
