---
title: Kubernetes Extension
date: 2026-07-16T13:41:35+08:00
lastmod: 2026-07-16T15:11:35+08:00
---

# Kubernetes Extension

Kubernetes 的 API 设计具有可扩展性，核心类型和自定义的类型，走的是同一套底层机制

```zsh
Kind（类型名，写在kind:字段里）:      Pod         Deployment
      ↓ 对应到                            ↓             ↓
Resource（REST端点，小写复数）:      pods         deployments
      ↓ 具体的URL路径                       ↓             ↓
                                    /api/v1/pods   /apis/apps/v1/deployments
e.g. kubectl get <资源类型>
注意： 
核心类型（Pod、Service、ConfigMap这些）没有group，直接用 apiVersion: v1，对应URL是最简洁的 /api/v1
```

|坐标|含义|举例|
| ----| ---------------------------------------------------------| ----------------------------------|
|**Kind**|类型名字，你写在 `kind:` ​字段里的那个词|`Pod`​、`Deployment`​、`GuestbookApp`|
|**Resource**|API server 上对应的 REST 端点，通常是 Kind 的小写复数形式|`pods → /api/v1/pods`​；`deployments → /apis/apps/v1/deployments`|
|**Object**|存在 etcd 里的一个具体、带名字的实例|`guestbook-backend-xxx` ​是 Kind `Pod` ​的一个 Object|
|**API group + version**|决定这个类型属于哪个"命名分组"、哪个稳定级别|`apiVersion: apps/v1`​ → group 是 `apps`​，version 是 `v1`|

‍

### kubectl

**Kubernetes API本质上就是一套标准REST接口，**​**​`kubectl`​**​**只是给你拼URL、处理认证等，是一个HTTP请求wrapper**

|绕开kubectl，直接调API server的方式|命令|
| -----------------------------------------------------------| ------|
|在本地开一个代理，自动处理好TLS证书和认证token|`kubectl proxy &`|
|通过代理curl|`curl http://localhost:8001/apis/apps/v1/namespaces/default/deployments`|
|不经过kubectl的对象格式化，直接从API server返回原始的JSON|`kubectl get --raw /api/v1/namespaces/default/pods`|
|列出所有resource名字|`kubectl api-resources`|

‍

### 扩展模型

|扩展方式|干什么|要不要改Kubernetes自己的代码|覆盖的场景占比|
| ------------------------------| ----------------------------------------------------| ------------------------------------------------| ----------------------------------------------|
|**CRD**（CustomResourceDefinition）|往API server里注册一个全新的Kind|**不需要**|**95%** ——今天课程用的就是这个|
|**Admission webhooks**|在对象真正存进etcd**之前**拦截请求，做校验(`validating`​)或修改(`mutating`)|不需要改K8s核心，但需要额外部署一个webhook服务|小众场景，比如"自动给每个新Pod注入sidecar"|
|**API aggregation**|跑一个独立的API server，主API server把请求代理过去|不需要|更小众，比如`metrics.k8s.io`，需要对存储层做完全自定义控制|

‍

### CRD 和 CustomResource

```zsh
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: guestbookapps.workshop.sws26.io # 命名规则固定：`<plural>.<group>`
spec:
  group: workshop.sws26.io # 这个新类型归属的group
  names:
    kind: GuestbookApp # 你写在`kind:`字段里的名字
    plural: guestbookapps # 对应的Resource名字（URL路径段)
    shortNames: [gba] # 之后能用`kubectl get gba`代替`kubectl get guestbookapp`
  scope: Namespaced # 这个类型的对象要不要区分namespace
  versions:
  - name: v1
    served: true # 这个version是否对外提供服务/是否用来实际存储
    storage: true
```

```zsh
   
apiVersion: workshop.sws26.io/v1
kind: GuestbookApp
metadata:
  name: production
spec:
  title: "My Guestbook" # ←you write this
  replicas: 2
status:
  readyReplicas: 2
```

‍

### 协调循环

|步骤|内容|
| ------| -------------------------------------------------------------------------------------|
|**Watch**|订阅GuestbookApp的事件（Add/Update/Delete），触发时把这个对象的名字放进"待处理队列"|
|**Reconcile**|拿到期望状态(CR)和实际状态(它管理的其他资源)，做diff，patch出差异|
|**Idempotent**|同一个CR，跑两次Reconcile，结果完全一样|
|**Requeue**|Reconcile执行完，可以主动要求"过一段时间再叫我一次"，用于周期性纠偏|

```zsh
─────────────────────────────────┐
│ API server │
│ GuestbookApp/production │
│ spec.title = "My Guestbook" │
│ spec.replicas = 2 │
└────────────┬────────────────────┘
│ Watch event (Add/Update/Delete)
▼
┌─────────────────────────────────┐
│ Controller │
│ Reconcile(name="production") │
│ │
│ 1. Get GuestbookApp (desired) │
│ 2. Get ConfigMap (actual) │
│ 3. Diff → patch ConfigMap │
│ 4. Get Deployment (actual) │
│ 5. Diff → patch replicas │
│ 6. Return: requeue in 1 min │
└─────────────────────────────────┘
```

‍

## Operator = CRD + Controller + Domain knowledge

|公式|Operator = CRD + Controller + Domain knowledge|
| ------| ------------------------------------------------|
|**CRD**|定义API：用户能配置哪些字段（`spec.replicas`​、`spec.version`）|
|**Controller**|协调循环本体：watch、fetch、diff、patch|
|**Domain knowledge**|**让它够格被称为"operator"的东西**——领域专家的经验被编码进逻辑里|

Domain knowledge例子：

- **Postgres数据库升级**​——人类DBA做这件事时，需要考虑"先做备份、检查兼容性、按正确顺序升级主从节点、验证数据完整性"这一整套专业流程；一个好的Postgres operator，会把这套流程​**编码进Reconcile逻辑里**，而不是简单粗暴地"删掉重建"
- **cert-manager**——知道"证书还有几天过期就该提前续期"、"续期要调用ACME协议的哪几个API步骤"，这些都是PKI证书管理的专业领域知识

‍

 **"The operator runs as a Pod in the cluster, using the same Watch/Reconcile machinery as any built-in controller"**

**operator本身也只是一个普通的Pod（一段跑在集群里的程序）** ，它跟`kube-controller-manager`​里那些管理Deployment/ReplicaSet的内建controller，用的是**完全相同的底层机制**（Watch API server、Reconcile循环）。

**唯一的区别是它管理的是你自己定义的CRD，以及它内部编码了多少"专业运维知识"**

举个例子：

||Redis Operator|AI Infra 里的Operator|
| --| -------------------------------------------------| ---------------------------------|
|**CRD**|`RedisFailover`（spec: redis.replicas, sentinel.replicas）|`PyTorchJob`​、`InferenceService`​、`RayCluster`等|
|**Controller**|watch CR → 维护StatefulSet/Sentinel|watch CR → 维护Pod/Job/Service|
|**Domain knowledge**|Redis主从协议、故障切换|**GPU资源管理、分布式训练协调、模型服务的扩缩容策略**|

|Operator|解决什么问题|体现的领域知识|
| ----------------------| --------------------------------------------------------------------------------------------| ----------------------------------------------------------------------------------------------------------------------|
|**NVIDIA GPU Operator**|在K8s节点上自动装GPU驱动、容器工具包（nvidia-container-toolkit）、设备插件、监控组件(DCGM)|K8s原生调度器根本不知道"GPU驱动版本要不要匹配、MIG(Multi-Instance GPU)怎么切分" —— 这些全靠这个Operator补上|
|**Kubeflow Training Operator**（PyTorchJob/TFJob）|启动分布式训练任务|知道怎么给每个Pod正确设置`RANK`​、`WORLD_SIZE`​、`MASTER_ADDR`这些PyTorch分布式训练必需的环境变量，知道parameter server和worker该按什么顺序起来|
|**KServe / Seldon Core**（InferenceService）|管理模型推理服务|知道怎么按GPU利用率或请求队列深度扩缩容（而不是普通HPA看CPU），知道怎么做模型版本的灰度发布(canary)|
|**KubeRay（Ray Operator）**|管理Ray分布式计算集群（常用于RL训练、大规模数据处理）|知道Ray自己的调度模型，知道head node和worker node怎么组织|

‍

### Operator maturity

定义：这个Operator到底有多少领域知识被自动化了

|Level|能力|例子|
| -------| -------------------------------------| ------------------------------------------|
|**1 — Basic install**|从CR部署应用|Apply一个Postgres CR → Postgres Pod出现|
|**2 — Seamless upgrades**|无停机版本升级|更新`spec.version` → 自动滚动升级|
|**3 — Full lifecycle**|备份、恢复、重新配置|定时备份；从快照恢复|
|**4 — Deep insights**|指标/告警/仪表盘自动接好|Operator自动暴露Prometheus指标|
|**5 — Auto-pilot**|水平/垂直自动扩缩容、自愈、自动调优|Operator根据负载自动调整集群规模|

我们自己写的GuestbookApp operator是Level 1；真实项目——CloudNativePG（Postgres）、Redis Operator、cert-manager、Prometheus Operator——通常做到Level 3-4

‍

### 例子

1. ## `guestbookapp-crd.yaml`​​<span data-type="text" style="font-size: 1em;">定义CustomResource类型</span>

[guestbookapp-crd.yaml](../assets/guestbookapp-crd-20260716150641-i69q20y.yaml)

|字段|值|含义|
| ------| ------| ----------------------------------------------------------------------------|
|`apiVersion`|`apiextensions.k8s.io/v1`|CRD本身也是K8s内置API的一个对象——"定义新API的API"|
|`metadata.name`|`guestbookapps.workshop.sws26.io`|**强制命名规则**：必须严格等于`<plural>.<group>`，两者对不上apply会报错|
|`spec.group`|`workshop.sws26.io`|新类型所属的group，会出现在CR的`apiVersion`里|
|`spec.names.kind`|`GuestbookApp`|CR里`kind:`字段要写的值（大小写敏感）|
|`spec.names.plural`|`guestbookapps`|URL路径段(`/apis/workshop.sws26.io/v1/.../guestbookapps`​)，也是`kubectl get guestbookapps`用的词|
|`spec.names.singular`|`guestbookapp`|单数形式，用于`kubectl get guestbookapp`和提示信息|
|`spec.names.shortNames`|`[gba]`|简写别名，之后可以`kubectl get gba`​，跟内置的`kubectl get po`是同一个机制|
|`spec.scope`|`Namespaced`|GuestbookApp对象要区分namespace（像Pod一样），不是集群级对象（像Node那样）|
