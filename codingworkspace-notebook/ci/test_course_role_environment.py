"""Run the real extension guard with stubbed Jupyter infrastructure, without Docker."""
import ast
import os
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
KEYS = ("CODINGWORKSPACE_COURSE_ROLE", "CODINGWORKSPACE_COURSE_ROLE_SUBJECT",
        "CODINGWORKSPACE_COURSE_ROLE_REVISION")


class RoleEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(zip(KEYS, ("ta", "staff-a", "roster-7")))
        self.env["JUPYTERHUB_USER"] = "staff-a"
        self.env["CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS"] = "120"
        self.patch = patch.dict(os.environ, self.env, clear=True)
        self.patch.start(); self.addCleanup(self.patch.stop)
        tree = ast.parse((ROOT / "codingworkspace_jupyter_runtime.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_jupyter_server_extension")
        required = next(n.value for n in ast.walk(function) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "required_environment" for t in n.targets))
        globals_ = dict(os=os, re=re, secrets=secrets, Any=object, time=SimpleNamespace(time=lambda: 1800000000),
                        TERMINATION_GRACE_ENV="CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS",
                        parse_termination_grace_seconds=int, derive_codingworkspace_shutdown_seconds=lambda _: 90,
                        termination_grace_seconds=120, expected_shutdown_seconds=90)
        self.environment = eval(compile(ast.Expression(required), "runtime-required-env", "eval"), globals_)
        self.environment.update(CODINGWORKSPACE_PROXY_AUTH_TOKEN="x" * 48,
                                CODINGWORKSPACE_OPENCODE_RUNTIME_VERSION="1.2.3",
                                CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH="0")
        process = SimpleNamespace(command=["/opt/conda/bin/python", "-I", "-P", "-m", "codingworkspace.server", "serve"],
            port=8768, absolute_url=True, name="codingworkspace", environment=self.environment,
            request_headers_override={"X-CodingWorkspace-Proxy-Token": "x" * 48},
            make_proxy_handler=lambda: (object, {}))
        globals_.update(ServerProxyConfig=lambda **_: SimpleNamespace(servers={"codingworkspace": process}),
                        url_path_join=lambda *args: "/".join(args), PREVIEW_CAPABILITY_ROUTE="preview",
                        make_preview_proxy_handler=lambda handler: handler, AddSlashHandler=object)
        exec(compile(ast.Module(body=[function], type_ignores=[]), "runtime-extension", "exec"), globals_)
        self.load = globals_[function.name]
        self.app = SimpleNamespace(jpserver_extensions={},
            web_app=SimpleNamespace(settings={"base_url": "/user/staff-a/"}, add_handlers=Mock()),
            log=SimpleNamespace(info=Mock()))

    def test_matching_spawn_roles_allow_registration(self):
        self.load(self.app)
        self.app.web_app.add_handlers.assert_called_once()

    def test_changed_or_missing_role_fields_refuse_registration(self):
        for key in KEYS:
            original = self.environment[key]
            for replacement in (None, "changed"):
                if replacement is None: self.environment.pop(key, None)
                else: self.environment[key] = replacement
                with self.subTest(key=key, value=replacement), self.assertRaisesRegex(RuntimeError, "overridden"):
                    self.load(self.app)
                self.environment[key] = original
        self.app.web_app.add_handlers.assert_not_called()

    def test_invalid_roles_subjects_and_partial_assignments_refuse_registration(self):
        for changes in ({KEYS[0]: "admin"}, {KEYS[1]: "someone-else"},
                        {KEYS[0]: ""}, {KEYS[2]: ""}, {KEYS[2]: "bad revision"}):
            with self.subTest(changes=changes), patch.dict(os.environ, changes):
                with self.assertRaisesRegex(RuntimeError, "Invalid or mismatched"):
                    self.load(self.app)
        self.app.web_app.add_handlers.assert_not_called()

    def test_mutation_between_proxy_evaluation_and_extension_load_is_rejected(self):
        # self.environment was evaluated before this mutation. This tests the
        # load-order guard, unlike the wiring-only expression test below.
        with patch.dict(os.environ, {KEYS[0]: "instructor"}):
            with self.assertRaisesRegex(RuntimeError, "overridden"):
                self.load(self.app)
        self.app.web_app.add_handlers.assert_not_called()

    def test_proxy_passes_exact_values_and_empty_defaults(self):
        # Wiring only: this does not authenticate a role or test evaluation order.
        tree = ast.parse((ROOT / "codingworkspace_server_proxy_config.py").read_text())
        env_node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "cw_env" for t in n.targets))
        expressions = {k.value: v for k, v in zip(env_node.keys, env_node.values)
                       if isinstance(k, ast.Constant) and k.value in KEYS}
        self.assertEqual(set(expressions), set(KEYS))
        for key, expression in expressions.items():
            code = compile(ast.Expression(expression), "proxy-role", "eval")
            self.assertEqual(eval(code, {"os": os}), self.env[key])
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(eval(code, {"os": os}), "")


if __name__ == "__main__":
    unittest.main()
