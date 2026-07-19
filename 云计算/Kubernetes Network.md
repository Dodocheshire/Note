---
title: Kubernetes Network
date: 2026-07-11T09:32:51+08:00
lastmod: 2026-07-13T18:30:50+08:00
---

# Kubernetes Network

## Overview

|组件|运行方式|作用|
| ------| -------------------------| -------------------------------------|
|`CoreDNS`|Deployment —— 2个副本|解析名字：Service 名字 → ClusterIP|
|`kube-proxy`|**DaemonSet** —— 每个节点一个|路由数据包：ClusterIP → Pod IP|

|启动顺序|发生的事|
| ----------| -----------------------------------------------------------------------------------------------------|
|①|`kube-proxy`​ 先启动 → 给所有 Service 配置 iptables 规则，包括 `kube-dns`​（`kube-dns` 是路由到CoreDNS的service）|
|②|`CoreDNS`​ 在自己的 ClusterIP（`10.96.0.10`）上变得对所有node可访问|
|③|`kubelet`​ 把 `/etc/resolv.conf`​ 写进每个新 Pod：`nameserver 10.96.0.10`|
|④|根据Service的(部分)域名通过 CoreDNS 解析到Service的ClusterIP，再由kube-proxy 路由到一个具体的Pod IP|

‍

## CoreDNS、Endpoints and kube-proxy

### DaemonSet

DaemonSet是一个Kubernete对象。

|<br />|Deployment|DaemonSet|
| -----------------------| ----------------------------| --------------------------------------------------------------|
|决定跑几个 Pod 的依据|你手动声明的 `replicas` 数字|**节点数量**——有几个 Node 就自动跑几个，不用你填数字|
|加一个新 Node 会怎样|不会自动多起 Pod|**自动**在新节点上补(Schedule)一个 Pod|
|典型用途|业务应用（比如 guestbook）|每个节点都必须有一份的基础设施组件（网络插件、日志采集器等）|

> `kube-proxy`​ 必须**每个节点都有一份**才能正常工作——因为它负责的是"这台机器上的网络转发规则"，所以它是DaemonSet对象

‍

### Pod内部的DNS解析

```zsh
(base) owl@owldeMacBook-Air L1-lab % kubectl get pods -l app=guestbook-frontend
# 获取pod name
kubectl exec -it <pod-name> -- sh
# 进入pod内部终端
/app % cat /etc/resolv.conf 
# 先在default namespace中找域名，再在所有Service中找，最后在整个集群中找。对应不同域名后缀。
search default.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.96.0.10
options ndots:5

/app % nslookup guestbook-backend
Server:         10.96.0.10
Address:        10.96.0.10:53

** server can't find guestbook-backend.cluster.local: NXDOMAIN

** server can't find guestbook-backend.svc.cluster.local: NXDOMAIN

Name:   guestbook-backend.default.svc.cluster.local
Address: 10.96.124.182

** server can't find guestbook-backend.svc.cluster.local: NXDOMAIN

** server can't find guestbook-backend.cluster.local: NXDOMAIN

(base) owl@owldeMacBook-Air L1-lab % kubectl get service guestbook-backend 
NAME                TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
guestbook-backend   ClusterIP   10.96.124.182   <none>        8081/TCP   12h
```

- `nameserver 10.96.0.10`​：遇到需要解析域名的请求，去问这个地址。它是**kube-dns service**的**Cluster-IP**
- `search`​：自动尝试补全的**域名后缀列表**。例如在pod guest-frontend中`curl http://guestbook-backend:8081`​会查询名字**​`guestbook-backend`​**​，会先搜索域名`guestbook-backend.default.svc.cluster.local`​，DNS解析失败后再搜索`guestbook-backend.svc.cluster.local`​,最后搜索`guestbook-backend.cluster.local`
- `nslookup`​ 通过(部分)域名查找ip(使用dns server)，这个IP是service的**Cluster-IP**

‍

### ClusterIP和Pod IP区别

|<br />|ClusterIP|Pod IP|
| --------------------------------| ----------------------------------------------| -----------------------------------------------------------------------------|
|属于谁|Service 对象|某个具体的 Pod|
|是否真实存在于某台机器的网卡上|**不是**——纯虚拟，没有任何网络接口真正持有这个地址|**是**——真实分配、有实际的网络命名空间/虚拟网卡对应着它是某个 Pod 真实的 Pod IP|
|会不会变|一般不变（除非 Service 被删了重建）|Pod 重启/重建后**会变**——这也是为什么要靠 Service 提供稳定的名字|
|数据包最终真正到达的地方|不是终点，只是个"转发入口"|**是**真正的终点——iptables 改写目标地址之后，包最终就是发到某个 Pod IP|

‍

### Endpoints

Enpoints也是一个Kubernete对象。

**定义**：Endpoints是Service 的附属对象，记录着这个 Service 背后当前有哪些 Pod IP，存在 `etcd`​ 里，是**集群全局共享**的一份数据。

|Endpoints controller（协调循环）|内容|
| ----------------------------------| --------------------------------------------------------------|
|期望状态 (Desired)|所有标签匹配这个 selector 的 Pod 的 IP|
|实际状态 (Actual)|当前 Endpoints 列表里已经记录的内容|
|动作 (Action)|新 Pod 出现就加进列表；Pod 被删或变成 not-Ready 就从列表移除|

### kube-proxy

**定义：** DaemonSet对象，每个节点上都跑一份，负责把发往 ClusterIP 的包，改写目标地址，转发到真实 Pod IP

```zsh
包的目标是 ClusterIP 10.96.124.182:8081
      ↓
iptables 规则(由 kube-proxy 写入)
      ↓ 改写目标地址
Pod IP 10.244.2.2:8081   ← 从 Endpoints 里随机选一个
```

> |<br />|Endpoints|iptables|
> | -------------| -----------------------------------------------------| ----------------------------------------------------------|
> |本质|一个 **Kubernetes API 对象**（数据），存在 `etcd` 里|Linux **内核**里真实的数据包过滤/转发规则|
> |存在的地方|集群的"账本"里（etcd），逻辑上的一份记录|每个 Node 自己的操作系统内核里，物理上真实存在的规则表|
> |谁能看/改它|可以用 `kubectl get endpoints` 查看，本质是 API 层面的数据|理论上能在 Node 上用 `iptables -L` 直接看到，是操作系统级别的配置|
> |谁负责生成|Endpoints controller（观察 Pod，生成/更新这份列表）|kube-proxy（监控Endpoints对象，更新对应的iptables 规则）|
> |角色| **"应该转发给谁"** ——声明性的、只是一份名单| **"实际怎么转发"** ——真正在处理每一个经过的数据包|

‍

## Service改进

### NodePort 缺点

|想要的效果--通过不同url路径转发|实际能力局限|
| ---------------------------------| --------------------------------------|
|`http://myapp.example.com/` → frontend|NodePort 只能按**端口号**分流，不认识域名/路径|
|`http://myapp.example.com/api` → backend|想区分两个不同路径，NodePort 做不到|

|用 NodePort 硬做的结果|问题|
| ------------------------| ----------------------------------|
|`http://myapp.example.com:30080` → frontend|用户必须记住一个奇怪的端口号|
|`http://myapp.example.com:30081` → backend|每加一个新服务就要占用一个新端口|

|NodePort 的三个具体缺陷|说明|
| -------------------------| --------------------------------------------------|
|端口范围受限|每个新 Service 都要在 30000–32767 里抢一个端口|
|用户体验差|URL 里必须带着端口号，没法给用户一个干净的域名|
|功能缺失|不支持 TLS（HTTPS）终止，也不支持按 URL 路径路由|

‍

### Ingress做法

历史上采用Ingress，它能理解 URL **路径**，可以做"同一个域名，不同路径转发到不同 Service"这种精细路由。

|Ingress 的做法|说明|
| ----------------------------| ---------------------------------------------------|
|用注解(annotation)配置行为|`nginx.ingress.kubernetes.io/rewrite-target: /$1`|
|用正则表达式匹配路径|`path: /api/(.*)`|
|路径重写举例|`GET /api/entries`​ → 匹配 `/api/(.*)`​ → `$1=entries`​ → 重写成 `/entries` 转发给 backend|

例子：

```yaml
kind: Ingress
metadata:
  annotations:
    nginx.ingress.kuberntes.io/rewrite-target: /$1 # 进行路径重写
spec:
  rules: # 路由规则
  - http: # 对http协议的请求如何路由
      paths: # 声明若干路径的正则表达式以进行匹配并提取位置参数
      - path: /api/(.*)
        pathType:ImplementationSpecific
        backend:
          service:
            name: guestbook-backend
            port: {number: 8081}
      - path: /(.*)
        pathType: ImplementationSpecific
        backend:
          service:
            name: guestbook-frontend
            port: {number: 8080}

```

```zsh
GET /api/entries
/api/(.*) matches → $1=entries → rewrites to /entries
guestbook-backend Pod receives: GET /entries ✓
GET /
/(.*) matches → $1=(empty) → rewrites to /
guestbook-frontend Pod receives: GET / ✓
```

|Ingress 的两个设计缺陷|具体表现|
| ------------------------| -------------------------------------------------------------------------------------------------------------|
|① 没有显示声明控制器|`nginx.ingress.kubernetes.io/rewrite-target`​是一个`annotation`，kubernetes不会校验它的内容和格式，它被具体的Ingress controller(如nginx-ingress)自己决定含义。|
|② 不可移植|换一个 Ingress controller，注解、正则写法、`ImplementationSpecific` 的具体行为全部可能失效；写错一个字符,静默不生效,不会报错|

‍

### Gateway API

**Gateway API实现了路由规则和具体控制器实现彻底解耦。**

|controllerName 举例|对应哪个具体实现|
| ---------------------| ------------------------------|
|`gateway.nginx.org/nginx-gateway-controller`|NGINX Gateway Fabric|
|`eks.amazonaws.com/alb`|AWS Load Balancer Controller|
|`gateway.envoyproxy.io/gatewayclass-controller`|Envoy Gateway|

|三个对象，对应三种角色|谁负责写|
| ------------------------| ------------------------------------------------------|
|**GatewayClass**|声明用哪个控制器实现 —— 集群管理员，通常只配置一次|
|**Gateway**|声明一个监听器（端口/协议）|
|**HTTPRoute**|具体的路由规则 —— 应用开发者|

<span data-type="text" style="color: var(--b3-font-color1);">注</span>：

- GatewayClass是集群级的，只有一份，全局共享

- Gateway是namespace级，比如 `default` 里声明一个

‍

|环境|入口点怎么来的|用户看到的 URL|
| -------------| ------------------------------------| ----------------|
|AWS|自动配置一个 Network Load Balancer|`http://myapp.example.com`|
|GCP / Azure|自动配置各自的 Cloud Load Balancer|`http://myapp.example.com`|

> Load Balancer是云厂商创建出来的一个真实基础设施资源，是一台（或一组）拥有真实公网 IP 的机器/服务，专门站在Kubernetes 集群"前面"，负责把外部互联网的流量，转发进集群里的某个 Node。
>
> Gateway对象的`status.addresses`​字段就是**Network Load Balancer的公网 IP**

‍

**GatewayClass（最先声明）**

```yaml
kind: GatewayClass
metadata:
  name: nginx # GatewayClass对象的名字，可被Gateway对象引用
spec:
  controllerName: gateway.nginx.org/nginx-gateway-controller
```

‍

**Gateway（依赖于GatewayClass）**

```yaml
kind: Gateway
metadata:
  name: guestbook-gateway # Gateway对象名称，可被HTTPRoute引用
  namespace: default
spec:
  gatewayClassName: nginx
  listeners:
    - name: http
      protocol: HTTP
      port: 80

```

- **声明"我要开一个监听 80 端口、协议是 HTTP 的入口"** ，并且指定这个入口该由刚才定义的 `nginx` 这个 GatewayClass 来实现。
- 声明完成后，控制器会自动去配置底层的 nginx，让它真的开始监听80端口接收HTTP流量

‍

**HTTPRoute（依赖于Gateway）**

定义：声明某个gateway的url路径路由规则，即具体请求怎么路由到不同的服务上，是应用开发者该自己声明的东西。

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: guestbook
spec:
  parentRefs:
  - name: guestbook-gateway # 把HTTPRoute"挂"到 Gateway 上
  rules:
  - matches:
    - path: {type: PathPrefix, value: /api} # 只要请求路径以 /api 开头就命中
    filters:
    - type: URLRewrite # 在转发之前，先把匹配到的url路径重写
      urlRewrite:
        path:
          type: ReplacePrefixMatch # 把匹配到的前缀 /api 替换成 /
          replacePrefixMatch: /
     backendRefs: # 转发目标是 guestbook-backend 这个 Service 的 8081 端口
     - name: guestbook-backend
       port: 8081
  - matches:
    - path: {type: PathPrefix, value: /} # 其他所有请求（/ 开头，也就是兜底）
    backendRefs:
    - name: guestbook-frontend # 转发目标是 guestbook-frontend 这个 Service 的8080端口
      port: 8080
    
      
```

‍

```zsh
kubectl apply -f httproute.yaml
kubectl get gateway guestbook-gateway # 获取httproute挂载到的gateway的地址
# 假设获得GATEWAY_IP
curl http://$GATEWAY_IP/                  # 测试frontend路由
curl http://$GATEWAY_IP/api/entries        # 测试backend路由，期望返回 []
```

‍

|<br />|Ingress|HTTPRoute|
| --------------------| -------------------------------------| -------------------------------------------------------------|
|怎么表达"重写路径"|`nginx.ingress.kubernetes.io/rewrite-target: /$1`（注解，字符串，API不认识内容）|`filters: - type: URLRewrite`​（**Kubernetes API 正式定义的字段类型**）|
|匹配路径用什么|正则表达式 `/api/(.*)`|结构化字段 `{type: PathPrefix, value: /api}`|
|写错了会怎样|静默失效，不报错|**API 会做类型校验**——字段名写错、结构不对，`kubectl apply` 直接拒绝，不会提交一个无效配置|

‍

### 总结

```zsh
Browser
│ http://myapp.example.com/ ← cloud load balancer (auto-provisioned)
▼
Gateway (port 80, NGINX Gateway Fabric)
│ HTTPRoute: /api → guestbook-backend:8081
│ HTTPRoute: / → guestbook-frontend:8080
▼
Service (ClusterIP) ← CoreDNS: name → IP
│ kube-proxy → Endpoints
▼
frontend Pod
│ http://guestbook-backend:8081
▼
Service (ClusterIP)
│ kube-proxy → Endpoints
▼
backend Pod
```

‍

### 根据目标域名进行路由筛选

```yaml
spec:
  parentRefs:
  - name: guestbook-gateway
  hostnames:
  - "guestbook.local"  #HTTPRoute只会处理请求头里 Host 精确等于 guestbook.local 的请求，其他请求无视
  rules:
    # 保留原来的 /api 和 / 规则

```

测试：

```zsh
curl -H "Host: guestbook.local" "http://$GATEWAY_HOST/api/entris"
```

‍

‍
