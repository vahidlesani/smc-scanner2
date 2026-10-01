"""R63-ACCESS: isolated, offline tests for the Railway access probe only.

No trading engine imports, credentials, provider calls or deployment actions.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rw_access_probe", HERE / "rw_api.py")
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)

PROJECT = "11111111-1111-4111-8111-111111111111"
ENVIRONMENT = "22222222-2222-4222-8222-222222222222"
OTHER_ENVIRONMENT = "33333333-3333-4333-8333-333333333333"
SERVICE = "44444444-4444-4444-8444-444444444444"
PROJECT_TOKEN = "fixture-only-not-a-real-project-token"
ACCOUNT_TOKEN = "fixture-only-not-a-real-account-token"
PASSPHRASE = "fixture-only-not-a-real-backup-passphrase"


def connection(*nodes):
    return {"edges": [{"node": node} for node in nodes]}


def project_fixture():
    return {"project": {
        "name": "probe-project",
        "createdAt": "2026-10-01T00:00:00Z",
        "environments": connection(
            {"id": ENVIRONMENT, "name": "production"},
            {"id": OTHER_ENVIRONMENT, "name": "staging"},
        ),
        "services": connection(
            {"id": SERVICE, "name": "scanner", "serviceInstances": connection({
                "environmentId": ENVIRONMENT,
                "numReplicas": 1,
                "region": "test-region",
                "sleepApplication": False,
                "cronSchedule": None,
                "startCommand": "DO_NOT_PRINT_LAUNCH_CREDENTIAL=" + PROJECT_TOKEN,
                "latestDeployment": {"status": "SUCCESS", "createdAt": "2026-10-01T00:00:00Z"},
            })},
            {"id": "55555555-5555-4555-8555-555555555555", "name": "other-environment-service",
             "serviceInstances": connection({"environmentId": OTHER_ENVIRONMENT})},
        ),
        "volumes": connection(
            {"name": "data", "volumeInstances": connection({
                "environmentId": ENVIRONMENT, "mountPath": "/data",
                "currentSizeMB": 10, "sizeMB": 100,
                "serviceInstance": {"serviceName": "scanner"},
            })},
            {"name": "other-environment-volume", "volumeInstances": connection({
                "environmentId": OTHER_ENVIRONMENT, "mountPath": "/other",
                "currentSizeMB": 20, "sizeMB": 100,
            })},
        ),
    }}


class AccessProbeTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "RAILWAY_TOKEN": PROJECT_TOKEN,
            "RAILWAY_API_TOKEN": ACCOUNT_TOKEN, "BACKUP_PASSPHRASE": PASSPHRASE,
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def run_probe(self, data=None, errors=None, ids=(PROJECT, ENVIRONMENT)):
        stdout = io.StringIO()
        with mock.patch.object(rw, "ids", return_value=ids), \
                mock.patch.object(rw, "gql", return_value=(data, errors or [])) as gql, \
                contextlib.redirect_stdout(stdout):
            result = rw.access()
        return result, stdout.getvalue(), gql

    def test_success_is_read_only_and_never_requests_or_prints_start_commands(self):
        result, output, gql = self.run_probe(project_fixture())
        self.assertEqual(result, 0)
        query, variables = gql.call_args.args
        self.assertTrue(query.lstrip().startswith("query"))
        self.assertNotIn("mutation", query)
        self.assertNotIn("startCommand", query)
        self.assertNotIn("variables(", query)
        self.assertEqual(variables, {"id": PROJECT})
        self.assertNotIn("DO_NOT_PRINT", output)
        self.assertNotIn(PROJECT_TOKEN, output)
        self.assertNotIn("start=", output)

    def test_success_annotation_contains_only_safe_metadata(self):
        result, output, _ = self.run_probe(project_fixture())
        self.assertEqual(result, 0)
        notice = next(line for line in output.splitlines() if line.startswith("::notice"))
        report = json.loads(notice.split("::", 2)[-1])
        self.assertEqual(report, {
            "status": "verified", "project_id": PROJECT, "environment_id": ENVIRONMENT,
            "services": 1, "volumes": 1,
        })
        self.assertNotIn(ACCOUNT_TOKEN, output)
        self.assertNotIn(PASSPHRASE, output)

    def test_service_and_volume_reporting_is_filtered_to_selected_environment(self):
        result, output, _ = self.run_probe(project_fixture())
        self.assertEqual(result, 0)
        self.assertNotIn("other-environment-service", output)
        self.assertNotIn("other-environment-volume", output)
        self.assertIn("- scanner  id=", output)
        self.assertIn("- data:", output)

    def test_missing_project_id_fails_without_query(self):
        result, output, gql = self.run_probe(ids=(None, ENVIRONMENT))
        self.assertEqual(result, 1)
        gql.assert_not_called()
        self.assertIn("::error", output)
        self.assertNotIn('"status": "verified"', output)

    def test_missing_environment_id_fails_without_query(self):
        result, output, gql = self.run_probe(ids=(PROJECT, None))
        self.assertEqual(result, 1)
        gql.assert_not_called()
        self.assertIn("::error", output)

    def test_missing_project_data_fails_closed(self):
        for payload in (None, {}, {"project": None}):
            with self.subTest(payload=payload):
                result, output, _ = self.run_probe(payload)
                self.assertEqual(result, 1)
                self.assertIn("::error", output)
                self.assertNotIn('"status": "verified"', output)

    def test_graphql_error_with_partial_data_is_not_success(self):
        result, output, _ = self.run_probe(project_fixture(), ["Cannot query field requested by probe"])
        self.assertEqual(result, 1)
        self.assertIn("::error", output)
        self.assertNotIn('"status": "verified"', output)

    def test_selected_environment_must_be_verified(self):
        payload = copy.deepcopy(project_fixture())
        payload["project"]["environments"] = connection({"id": OTHER_ENVIRONMENT, "name": "staging"})
        result, output, _ = self.run_probe(payload)
        self.assertEqual(result, 1)
        self.assertIn("selected environment", output)
        self.assertNotIn('"status": "verified"', output)

    def test_error_output_redacts_all_configured_credentials(self):
        message = "Request rejected: " + " ".join((PROJECT_TOKEN, ACCOUNT_TOKEN, PASSPHRASE))
        result, output, _ = self.run_probe(errors=[message])
        self.assertEqual(result, 1)
        for value in (PROJECT_TOKEN, ACCOUNT_TOKEN, PASSPHRASE):
            self.assertNotIn(value, output)
        self.assertIn("[REDACTED]", output)

    def test_failed_token_lookup_redacts_error_and_cannot_succeed(self):
        stdout = io.StringIO()
        with mock.patch.object(rw, "gql", return_value=(None, ["Unauthorized: " + PROJECT_TOKEN])), \
                contextlib.redirect_stdout(stdout):
            result = rw.access()
        self.assertEqual(result, 1)
        self.assertNotIn(PROJECT_TOKEN, stdout.getvalue())
        self.assertIn("projectToken lookup failed", stdout.getvalue())
        self.assertIn("::error", stdout.getvalue())

    def test_annotation_escapes_workflow_command_injection(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rw._workflow_annotation("notice", "line1\n::error::injected\r100%")
        output = stdout.getvalue()
        self.assertEqual(len(output.splitlines()), 1)
        self.assertIn("%0A", output)
        self.assertIn("%0D", output)
        self.assertIn("100%25", output)
        self.assertFalse(any(line.startswith("::error::") for line in output.splitlines()))

    def test_no_workflow_commands_are_emitted_outside_actions(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            result, output, _ = self.run_probe(project_fixture())
        self.assertEqual(result, 0)
        self.assertNotIn("::notice", output)
        self.assertNotIn("::error", output)

    def test_annotation_levels_are_allowlisted(self):
        with self.assertRaises(ValueError):
            rw._workflow_annotation("set-output", "forbidden")

    def test_public_id_rejects_arbitrary_text(self):
        self.assertEqual(rw._public_id(PROJECT), PROJECT)
        self.assertEqual(rw._public_id("arbitrary\ntext"), "unavailable")

    def test_project_token_uses_project_access_header_not_account_bearer(self):
        headers = rw._headers()
        self.assertEqual(headers["Project-Access-Token"], PROJECT_TOKEN)
        self.assertNotIn("Authorization", headers)

    def test_request_is_access_only_and_contains_no_credential_field(self):
        request = json.loads((HERE / "request.json").read_text())
        self.assertEqual(request["action"], "access")
        self.assertEqual(request["service"], "")
        self.assertEqual(set(request), {"action", "service", "nonce", "note"})

    def test_workflow_selects_confirmed_secret_environment(self):
        workflow = (HERE.parent.parent / ".github" / "workflows" / "railway-ops.yml").read_text()
        self.assertRegex(workflow, r"(?m)^    environment: RAILWAY_TOKEN$")
        self.assertIn("RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}", workflow)
        self.assertNotIn("${{ vars.RAILWAY_TOKEN }}", workflow)

    def test_shell_access_does_not_fetch_variable_values(self):
        with tempfile.TemporaryDirectory() as directory:
            bin_path = Path(directory)
            railway = bin_path / "railway"
            railway.write_text('#!/bin/sh\n[ "$1" = "--version" ] || exit 90\necho "railway offline fixture"\n')
            railway.chmod(0o700)
            python = bin_path / "python3"
            python.write_text('#!/bin/sh\n[ "$2" = "access" ] || exit 91\necho "metadata-only offline fixture"\n')
            python.chmod(0o700)
            result = subprocess.run(
                ["/bin/bash", str(HERE / "ops.sh"), "access"],
                env={"PATH": str(bin_path) + ":/usr/bin:/bin"},
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("metadata-only offline fixture", result.stdout)
        self.assertNotIn("variable", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
