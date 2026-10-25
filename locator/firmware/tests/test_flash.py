"""Exercise the flash helper with a fake CLI: never access a physical serial port."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "flash.sh"
FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CLI_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["core", "list"]:
    print(json.dumps({"platforms": [{"id": "esp32:esp32", "installed_version": os.environ.get("CORE", "3.3.12")}]}))
elif args[:2] == ["board", "list"]:
    print(json.dumps({"detected_ports": [{"port": {"protocol": "serial", "address": "/dev/fake"}}]}))
elif args[0] == "compile":
    sys.exit(int(os.environ.get("COMPILE_EXIT", "0")))
elif args[0] == "upload":
    sys.exit(int(os.environ.get("UPLOAD_EXIT", "0")))
else:
    sys.exit(99)
'''


class FlashTests(unittest.TestCase):
    def run_helper(self, *arguments, **settings):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / "arduino-cli"
            cli.write_text(FAKE_CLI)
            cli.chmod(0o755)
            log = root / "calls.jsonl"
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", CLI_LOG=str(log), **settings)
            result = subprocess.run(
                ["bash", str(SCRIPT), *arguments], env=env, input="",
                text=True, capture_output=True, check=False,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_compile_only_never_uploads(self):
        result, calls = self.run_helper("--compile-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in calls], ["core", "compile"])
        self.assertIn("No board was flashed", result.stdout)

    def test_wrover_flag_reaches_compiler(self):
        result, calls = self.run_helper("--wrover", "--compile-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compiler.cpp.extra_flags=-DBOARD_WROVER", calls[-1])

    def test_explicit_port_uploads_only_after_compile(self):
        result, calls = self.run_helper("--port", "/dev/test board")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in calls], ["core", "compile", "upload"])
        self.assertIn("/dev/test board", calls[-1])
        self.assertIn("hold the BOOT button if the upload hangs", result.stdout)

    def test_compile_failure_does_not_upload(self):
        result, calls = self.run_helper("--port", "/dev/fake", COMPILE_EXIT="7")
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("upload", [call[0] for call in calls])

    def test_upload_failure_is_not_success(self):
        result, _ = self.run_helper("--port", "/dev/fake", UPLOAD_EXIT="9")
        self.assertEqual(result.returncode, 9)
        self.assertNotIn("Upload finished", result.stdout)

    def test_wrong_core_gives_install_instructions(self):
        result, calls = self.run_helper("--compile-only", CORE="2.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("core install esp32:esp32@3.3.12", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_discovery_requires_interactive_confirmation(self):
        result, calls = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--port SERIAL_PORT", result.stderr)
        self.assertIn("/dev/fake", result.stdout)
        self.assertNotIn("upload", [call[0] for call in calls])

    def test_invalid_argument_and_missing_port(self):
        for arguments in [("--unknown",), ("--port",)]:
            with self.subTest(arguments=arguments):
                result, calls = self.run_helper(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
