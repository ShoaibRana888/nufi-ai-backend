"""Purity guard for services.health_trends.

The module's whole value is that it can be tested without a database, a
network, or an event loop. "Please keep it pure" in a docstring does not
survive contact with a deadline; these tests do. If one of them fails, the fix
is to move the I/O back out to the caller, not to relax the test.
"""
import ast
import os

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'services', 'health_trends.py',
)


def _module_ast():
    with open(MODULE_PATH) as handle:
        return ast.parse(handle.read())


def test_module_defines_no_coroutines():
    coroutines = [
        node.name for node in ast.walk(_module_ast())
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert coroutines == [], (
        f"health_trends must stay synchronous; found async def {coroutines}"
    )


def test_module_imports_nothing_that_can_reach_the_database():
    forbidden = ('services.supabase_service', 'supabase', 'httpx', 'aiohttp',
                 'requests', 'openai')
    imported = set()

    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = sorted(
        name for name in imported
        if any(name == f or name.startswith(f + '.') for f in forbidden)
    )
    assert offenders == [], (
        f"health_trends must not import I/O; found {offenders}"
    )


def test_module_defines_only_free_functions():
    """No classes: these are functions, and `self` would be a lie."""
    tree = _module_ast()
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert classes == [], f"health_trends should hold free functions, found {classes}"


def test_module_imports_without_any_environment():
    """Importable with no SUPABASE_URL, no keys, nothing configured."""
    import importlib

    module = importlib.import_module('services.health_trends')
    assert callable(module.weight_status)
