"""Unit tests for scripts/eva.py. Standard library only; no Docker needed."""

import io
import re
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import eva  # noqa: E402


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class I18nTests(unittest.TestCase):
    def test_every_message_has_every_language(self):
        for key, entry in eva.STR.items():
            self.assertEqual(len(entry), len(eva.LANGS), key)
            for text in entry:
                self.assertTrue(text.strip(), key)

    def test_placeholders_match_across_languages(self):
        for key, entry in eva.STR.items():
            sets = [placeholders(text) for text in entry]
            self.assertTrue(all(s == sets[0] for s in sets), key)

    def test_unknown_key_falls_back_to_the_key(self):
        self.assertEqual(eva.t("no.such.key"), "no.such.key")

    def test_formatting(self):
        for lang in eva.LANGS:
            with mock.patch.object(eva, "LANG", lang):
                self.assertIn("api", eva.t("notfound", name="api"))

    def test_usage_lists_the_same_commands_in_every_language(self):
        def commands(text):
            found = (re.match(r"  eva (\S+)", ln) for ln in text.splitlines())
            return {m.group(1) for m in found if m}
        usages = [commands(text) for text in eva.STR["usage"]]
        self.assertGreater(len(usages[0]), 5)
        self.assertEqual(usages[0], usages[1])


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.multiple(
            eva, CONFIG_DIR=self.tmp / "config", ENV_FILE=self.tmp / "config" / ".env")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_write_and_read_env(self):
        eva.write_env("language", "en")
        eva.write_env("containers_location", "/srv/stacks")
        eva.write_env("language", "es")  # overwrite, no duplicate line
        self.assertEqual(eva.read_env(), {"language": "es", "containers_location": "/srv/stacks"})
        self.assertEqual(eva.ENV_FILE.read_text().count("language="), 1)

    def test_read_env_ignores_comments_and_quotes(self):
        eva.CONFIG_DIR.mkdir()
        eva.ENV_FILE.write_text('# note\n\nlanguage="en"\nexcluded_stacks=db, proxy\n')
        env = eva.read_env()
        self.assertEqual(env["language"], "en")
        self.assertEqual(eva.excluded_stacks(), {"db", "proxy"})

    def test_missing_env_is_empty(self):
        self.assertEqual(eva.read_env(), {})
        self.assertEqual(eva.excluded_stacks(), set())

    def test_unknown_language_falls_back_to_spanish(self):
        eva.write_env("language", "xx")
        with mock.patch.object(eva, "LANG", "en"):
            eva.load_language()
            self.assertEqual(eva.LANG, "es")

    def test_load_config_requires_an_existing_folder(self):
        eva.write_env(eva.ENV_KEY, str(self.tmp / "missing"))
        self.assertFalse(eva.load_config())
        eva.write_env(eva.ENV_KEY, str(self.tmp))
        with mock.patch.object(eva, "ROOT", None):
            self.assertTrue(eva.load_config())
            self.assertEqual(eva.ROOT, self.tmp)


class StackDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        for rel in ("blog/compose.yml", "app/docker-compose.yaml", "infra/proxy/compose.yaml",
                    "blog/data/compose.yml", "both/compose.yml", "both/docker-compose.yml"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("services: {}\n")
        patcher = mock.patch.object(eva, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_finds_every_compose_file_name(self):
        names = sorted(s.parent.name for s in eva.find_stacks())
        self.assertEqual(names, ["app", "blog", "both", "proxy"])

    def test_skips_data_folders(self):
        self.assertFalse(any("data" in s.parts for s in eva.find_stacks()))

    def test_prefers_compose_yml_over_docker_compose(self):
        both = [s for s in eva.find_stacks() if s.parent.name == "both"]
        self.assertEqual([s.name for s in both], ["compose.yml"])

    def test_find_stack_by_name(self):
        self.assertEqual(eva.find_stack("proxy").parent.name, "proxy")
        self.assertIsNone(eva.find_stack("nope"))

    def test_bulk_selection_honours_excluded_stacks(self):
        with mock.patch.object(eva, "excluded_stacks", return_value={"proxy"}):
            targets = eva.resolve_targets("all", "title", eva.find_stacks())
        self.assertEqual(sorted(t.parent.name for t in targets), ["app", "blog", "both"])
        self.assertEqual(eva.SKIPPED, ["proxy"])

    def test_naming_a_stack_ignores_the_exclusion(self):
        with mock.patch.object(eva, "excluded_stacks", return_value={"proxy"}):
            targets = eva.resolve_targets("proxy", "title", eva.find_stacks())
        self.assertEqual([t.parent.name for t in targets], ["proxy"])


class CompletionTests(unittest.TestCase):
    def test_scripts_list_every_command(self):
        names = [name for name, _ in eva.COMP_COMMANDS]
        for shell in ("zsh", "bash"):
            script = eva.completion_script(shell)
            for name in names:
                self.assertIn(name, script, shell)
            self.assertNotIn("@CMDS@", script)
            self.assertNotIn("@NAMES@", script)

    def test_every_completed_command_is_dispatched(self):
        source = Path(eva.__file__).read_text()
        for name, _ in eva.COMP_COMMANDS:
            self.assertIn('"%s"' % name, source, name)

    @unittest.skipUnless(shutil.which("bash"), "bash not installed")
    def test_bash_script_is_valid_syntax(self):
        result = subprocess.run(["bash", "-n"], input=eva.completion_script("bash"),
                                universal_newlines=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_script_is_valid_syntax(self):
        result = subprocess.run(["zsh", "-n"], input=eva.completion_script("zsh"),
                                universal_newlines=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)


class CliTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = eva.main(list(argv))
        return code, out.getvalue()

    def test_version(self):
        code, out = self.run_main("--version")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("eva " + eva.VERSION))

    def test_help_in_every_language(self):
        for lang in eva.LANGS:
            with mock.patch.object(eva, "LANG", lang), \
                    mock.patch.object(eva, "load_language"):
                code, out = self.run_main("--help")
            self.assertEqual(code, 0)
            self.assertIn("eva doctor", out)

    def test_completion_prints_a_script(self):
        code, out = self.run_main("completion", "bash")
        self.assertEqual(code, 0)
        self.assertIn("complete -F _eva eva", out)

    def test_unknown_completion_shell_fails(self):
        code, _ = self.run_main("completion", "fish")
        self.assertEqual(code, 1)


class UpdateCheckTests(unittest.TestCase):
    def test_pending_stacks_are_those_with_new_or_missing_images(self):
        a, b, c = Path("a/compose.yml"), Path("b/compose.yml"), Path("c/compose.yml")
        result = {a: [("x", "ok")], b: [("y", "new")], c: [("z", "unknown"), ("w", "missing")]}
        self.assertEqual(eva.pending_stacks(result), [b, c])

    def test_image_state_compares_local_and_remote_digests(self):
        def fake_run(cmd, **_):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, '["repo/app@sha256:aaa"]', "")
            return subprocess.CompletedProcess(cmd, 0, "sha256:%s\n" % self.remote, "")
        with mock.patch.object(eva, "run", side_effect=fake_run):
            self.remote = "aaa"
            self.assertEqual(eva.image_state("repo/app"), "ok")
            self.remote = "bbb"
            self.assertEqual(eva.image_state("repo/app"), "new")

    def test_image_state_without_local_image(self):
        failed = subprocess.CompletedProcess([], 1, "", "no such image")
        with mock.patch.object(eva, "run", return_value=failed):
            self.assertEqual(eva.image_state("repo/app"), "missing")


if __name__ == "__main__":
    unittest.main()
