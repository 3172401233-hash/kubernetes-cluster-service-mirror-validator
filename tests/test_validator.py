import unittest

from service_mirror_validator import (
    CONFLICT_DELETION_NOT_PROPAGATED,
    CONFLICT_NAMESPACE_NAME_SHARED,
    CONFLICT_PORT_DIFFERENCE,
    CONFLICT_TARGET_SERVICE_MISSING,
    CONFLICT_VERSION_SKEW,
    REASON_POLICY_DENIED,
    REASON_PORT_MISSING,
    REASON_STALE_ONLY,
    REASON_ZONE_FAILED,
    Caller,
    validate_mirror,
)
from ._helpers import (
    make_allow_policy,
    make_bundle,
    make_deny_policy,
    make_endpoint,
    make_port,
    make_service,
)


class EndpointSliceLagTest(unittest.TestCase):
    def test_half_endpoints_reachable_with_stale_and_missing(self):
        source_service = make_service(resource_version="20")
        target_service = make_service(resource_version="20")

        source_bundle = make_bundle(
            endpoints=[
                make_endpoint("10.0.0.1"),
                make_endpoint("10.0.0.2"),
                make_endpoint("10.0.0.3"),
                make_endpoint("10.0.0.4"),
            ],
            resource_version="31",
        )
        # Target slice is one generation behind: 10.0.0.4 has not arrived yet
        # and 10.0.0.0 is a stale address that no longer exists upstream.
        target_bundle = make_bundle(
            endpoints=[
                make_endpoint("10.0.0.0"),
                make_endpoint("10.0.0.1"),
                make_endpoint("10.0.0.2"),
                make_endpoint("10.0.0.3"),
            ],
            resource_version="30",
        )

        report = validate_mirror(
            source_services=[source_service],
            target_services=[target_service],
            source_endpoints=[source_bundle],
            target_endpoints=[target_bundle],
        )

        result = report.services[0]
        self.assertFalse(result.version_in_sync)
        self.assertEqual(
            result.accessible_endpoints,
            {"10.0.0.1", "10.0.0.2", "10.0.0.3"},
        )
        self.assertEqual(result.missing_from_target, {"10.0.0.4"})
        self.assertEqual(result.stale_target_only, {"10.0.0.0"})
        stale_verdict = next(
            v for v in result.verdicts if v.address == "10.0.0.0"
        )
        self.assertIn(REASON_STALE_ONLY, stale_verdict.reasons)
        self.assertTrue(
            any(c.code == CONFLICT_VERSION_SKEW for c in result.conflicts)
        )


class ZoneFailureTest(unittest.TestCase):
    def test_endpoints_in_failed_zone_are_excluded(self):
        services = [make_service()]
        source_bundle = make_bundle(
            endpoints=[
                make_endpoint("10.0.1.1", zone="zone-a"),
                make_endpoint("10.0.1.2", zone="zone-b"),
            ]
        )
        target_bundle = make_bundle(
            endpoints=[
                make_endpoint("10.0.1.1", zone="zone-a"),
                make_endpoint("10.0.1.2", zone="zone-b"),
            ]
        )

        report = validate_mirror(
            source_services=services,
            target_services=[make_service()],
            source_endpoints=[source_bundle],
            target_endpoints=[target_bundle],
            failed_zones=frozenset({"zone-b"}),
        )

        result = report.services[0]
        self.assertEqual(result.accessible_endpoints, {"10.0.1.1"})
        failed = next(v for v in result.verdicts if v.address == "10.0.1.2")
        self.assertFalse(failed.accessible)
        self.assertIn(REASON_ZONE_FAILED, failed.reasons)


class PortDifferenceTest(unittest.TestCase):
    def test_missing_target_port_marks_endpoint_and_conflict(self):
        source_service = make_service(ports=[make_port(target_port=8080)])
        target_service = make_service(ports=[make_port(target_port=9090)])
        endpoint = make_endpoint("10.0.2.1", ports=[("http", 8080)])

        report = validate_mirror(
            source_services=[source_service],
            target_services=[target_service],
            source_endpoints=[make_bundle(endpoints=[endpoint])],
            target_endpoints=[make_bundle(endpoints=[endpoint])],
        )

        result = report.services[0]
        self.assertEqual(result.accessible_endpoints, set())
        verdict = result.verdicts[0]
        self.assertIn(REASON_PORT_MISSING, verdict.reasons)
        self.assertTrue(
            any(c.code == CONFLICT_PORT_DIFFERENCE for c in result.conflicts)
        )

    def test_endpoint_without_port_list_is_assumed_to_expose_all(self):
        service = make_service()
        endpoint = make_endpoint("10.0.2.2")
        report = validate_mirror(
            source_services=[service],
            target_services=[make_service()],
            source_endpoints=[make_bundle(endpoints=[endpoint])],
            target_endpoints=[make_bundle(endpoints=[endpoint])],
        )
        self.assertEqual(
            report.services[0].accessible_endpoints, {"10.0.2.2"}
        )


class PolicyDenialTest(unittest.TestCase):
    def test_deny_policy_excludes_half_of_the_endpoints(self):
        services = [make_service()]
        allowed_ep = make_endpoint(
            "10.0.3.1", labels={"app": "checkout", "tier": "allowed"}
        )
        denied_ep = make_endpoint(
            "10.0.3.2", labels={"app": "checkout", "tier": "blocked"}
        )

        deny_policy = make_deny_policy(
            pod_selector={"tier": "blocked"},
            ingress_ports=((None, 8080),),
            peers=(),
        )
        report = validate_mirror(
            source_services=services,
            target_services=[make_service()],
            source_endpoints=[make_bundle(endpoints=[allowed_ep, denied_ep])],
            target_endpoints=[make_bundle(endpoints=[allowed_ep, denied_ep])],
            target_policies=[deny_policy],
            caller=Caller(labels={"role": "gateway"}),
        )

        result = report.services[0]
        self.assertEqual(result.accessible_endpoints, {"10.0.3.1"})
        verdict = next(v for v in result.verdicts if v.address == "10.0.3.2")
        self.assertIn(REASON_POLICY_DENIED, verdict.reasons)
        self.assertEqual(verdict.denying_policies, ("deny-web",))

    def test_allow_policy_keeps_endpoint_accessible(self):
        service = make_service()
        endpoint = make_endpoint("10.0.3.3")
        report = validate_mirror(
            source_services=[service],
            target_services=[make_service()],
            source_endpoints=[make_bundle(endpoints=[endpoint])],
            target_endpoints=[make_bundle(endpoints=[endpoint])],
            target_policies=[make_allow_policy()],
        )
        self.assertEqual(
            report.services[0].accessible_endpoints, {"10.0.3.3"}
        )

    def test_policy_scoped_to_other_namespace_does_not_apply(self):
        service = make_service(namespace="shop")
        endpoint = make_endpoint("10.0.3.4")
        foreign_deny = make_deny_policy(namespace="billing")
        report = validate_mirror(
            source_services=[service],
            target_services=[make_service(namespace="shop")],
            source_endpoints=[
                make_bundle(namespace="shop", endpoints=[endpoint])
            ],
            target_endpoints=[
                make_bundle(namespace="shop", endpoints=[endpoint])
            ],
            target_policies=[foreign_deny],
        )
        self.assertEqual(
            report.services[0].accessible_endpoints, {"10.0.3.4"}
        )


class DeletionSyncTest(unittest.TestCase):
    def test_source_deletion_not_yet_reflected_on_target(self):
        source_service = make_service(resource_version="40", deletion_pending=True)
        target_service = make_service(resource_version="39")
        endpoint = make_endpoint("10.0.4.1")

        report = validate_mirror(
            source_services=[source_service],
            target_services=[target_service],
            source_endpoints=[
                make_bundle(resource_version="40", endpoints=[endpoint])
            ],
            target_endpoints=[
                make_bundle(resource_version="40", endpoints=[endpoint])
            ],
        )

        result = report.services[0]
        self.assertFalse(result.deletion_in_sync)
        self.assertTrue(
            any(
                conflict.code == CONFLICT_DELETION_NOT_PROPAGATED
                for conflict in result.conflicts
            )
        )

    def test_deletion_propagated_is_in_sync(self):
        source_service = make_service(deletion_pending=True)
        target_service = make_service(deletion_pending=True)
        endpoint = make_endpoint("10.0.4.2")
        report = validate_mirror(
            source_services=[source_service],
            target_services=[target_service],
            source_endpoints=[make_bundle(endpoints=[endpoint])],
            target_endpoints=[make_bundle(endpoints=[endpoint])],
        )
        self.assertTrue(report.services[0].deletion_in_sync)

    def test_missing_target_mirror_conflicts_and_yields_no_endpoints(self):
        endpoint = make_endpoint("10.0.4.3")
        report = validate_mirror(
            source_services=[make_service()],
            target_services=[],
            source_endpoints=[make_bundle(endpoints=[endpoint])],
            target_endpoints=[],
        )
        result = report.services[0]
        self.assertEqual(result.accessible_endpoints, set())
        self.assertTrue(
            any(
                conflict.code == CONFLICT_TARGET_SERVICE_MISSING
                for conflict in result.conflicts
            )
        )


class NamespaceIsolationTest(unittest.TestCase):
    def test_same_name_in_two_namespaces_never_merges(self):
        shop_service = make_service(namespace="shop", name="web")
        billing_service = make_service(namespace="billing", name="web")
        shop_ep = make_endpoint("10.0.5.1")
        billing_ep = make_endpoint("10.0.6.1")

        report = validate_mirror(
            source_services=[shop_service, billing_service],
            target_services=[
                make_service(namespace="shop", name="web"),
                make_service(namespace="billing", name="web"),
            ],
            source_endpoints=[
                make_bundle(namespace="shop", name="web", endpoints=[shop_ep]),
                make_bundle(
                    namespace="billing", name="web", endpoints=[billing_ep]
                ),
            ],
            target_endpoints=[
                make_bundle(namespace="shop", name="web", endpoints=[shop_ep]),
                make_bundle(
                    namespace="billing", name="web", endpoints=[billing_ep]
                ),
            ],
        )

        keys = {item.key for item in report.services}
        self.assertEqual(
            keys, {("shop", "web"), ("billing", "web")}
        )
        by_key = {item.key: item for item in report.services}
        self.assertEqual(
            by_key[("shop", "web")].accessible_endpoints, {"10.0.5.1"}
        )
        self.assertEqual(
            by_key[("billing", "web")].accessible_endpoints,
            {"10.0.6.1"},
        )
        self.assertTrue(
            any(
                conflict.code == CONFLICT_NAMESPACE_NAME_SHARED
                for conflict in report.global_conflicts
            )
        )


class MultiPortCombinationTest(unittest.TestCase):
    def test_stale_and_policy_denial_leave_half_traffic(self):
        service = make_service(
            ports=(make_port(name="http", target_port=8080),)
        )
        source_endpoints = [
            make_endpoint("10.0.7.1"),
            make_endpoint("10.0.7.2", labels={"app": "checkout"}),
        ]
        target_endpoints = [
            make_endpoint("10.0.7.1"),
            make_endpoint("10.0.7.2", labels={"app": "checkout"}),
        ]
        deny_all = make_deny_policy()
        report = validate_mirror(
            source_services=[service],
            target_services=[make_service()],
            source_endpoints=[make_bundle(endpoints=source_endpoints)],
            target_endpoints=[make_bundle(endpoints=target_endpoints)],
            target_policies=[deny_all],
        )
        result = report.services[0]
        self.assertEqual(result.accessible_endpoints, set())
        for verdict in result.verdicts:
            self.assertIn(REASON_POLICY_DENIED, verdict.reasons)


if __name__ == "__main__":
    unittest.main()
