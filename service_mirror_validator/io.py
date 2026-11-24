"""JSON loading helpers.

The validator is offline by design: callers export Service / Endpoint /
NetworkPolicy manifests (or hand-written snapshots) to JSON and pass the
file path in.  No kubeconfig or API connection is ever used.
"""

import json
from typing import Any, Dict

from .model import (
    Caller,
    Endpoint,
    EndpointBundle,
    NetworkPolicy,
    NetworkPolicyPeer,
    Port,
    Service,
)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON document must be an object")
    return data


def _parse_port(raw: Dict[str, Any]) -> Port:
    return Port(
        name=str(raw.get("name", "")),
        port=int(raw["port"]),
        target_port=int(raw.get("target_port", raw["port"])),
        protocol=str(raw.get("protocol", "TCP")),
    )


def _parse_service(raw: Dict[str, Any]) -> Service:
    return Service(
        namespace=str(raw["namespace"]),
        name=str(raw["name"]),
        labels=dict(raw.get("labels", {})),
        ports=tuple(_parse_port(item) for item in raw.get("ports", [])),
        resource_version=str(raw.get("resource_version", "0")),
        deletion_pending=bool(raw.get("deletion_pending", False)),
    )


def _parse_endpoint(raw: Dict[str, Any]) -> Endpoint:
    ports = tuple(
        (str(item.get("name", "")), int(item["target_port"]))
        for item in raw.get("ports", [])
    )
    return Endpoint(
        address=str(raw["address"]),
        zone=str(raw.get("zone", "unknown")),
        ready=bool(raw.get("ready", True)),
        labels=dict(raw.get("labels", {})),
        ports=ports,
    )


def _parse_bundle(raw: Dict[str, Any]) -> EndpointBundle:
    return EndpointBundle(
        namespace=str(raw["namespace"]),
        name=str(raw["name"]),
        endpoints=tuple(
            _parse_endpoint(item) for item in raw.get("endpoints", [])
        ),
        resource_version=str(raw.get("resource_version", "0")),
        deletion_pending=bool(raw.get("deletion_pending", False)),
    )


def _parse_peer(raw: Dict[str, Any]) -> NetworkPolicyPeer:
    return NetworkPolicyPeer(
        pod_selector=raw.get("pod_selector"),
        namespace_selector=raw.get("namespace_selector"),
    )


def _parse_policy(raw: Dict[str, Any]) -> NetworkPolicy:
    ingress_ports = tuple(
        (
            item.get("name"),
            int(item["port"]) if item.get("port") is not None else None,
        )
        for item in raw.get("ingress_ports", [])
    )
    return NetworkPolicy(
        namespace=str(raw["namespace"]),
        name=str(raw["name"]),
        pod_selector=dict(raw.get("pod_selector", {})),
        ingress_ports=ingress_ports,
        peers=tuple(_parse_peer(item) for item in raw.get("peers", [])),
        ingress_enforced=bool(raw.get("ingress_enforced", True)),
    )


def _parse_caller(raw: Dict[str, Any]) -> Caller:
    return Caller(
        labels=dict(raw.get("labels", {})),
        namespace_labels=dict(raw.get("namespace_labels", {})),
    )


def load_snapshot(path: str) -> Dict[str, Any]:
    """Parse a full validation snapshot from a JSON file.

    Expected schema (all lists optional except source/target services)::

        {
          "source": {"services": [...], "endpoints": [...]},
          "target": {"services": [...], "endpoints": [...],
                     "network_policies": [...]},
          "failed_zones": ["zone-a"],
          "caller": {"labels": {...}, "namespace_labels": {...}}
        }
    """

    data = _load_json(path)
    source = data.get("source", {})
    target = data.get("target", {})

    source_services = [
        _parse_service(item) for item in source.get("services", [])
    ]
    target_services = [
        _parse_service(item) for item in target.get("services", [])
    ]
    source_bundles = [
        _parse_bundle(item) for item in source.get("endpoints", [])
    ]
    target_bundles = [
        _parse_bundle(item) for item in target.get("endpoints", [])
    ]
    policies = [
        _parse_policy(item) for item in target.get("network_policies", [])
    ]
    caller = _parse_caller(data["caller"]) if data.get("caller") else None

    return {
        "source_services": source_services,
        "target_services": target_services,
        "source_endpoints": source_bundles,
        "target_endpoints": target_bundles,
        "target_policies": policies,
        "failed_zones": frozenset(data.get("failed_zones", [])),
        "caller": caller,
    }


def snapshot_kwargs(path: str) -> Dict[str, Any]:
    """Keyword arguments ready to pass into :func:`validate_mirror`."""

    return load_snapshot(path)
