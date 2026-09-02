from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class PluginLoadingTests(unittest.TestCase):
    def test_main_imports_sibling_backend_from_decky_working_directory(self) -> None:
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        script = textwrap.dedent(
            f"""
            import importlib.util
            import sys
            import types

            sys.modules["decky"] = types.SimpleNamespace(
                emit=lambda *args: None,
                logger=types.SimpleNamespace(
                    info=lambda *args: None,
                    warning=lambda *args: None,
                    error=lambda *args: None,
                ),
            )
            spec = importlib.util.spec_from_file_location("caret_control_plugin", {str(main_path)!r})
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            assert module.Plugin is not None
            assert module.EvdevControllerWorker is not None
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
