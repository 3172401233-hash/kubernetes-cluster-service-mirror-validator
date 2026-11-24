"""Offline validator for cross-cluster service mirroring.

The package computes the reachable target endpoint set from in-memory
snapshots without contacting any Kubernetes cluster.
"""

from .io import load_snapshot, snapshot_kwargs
from .model import (
    Caller,
    Endpoint,
    EndpointBundle,
    NetworkPolicy,
    NetworkPolicyPeer,
    Port,
    Service,
)
from .report import render_report
from .validator import (
    CONFLICT_DELETION_NOT_PROPAGATED,
    CONFLICT_DUPLICATE_KEY,
    CONFLICT_NAMESPACE_NAME_SHARED,
    CONFLICT_PORT_DIFFERENCE,
    CONFLICT_TARGET_SERVICE_MISSING,
    CONFLICT_VERSION_SKEW,
    REASON_NOT_READY,
    REASON_POLICY_DENIED,
    REASON_PORT_MISSING,
    REASON_STALE_ONLY,
    REASON_ZONE_FAILED,
    EndpointVerdict,
    ServiceValidation,
    ValidationReport,
    validate_mirror,
)

__all__ = [
    "Caller",
    "Endpoint",
    "EndpointBundle",
    "EndpointVerdict",
    "NetworkPolicy",
    "NetworkPolicyPeer",
    "Port",
    "Service",
    "ServiceValidation",
    "ValidationReport",
    "load_snapshot",
    "render_report",
    "snapshot_kwargs",
    "validate_mirror",
    "CONFLICT_DELETION_NOT_PROPAGATED",
    "CONFLICT_DUPLICATE_KEY",
    "CONFLICT_NAMESPACE_NAME_SHARED",
    "CONFLICT_PORT_DIFFERENCE",
    "CONFLICT_TARGET_SERVICE_MISSING",
    "CONFLICT_VERSION_SKEW",
    "REASON_NOT_READY",
    "REASON_POLICY_DENIED",
    "REASON_PORT_MISSING",
    "REASON_STALE_ONLY",
    "REASON_ZONE_FAILED",
]

__version__ = "1.0.0"
