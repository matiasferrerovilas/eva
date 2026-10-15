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


class StatsTests(unittest.TestCase):
    def test_parse_size(self):
        self.assertAlmostEqual(eva.parse_size("245.3MiB"), 245.3 * 1024 ** 2)
        self.assertAlmostEqual(eva.parse_size("1.5GB"), 1.5e9)
        self.assertEqual(eva.parse_size("12B"), 12)
        self.assertEqual(eva.parse_size(""), 0)
        self.assertEqual(eva.parse_size(None), 0)

    def test_human(self):
        self.assertEqual(eva.human(512), "512 B")
        self.assertEqual(eva.human(2048), "2.0 KiB")
        self.assertEqual(eva.human(5 * 1024 ** 2), "5.0 MiB")
        self.assertEqual(eva.human(3 * 1024 ** 3), "3.00 GiB")

    def test_container_stats_parses_docker_output(self):
        out = "\n".join([
            '{"Name":"api","CPUPerc":"12.50%","MemUsage":"245.3MiB / 7.8GiB","MemPerc":"3.05%"}',
            "not json",
            '{"Name":"db","CPUPerc":"--","MemUsage":"1GiB / 7.8GiB","MemPerc":"--"}',
        ])
        with mock.patch.object(eva, "run", return_value=subprocess.CompletedProcess([], 0, out, "")):
            stats = eva.container_stats()
        self.assertEqual(sorted(stats), ["api", "db"])
        self.assertEqual(stats["api"]["cpu"], 12.5)
        self.assertAlmostEqual(stats["api"]["mem"], 245.3 * 1024 ** 2)
        self.assertEqual(stats["db"]["cpu"], 0.0)  # docker prints "--" for a starting container

    def test_stack_usage_sums_running_containers(self):
        stats = {"a": {"cpu": 10.0, "mem": 100.0, "mem_pct": 1.0},
                 "b": {"cpu": 5.5, "mem": 50.0, "mem_pct": 0.5}}
        mine = [{"name": "a"}, {"name": "b"}, {"name": "stopped"}]
        usage = eva.stack_usage(mine, stats)
        self.assertEqual((usage["cpu"], usage["mem"]), (15.5, 150.0))
        self.assertIsNone(eva.stack_usage([{"name": "stopped"}], stats))

    def test_render_ps_shows_cpu_and_ram_for_running_containers(self):
        cts = [{"name": "api", "stack": "app", "state": "running", "status": "Up 1 hour",
                "networks": "net", "ports": ""},
               {"name": "old", "stack": "app", "state": "exited", "status": "Exited (0)",
                "networks": "", "ports": ""}]
        stats = {"api": {"cpu": 12.5, "mem": 245.3 * 1024 ** 2, "mem_pct": 3.0}}
        out = eva.capture(lambda: eva.render_ps(cts, stats))
        self.assertIn("12.5%", out)
        self.assertIn("245.3 MiB", out)
        self.assertIn("CPU", out)

    def test_show_live_prints_once_without_a_terminal(self):
        calls = []
        out = io.StringIO()
        with redirect_stdout(out):
            eva.show_live(lambda: calls.append(1) or "frame\n", interval=3)
        self.assertEqual((calls, out.getvalue()), ([1], "frame\n"))


class DestructiveActionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(eva, "ASSUME_YES", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_confirm_with_yes_flag_does_not_ask(self):
        with mock.patch.object(eva, "ASSUME_YES", True), mock.patch.object(eva, "pick") as pick:
            self.assertTrue(eva.confirm("sure?"))
        pick.assert_not_called()

    def test_confirm_without_a_terminal_refuses(self):
        with mock.patch.object(eva.sys, "stdin") as stdin, redirect_stdout(io.StringIO()):
            stdin.isatty.return_value = False
            self.assertFalse(eva.confirm("sure?"))

    def test_confirm_follows_the_picker(self):
        with mock.patch.object(eva.sys, "stdin") as stdin, \
                mock.patch.object(eva.sys, "stdout") as stdout, \
                mock.patch.object(eva, "pick", side_effect=[1, 0, None]):
            stdin.isatty.return_value = stdout.isatty.return_value = True
            self.assertTrue(eva.confirm("sure?"))
            self.assertFalse(eva.confirm("sure?"))
            self.assertFalse(eva.confirm("sure?"))  # Esc

    def stacks(self):
        return [Path("a/compose.yml"), Path("b/compose.yml")]

    def run_compose(self, action, name, confirmed):
        ok_run = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(eva, "find_stacks", return_value=self.stacks()), \
                mock.patch.object(eva, "containers", return_value=[]), \
                mock.patch.object(eva, "confirm", return_value=confirmed) as confirm, \
                mock.patch.object(eva, "run", return_value=ok_run) as run, \
                redirect_stdout(io.StringIO()):
            eva.cmd_compose(action, name)
        return confirm, run

    def test_down_asks_first_and_stops_when_declined(self):
        confirm, run = self.run_compose("down", "all", confirmed=False)
        confirm.assert_called_once()
        run.assert_not_called()

    def test_down_all_is_flagged_as_dangerous(self):
        confirm, _ = self.run_compose("down", "all", confirmed=True)
        self.assertTrue(confirm.call_args[1]["danger"])

    def test_down_runs_once_confirmed(self):
        _, run = self.run_compose("down", "all", confirmed=True)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args[0][0], ["docker", "compose", "down"])

    def test_up_and_restart_do_not_ask(self):
        for action in ("up", "restart"):
            confirm, run = self.run_compose(action, "all", confirmed=False)
            confirm.assert_not_called()
            self.assertEqual(run.call_count, 2)

    def test_yes_flag_is_parsed_and_removed_from_the_arguments(self):
        with redirect_stdout(io.StringIO()):
            eva.main(["--version", "--yes"])
        self.assertTrue(eva.ASSUME_YES)
        with redirect_stdout(io.StringIO()):
            eva.main(["--version"])
        self.assertFalse(eva.ASSUME_YES)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(eva, "ASSUME_YES", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_volumes_level_can_delete_volumes(self):
        flat = {k: [" ".join(c) for c in cmds] for k, cmds in eva.CLEAN_COMMANDS.items()}
        self.assertFalse(any("--volumes" in c for c in flat["safe"] + flat["all"]))
        self.assertTrue(any("--volumes" in c for c in flat["volumes"]))

    def test_safe_cleanup_never_touches_containers_or_volumes(self):
        flat = " ".join(" ".join(c) for c in eva.CLEAN_COMMANDS["safe"])
        self.assertNotIn("system prune", flat)
        self.assertNotIn("volume", flat)

    def test_updates_use_the_safe_level_by_default(self):
        import inspect
        self.assertEqual(inspect.signature(eva.docker_prune).parameters["level"].default, "safe")

    def cleanup(self, level, confirmed=False):
        preview = {"volumes": ["data_vol"], "stopped": [], "dangling": [], "unused": [], "df": ""}
        with mock.patch.object(eva, "docker_prune") as prune, \
                mock.patch.object(eva, "cleanup_preview", return_value=preview), \
                mock.patch.object(eva, "confirm", return_value=confirmed) as confirm, \
                mock.patch.object(eva.sys, "stdin") as stdin, \
                redirect_stdout(io.StringIO()):
            stdin.isatty.return_value = False
            eva.cmd_cleanup(level)
        return prune, confirm

    def test_safe_cleanup_runs_without_asking(self):
        prune, confirm = self.cleanup("safe")
        confirm.assert_not_called()
        prune.assert_called_once_with("safe")

    def test_volume_cleanup_needs_confirmation(self):
        prune, confirm = self.cleanup("volumes", confirmed=False)
        confirm.assert_called_once()
        prune.assert_not_called()
        prune, _ = self.cleanup("volumes", confirmed=True)
        prune.assert_called_once_with("volumes")

    def test_full_cleanup_needs_confirmation(self):
        prune, confirm = self.cleanup("all", confirmed=False)
        confirm.assert_called_once()
        prune.assert_not_called()

    def test_preview_separates_dangling_unused_and_used_images(self):
        def fake_run(cmd, **_):
            if cmd[:2] == ["docker", "ps"] and "-aq" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "c1\n", "")
            if cmd[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, "sha256:used\n", "")
            if cmd[:3] == ["docker", "image", "ls"]:
                rows = ["sha256:used\tapp:1\t100MB", "sha256:old\t<none>:<none>\t50MB",
                        "sha256:spare\tother:2\t20MB"]
                return subprocess.CompletedProcess(cmd, 0, "\n".join(rows), "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(eva, "run", side_effect=fake_run):
            preview = eva.cleanup_preview()
        self.assertEqual(preview["dangling"], ["<none>:<none> (50MB)"])
        self.assertEqual(preview["unused"], ["other:2 (20MB)"])


if __name__ == "__main__":
    unittest.main()
