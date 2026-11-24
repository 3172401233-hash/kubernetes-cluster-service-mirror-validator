"""Domain objects describing a mirrored service and its endpoints.

All data is supplied by the caller; this module never connects to a
Kubernetes API server.  Python 3.8 compatible.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple


@dataclass(frozen=True)
class Port:
    """A service port mirrored from source to target."""

    name: str
    port: int
    target_port: int
    protocol: str = "TCP"


@dataclass(frozen=True)
class Endpoint:
    """A single backing endpoint (one pod IP / address)."""

    address: str
    zone: str
    ready: bool = True
    labels: Dict[str, str] = field(default_factory=dict)
    # Ports actually exposed by this endpoint as (name, number).  When empty
    # the endpoint is assumed to expose every service target port.
    ports: Tuple[Tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Service:
    """A Service object in one cluster."""

    namespace: str
    name: str
    labels: Dict[str, str] = field(default_factory=dict)
    ports: Tuple[Port, ...] = ()
    # ResourceVersion observed locally; compared between clusters to detect
    # delayed EndpointSlice synchronisation.
    resource_version: str = "0"
    deletion_pending: bool = False


@dataclass(frozen=True)
class EndpointBundle:
    """Endpoints/EndpointSlice content associated with a service."""

    namespace: str
    name: str
    endpoints: Tuple[Endpoint, ...] = ()
    resource_version: str = "0"
    deletion_pending: bool = False


@dataclass(frozen=True)
class NetworkPolicyPeer:
    """Ingress peer selector.

    An empty selector matches any caller.  A namespace selector without a pod
    selector matches every pod in the selected namespaces.
    """

    pod_selector: Optional[Dict[str, str]] = None
    namespace_selector: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class NetworkPolicy:
    """Subset of a Kubernetes NetworkPolicy needed for the calculation."""

    namespace: str
    name: str
    pod_selector: Dict[str, str] = field(default_factory=dict)
    # Port references as (port_name_or_None, port_number_or_None).  An empty
    # tuple means all ports.
    ingress_ports: Tuple[Tuple[Optional[str], Optional[int]], ...] = ()
    peers: Tuple[NetworkPolicyPeer, ...] = ()
    # True when policyTypes contains Ingress (or policyTypes is empty and
    # ingress rules exist).  Policies without ingress enforcement are ignored.
    ingress_enforced: bool = True


@dataclass(frozen=True)
class Caller:
    """Traffic source used when evaluating ingress peers."""

    labels: Dict[str, str] = field(default_factory=dict)
    namespace_labels: Dict[str, str] = field(default_factory=dict)


ServiceKey = Tuple[str, str]


def service_key(namespace: str, name: str) -> ServiceKey:
    """Composite identity so same-named services never merge across namespaces."""

    return namespace, name


def label_selector_matches(
    selector: Dict[str, str], labels: Dict[str, str]
) -> bool:
    """Kubernetes-style equality-based selector: every key/value must match."""

    return all(labels.get(key) == value for key, value in selector.items())


def endpoint_exposes_port(endpoint: Endpoint, port: Port) -> bool:
    """Whether the endpoint actually listens on the service target port."""

    if not endpoint.ports:
        return True
    exposed = frozenset(endpoint.ports)
    return (port.name, port.target_port) in exposed or (
        None,
        port.target_port,
    ) in exposed


def endpoint_labels(endpoint: Endpoint) -> Dict[str, str]:
    return dict(endpoint.labels)


def zone_set(endpoints: Tuple[Endpoint, ...]) -> FrozenSet[str]:
    return frozenset(ep.zone for ep in endpoints)
