---
title: Kubernetes Storage
date: 2026-07-13T13:09:01+08:00
lastmod: 2026-07-14T17:35:34+08:00
---

# Kubernetes Storage

## Volume Types

定义：Volume不像Deployment、Service、ConfigMap 那样是一个独立的API 对象，它没有自己的 `apiVersion`​/`kind`​。**Volume 本身没有独立的生命周期，它依附于 Pod 而存在，是 Pod 定义的一部分。**

- emptyDir
- hostPath
- configMap
- secret
- nfs
- persistentVolumnClaim

‍

每一个 Volume 的定义，永远由**两个部分**组成：

```yaml
spec:
  volumes: #第一步：声明"有哪些可用的存储来源"，属于Pod级别
    - name: <name>
      <Volume Type>: {...}     # emptyDir / hostPath / configMap / secret / nfs / persistentVolumeClaim ...

  containers:
    - name: ...
      volumeMounts: # 第二步：挂载在哪个容器的哪个路径下，挂载哪些volume
        - name: <引用上面的名字>
          mountPath: <容器内的路径>

```

‍

问题：**为什么Pod重启时会丢失读取时的配置？**

回答：它们存在容器的**易失的**可写层

```zsh
Writable layer (per container instance) ← deleted when the container exits
└── Image (read-only)
```

‍

|Volume 类型|生命周期(Lifetime)|用途|
| -------------| --------------------| ---------------------------------------------------------|
|`emptyDir`|跟着 **Pod**|临时暂存空间、同一 Pod 内多个容器之间共享缓存|
|`hostPath`|跟着 **Node**|挂载节点本地的工具/文件（生产环境应避免使用）|
|`configMap`|跟着 **etcd**|把 ConfigMap 的内容变成文件注入容器|
|`secret`|跟着 **etcd**|把 Secret 的内容变成文件注入容器|
|`downwardAPI`|跟着 **etcd**|把 Pod 自身的元数据（名字、标签、资源限制等）暴露成文件|
|`nfs`|**独立**存在|网络共享存储，支持多个 Node 同时读写（ReadWriteMany）|
|`persistentVolumeClaim`|**独立**存在|持久化存储——比任何一个 Pod 活得都久|

- hostPath：数据绑定在Node上，**Pod 下次可能被调度到别的 Node**，那时候这份数据就完全访问不到了
- configMap，secret，downwardAPI绑定在etcd上，持久，但应用只能读取，不可写入
- nfs，persistentVolumeClaim 生命周期跟 Pod 完全脱钩。

  - nfs：网络共享文件系统，**多个 Node 上的多个 Pod 可以同时挂载、同时读写同一份存储，不同的replicas可以共享同一份数据**
  - PVC：重要的存储抽象层

‍

### emptyDir

同一个Pod的不同容器共享

```yaml
volumes:
- name: scratch # scratch：临时硬盘存储区
  emptyDir: {} # volume type = emptyDir 默认存储在硬盘上
- name: shm # shared memory
  emptyDir: 
    medium: Memory # 使用tmpfs文件系统，存在易失性存储器上（内存），一般挂载在/tmp上
```

> medium: Memory用于容器间的高速通信，受容器内存上限限制

‍

### hostPath

存在宿主机(node)上，pod销毁时不回消失。

```zsh
volumes:
- name: node-logs
  hostPath:
    path: /var/log
    type: Directory # 校验规则，这个路径应该是什么性质的东西
- name: runtime-sock
  hostPath:
    path: /run/containerd/containerd.sock
    type: Socket # 校验是否是unix socket
```

> `containerd`​：每个 Node 上负责启动/停止容器的底层运行时，`kubelet`​ 通过 **CRI（Container Runtime Interface）**  跟它对话。
>
> `containerd.sock`​是containerd这个进程对外暴露API的入口，是一个**Unix Domain Socket，** 专门接收别的进程发来的指令（比如"列出所有容器"、"启动一个新容器"、"杀掉某个容器"）
>
> `Unix Domain Socket`​普通网络通信（比如 HTTP 请求）走的是 TCP/IP，需要经过完整的网络协议栈。**Unix Domain Socket 是专门给"同一台机器上的进程之间通信"设计的一种更轻量的机制**——它在文件系统上表现为一个特殊的文件（用 `ls -l`​ 看会显示类型是 `s`，就是 socket），但它不存储数据字节，而是一个"通信端点"，两个进程只要都能访问这个文件路径，就能互相收发消息，不需要走网络栈，速度更快、开销更小。

我们可以创建一个pod，它通过创建一个指向宿主机的`/run/containerd/containerd.sock`type=hostPath的volume对象，volumeMounts挂载到自己容器内的路径，来实现容器内调用宿主机上containerd进程提供的API功能。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: node-inspector
spec:
  containers:
    - name: inspector
      image: some-image-with-crictl
      volumeMounts:
        - name: runtime-sock
          mountPath: /run/containerd/containerd.sock   # 容器内的路径
  volumes:
    - name: runtime-sock
      hostPath:
        path: /run/containerd/containerd.sock            # 宿主机上的真实路径
        type: Socket

```

该pod运行`crictl`命令行工具。

`crictl --runtime-endpoint unix:///run/containerd/containerd.sock ps -a`会列出这台Node上所有容器。

‍

### nfs

定义：是一种允许多台机器通过网络，同时挂载并读写同一份远程存储的协议。NFS服务器独立于任何kubernetes节点存在。

```yaml
volumes:
  - name: shared
    nfs:
      server: nfs.example.com #真实存在的NFS服务器地址
      path: /exports/data # 这台 NFS 服务器上，要共享出来的具体目录路径
volumeMounts:
  - name: shared
    mountPath: /data # 容器内部看到这份共享存储时，路径是 /data

```

假设要将guestbook-backend的数据存储到共享的NFS上，需要在backend-deployment.yaml中写：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: guestbook-backend
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: backend
          image: guestbook-backend:latest
          volumeMounts:
            - name: shared
              mountPath: /data # 容器代码需要改成把数据写到 /data 目录下
      volumes:
        - name: shared
          nfs:
            server: nfs.example.com
            path: /exports/data

```

‍

> 注意，不是所有存储类型都支持"多个 Pod 同时读写同一份数据"。
>
> |访问模式|含义|支持这个模式的存储|
> | ----------| ---------------------| ------------------------------------------------------------|
> |`ReadWriteMany`|**多个 Node 上的多个 Pod，可以同时挂载并读写**|`nfs`、AWS EFS（"NFS-compatible"服务）|
> |`ReadWriteOnce`|同一时刻**只有一个 Node** 能挂载读写|大多数云端块存储（AWS EBS）、`kind` 自带的本地存储 provisioner|

‍

## Storage Layer Model

|概念|定义|
| ------| ---------------------------------------------------------------------------------------------------------|
|**Volume**|挂载进容器的一个目录，有很多类型（`emptyDir`​、`hostPath`​、`configMap`​、`secret`​、`downwardAPI`​、`nfs`​、`persistentVolumeClaim`）。生命周期只到"同一个 Pod 内容器重启"为止|
|**PersistentVolume (PV)**|集群里**真实存在的一块存储资源**——有容量(capacity)、访问模式(`ReadWriteOnce`​/`ReadWriteMany`​)、回收策略(`Delete`​/`Retain`)|
|**PersistentVolumeClaim (PVC)**|Pod（开发者）发出的"**存储申请**"——声明需要多少容量、什么访问模式；API server 负责把它跟一个匹配的 PV 绑定起来|
|**StorageClass**|一份"**自动配置的菜谱**"——PVC 一创建，StorageClass 的控制器就自动生产一个 PV 来满足它，不需要管理员手动介入|

问题：**为什么需要PV/PVC/StorageClass？**

回答：应用开发者(写deployment的人）需要知道`server: nfs.example.com`​、`path: /exports/data`​ 这些**底层存储**信息才能创建volume对象，这些被硬编码进Pod/Deployment的YAML中。

解决：

- 应用开发者使用**PVC**，只需要声明"要多大、什么访问模式"，不关心具体是哪块盘、在哪台机器。
- **StorageClass**在PVC提交后，自动分配一个匹配的 PV。

‍

### Storage Class

```zsh
StorageClass  ──(自动生产)──>  PersistentVolume  <──(申请/绑定)──  PersistentVolumeClaim
GatewayClass  ──(实现绑定)──>  Gateway            <──(挂载路由)──  HTTPRoute
```

|角色|存储场景|Gateway场景|
| ------------------| -----------------------------------------------| ----------------------------------------------|
|**Operator**（定义基础设施）|写 `StorageClass`，决定"用哪个云厂商的存储驱动、怎么生产"|写 `GatewayClass`，决定"用哪个具体的实现（NGINX/Envoy）"|
|**Developer**（只管提需求）|写 `PersistentVolumeClaim`​： *"我要 1Gi，ReadWriteOnce"*|写 `HTTPRoute`​： *"把 /api 路由到我的 backend"*|

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
```

- **​`reclaimPolicy: Delete`​**:一旦 PVC 被删除，背后真实的存储(以及里面所有数据)也会立刻被清理掉。
- **​`volumeBindingMode: WaitForFirstConsumer`​**​: 假设某种存储类型只能被"同一台 Node"访问, 例如`ReadWriteOnce`​只能单节点挂载，如果 PVC 一提交，立刻在 Node-A 上生产了一个 PV，但**调度器后来决定把这个 Pod 排到 Node-B**——那这个已经生产好、绑在 Node-A 上的存储，Node-B 上的 Pod 根本没法挂载，直接卡住。  
  ​`WaitForFirstConsumer`先让调度器决定"这个 Pod 到底该跑在哪个 Node"，于是就可以去那台确定下来的 Node 上生产 PV

### PV and PVC

#### 动态分配存储卷

声明**PersistentVolumeClaim对象**来动态分配存储卷  **——Dynamic Provisioned**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pgdata
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

|PVC 提交后，`kubectl get pvc` 显示的字段|含义|
| ---------------------------| ----------------------------------------------|
|`STATUS: Bound`|已经成功匹配/绑定到一个 PV|
|`VOLUME: pvc-3f2a1b...`|绑定到的这个 PV 的名字（**系统自动生成**，你从来不用自己起）|
|`CAPACITY: 1Gi`|实际拿到的容量|
|`ACCESS MODES: RWO`|实际获得的访问模式|

#### PVC访问模式

- `ReadWriteOnce`​（RWO）——最常见，**单节点**独占读写。数据库这类需要严格保证"同一时刻只有一个写入者"的应用，必须用这个模式，避免多个副本同时写导致数据损坏。
- `ReadOnlyMany`（ROX）——多节点共享，但只读。
- `ReadWriteMany`​（RWX）——多节点共享读写`nfs` 支持的模式，需要 NFS 或 CephFS 这类网络共享存储才能实现。

#### 静态分配存储卷

直接声明**PersistentVolume对象**预先分配存储卷 **——Static Provisioned**

搭配hostPath使用（类似volumes[].hostPath)——使用本地Node上的存储

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: postgres-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "" # 静态PV
  hostPath:
    path: /mnt/kubedeploy/postgres
    type: DirectoryOrCreate
```

结果如下：

```zsh
NAME          CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      CLAIM   STORAGECLASS   VOLUMEATTRIBUTESCLASS   REASON   AGE
postgres-pv   1Gi        RWO            Retain           Available                          <unset>                          14s
```

可以看到是单节点独占读写（RWO）

‍

‍

然后在PVC中进行静态绑定：

```yaml
volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes:
      - ReadWriteOnce
      storageClassName: ""      # ← 就是这一行，决定了整个绑定方式
      resources:
        requests:
          storage: 1Gi
```

**PersistentVolume controller（** 跑在 `kube-controller-manager`​ 里 **）会扫描所有还没被绑定、状态是**​**​`Available`​**​**的PV，尝试跟新出现的PVC做匹配**。匹配需要同时满足这几个条件：

|匹配条件|PVC要求|你的PV是否满足|
| ------------------| -----------------------| ------------------------------------------|
|accessModes|ReadWriteOnce|✓ 一致|
|capacity|requests.storage: 1Gi|✓ PV的 capacity.storage 也是1Gi(≥即可)|
|storageClassName|""|✓ 完全一致|

‍

## StatefulSet

### 为什么需要：

|StatefulSet 提供的四种"稳定性"|具体表现|
| --------------------------------| -----------------------------------------------------------------------------------|
|稳定的 Pod 名字|`postgres-0`​、`postgres-1`——固定的序号，不是像 Deployment 那样的随机哈希后缀|
|有序的启动/关闭|启动：必须等 `postgres-0`​ 变成 Running+Ready，`postgres-1` 才会开始启动；关闭：反过来，倒序执行|
|稳定的存储|每个 Pod 通过 `volumeClaimTemplates`​ 拿到**专属于自己**的 PVC；`postgres-0` 永远挂载同一个 PVC，Pod 删了 PVC 不会跟着删|
|稳定的 DNS|配合 headless Service，每个 Pod 有独立的 DNS 记录：`postgres-0.postgres.default.svc.cluster.local`(deployment的Pod没有DNS记录)|

**应用例子**：

- quorum系统（ZooKeeper、etcd）——这些系统需要明确知道"谁是谁"才能做投票/选举
- 消息队列（Kafka）——"each broker owns its partition logs"——每个 broker 管理着特定的一部分数据，不是随便哪个 broker 都能顶上
- 数据库复制（PostgreSQL + Patroni）——需要明确区分"谁是主库、谁是从库"
- 分布式数据库（Cassandra、CockroachDB）——每个节点各自负责一部分数据分片

总结：多个成员之间**不是对等、可互换的关系**，而是各自拥有一部分"独一无二"的职责和数据时，必须使用StatefulSet组织多个Pod副本。

‍

### YAML结构

假设我们想申请1G的持久化存储卷，运行一个postgres数据库服务。

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres # 哪个headless Service来负责治理我
  replicas: 1
  selector: 
    matchLabels:
      app: postgres # 用标签筛选，声明"这个 controller 该管理哪些 Pod"
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pgdata
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 1Gi
```

|字段|含义|
| ------| ------------------------------------------------------------------------------------------------------|
|`spec.serviceName: postgres`|指定"治理这个 StatefulSet"的 **headless Service** 名字，实现**稳定DNS**的必要条件|
|`spec.volumeClaimTemplates`|一份"PVC模板"——StatefulSet controller 会照着这份模板，给**每个** Pod 各自生成一个独立的 PVC，命名规则是 `<模板名>-<StatefulSet名>-<序号>`|
|`containers[].volumeMounts`|每个 Pod 内部，用模板名（`pgdata`）引用属于自己的那个 PVC|

> 普通 Deployment 里，`volumes`​ 是**一次性声明，所有副本共用同一份**；
>
> 而 **StatefulSet 的** **​`volumeClaimTemplates`​**​ **是"一份模板"，controller 会照着这份模板，为每个 Pod 单独生成一个专属 PVC**：
>
> ```zsh
> volumeClaimTemplates（模板，只写一次）
>     ↓ StatefulSet controller 为每个副本各自生成
> pgdata-postgres-0（专属于 postgres-0 的PVC）
> pgdata-postgres-1（专属于 postgres-1 的PVC，如果replicas>1）
>
> 命名规则是 <模板名>-<StatefulSet名>-<序号>
> ```
>
> `postgres-0`​ 就算被删除重建，**新的** **​`postgres-0`​**​ **依然会精确挂载回同一个** **​`pgdata-postgres-0`​**，实现了"每个副本都有自己专属的、持久的存储身份"

‍

### Headless Service——与StatefulSet配套使用

|对比维度|普通 Service|Headless Service|
| ----------------| ---------------------------------------------------------------| ----------------------------------------------------------------|
|DNS 解析结果|一个统一的虚拟 ClusterIP|**直接返回每个 Pod 各自真实的 IP**，没有虚拟IP这一层|
|转发路径|名字 → ClusterIP → kube-proxy(DNAT) → 随机选一个匹配的 Pod|具体Pod名字(如postgres-0) → **直接**是postgres-0的真实 IP，客户端直连|
|有没有负载均衡|有（kube-proxy 随机分摊流量）|**没有**——你查的是哪个 Pod 的名字，就连到哪个具体 Pod|
|怎么声明|默认（不用特殊配置）|`spec.clusterIP: None`|

|配合 StatefulSet 后，DNS记录变成|指向谁|
| ----------------------------------| ------------------------------------|
|`postgres-0.postgres.default.svc.cluster.local`|精确指向 postgres-0 这一个具体 Pod|
|`postgres-1.postgres.default.svc.cluster.local`|精确指向 postgres-1 这一个具体 Pod|

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  clusterIP: None # 指定是headless service
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

‍

### 数据持久化

有了postgres服务，guestbook后端就可以连接到postgres数据库存储数据了。

‍

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
type: Opaque
stringData:
  DATABASE_URL: "postgres://postgres:postgres\
    @postgres-0.postgres:5432\
    /guestbook?sslmode=disable"
```

接着在backend-deployment.yaml中更新env

```yaml
env:
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: postgres-secret
      key: DATABASE_URL
```

若main.go中发现环境变量DATABASE_URL不为空，就使用Postgres数据库存储。

```go
if dbURL := os.Getenv("DATABASE_URL"); dbURL != "" {
  s, _ = newPGStore(dbURL)
} else {
  s = &memStore{nextID: 1}
}
```

‍

## 其他

### Postgres DSN

**DSN（Data Source Name，数据源名称）是一种标准化的字符串格式，把"怎么连接一个数据库"所需的所有信息，打包压缩进一个URL形式的字符串里**——协议、用户名密码、地址、端口、具体连哪个数据库、以及各种连接选项，全部编码在一行文本里。例如：

```zsh
postgres://postgres:postgres@postgres-0.postgres:5432/guestbook?sslmode=disable
   │          │        │              │              │      │           │
 协议(scheme) 用户名   密码           主机名           端口   数据库名    连接选项

客户端知道了Postgres数据库的DSN后，可以sql.Open("postgres", url)。
go语言中的lib/pq驱动库会把这一整段字符串解析出用户名、密码、主机、端口、数据库名、选项这几个部分，然后真正去建立TCP连接、完成Postgres协议握手。
```

- sslmode：Postgres 默认支持客户端和服务器之间用 TLS 加密通信。但这个lab里部署的Postgres容器，没有配置任何TLS证书。如果不显式加上 `sslmode=disable`，客户端库会尝试和服务器协商加密连接，但服务器没有证书可以协商，会导致连接失败。

‍

### Init Container

在backend-deployment.yaml中Pod的spec中添加一个initContainer，等待Postgres能接受连接后再启动backend：

```yaml
spec:
  initContainers:
  - name: wait-for-postgres
    image: busybox:1.36
    command: [sh, -c]
    args:
    - |
      until nc -z postgres 5432; do
        echo "waiting for postgres..."; sleep 2
      done
```

```zsh
kubectl logs -l app=guestbook-backend
Defaulted container "backend" out of: backend, wait-for-postgres (init)
2026/07/13 16:10:19 connecting to Postgres...
2026/07/13 16:10:19 connected to Postgres
2026/07/13 16:10:19 backend listening on :8081
```
