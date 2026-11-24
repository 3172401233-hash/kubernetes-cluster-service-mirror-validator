"""Small object factories shared by the unit tests."""

from service_mirror_validator.model import (
    Endpoint,
    EndpointBundle,
    NetworkPolicy,
    NetworkPolicyPeer,
    Port,
    Service,
)


def make_port(name="http", port=80, target_port=8080, protocol="TCP"):
    return Port(
        name=name, port=port, target_port=target_port, protocol=protocol
    )


def make_service(
    namespace="shop",
    name="checkout",
    ports=None,
    resource_version="10",
    labels=None,
    deletion_pending=False,
):
    return Service(
        namespace=namespace,
        name=name,
        labels=labels or {"app": name},
        ports=(make_port(),) if ports is None else tuple(ports),
        resource_version=resource_version,
        deletion_pending=deletion_pending,
    )


def make_endpoint(
    address,
    zone="zone-a",
    ready=True,
    labels=None,
    ports=(),
):
    return Endpoint(
        address=address,
        zone=zone,
        ready=ready,
        labels=labels if labels is not None else {"app": "checkout"},
        ports=tuple(ports),
    )


def make_bundle(
    namespace="shop",
    name="checkout",
    endpoints=(),
    resource_version="10",
    deletion_pending=False,
):
    return EndpointBundle(
        namespace=namespace,
        name=name,
        endpoints=tuple(endpoints),
        resource_version=resource_version,
        deletion_pending=deletion_pending,
    )


def make_deny_policy(
    namespace="shop",
    name="deny-web",
    pod_selector=None,
    ingress_ports=(),
    peers=(),
):
    return NetworkPolicy(
        namespace=namespace,
        name=name,
        pod_selector=pod_selector or {"app": "checkout"},
        ingress_ports=tuple(ingress_ports),
        peers=tuple(peers),
        ingress_enforced=True,
    )


def make_allow_policy(
    namespace="shop",
    name="allow-web",
    pod_selector=None,
    ingress_ports=((None, 8080),),
):
    return NetworkPolicy(
        namespace=namespace,
        name=name,
        pod_selector=pod_selector or {"app": "checkout"},
        ingress_ports=tuple(ingress_ports),
        peers=(NetworkPolicyPeer(),),
        ingress_enforced=True,
    )
