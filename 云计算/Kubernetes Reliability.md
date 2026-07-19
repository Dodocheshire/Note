---
title: Kubernetes Reliability
date: 2026-07-14T13:16:17+08:00
lastmod: 2026-07-14T16:52:48+08:00
---

# Kubernetes Reliability

**未解决的问题**

|问题|具体场景|后果|
| --------------| --------------------------------------------------------| ------------------------------------------------------------------------------|
|**App deadlock**（应用死锁）|backend 进程还活着（容器状态正常），但已经卡死不响应了|Kubernetes 只看到"容器在跑"，看不出它已经失能，流量继续被转发给这个坏掉的Pod|
|**Slow startup**（启动慢）|backend 需要花10秒才能连上Postgres|Kubernetes 在它真正准备好之前就开始转发流量，用户看到报错|
|**Resource starvation**（资源饥饿）|某个Pod贪婪地占满了CPU|同一台机器上其他Pod被饿死，甚至整个节点OOM(out of memory)|
|**Abrupt shutdown**（粗暴关闭）|Kubernetes发SIGTERM信号|frontend 在处理请求的过程中socket被直接切断，请求处理到一半中断|

‍

## Probe

### Probe机制

|探针类型|回答的问题|失败后果|适用场景|
| ----------| ------------------------------| --------------------------------------| ------------------------------|
|**Liveness probe**|这个容器还活着吗？|失败达到 `failureThreshold`​ 次后，**kubelet 杀掉并重启这个容器(在同一个Pod中）**|死锁、卡死的进程|
|**Readiness probe**|这个容器准备好接收流量了吗？|失败时，**Endpoints controller 把这个Pod的IP从Service端点列表里摘除**，不发流量过去，通过后再恢复|启动慢、临时过载|
|**Startup probe**|这个容器的初始启动完成了吗？|在它成功之前，**Liveness和Readiness探针都暂停执行**|有较长一次性初始化过程的应用|

- Liveness probe定期发送探测请求，如果容器进程崩溃或卡死，探测失败多次则杀掉重启。注意Pod name和Pod IP不会变化。
- 如果一个Pod暂时因为压力过大响应变慢（临时过载），无法接受新流量，则Readiness Probe会失败。
- 有些应用启动特别慢（比如需要预热大量缓存、加载海量配置），如果直接套用 Liveness probe 的常规检测频率，可能应用还没启动完就被 Liveness probe 误判为"死了"反复重启，陷入死循环。所以在应用Liveness probe前会先应用Startup probe给这类应用一个"充分的初始化时间”

无论用哪种探针类型（Liveness/Readiness/Startup），具体"怎么发起探测"都可以选这三种方式之一：

|探测机制|判定"成功"的标准|适合谁|
| ----------| ----------------------------------| ----------------------------------|
|`httpGet`|HTTP响应状态码是 2xx|guestbook 用的就是这个|
|`tcpSocket`|能成功建立TCP连接即可|没有HTTP接口的服务（比如 Redis）|
|`exec`|在容器里执行一个命令，退出码是 0|类似 `pg_isready` 这种检测工具|

‍

### Liveness Probe

```yaml
spec:
  containers:
  - name: backend
    livenessProbe:
      httpGet:
        path: /healthz # 探测哪个HTTP路径
        port: 8081 # 探测哪个端口
      initialDelaySeconds: 5 # 容器启动后，等5秒再开始第一次探测
      periodSeconds: 10 # 之后每隔10秒探测一次 
      failureThreshold: 3 # 连续失败3次才判定为"死亡"
```

现象：

```zsh
$ kubectl get pods
NAME                   READY  STATUS   RESTARTS
guestbook-backend-aaa   1/1   Running     0
# After 3 liveness failures:
NAME                     READY   STATUS   RESTARTS
guestbook-backend-aaa     1/1    Running     1 # RESTARTS column increments. 
# same Pod — kubelet restarted the container in-place
```

```zsh
$ kubectl describe pod guestbook-backend-aaa
Warning Unhealthy ... Liveness probe failed
Normal Killing ... Container backend failed
Normal Started ... Started container backend
```

‍

### Readiness probe

```yaml
spec:
  containers:
  - name: backend
  readinessProbe:
    httpGet:
      path: /healthz
      port: 8081
    initialDelaySeconds: 3
    periodSeconds: 5
    failureThreshold: 2
  
```

与Liveness probe机制类似，但探测失败的结果不一样。

```zsh
$ kubectl get pods
NAME                   READY   STATUS   RESTARTS
guestbook-backend-aaa   1/1   Running      0
guestbook-backend-bbb   0/1   Running      0 # probe failing, READY set 0
# endpoints controller removes Pod(bbb) IP from Service
# Pod bbb stays Running
```

```zsh
$ kubectl get endpoints guestbook-backend
NAME               ENDPOINTS
guestbook-backend  10.244.0.5:8081 # only one endpoint(aaa)
# bbb removed; re-added automatically when probe passes
```

‍

### Startup probe

```yaml
spec:
  containers:
  - name: backend
    startupProbe:
      httpGet:
        path: /healthz
        port: 8081
      failureThreshold: 30
      periodSeconds: 10
```

`最大启动窗口 = failureThreshold × periodSeconds = 30 × 10 = 300秒（5分钟）`

```zsh
$ kubectl describe pod guestbook-backend-aaa
Warning Unhealthy Startup probe failed: ...
# liveness and readiness not run until this clears
Normal Started Started container backend
# startup probe passed — liveness now active
```

‍

## 资源管理

### resource request and limits

```yaml
spec:
  containers:
  - name: backend
    resources:
      requests:
        cpu: "100m" # millicores (1000m = 1 CPU core)
        memory: "64Mi" # Mi = mebibytes即2^20字节
      limits:
        cpu: "500m"
        memory: "128Mi"
```

|YAML字段|值|谁在用|作用|
| ----------| ------| --------------------| -----------------------------------------------|
|`requests.cpu`|`100m`|**调度器**（放置Pod时参考）|Pod只会被放到"至少还有这么多空闲容量"的Node上|
|`requests.memory`|`64Mi`|同上|同上|
|`limits.cpu`|`500m`|**kubelet**（运行时强制执行）|超过限制：CPU被**节流(throttle)**|
|`limits.memory`|`128Mi`|同上|超过限制：容器被**OOM杀死**|

>  如果requests设置的太低，Pod可能调度不了

### QoS classes

**什么时候起作用：**

当单个容器自己超过了limit(自己设定的内存上限)，QoS等级不起作用，直接被内核杀死。只有当Node上跑着好几个Pod，各自都没有超过自己的limit，但加起来把整台机器的内存都快耗尽了。这时候kubelet会**主动、提前**驱逐一些Pod

|QoS等级|判定条件|内存压力下的驱逐顺序|
| ---------| ------------------| ----------------------|
|**Guaranteed**|每个容器 `requests == limits`|**最后**被驱逐|
|**Burstable**|至少一个容器 `requests < limits`|**第二**被驱逐|
|**BestEffort**|任何容器都**没设置** `requests`​/`limits`|**最先**被驱逐|

> **为什么这个顺序是合理的**——`Guaranteed`​（`requests == limits`​）代表"这个Pod声明的需求和实际用量完全对得上，没有任何'超预期'的弹性空间"，说明运维人员对这个Pod的资源需求做过精确规划，通常是最关键的工作负载，理应最后被牺牲；而 `BestEffort`（完全没声明资源）代表"连最基本的资源规划都没做"，理应在紧急情况下第一个被让出资源

‍

## 生命周期管理

### Lifecycle hooks

负责管理**同一个Pod内部的生命周期时序**

```yaml
spec:
  containers:
  - name: frontend
    lifecycle:
      postStart:
        exec:
          command: [sh, -c, echo started >> /tmp/lifecycle.log]
       preStop:
        exec:
          command: [sh, -c, sleep 5]
    # Grace termination:优雅退出
    terminationGracePeriodSeconds: 30 # preStop 执行 + 进程收到SIGTERM后自己收尾的上限时间
```

|Hook类型|什么时候执行|特点|
| ----------| -----------------| ---------------------------------------------------|
|`postStart`|容器**启动后立刻**执行|跟entrypoint**并发**执行，必须先完成，才能开始跑任何探针|
|`preStop`|Pod被删除、**SIGTERM发送之前**执行|容器会**一直存活**，直到这个hook执行完，SIGTERM才会真正被发出|

> postStart跟主进程（entrypoint）**同时**开始跑，**postStart必须先跑完，探针才会开始工作**
>
> preStop的`sleep 5`是为了：
>
> ① Pod被删除  
> ② 先执行 preStop（sleep 5）——这5秒内容器进程完全没受影响,继续正常处理请求  
> ③ 与此同时，kube-proxy在这5秒的窗口里，已经从容地将这个即将消失的Pod从路由规则里清理干净  
> ④ 5秒后 preStop（sleep）结束，这才真正发出SIGTERM，进程正常退出  
> ⑤ 因为流量早就已经不转发过来了，这次退出**不会中断任何正在处理的请求**

‍

### initContainers

负责管理**不同Pod/不同Deployment之间的启动依赖顺序**

```yaml
spec:
  initContainers:
  - name: wait-for-postgres # 主容器的启动依赖postgres程序的就绪
    image: busybox:1.36
    command: [sh, -c]
    args:
    - |
      until nc -z postgres-0.postgres 5432 # netcat，反复轮询测试端口是否可连
      do
        echo "waiting for postgres..."
        sleep 2
      done
  containers:
  - name: backend
    image: guestbook-backend:latest
    env:
     - name: DATABASE_URL
       valueFrom:
         secretKeyRef:
           name: postgres-secret
           key: DATABASE_URL
```

- 如果有多个init容器，是按多个声明容器**串行**跑的，不是并发
- `wait-for-postgres`​容器不退出，主容器 `backend`​ 就**永远不会启动**，Pod会一直卡在 `Init:0/1` 状态
- 如果init容器本身失败（比如非0退出码），Kubernetes会**自动重试**，不会直接放弃

‍

### 总结

```zsh
Init Container（Pod启动之前，跨Pod依赖）→ postStart（容器刚启动，同一Pod内并发执行）
                                                      ↓
                                          容器正常运行,接受探针检测
                                                      ↓
                             preStop（Pod即将删除，容器仍存活，给外部系统收敛时间）→ SIGTERM

```

‍

## 容器辅助功能

### Sidecar pattern

定义：同一个Pod内部的一种**设计模式**，把“辅助职责”从主容器中拆出去。Sidecar是主容器的辅助容器。

例子：主应用+日志收集

```yaml
spec:
  volumes:
    - name: logs
      emptyDir: {}
  containers:
    - name: backend
      volumeMounts:
        - name: logs
          mountPath: /var/log/app    # backend往这里写日志

    - name: log-tail # the Sidecar
      image: busybox:1.36
      command: [sh, -c]
      args: [tail -f /var/log/app/app.log]
      volumeMounts:
        - name: logs
          mountPath: /var/log/app    # log-tail从同一个路径读，可以转发日志内容
```

**Sidecar和主容器**的3个共享特性 **：**

- **共享生命周期**——Pod是最小可部署单元，一个或多个容器被打包在一起当作整体调度、创建、删除
- **共享网络**——共享同一个网络命名空间，容器间可以直接用localhost互相访问
- **共享Volume**——讲Volume定义时，Volume声明在Pod级别，可以被多个容器各自mount

|Sidecar 常见用途|具体例子|
| ------------------| ------------------------------------------------|
|**可观测性**|日志转发（Fluent Bit）、指标采集（Prometheus）|
|**流量处理**|Service mesh（Istio、Linkerd）、TLS终止|
|**配置**|热加载（不重启主容器就能应用新配置）|

‍

### Downward API

作用：让容器了解自身的元信息，不依赖于查询Kubernetes API

```yaml
spec:
  containers:
  - name: backend
    env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
    - name: MEMORY_LIMIT
      valueFrom:
        resourceFieldRef:
          resource: limits.memory
```

|引用方式|能暴露什么|举例|
| ----------| ------------------------| ------------------------------------------------------------------------|
|`fieldRef`|Pod自身的元数据|`metadata.name`​（Pod名字）、`metadata.namespace`​（命名空间）、`metadata.labels['app']`​（某个具体标签的值）、`status.podIP`（Pod的IP）|
|`resourceFieldRef`|这个容器的资源配置数值|`limits.memory`​、`requests.cpu` 等|

|实际用途|说明|
| ---------------------------| ------------------------------------------------------------------------------|
|结构化日志里带上Pod名字|方便在几十上百个副本里，快速定位是哪个具体Pod打的日志|
|JVM堆内存按 `limits.memory` 的比例设置|让应用自己知道"我被分配了多少内存"，动态调整内部参数，而不是硬编码一个固定值|

‍

## Node维护

**问题**：维护一台Node时，怎么安全地把上面的Pod挪走，不影响正在运行的应用？

```zsh
# mark node unschedulable — no new Pods land here
$ kubectl cordon node-1
node/node-1 cordoned
# evict all Pods via the eviction API
# DaemonSet Pods are skipped — they run on every node by design
$ kubectl drain node-1 --ignore-daemonsets
evicting pod guestbook-frontend-aaa
evicting pod guestbook-backend-aaa
node/node-1 drained
# after maintenance, re-enable scheduling
$ kubectl uncordon node-1
node/node-1 uncordoned
```

|命令|作用|
| ------| ---------------------------------------------------------------------------------------------------------------------|
|`kubectl cordon node-1`|把 Node 标记为"不可调度"——**不影响已经在跑的Pod**，只是不再有**新**Pod被放到这台机器上|
|`kubectl drain node-1 --ignore-daemonsets`|通过**驱逐API**，把这台Node上所有Pod迁走；`--ignore-daemonsets`让DaemonSet管理的Pod跳过（因为它们设计上就是"每个节点必须有一份"，没法真正"迁走"）|
|`kubectl uncordon node-1`|维护完成后，重新允许调度新Pod到这台机器|

|流程|谁负责|
| -----------------| -------------------------------------------------------------|
|Pod被驱逐后消失|Deployment controller 察觉到"少了副本"，在**别的Node**上重新调度出新Pod|
|drain命令本身|**会阻塞**，直到这个Pod真正被清空才继续处理下一个|

‍

> Why eviction, not kubectl delete—— Eviction会检查**PodDisruptionBudgets**

‍

### PodDisruptionBudget

定义：PodDisruptionBudget（PDB）是一个声明式对象：你在其中声明"驱逐我这批Pod时，任何时刻至少（或最多）要保留多少个可用"，驱逐API在执行主动式操作（如 `drain`、集群升级、Autoscaler缩容）时必须遵守这条底线，超出底线的驱逐请求会被直接拒绝——但它对硬件故障、OOM-kill这类被动式中断完全无效。

> Disruption：干扰/中断。泛指"**任何导致 Pod 停止运行的事件**"

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: frontend-pdb
spec:
  minAvailable: 1 # 不管你想驱逐哪个Pod，先算一下：驱逐它之后，剩下还在跑的Pod数量，够不够1个？不够的话，这次驱逐直接被拒绝
  selector:
    matchLabels:
      app: guestbook-frontend
```

```zsh
$ kubectl get pdb
NAME             MIN AVAILABLE       ALLOWED DISRUPTIONS # 允许的驱逐数
frontend-pdb         1                       1
```

时序图：

```zsh
2个frontend副本 + minAvailable: 1
①驱逐第一个 → 剩1个 ≥ 1（刚好达标）→ 允许
②drain卡住，不会立刻驱逐第二个 → 一直等到替补Pod在别的Node上Running且通过Readiness
③替补起来后，剩余数量又恢复到2 → 这时才允许驱逐第二个（原来的那个）
```

‍

## 总结

|触发的事件|Reconciliation Loop(协调循环)的响应|
| ---------------------------| -----------------------------------------------------------------|
|Liveness探针连续失败3次|kubelet杀掉并重启容器；RESTARTS计数递增|
|Readiness探针失败|Endpoints controller把该Pod从Service里摘除；流量停止转发|
|Pod超过内存limit|kubelet执行OOM-kill（优先杀BestEffort/Burstable）|
|Pod的preStop hook正在执行|容器保持存活，直到hook退出或宽限期用完|
|`postStart` hook失败|kubelet立刻杀掉容器|
|Init容器以非0退出|Pod停留在`Init:0/1`；kubelet持续重试直到退出码为0|
|Sidecar容器崩溃|kubelet重启这个sidecar；Pod本身保持Running|
|`kubectl drain`时Pod被删除|先检查PDB：如果会违反`minAvailable`，drain会被阻塞|
|读取Downward API字段|没有协调循环参与——值是在Pod创建那一刻就注入好的，是唯一的例外|
