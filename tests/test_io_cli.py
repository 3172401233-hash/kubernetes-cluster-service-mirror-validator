import io
import json
import unittest
from contextlib import redirect_stdout

from service_mirror_validator.__main__ import main
from service_mirror_validator.io import load_snapshot
from service_mirror_validator.report import render_report


SNAPSHOT = {
    "source": {
        "services": [
            {
                "namespace": "shop",
                "name": "checkout",
                "labels": {"app": "checkout"},
                "ports": [
                    {"name": "http", "port": 80, "target_port": 8080}
                ],
                "resource_version": "20",
            }
        ],
        "endpoints": [
            {
                "namespace": "shop",
                "name": "checkout",
                "resource_version": "31",
                "endpoints": [
                    {"address": "10.0.0.1", "zone": "zone-a",
                     "labels": {"app": "checkout"}},
                    {"address": "10.0.0.2", "zone": "zone-a",
                     "labels": {"app": "checkout"}},
                ],
            }
        ],
    },
    "target": {
        "services": [
            {
                "namespace": "shop",
                "name": "checkout",
                "ports": [
                    {"name": "http", "port": 80, "target_port": 8080}
                ],
                "resource_version": "20",
            }
        ],
        "endpoints": [
            {
                "namespace": "shop",
                "name": "checkout",
                "resource_version": "30",
                "endpoints": [
                    {"address": "10.0.0.1", "zone": "zone-a",
                     "labels": {"app": "checkout"}},
                    {"address": "10.0.0.2", "zone": "zone-b",
                     "labels": {"app": "checkout"}},
                ],
            }
        ],
        "network_policies": [
            {
                "namespace": "shop",
                "name": "block-zone-b",
                "pod_selector": {"app": "checkout"},
                "ingress_ports": [{"port": 9090}],
                "peers": [],
            }
        ],
    },
    "failed_zones": ["zone-b"],
    "caller": {"labels": {"role": "gateway"}},
}


class SnapshotLoadingTest(unittest.TestCase):
    def test_load_snapshot_builds_domain_objects(self):
        path = self._write(SNAPSHOT)
        kwargs = load_snapshot(path)
        self.assertEqual(len(kwargs["source_services"]), 1)
        self.assertEqual(len(kwargs["target_policies"]), 1)
        self.assertEqual(kwargs["failed_zones"], frozenset({"zone-b"}))
        self.assertEqual(kwargs["caller"].labels, {"role": "gateway"})

    def _write(self, payload):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        with handle:
            json.dump(payload, handle)
        return handle.name


class CliTest(unittest.TestCase):
    def test_cli_renders_report_and_returns_nonzero_on_issues(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        with handle:
            json.dump(SNAPSHOT, handle)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([handle.name])

        output = buffer.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("Service mirror validation report", output)
        self.assertIn("10.0.0.1", output)
        # zone-b endpoint is failed and policy-denied; never reachable.
        self.assertIn("denied by target NetworkPolicy", output)

    def test_clean_snapshot_returns_zero(self):
        import tempfile

        clean = {
            "source": {
                "services": [
                    {
                        "namespace": "ns",
                        "name": "ok",
                        "ports": [{"name": "http", "port": 80}],
                        "resource_version": "1",
                    }
                ],
                "endpoints": [
                    {
                        "namespace": "ns",
                        "name": "ok",
                        "resource_version": "1",
                        "endpoints": [
                            {
                                "address": "10.1.0.1",
                                "zone": "zone-a",
                                "labels": {"app": "ok"},
                            }
                        ],
                    }
                ],
            },
            "target": {
                "services": [
                    {
                        "namespace": "ns",
                        "name": "ok",
                        "ports": [{"name": "http", "port": 80}],
                        "resource_version": "1",
                    }
                ],
                "endpoints": [
                    {
                        "namespace": "ns",
                        "name": "ok",
                        "resource_version": "1",
                        "endpoints": [
                            {
                                "address": "10.1.0.1",
                                "zone": "zone-a",
                                "labels": {"app": "ok"},
                            }
                        ],
                    }
                ],
            },
        }
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        with handle:
            json.dump(clean, handle)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([handle.name])
        self.assertEqual(exit_code, 0)
        self.assertIn("accessible endpoints: 1/1", buffer.getvalue())


class ReportRenderingTest(unittest.TestCase):
    def test_report_lists_versions_conflicts_and_reasons(self):
        from service_mirror_validator.validator import validate_mirror

        path = self._write(SNAPSHOT)
        report = validate_mirror(**load_snapshot(path))
        text = render_report(report)
        self.assertIn("service versions: source=20 target=20 (in sync)", text)
        self.assertIn("endpoint versions: source=31 target=30", text)
        self.assertIn("SKEWED", text)
        self.assertIn("zone in failure list", text)
        self.assertIn("block-zone-b", text)

    def _write(self, payload):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        with handle:
            json.dump(payload, handle)
        return handle.name


if __name__ == "__main__":
    unittest.main()
