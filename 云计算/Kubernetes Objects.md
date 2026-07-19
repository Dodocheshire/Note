---
title: Kubernetes Objects
date: 2026-07-10T14:18:29+08:00
lastmod: 2026-07-11T12:34:01+08:00
---

# Kubernetes Objects

基本概念

|对象类型 (Object Type)|定义|作用|
| ------------------------| ----------------------------------------------| ---------------------------------------------------|
|**Pod**|最原子的单元：一个或多个跑在同一节点上的容器|由 Deployment 代为管理，不直接手动创建|
|**Deployment**|声明"要几份副本"，由协调循环负责维持|保证 Pod 可靠地持续运行|
|**Service**|虚拟的Api对象，提供一个稳定的 DNS 名字|即使 Pod 重启、IP 变了，也能根据标签稳定找到应用|
|**ConfigMap**|从镜像外部注入环境变量|不用重新构建镜像就能改配置|
|**Secret**|专门存放敏感配置的独立对象类型|注入机制和 ConfigMap 一样，但访问权限可以单独控制|

每个Kubernete对象都是一个可持久化的实体，存储在**etcd中。**

|字段 (Field)|谁来写 (Who writes it)|含义 (What it means)|
| --------------| ------------------------| --------------------------------|
|`spec`|你 (You)|期望状态 —— 你想要什么|
|`status`|Kubernetes|当前状态 —— 现在实际存在什么|
|*gap 差距*|*loop 协调循环*|Observe → Diff → Act|

|你想做的事|该创建的对象|
| ----------------| -----------------------------|
|"跑我的应用"|Pod（或用 Deployment 代管）|
|"把它暴露出去"|Service|
|"配置它"|ConfigMap|

‍

通常，我们在**yaml**文件中声明一个Kubernete Object的**spec，** 这样它的期望状态能被git管理。这被称为一个**Manifest（声明文件**）

```zsh
kubectl apply -f manifest.yaml         # 创建或更新一个对象
kubectl get ... -o yaml   # 查看某个活跃对象的 spec + status
```

‍

## 声明Kubernetes对象

每个kubernete对象都有5个顶层字段

|字段 (Field)|谁来写|含义|
| --------------| ------------| ----------------------------------------------------------------------------|
|`apiVersion`|你|这个对象类型由哪个 API 组、哪个版本定义|
|`kind`|你|这个对象的类型是什么(比如 Pod、Deployment)|
|`metadata`|你|对象的身份信息:`name`​(命名空间内唯一名字)、`labels`(用于筛选和组织的 key-value 标签)|
|`spec`|你|你的期望状态——你想让它存在成什么样|
|`status`|Kubernetes|现实状态——你从不手写，Kubernetes 自动帮你填,能在 `kubectl get ... -o yaml` 里看到|

例如：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: guestbook-backend
  labels:
    app: guestbook-backend # key-value tag for selection (-l app=guestbook-backend)
spec:
  containers:
  - name: backend # 使用的容器名字
  image: guestbook-backend:latest # 用哪个镜像
  ports:
  - containerPort: 8081 # 监听哪个端口

status:
  phase: Running
  podIP: 10.244.0.5
```

使用**Manifest(apply -f)** 的**优点:**

- YAML 文件可被git管理
- 同一份yaml apply多次，Kubernetes发现期望状态没变，不会报错也不回重建
- `git diff`可查看前后yaml文件的变化

‍

## Deployment

**定义：一个Deployment声明若干个Pod应该同时运行以及它们**

|Deployment spec 里的关键字段|含义|
| ------------------------------| ---------------------------------------------|
|`replicas`|你想要几个 Pod 副本|
|`selector`|这个 Deployment 该管哪些 Pod（必须匹配 `template.metadata.labels`）|
|`template`|Pod 的"模板"：镜像、端口、环境变量等|

|你**不**需要声明的东西|谁来决定|
| ----------------------| --------------|
|Pod 跑在哪个节点上|`kube-scheduler` 决定|
|Pod 分到什么 IP|CNI 插件分配|
|Pod 具体什么时刻启动|`kubelet` 处理|

例子：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: guestbook-backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: guestbook-backend
  template: # pod的模版
    metadata:
      labels:
        app: guestbook-backend
    spec:
      containers:
      - name: backend
        image: guestbook-backend:latest
        imagePullPolicy: Never
        ports:
        - containerPort: 8081
```

```zsh
kubectl apply -f backend-deployment.yaml
kubectl get pods -l app=guestbook-backend
kubectl describe pod -l app=guestbook-backend
```

> <span data-type="text" style="color: var(--b3-font-color7);">注意：</span>
>
> - 同一个deployment下每个pod都有唯一的名字，但不是自己起的，而是系统自动生成的：`<Deployment名字>-<ReplicaSet哈希后缀>-<随机5位后缀>`
> - 同一个 Deployment 下的所有 Pod，`labels` 字段的值是完全相同的。
> - 每个 Pod 分到独立的集群内IP和UID是不同的

### Deployment的所有权链

kubectl apply -f deployment.yaml 一次性产生3个对象：

```zsh
Deployment ──owns──► ReplicaSet ──owns──► Pod Pod Pod
(your YAML)          (generated)        (actual containers)
```

> 在更换镜像版本时，Deployment controller不会直接改旧的Pod，而是：
>
> 1. 创建一个全新的ReplicaSet(对应新版本的`template`)
> 2. 把新 ReplicaSet 的副本数**逐步调高**，同时把旧 ReplicaSet 的副本数**逐步调低**
> 3. 整个过程中始终有 Pod 在正常服务，即"zero downtime"

‍

### Deployment的版本更新

#### Pod的替换策略

```yaml
spec:
  strategy:
    type: Recreate
```

|策略 (Strategy)|怎么做|过程|适用场景|
| -----------------| ------------------------| -------------------------------------| ---------------------------------------------------------------------|
|**Recreate**|先全部停掉，再全新启动|`[v1][v1][v1]`​ → (全部终止,有停机 gap) → `[v2][v2][v2]`|应用没法同时跑两个版本（比如数据库迁移改了 schema，新旧版本不兼容）|
|**RollingUpdate**（默认）|逐步替换 Pod|`[v1][v1][v1]`​ → `[v1][v1][v2]`​ → `[v2][v2][v2]`|想要零停机部署，大多数应用场景|

|RollingUpdate 的两个关键参数|含义|
| ------------------------------| ------------------------------------------|
|`maxSurge`|更新过程中，最多允许比期望副本数**多出**几个 Pod|
|`maxUnavailable`|更新过程中，最多允许有几个 Pod **不可用**|

```yaml
spec:
  strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge:1
    maxUnavailable: 0
```

|更高级的部署方式（超出这两种基本策略）|原理|需要的额外工具|
| ----------------------------------------| ----------------------------------------------------------------| ------------------------------------------------------|
|Blue/Green|跑两套完整的 Deployment，切换 Service 的 selector 一次性切流量|不需要额外工具|
|Canary|只把一部分流量导向新版本|需要 Gateway API 或 service mesh（Lecture 2 之后讲）|

‍

#### Rolling Update

设想我们更改了frontend-deployment的镜像:

- 声明式(使用yaml)

```zsh
kubectl apply -f frontend-deployment.yaml # image: guestbook-frontend:v2
# watch rollout progress
kubectl rollout status deployment/guestbook-frontend
# undo if sth wrong -- revert to the previous ReplicaSet
kubectl rollout undo deployment/guestbook-frontend
```

- 命令式(使用命令行)

```zsh
# 更改deployment中名为frontend的容器使用的镜像
kubectl set image deployent/guestbook-frontend frontend=guestbook-frontend:v2
# 如果deployment下的pod使用多个容器，且想同时改所有容器的镜像，使用通配符*
kubectl set image deployment/guestbook-frontend *=some-new-base-image:v2
```

‍

## Label

**定义**：Labels 不是装饰性的注释，是 Kubernetes 里对象之间互相"找到对方"的唯一机制。

|Labels 连接的两组关系|具体字段|
| ----------------------------| ----------|
|Deployment <->它管的 Pod|`selector.matchLabels`|
|Service <-> 它路由到的 Pod|`spec.selector`|

> <span data-type="text" style="color: var(--b3-font-color1);">Bug！</span>如果 Service 的 selector 和 Pod 的 labels 对不上，不会报任何错误，只是流量路由不出去，可以使用：
>
> `kubectl get pods --show-labels` 显示每个Pod实际打的标签

‍

## Service

### Service定义

**Service 是一个 Kubernetes API 对象（**​**​`kind: Service`​**​ **），它的作用是：为一组通过标签选择器（label selector）匹配到的 Pod，提供一个稳定、持久的虚拟网络身份（一个 ClusterIP + DNS 名字），使得这组 Pod 背后具体是谁、有几个、IP 是什么，对调用方完全透明。**

### Service实现

#### Service的关联对象Endpoints

Service 的 `spec.selector`​ 刚一生效，**Endpoints controller 就会去查一遍当前集群里所有标签匹配的、状态是 Ready 的 Pod**，把它们的 `IP:port` 写进一个新建的、跟这个 Service 同名的 Endpoints 对象里。只要有符合条件的 Pod 创建/删除/变成 not-Ready，这份 Endpoints 列表就会被立刻更新。

#### kube-proxy

kube-proxy是一个DaemonSet对象。**集群里每一台 Node 上的 kube-proxy，都各自独立地监听这个新 Endpoints 对象，一旦发现更新，** 就立刻在**自己那台 Node 本地**的内核里写入/更新对应的 iptables 规则："如果看到目标是这个 ClusterIP:port 的包，就把它 DNAT 改写成 Endpoints 里的某一个Pod IP"。

#### CoreDNS

CoreDNS是一个Deployment对象，是专门负责"名字翻译"的组件。CoreDNS持续监听集群里的 Service 对象，一旦发现新 Service，就自动生成对应的 DNS A 记录，格式是 `<service名>.<namespace>.svc.cluster.local → ClusterIP`。

#### 总结

```zsh
apply 的 Service (spec: selector + ports + type)
        │
        ├──→ Endpoints controller ──→ Endpoints 对象（哪些真实 Pod）
        │
        ├──→ 每个 Node 的 kube-proxy ──→ 本地 iptables 规则（怎么转发）
        │
        └──→ CoreDNS ──→ DNS 记录（名字怎么查到 ClusterIP）
```

#### **例子**(backend Service)

```yaml
apiVersion: v1
kind: Service # 声明一个Service对象
metadata:
  name: guestbook-backend    # ← CoreDNS (只)会给 Service 对象自动创建 DNS 记录
spec:
  selector:
    app: guestbook-backend    # ← Service路由到的Pod(只能通过label筛选)
  ports:
    - port: 8081
      targetPort: 8081
```

从集群内部某个pod `curl http://guestbook-backend:8081/healthz`的翻译过程如下：

```zsh
(部分)域名: guestbook-backend（这是yaml中定义的Service对象名字）
       ↓ CoreDNS 查表翻译
真实地址: 该Service的 ClusterIP，比如 10.100.xxx.xxx
       ↓ kube-proxy 维护的iptables，把这个请求的目标IP设置成一个Pod IP上(如10.244.0.5)
最终落到: 某个Pod处理 /healthz这个请求，返回"ok"
```

‍

### Service 结构

|Service 字段|含义|
| --------------| -----------------------------------------------------------------------------------|
|`metadata.name`|Service 在集群内的 DNS 名字（简写形式在同一 namespace 内直接可用，完整形式是 `<name>.<namespace>.svc.cluster.local`）|
|`spec.selector`|标签筛选条件——只把流量转发给标签匹配的 Pod；一个都不匹配就"什么都不转发"|
|`spec.ports[].port`|调用方要拨打的端口——Service 对外暴露的"稳定端口"|
|`spec.ports[].targetPort`|这个 Service 要转发流量过去的、被 selector 匹配到的 Pod，其容器实际监听的端口。|

> 一个请求只会被service转发到一个pod

‍

|环节|内容|
| -----------| -------------------------------------------------------|
|Service|通过 selector 去匹配标签|
|Endpoints|自动生成，列出所有匹配上的、且状态 Ready 的 Pod 的 `IP:port`|

#### Deployment 和 Service对比

|对比维度|Deployment|Service|
| --------------------| --------------------------| -------------------------------|
|和 Pod 的关系|**拥有（owns）** ——创建、重启、删除 Pod|**选择（selects）** ——只负责路由，不管 Pod 生死|
|删除这个对象后|Pod 跟着一起消失|Pod 继续正常运行，不受影响|
|自动生成的中间对象|ReplicaSet|Endpoints|

‍

### Service类型

**访问Service的对象范围决定Service的类型**

|谁要访问这个 Service（Caller）|该用的 Service 类型|
| -----------------------------------------------| ---------------------|
|集群内的另一个 Pod|`ClusterIP`（默认类型）|
|开发者自己的笔记本（在集群外，但能连到 Node）|`NodePort`|
|终端用户 / 公网|`LoadBalancer`|

```zsh
Internet（最外层）
  └─ LoadBalancer
       └─ Your machine（你的电脑）
            └─ NodePort
                 └─ Cluster（集群）
                      └─ ClusterIP（最内层）
```

- service.yaml没有显示指定`spec.type`​时，默认是`ClusterIP`
- `ClusterIP`​只能从**集群内部**访问
- `NodePort`​ 在 `ClusterIP` 的基础上，多开放了一个端口给"开发者的机器"，或者更准确说是能连到 Node 网络的任何机器。
- `LoadBalancer`​在 `NodePort`​ 的基础上，**再加一层**：云厂商（AWS/GCP/Azure）自动分配一个真实的公网 IP，把整个互联网的流量都能导进来。即`LoadBalancer = NodePort + cloud-assigned external IP`

‍

例子：

|Service|类型|为什么这么选|
| ---------| ----------------------------------| --------------------------------------------------------------------------|
|`backend-service.yaml`|`ClusterIP`​（没写 `type`，默认是ClusterIP）|只有 `guestbook-frontend`（集群内的另一个 Pod）需要访问 backend，不需要暴露给外部|
|`frontend-service.yaml`|`NodePort`​（`nodePort: 30080`）|你（开发者）需要从浏览器直接访问这个页面，属于"Developer's laptop"这一档|

> `NodePort`​ 这种"暴露一个固定端口号的方式比较原始、不够灵活。之后可以采用**Gateway API** 这个更高级的抽象层

‍

service的spec.ports是一个数组，每一项表示一个要暴露的端口，当同时暴露多个端口时，比如一个应用同时提供HTTP(8081)和metrics 监控接口(9100),必须写端口名称，例如:

```yaml
ports:
  - name: http        # ← 必须写
    protocol: UDP # 哪种传输层协议
    port: 8081
    targetPort: 8081
  - name: metrics      # ← 必须写
    port: 9100
    targetPort: 9100
```

‍

#### NodePort

```yaml
spec:
  type: NodePort
  selector:
    app: guestbook-frontend
  ports:
  - port: 8080 # service's in-cluster port
    targetPort: 3000
    nodePort: 30080 # range 30000-32767
```

|端口字段|谁在用它拨号|含义|
| ----------| ----------------------| -------------------------------------------------------------|
|`port`|集群**内部**调用方|Service 的虚拟端口（跟 ClusterIP 场景下的 `port` 是同一个概念）|
|`targetPort`|——|路由到的pod的容器实际监听的端口|
|`nodePort`|专门给集群**外部**的调用方用|在**每个 Node**上都开放的端口，范围固定在 30000–32767|

> `port-forward`可以绕过nodePort从开发者机器上访问集群的service，即经由Kubernetes API server直接创建一个隧道连接本地port 8090到service的port 8080
>
> ```zsh
> kubectl port-forward svc/guestbook-frontend 8090:8080
> ```

‍

## ConfigMap

|项目|内容|
| ------------------| ------------------------------------------------------------|
|ConfigMap 是什么|存储**非敏感**配置的 key-value 对象，注入方式是变成**环境变量**|
|要解决的问题|`PAGE_TITLE` 硬编码在镜像里，每次要改都得重新构建镜像|
|解决方案|把配置抽到 ConfigMap 对象里，跟镜像完全解耦|
|效果|改 ConfigMap + 触发一次 rollout，所有新 Pod 自动拿到新值，**不需要重新构建镜像**|

|注入方式|语法|效果|适用场景|
| -----------| ------| ------------------------------------------| ---------------------------------------------------|
|`envFrom`|`envFrom: - configMapRef: name: guestbook-config`|**批量**注入 ConfigMap 里的**所有** key|key 之间本来就是一组、都要用|
|`env`​ + `valueFrom`|`env: - name: PAGE_TITLE valueFrom: configMapKeyRef: name: guestbook-config key: PAGE_TITLE`|只注入**某一个**指定的 key，还可以重命名环境变量名|只需要 ConfigMap 里的某一两个特定值，不想全量导入|

- 环境变量只在 Pod **启动那一刻**被读取一次，之后 ConfigMap 内容再变，运行中的 Pod 不会自动感知，类似于`docker run -e GREETING=Ahoy my-server:v1`
- 必须 `kubectl rollout restart deployment/guestbook-frontend`，触发新 Pod 重建，新 Pod 才会读到新值

‍

以下是一个ConfigMap例子：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: guestbook-config
data:
  PAGE_TITLE: "KubeDeploy Guestbook"
  APP_ENV: "kind"
  API_URL: "http://guestbook-backend:8081"
```

‍

以下是使用ConfigMap注入到一个容器中的例子的例子:

```yaml
containers:
  - name: frontend
    # envFrom: bulk — injects ALL keys from the ConfigMap as env vars
    envFrom:
      - configMapRef:
          name: guestbook-config
          # PAGE_TITLE, APP_ENV, API_URL all injected
    # env.valueFrom: explicit — injects ONE specific key by name
    env:
      # 单独声明一个叫 PAGE_TITLE 的环境变量，它的值来自 guestbook-config 这个 ConfigMap 里的 PAGE_TITLE 这个 key
      - name: PAGE_TITLE
        valueFrom:
          configMapKeyRef:
            name: guestbook-config
            key: PAGE_TITLE

```

‍

## Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: guestbook-secret
type: Opaque
# generic secret — Kubernetes doesn't interpret the data
data:
  API_KEY: Y2hhbmdlbWU=  # base64("changeme") 敏感数据
```

- 与ConfigMap的注入机制相同
- `kubectl get secret guestbook-secret -o jsonpath='{.data.API_KEY}' | base64 -d changeme`访问，但集群管理员可以单独配置get的权限限制

‍

### 注入方法

```yaml
containers:
- name: frontend
  envFrom:
  - configMapRef:
    name: guestbook-config # bulk: PAGE_TITLE, APP_ENV, API_URL
  env:
  - name: API_KEY
    valueFrom:
      secretKeyRef: # 从secret对象中注入
        name: guestbook-secret
        key: API_KEY # explicit: only this one key from the Secret
```

```zsh
# Value inside the Pod is decoded — plain text
kubectl exec <pod> -- env | grep API_KEY # → API_KEY=changeme
# Value stored in etcd is base64-encoded
kubectl get secret guestbook-secret -o yaml # data.API_KEY: Y2hhbmdlbWU=
```
