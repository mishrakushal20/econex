"""
Structurally verifies doc section 2's absolute architectural principle:
"The deterministic core must contain NO LLM client dependency. This
boundary must be structurally verifiable."

This test does not just eyeball imports — it parses every .py file under
app/core/ with the `ast` module and fails if any of them import app.llm,
app.agents, or any known LLM SDK/network-calling module.
"""

import ast
import os
import unittest

CORE_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "core")

FORBIDDEN_MODULE_PREFIXES = (
    "app.llm",
    "app.agents",
    "anthropic",
    "openai",
)
# NOTE: razorpay_adapter.py lives in app/core per doc section 27's repo
# layout, and it legitimately needs network I/O (urllib) to call Razorpay's
# REST API. The architectural boundary in doc section 2 is specifically "no
# LLM client dependency", not "no I/O at all" — so urllib/requests/httpx are
# intentionally NOT in this forbidden list.


def _imported_modules(path):
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


class TestArchitectureBoundary(unittest.TestCase):
    def test_core_has_no_llm_dependency(self):
        violations = []
        for filename in os.listdir(CORE_DIR):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(CORE_DIR, filename)
            for module in _imported_modules(path):
                if any(module.startswith(prefix) for prefix in FORBIDDEN_MODULE_PREFIXES):
                    violations.append(f"{filename} imports forbidden module '{module}'")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_core_directory_is_non_empty(self):
        # guards against the test silently passing because the core dir is missing
        py_files = [f for f in os.listdir(CORE_DIR) if f.endswith(".py")]
        self.assertGreaterEqual(len(py_files), 6)


if __name__ == "__main__":
    unittest.main()
