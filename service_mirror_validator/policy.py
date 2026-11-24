"""Kubernetes NetworkPolicy ingress evaluation (offline, subset).

Only the pieces required by the mirror validator are modelled:
pod selectors, named/numeric ports and basic peer selectors.  egress is
intentionally out of scope because the question is whether mirrored
traffic can reach target endpoints.
"""

from typing import List, Optional, Tuple

from .model import (
    Caller,
    Endpoint,
    NetworkPolicy,
    NetworkPolicyPeer,
    Port,
    label_selector_matches,
)


def _peer_matches(peer: NetworkPolicyPeer, caller: Caller) -> bool:
    if peer.namespace_selector is not None and not label_selector_matches(
        peer.namespace_selector, caller.namespace_labels
    ):
        return False
    if peer.pod_selector is not None and not label_selector_matches(
        peer.pod_selector, caller.labels
    ):
        return False
    return True


def _port_allowed(
    allowed_ports: Tuple[Tuple[Optional[str], Optional[int]], ...], port: Port
) -> bool:
    if not allowed_ports:
        return True
    for port_name, port_number in allowed_ports:
        if port_name is not None and port_name == port.name:
            return True
        if port_number is not None and port_number == port.target_port:
            return True
    return False


def ingress_allowed(
    namespace_policies: List[NetworkPolicy],
    endpoint: Endpoint,
    port: Port,
    caller: Caller,
) -> Tuple[bool, List[str]]:
    """Evaluate ingress policies already scoped to the endpoint namespace.

    Returns ``(allowed, denying_policy_names)``.  With no enforced policy the
    endpoint is allowed by default.  Any enforced policy that does not grant
    the (caller, port) pair isolates the endpoint, mirroring Kubernetes
    additive allow semantics.
    """

    enforced = [
        policy
        for policy in namespace_policies
        if policy.ingress_enforced
        and label_selector_matches(policy.pod_selector, endpoint.labels)
    ]
    if not enforced:
        return True, []

    denying: List[str] = []
    for policy in enforced:
        granted = False
        # An empty peer list means the rule can never match (Kubernetes
        # deny-all ingress), so the loop simply does not run.
        for peer in policy.peers:
            if _peer_matches(peer, caller) and _port_allowed(
                policy.ingress_ports, port
            ):
                granted = True
                break
        if not granted:
            denying.append(policy.name)
    return not denying, denying
