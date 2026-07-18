import ast
from pathlib import Path


def test_detection_never_imports_agents_layer() -> None:
    root = Path(__file__).parents[1] / "detection"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    name.name != "agents" and not name.name.startswith("agents.")
                    for name in node.names
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "agents" and not node.module.startswith("agents.")
