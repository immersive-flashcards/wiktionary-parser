# tests/pylint_checks/whitelist_module_name.py
from __future__ import annotations
from pathlib import Path
from typing import Optional
import re
from pylint.checkers import BaseChecker
from pylint.lint import PyLinter


class WhitelistModuleNameChecker(BaseChecker):
    """Check module & package names (subset of C0103), but whitelist the
    top-level kebab-case package (dir name == repo root) for its __init__.py."""

    name = "whitelist_module_name"
    msgs = {
        "C9001": (
            "directory '%s' doesn't follow snake_case naming convention",
            "invalid-directory-name",
            "Used when a package directory or module filename violates naming conventions, "
            "except for the top-level kebab-case package __init__.py.",
        ),
    }
    options = ()

    def open(self) -> None:  # pylint: disable=arguments-differ
        cwd = Path.cwd().resolve()
        toml = cwd / "pyproject.toml"
        self.repo_root = (toml.parent if toml.exists() else cwd).resolve()

        default = r"(([a-z_][a-z0-9_]*)|(__init__))$"
        raw = getattr(self.linter.config, "module_rgx", default)
        if isinstance(raw, str):
            self._module_rgx = re.compile(raw)
        elif hasattr(raw, "match"):  # compiled Pattern
            self._module_rgx = raw
        elif hasattr(raw, "pattern"):
            self._module_rgx = re.compile(raw.pattern)  # type: ignore[arg-type]
        else:
            self._module_rgx = re.compile(default)

        self._reported_pkg_dirs: set[Path] = set()

    def visit_module(self, node) -> None:
        file_path = _safe_node_path(node)
        if not file_path:
            return

        try:
            rel = file_path.resolve().relative_to(self.repo_root)
        except Exception:
            return  # outside project; ignore

        # 1) Check each package dir name once
        parts = rel.parts[:-1]  # exclude filename
        for idx, part in enumerate(parts):
            dir_path = (self.repo_root / Path(*parts[: idx + 1])).resolve()
            if not (dir_path / "__init__.py").exists():
                continue
            if idx == 0 and part == self.repo_root.name:
                continue  # whitelist top-level kebab-case
            if dir_path in self._reported_pkg_dirs:
                continue
            if not self._module_rgx.match(part):
                self.add_message("invalid-directory-name", node=node, args=(part,))
                self._reported_pkg_dirs.add(dir_path)

        # 2) Check module file name (per file), unless it's __init__.py
        if file_path.name != "__init__.py":
            mod_name = file_path.stem
            if not self._module_rgx.match(mod_name):
                self.add_message("invalid-directory-name", node=node, args=(mod_name,))


def _safe_node_path(node) -> Optional[Path]:
    try:
        f = getattr(node, "file", None)
        if f:
            return Path(f).resolve()
        root = getattr(node, "root", lambda: None)()
        if root is not None and getattr(root, "file", None):
            return Path(root.file).resolve()
    except Exception:
        pass
    return None


def register(linter: PyLinter) -> None:
    linter.register_checker(WhitelistModuleNameChecker(linter))
