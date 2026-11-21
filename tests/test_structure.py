"""Guards the module layout so the backend stays easy to change.

Each module must import cleanly on its own (this catches import cycles, which the layered design forbids),
and nobody may reach "up" the layers.
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / 'aos'

# Lowest layer first. A module may import only from modules earlier in this list.
LAYERS = ['config', 'db', 'settings', 'accounts', 'approvals', 'comments', 'attachments', 'trash', 'digest', 'records', 'reports', 'backups', 'automation', 'server']


class StructureTests(unittest.TestCase):
    def test_every_module_is_in_the_layer_list(self):
        found = sorted(p.stem for p in PACKAGE.glob('*.py') if p.stem != '__init__')
        self.assertEqual(found, sorted(LAYERS), 'add new modules to LAYERS (and think about where they belong)')

    def test_each_module_imports_on_its_own(self):
        for name in LAYERS:
            result = subprocess.run([sys.executable, '-I', '-c', f'import sys; sys.path.insert(0, {str(ROOT)!r}); import aos.{name}'],
                                    capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, f'aos.{name} failed to import alone:\n{result.stderr}')

    def test_modules_only_depend_on_lower_layers(self):
        for index, name in enumerate(LAYERS):
            tree = ast.parse((PACKAGE / f'{name}.py').read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                    target = node.module.split('.')[0]
                    self.assertIn(target, LAYERS, f'{name} imports unknown module {target}')
                    self.assertLess(LAYERS.index(target), index, f'{name} must not import {target} (it is a higher layer)')

    def test_no_wildcard_imports_inside_the_package(self):
        for path in PACKAGE.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn('*', [a.name for a in node.names], f'{path.name} uses a wildcard import')

    def test_config_constants_are_read_through_the_module(self):
        """`config.AUTH` can be changed at run time; `from .config import AUTH` would freeze a copy."""
        for path in PACKAGE.glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == 'config':
                    self.fail(f'{path.name}: use `from . import config` and read config.NAME')

    def test_the_entry_point_re_exports_every_module(self):
        """`import app` must keep exposing everything, so a new module has to be added to app.py too."""
        facade = (ROOT / 'app.py').read_text(encoding='utf-8')
        for name in LAYERS:
            if name != 'config':
                self.assertIn(f'from aos.{name} import *', facade, f'app.py does not re-export aos.{name}')

    def test_entry_point_still_exposes_the_public_api(self):
        code = ('import sys; sys.path.insert(0, %r); import app; '
                'assert all(hasattr(app, n) for n in ("Handler", "init", "main", "decide_approval", "create_user", "config", "DB")); '
                'assert app.config.DB == app.DB') % str(ROOT)
        result = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
