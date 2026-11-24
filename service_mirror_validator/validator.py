"""Offline cross-cluster service-mirror validation.

The validator consumes plain Python objects describing the source and
target clusters (services, endpoints, network policies, failed zones and
sync versions) and computes which target endpoints are actually reachable
for mirrored traffic.  It never opens a network connection.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from .model import (
    Caller,
    Endpoint,
    EndpointBundle,
    NetworkPolicy,
    Service,
    ServiceKey,
    endpoint_exposes_port,
    service_key,
)
from .policy import ingress_allowed

# Reason codes attached to unreachable endpoints.
REASON_NOT_READY = "not_ready"
REASON_ZONE_FAILED = "zone_failed"
REASON_PORT_MISSING = "port_missing"
REASON_POLICY_DENIED = "policy_denied"
REASON_STALE_ONLY = "stale_target_only"

# Conflict codes.
CONFLICT_DUPLICATE_KEY = "duplicate_service_key"
CONFLICT_NAMESPACE_NAME_SHARED = "same_name_different_namespace"
CONFLICT_PORT_DIFFERENCE = "port_difference"
CONFLICT_VERSION_SKEW = "version_skew"
CONFLICT_DELETION_NOT_PROPAGATED = "deletion_not_propagated"
CONFLICT_TARGET_SERVICE_MISSING = "target_service_missing"


@dataclass(frozen=True)
class EndpointVerdict:
    address: str
    zone: str
    accessible: bool
    reasons: Tuple[str, ...] = ()
    denying_policies: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Conflict:
    code: str
    message: str


@dataclass
class ServiceValidation:
    key: ServiceKey
    namespace: str
    name: str
    source_version: Optional[str] = None
    target_version: Optional[str] = None
    source_endpoint_version: Optional[str] = None
    target_endpoint_version: Optional[str] = None
    version_in_sync: bool = True
    service_version_in_sync: bool = True
    endpoint_version_in_sync: bool = True
    deletion_in_sync: bool = True
    accessible_endpoints: Set[str] = field(default_factory=set)
    source_endpoint_addresses: Set[str] = field(default_factory=set)
    target_endpoint_addresses: Set[str] = field(default_factory=set)
    verdicts: List[EndpointVerdict] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)

    @property
    def unreachable_endpoints(self) -> Set[str]:
        return {
            verdict.address
            for verdict in self.verdicts
            if not verdict.accessible
        }

    @property
    def missing_from_target(self) -> Set[str]:
        return self.source_endpoint_addresses - self.target_endpoint_addresses

    @property
    def stale_target_only(self) -> Set[str]:
        return self.target_endpoint_addresses - self.source_endpoint_addresses


@dataclass
class ValidationReport:
    services: List[ServiceValidation] = field(default_factory=list)
    global_conflicts: List[Conflict] = field(default_factory=list)

    @property
    def accessible_endpoint_count(self) -> int:
        return sum(len(item.accessible_endpoints) for item in self.services)

    @property
    def endpoint_count(self) -> int:
        return sum(len(item.source_endpoint_addresses) for item in self.services)


def _index_services(services: Sequence[Service]) -> Tuple[
    Dict[ServiceKey, Service], List[Conflict]
]:
    indexed: Dict[ServiceKey, Service] = {}
    conflicts: List[Conflict] = []
    for service in services:
        key = service_key(service.namespace, service.name)
        if key in indexed:
            conflicts.append(
                Conflict(
                    CONFLICT_DUPLICATE_KEY,
                    "duplicate service %s/%s supplied as input"
                    % (service.namespace, service.name),
                )
            )
            continue
        indexed[key] = service
    return indexed, conflicts


def _index_bundles(
    bundles: Sequence[EndpointBundle],
) -> Dict[ServiceKey, EndpointBundle]:
    return {
        service_key(bundle.namespace, bundle.name): bundle for bundle in bundles
    }


def _index_policies(
    policies: Sequence[NetworkPolicy],
) -> Dict[str, List[NetworkPolicy]]:
    by_namespace: Dict[str, List[NetworkPolicy]] = {}
    for policy in policies:
        by_namespace.setdefault(policy.namespace, []).append(policy)
    return by_namespace


def _versions_equal(left: Optional[str], right: Optional[str]) -> bool:
    if left is None or right is None:
        return left == right
    return str(left) == str(right)


def _evaluate_endpoint(
    endpoint: Endpoint,
    service: Service,
    namespace_policies: Sequence[NetworkPolicy],
    failed_zones: FrozenSet[str],
    caller: Caller,
    source_addresses: Set[str],
) -> EndpointVerdict:
    reasons: List[str] = []
    denying: List[str] = []

    if endpoint.address not in source_addresses:
        reasons.append(REASON_STALE_ONLY)
    if not endpoint.ready:
        reasons.append(REASON_NOT_READY)
    if endpoint.zone in failed_zones:
        reasons.append(REASON_ZONE_FAILED)

    for port in service.ports:
        if not endpoint_exposes_port(endpoint, port):
            reasons.append(REASON_PORT_MISSING)
            break

    for port in service.ports:
        if not endpoint_exposes_port(endpoint, port):
            continue
        allowed, policy_names = ingress_allowed(
            list(namespace_policies), endpoint, port, caller
        )
        if not allowed:
            reasons.append(REASON_POLICY_DENIED)
            denying.extend(policy_names)
            break

    return EndpointVerdict(
        address=endpoint.address,
        zone=endpoint.zone,
        accessible=not reasons,
        reasons=tuple(reasons),
        denying_policies=tuple(dict.fromkeys(denying)),
    )


def _validate_pair(
    key: ServiceKey,
    source_services: Dict[ServiceKey, Service],
    target_services: Dict[ServiceKey, Service],
    source_bundles: Dict[ServiceKey, EndpointBundle],
    target_bundles: Dict[ServiceKey, EndpointBundle],
    target_policies: Dict[str, List[NetworkPolicy]],
    failed_zones: FrozenSet[str],
    caller: Caller,
) -> ServiceValidation:
    namespace, name = key
    source = source_services.get(key)
    target = target_services.get(key)
    result = ServiceValidation(key=key, namespace=namespace, name=name)

    result.source_version = source.resource_version if source else None
    result.target_version = target.resource_version if target else None

    source_bundle = source_bundles.get(key)
    target_bundle = target_bundles.get(key)
    result.source_endpoint_version = (
        source_bundle.resource_version if source_bundle else None
    )
    result.target_endpoint_version = (
        target_bundle.resource_version if target_bundle else None
    )

    if source is None:
        # Endpoints existing only on the target have no source identity to
        # validate against; they are reported through global reconciliation.
        return result

    source_endpoints: Tuple[Endpoint, ...] = (
        source_bundle.endpoints if source_bundle else ()
    )
    target_endpoints: Tuple[Endpoint, ...] = (
        target_bundle.endpoints if target_bundle else ()
    )
    result.source_endpoint_addresses = {ep.address for ep in source_endpoints}
    result.target_endpoint_addresses = {ep.address for ep in target_endpoints}

    # --- deletion propagation ---------------------------------------------
    source_deleting = source.deletion_pending or (
        source_bundle is not None and source_bundle.deletion_pending
    )
    target_deleting = target is None or target.deletion_pending or (
        target_bundle is not None and target_bundle.deletion_pending
    )
    result.deletion_in_sync = not source_deleting or target_deleting
    if source_deleting and not target_deleting:
        result.conflicts.append(
            Conflict(
                CONFLICT_DELETION_NOT_PROPAGATED,
                "source service %s/%s is deleting but the target mirror "
                "still exists" % (namespace, name),
            )
        )
    if target is None:
        result.conflicts.append(
            Conflict(
                CONFLICT_TARGET_SERVICE_MISSING,
                "target mirror of %s/%s is absent" % (namespace, name),
            )
        )
        result.version_in_sync = False
        return result

    # --- service / endpoint version skew ----------------------------------
    service_versions_equal = _versions_equal(
        result.source_version, result.target_version
    )
    endpoint_versions_equal = _versions_equal(
        result.source_endpoint_version, result.target_endpoint_version
    )
    result.service_version_in_sync = service_versions_equal
    result.endpoint_version_in_sync = endpoint_versions_equal
    result.version_in_sync = (
        service_versions_equal and endpoint_versions_equal
    )
    if not result.version_in_sync:
        result.conflicts.append(
            Conflict(
                CONFLICT_VERSION_SKEW,
                "sync version skew on %s/%s: service %s->%s, endpoints "
                "%s->%s"
                % (
                    namespace,
                    name,
                    result.source_version,
                    result.target_version,
                    result.source_endpoint_version,
                    result.target_endpoint_version,
                ),
            )
        )

    # --- port differences --------------------------------------------------
    source_ports = {(port.name, port.port, port.target_port, port.protocol)
                    for port in source.ports}
    target_ports = {(port.name, port.port, port.target_port, port.protocol)
                    for port in target.ports}
    if source_ports != target_ports:
        result.conflicts.append(
            Conflict(
                CONFLICT_PORT_DIFFERENCE,
                "port definitions differ on %s/%s: source-only %s, "
                "target-only %s"
                % (
                    namespace,
                    name,
                    sorted(source_ports - target_ports),
                    sorted(target_ports - source_ports),
                ),
            )
        )

    # --- reachable endpoint set -------------------------------------------
    # A mirrored endpoint must exist on both sides.  Source-only addresses
    # are missing mirrors; target-only addresses are stale EndpointSlices.
    mirrored_addresses = (
        result.source_endpoint_addresses & result.target_endpoint_addresses
    )
    namespace_policies = target_policies.get(namespace, [])
    for endpoint in target_endpoints:
        verdict = _evaluate_endpoint(
            endpoint=endpoint,
            service=target,
            namespace_policies=namespace_policies,
            failed_zones=failed_zones,
            caller=caller,
            source_addresses=result.source_endpoint_addresses,
        )
        result.verdicts.append(verdict)
        if verdict.accessible and endpoint.address in mirrored_addresses:
            result.accessible_endpoints.add(endpoint.address)

    return result


def _cross_namespace_conflicts(
    services: Sequence[Service],
) -> List[Conflict]:
    namespaces_by_name: Dict[str, Set[str]] = {}
    for service in services:
        namespaces_by_name.setdefault(service.name, set()).add(
            service.namespace
        )
    conflicts: List[Conflict] = []
    for name, namespaces in sorted(namespaces_by_name.items()):
        if len(namespaces) > 1:
            conflicts.append(
                Conflict(
                    CONFLICT_NAMESPACE_NAME_SHARED,
                    "service name %r exists in multiple namespaces %s; "
                    "they are validated separately and must never be merged"
                    % (name, sorted(namespaces)),
                )
            )
    return conflicts


def validate_mirror(
    source_services: Sequence[Service],
    target_services: Sequence[Service],
    source_endpoints: Sequence[EndpointBundle],
    target_endpoints: Sequence[EndpointBundle],
    target_policies: Optional[Sequence[NetworkPolicy]] = None,
    failed_zones: Optional[FrozenSet[str]] = None,
    caller: Optional[Caller] = None,
) -> ValidationReport:
    """Compute the accessible endpoint set for every mirrored service.

    Services are keyed by ``(namespace, name)`` so same-named objects in
    different namespaces can never be merged.  Endpoints missing from the
    target, stale target-only endpoints, failed-zone endpoints and endpoints
    denied by a target NetworkPolicy are all excluded from the accessible
    set.
    """

    source_index, source_dupes = _index_services(source_services)
    target_index, target_dupes = _index_services(target_services)
    report = ValidationReport()
    report.global_conflicts.extend(source_dupes)
    report.global_conflicts.extend(target_dupes)
    report.global_conflicts.extend(
        _cross_namespace_conflicts(list(source_services) + list(target_services))
    )

    source_bundles = _index_bundles(source_endpoints)
    target_bundles = _index_bundles(target_endpoints)
    policy_index = _index_policies(target_policies or [])
    failed = frozenset(failed_zones or ())
    traffic_caller = caller or Caller()

    for key in sorted(source_index):
        report.services.append(
            _validate_pair(
                key=key,
                source_services=source_index,
                target_services=target_index,
                source_bundles=source_bundles,
                target_bundles=target_bundles,
                target_policies=policy_index,
                failed_zones=failed,
                caller=traffic_caller,
            )
        )
    return report
