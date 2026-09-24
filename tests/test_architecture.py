"""
Layering guard (ratchet).

Controllers (app/web, app/routers) should call services, not Mongo directly.
Existing direct-DB usage is frozen at the counts below: the test fails if a
file gains DB calls or a new controller starts using `db`. When you move
queries into services, lower (or delete) the file's entry.

Services must never render templates or build redirects.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"

# file (relative to app/) -> max allowed direct `db.<collection>` / `db[...]` uses
CONTROLLER_DB_BASELINE = {
    "web/admin.py": 24,
    "web/auth.py": 16,
    "web/profile.py": 29,
    "routers/chat.py": 20,
}

FORBIDDEN_IN_SERVICES = {"RedirectResponse", "TemplateResponse", "Jinja2Templates"}


def _db_uses(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            target = node.value
            if isinstance(target, ast.Name) and target.id == "db":
                count += 1
    return count


def _py_files(*dirs):
    for d in dirs:
        yield from sorted((ROOT / d).rglob("*.py"))


class TestLayering(unittest.TestCase):
    def test_controllers_do_not_grow_direct_db_access(self):
        problems = []
        for path in _py_files("web", "routers"):
            rel = path.relative_to(ROOT).as_posix()
            uses = _db_uses(ast.parse(path.read_text(encoding="utf-8")))
            allowed = CONTROLLER_DB_BASELINE.get(rel, 0)
            if uses > allowed:
                problems.append(f"{rel}: {uses} direct db uses (allowed {allowed}); move queries into a service")
        self.assertEqual(problems, [])

    def test_baseline_is_not_stale(self):
        # Keeps the ratchet tight: once a file improves, lock in the lower number.
        stale = []
        for rel, allowed in CONTROLLER_DB_BASELINE.items():
            path = ROOT / rel
            uses = _db_uses(ast.parse(path.read_text(encoding="utf-8"))) if path.exists() else 0
            if uses < allowed:
                stale.append(f"{rel}: now {uses}, baseline {allowed}; lower CONTROLLER_DB_BASELINE")
        self.assertEqual(stale, [])

    def test_services_do_not_render_or_redirect(self):
        problems = []
        for path in _py_files("services"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if name in FORBIDDEN_IN_SERVICES:
                    problems.append(f"{path.relative_to(ROOT)}:{node.lineno} uses {name}")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
