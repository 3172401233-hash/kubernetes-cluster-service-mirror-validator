"""Human-readable rendering of :class:`ValidationReport`."""

from typing import List

from .validator import (
    CONFLICT_DELETION_NOT_PROPAGATED,
    CONFLICT_NAMESPACE_NAME_SHARED,
    CONFLICT_PORT_DIFFERENCE,
    CONFLICT_TARGET_SERVICE_MISSING,
    CONFLICT_VERSION_SKEW,
    REASON_NOT_READY,
    REASON_POLICY_DENIED,
    REASON_PORT_MISSING,
    REASON_STALE_ONLY,
    REASON_ZONE_FAILED,
    ValidationReport,
)

REASON_LABELS = {
    REASON_NOT_READY: "endpoint not ready",
    REASON_ZONE_FAILED: "zone in failure list",
    REASON_PORT_MISSING: "required target port not exposed",
    REASON_POLICY_DENIED: "denied by target NetworkPolicy",
    REASON_STALE_ONLY: "stale: absent from source EndpointSlice",
}

CONFLICT_LABELS = {
    CONFLICT_VERSION_SKEW: "sync version skew",
    CONFLICT_PORT_DIFFERENCE: "port difference",
    CONFLICT_DELETION_NOT_PROPAGATED: "deletion not propagated",
    CONFLICT_TARGET_SERVICE_MISSING: "target mirror missing",
    CONFLICT_NAMESPACE_NAME_SHARED: "same name in multiple namespaces",
}


def _reason_text(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


def render_report(report: ValidationReport) -> str:
    lines: List[str] = []
    lines.append("Service mirror validation report")
    lines.append("=" * 32)
    lines.append(
        "accessible endpoints: %d/%d (across %d service(s))"
        % (
            report.accessible_endpoint_count,
            report.endpoint_count,
            len(report.services),
        )
    )

    if report.global_conflicts:
        lines.append("")
        lines.append("Global conflicts:")
        for conflict in report.global_conflicts:
            label = CONFLICT_LABELS.get(conflict.code, conflict.code)
            lines.append("  - [%s] %s" % (label, conflict.message))

    for item in report.services:
        lines.append("")
        lines.append("Service %s/%s" % (item.namespace, item.name))
        lines.append("-" * (10 + len(item.namespace) + len(item.name)))
        lines.append(
            "  service versions: source=%s target=%s (%s)"
            % (
                item.source_version,
                item.target_version,
                "in sync" if item.service_version_in_sync else "SKEWED",
            )
        )
        lines.append(
            "  endpoint versions: source=%s target=%s (%s)"
            % (
                item.source_endpoint_version,
                item.target_endpoint_version,
                "in sync" if item.endpoint_version_in_sync else "SKEWED",
            )
        )
        lines.append(
            "  deletion propagation: %s"
            % ("in sync" if item.deletion_in_sync else "LAGGING")
        )
        lines.append(
            "  source endpoints: %s"
            % (sorted(item.source_endpoint_addresses) or "<none>")
        )
        lines.append(
            "  target endpoints: %s"
            % (sorted(item.target_endpoint_addresses) or "<none>")
        )
        lines.append(
            "  accessible endpoints: %s"
            % (sorted(item.accessible_endpoints) or "<none>")
        )

        missing = item.missing_from_target
        if missing:
            lines.append("  missing on target: %s" % sorted(missing))
        stale = item.stale_target_only
        if stale:
            lines.append("  stale target-only: %s" % sorted(stale))

        unreachable = item.unreachable_endpoints
        if unreachable:
            lines.append("  unreachable detail:")
            for verdict in item.verdicts:
                if verdict.accessible:
                    continue
                detail = "; ".join(
                    _reason_text(reason) for reason in verdict.reasons
                )
                policy_detail = ""
                if verdict.denying_policies:
                    policy_detail = " (policies: %s)" % ", ".join(
                        verdict.denying_policies
                    )
                lines.append(
                    "    * %s [zone=%s]: %s%s"
                    % (
                        verdict.address,
                        verdict.zone,
                        detail,
                        policy_detail,
                    )
                )

        if item.conflicts:
            lines.append("  conflicts:")
            for conflict in item.conflicts:
                label = CONFLICT_LABELS.get(conflict.code, conflict.code)
                lines.append("    - [%s] %s" % (label, conflict.message))

    return "\n".join(lines)
