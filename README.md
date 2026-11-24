# kubernetes-cluster-service-mirror-validator

跨集群服务镜像（service mirroring）离线校验器。输入源集群与目标集群的
Service、Endpoints/EndpointSlice、标签、端口、NetworkPolicy、故障区域和
同步版本（resourceVersion），计算镜像流量在目标集群**实际可访问的端点集合**，
并输出差异、冲突和同步版本。

## 适用场景

服务从源集群镜像到目标集群时，EndpointSlice 同步存在延迟，而目标集群本地
NetworkPolicy 又拒绝部分端口/端点。此时“导入成功”不代表流量可达：目标侧可能
同时存在尚未同步的新端点、已删除但残留的旧端点，以及被策略隔离的端点。
本工具基于快照数据复现该判定过程，例如 `examples/half_endpoints.json` 中
4 个源端点只有 2 个真正可访问。

## 不连接集群

- 本工具**完全离线**运行，不读取 kubeconfig，不调用 Kubernetes API，
  不建立任何网络连接。
- 集群状态由调用方导出为 JSON 快照（或直接在 Python 中构造数据对象）后传入。
- 适合在 CI、巡检流水线或故障复盘时对导出的快照做确定性校验。

## 环境要求

- Python 3.8.2+（仅使用标准库，无第三方依赖）

## 快速开始

```bash
python -m service_mirror_validator examples/half_endpoints.json
```

存在不可达端点或冲突时退出码为 `1`，全部健康时为 `0`。

也可以在 Python 中直接使用：

```python
from service_mirror_validator import (
    Caller, Endpoint, EndpointBundle, NetworkPolicy,
    NetworkPolicyPeer, Port, Service, render_report, validate_mirror,
)

port = Port(name="http", port=80, target_port=8080)
source = Service(namespace="shop", name="checkout", ports=(port,),
                 resource_version="20")
target = Service(namespace="shop", name="checkout", ports=(port,),
                 resource_version="20")
eps = (Endpoint(address="10.0.0.1", zone="zone-a",
                labels={"app": "checkout"}),)
report = validate_mirror(
    source_services=[source],
    target_services=[target],
    source_endpoints=[EndpointBundle("shop", "checkout", eps, "31")],
    target_endpoints=[EndpointBundle("shop", "checkout", eps, "30")],
    target_policies=[],
    failed_zones=frozenset(),
    caller=Caller(labels={"role": "gateway"}),
)
print(render_report(report))
```

## 判定规则

服务以 `(namespace, name)` 复合键索引，**同名服务位于不同命名空间时绝不会
合并**，并产生 `same_name_different_namespace` 全局冲突提示。

一个目标端点计入“可访问集合”必须同时满足：

1. 源、目标两侧都存在该地址（源侧独有 = 未同步缺失，目标侧独有 = 残留过期端点）；
2. 端点 `ready=true`，且所在区域不在故障区域列表中；
3. 端点暴露 Service 引用的全部 targetPort；
4. 目标集群同命名空间内选中该端点的 NetworkPolicy 允许该调用方访问对应端口。

其余差异与冲突：

- `version_skew`：Service 或 Endpoint 的 resourceVersion 两侧不一致，
  表明镜像同步存在延迟；
- `port_difference`：源/目标 Service 端口定义（名称、端口、targetPort、协议）不同；
- `deletion_not_propagated`：源侧已标记删除而目标镜像仍然存在；
- `target_service_missing`：目标集群缺少对应镜像 Service；
- 端点不可达原因码：`not_ready`、`zone_failed`、`port_missing`、
  `policy_denied`、`stale_target_only`。

NetworkPolicy 按 Kubernetes 语义近似实现：无强制 Ingress 策略默认放行；
存在强制策略时采用加性允许，任一策略未授予 `(调用方, 端口)` 即拒绝；
空 peers 的规则等价于 deny-all。

## JSON 快照结构

```json
{
  "source": {
    "services": [{"namespace": "shop", "name": "checkout",
                  "labels": {}, "ports": [{"name": "http", "port": 80,
                  "target_port": 8080, "protocol": "TCP"}],
                  "resource_version": "20"}],
    "endpoints": [{"namespace": "shop", "name": "checkout",
                   "resource_version": "31",
                   "endpoints": [{"address": "10.0.0.1", "zone": "zone-a",
                                  "ready": true, "labels": {},
                                  "ports": [{"name": "http",
                                             "target_port": 8080}]}]}]
  },
  "target": {
    "services": [],
    "endpoints": [],
    "network_policies": [{"namespace": "shop", "name": "deny-web",
                          "pod_selector": {"app": "checkout"},
                          "ingress_ports": [{"name": null, "port": 8080}],
                          "peers": [], "ingress_enforced": true}]
  },
  "failed_zones": ["zone-b"],
  "caller": {"labels": {"role": "gateway"},
             "namespace_labels": {"mesh": "true"}}
}
```

端点的 `ports` 留空表示默认暴露 Service 的全部 targetPort。

## 运行测试

```bash
python -m unittest
```

测试覆盖：

- EndpointSlice 延迟同步（版本偏差、缺失端点、残留过期端点，仅半数可达）；
- 区域故障隔离；
- 端口差异与端点未暴露 targetPort；
- 目标 NetworkPolicy 拒绝（含跨命名空间策略不生效、deny-all、放行策略）；
- 删除同步（已传播 / 未传播 / 目标镜像缺失）；
- 同名服务跨命名空间不合并；
- 离线 JSON 加载、CLI 退出码与报告渲染。

## 目录结构

```
service_mirror_validator/
  model.py      # Service / Endpoint / NetworkPolicy 等数据对象
  policy.py     # NetworkPolicy Ingress 判定
  validator.py  # 可访问端点集合、差异与冲突、同步版本计算
  report.py     # 文本报告渲染
  io.py         # 离线 JSON 快照加载
  __main__.py   # python -m service_mirror_validator 入口
tests/          # unittest 测试
examples/       # 示例快照
```
