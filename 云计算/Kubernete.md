---
title: Kubernete
date: 2026-07-10T18:34:56+08:00
lastmod: 2026-07-13T23:06:01+08:00
---

# Kubernete

### 概念速查

|概念|定义|关键特点|
| ------| -----------------------------------------------| ----------------------------------------------------------------------------------------------------|
|**镜像 (Image)**|只读模板|任意多个容器都能基于同一个镜像启动|
|**容器 (Container)**|镜像的运行中实例|有自己的可写文件系统层、自己的进程、自己的网络命名空间——即使基于同一镜像，两个容器实例也互不相通|
|**Node**|集群里的一台机器——能跑 Pod 的计算单元|kind 环境下不是真机/虚拟机,而是 **Docker 容器**;方便一台笔记本模拟出多节点集群|
|**Pod**|最小可部署单元:一个或多个共享网络和存储的容器|详见下表|
|**Deployment**|可靠地运行 Pod|声明要几份副本，协调循环负责维持|
|**Service**|可靠地找到应用|提供稳定的 DNS 名字,即使 Pod 重启、IP 变化也不受影响|
|**ConfigMap**|不重建镜像也能配置应用|从镜像外部注入环境变量|
|**Secret**|专门存放敏感配置的独立对象类型|注入机制和 ConfigMap 一样,但访问权限可单独控制|

|Pod 特性|说明|
| ------------------| ------------------------------------------------------------------------------------------|
|共享网络命名空间|同一 Pod 内多个容器共用同一个 IP 地址,可用 `localhost` 互相访问,不用跨网络|
|可共享 Volume|一个容器写文件,另一个容器能直接读到|
|调度单位|整个 Pod 被作为一个整体调度到同一个 Node 上|
|容器数量声明|在 `spec.containers` 里定义(不包括隐藏的 pause 容器)|
|自愈能力|**没有**——Pod 一旦被删除就彻底消失,不能"重启"同一个 Pod;要靠 Deployment 等上层对象重建全新 Pod|

‍

### Kubernete集群结构与机制

```zsh
Cluster（整个集群，几台机器组成）
└── Namespace（default / kube-system / ...）
    └── Deployment（kubectl create deployment创建）
        └── ReplicaSet（Deployment 自动生成，负责维持副本数）
            └── Pod
                └── Container
```

与docker不同，kubernete通过**Observe-Diff-Act** 循环：**Reconciliation Loop**

|期望状态|出问题|循环的动作|
| -------------| ------------------| --------------------------------------------|
|1个副本在跑|容器崩了|检测到0个在跑 → 启动新 Pod|
|`PAGE_TITLE=NewTitle`|ConfigMap 更新了|检测到配置漂移 → 用新环境变量重新发布 Pod|
|`replicas: 3`|实际只有1个在跑|检测到少2个 → 创建2个新 Pod|

- control-plane 掌管"期望状态 vs 实际状态"这套协调循环

‍

## kubectl CLI

### 集群 / 上下文（Context）管理

|命令|含义|
| ------| -----------------------------------------------------------------------|
|`kind create cluster --name kubedeploy --config kind-config.yaml`|创建一个名为 `kubedeploy` 的本地 kind 集群|
|`kind delete cluster --name kubedeploy`|删除这个 kind 集群|
|`kubectl cluster-info`|显示集群的 API server 地址等基本信息|
|`kubectl config get-contexts`|列出本机配置过的所有集群"上下文"（可能同时连着 kind、EKS 等多个集群）|
|`kubectl config current-context`|查看当前正在使用哪个上下文|
|`kubectl config use-context kind-kubedeploy`|切换到指定的上下文|
|`aws eks update-kubeconfig --region <region> --name <cluster-name>`|把 kubectl 连接到指定的 EKS 集群（自动写入/切换 kubeconfig）|

‍

### 节点层面

|命令|含义|
| ------| -------------------------------------------------------------------------|
|`kubectl get nodes`|列出集群里所有 Node（control-plane + worker）|
|`kubectl get nodes -o wide`|同上，额外显示 IP、操作系统、容器运行时等详细信息|
|`kubectl describe node <node-name>`|看某个 Node 的详细信息（资源用量、Conditions、上面跑了哪些 Pod）|
|`kubectl debug node/<node-name> -it --image=busybox`|在指定 Node 上起一个调试 Pod，`chroot /host` 后可直接操作该节点的文件系统，替代 SSH|

‍

### 命令式创建

|命令|含义|
| ------| --------------------------------------------------------|
|`kubectl run <pod-name> --image=<image-name>`|直接创建一个**裸 Pod**（无 controller 管理，删除后不会自动重建）|
|`kubectl create deployment <deploy-name> --image=<image-name> --replicas=N`|创建一个 Deployment，声明维持 N 个该镜像的 Pod 副本|
|`kubectl scale deployment <deploy-name> --replicas=N`|修改已有 Deployment 的期望副本数为 N|
|`kubectl set image deployment/<deploy-name> container=<new-image>`|直接修改集群里某 Deployment 的镜像版本，触发滚动更新|

‍

### 声明式部署应用

|命令|含义|
| ------| -------------------------------------------------------------------|
|`kubectl apply -f xxx.yaml`|把 YAML 里描述的期望状态提交给 API server（创建或更新对象，幂等）|
|`kubectl apply -f <dir>/`|对某个目录下所有 YAML 文件批量 apply|
|`kubectl delete -f xxx.yaml`|按 YAML 文件里声明的对象删除|
|`kubectl diff -f xxx.yaml`|预览这次 apply 会改动哪些字段，不真正提交|

‍

### 查询当前状态

|命令|含义|
| ------| -------------------------------------------------------------------------------|
|`kubectl get pods`|列出当前 namespace 下的 Pod|
|`kubectl get all`|一次列出 Deployment、Pod、Service、ReplicaSet 等常见类型|
|`kubectl get pods -w`|持续监听状态变化（`-w`​ \= watch），直观看到协调循环在工作|
|`kubectl get pods -A`|查看所有 namespace 的 Pod（`-A`​ \= --all-namespaces）|
|`kubectl get pods -n <namespace>`|指定只看某个 namespace|
|`kubectl get pods -o wide`|显示更多列（IP、所在 Node）|
|`kubectl get pods -o yaml`|完整输出该对象的 `spec`​ + `status` 原始数据|
|`kubectl get namespaces`|列出所有 namespace（虚拟分区）|
|`kubectl get endpoints <svc-name>`|查看某个 Service 实际能转发到哪些 Pod 的 `IP:port`；为空说明标签不匹配，不是网络问题|
|`kubectl get events --sort-by='.lastTimestamp'`|按时间顺序看集群最近发生的所有事件|
|`kubectl describe pod <pod-name> [-n <namespace>]`|看某个 Pod 的详细信息和 Events（`Scheduled → Pulling → Pulled → Created → Started`）|
|`kubectl delete pod <pod-name>`|删除一个 Pod——如果它属于 Deployment，会被自动重建|
|`kubectl delete pod <pod-name> --grace-period=0 --force`|不等待优雅关闭（默认30秒宽限期），立即强制删除|

‍

### 标签与筛选

|命令|含义|
| ------| --------------------------------------------------------------|
|`kubectl get pods -l app=guestbook-backend`|按标签 `app=guestbook-backend` 筛选 Pod|
|`kubectl get pods --show-labels`|额外列出每个 Pod 身上打的所有标签（key\=value）|
|`kubectl describe pod -l component=kube-controller-manager -n <namespace>`|按标签筛选并描述匹配到的 Pod（可能匹配多个，会依次全部输出）|
|`kubectl delete pod -l app=my-nginx-deploy --grace-period=0 --force`|按标签筛选后批量强制删除|
|`kubectl label node <node-name> <key>=<value>`||

‍

### 调试

|命令|含义|
| ------| ---------------------------------------------------------------------------------|
|`kubectl logs <pod-name>`|看容器的标准输出日志，排查 `CrashLoopBackOff` 之类问题|
|`kubectl logs -l app=<label-value>`|按标签筛选 Pod，看它们的日志|
|`kubectl logs <pod-name> -c <container-name>`|多容器 Pod 时，指定看哪一个容器的日志|
|`kubectl exec -it <pod-name> -- sh`|进入容器内部交互式 shell|
|`kubectl exec <pod-name> -- env`|在容器里执行一次性命令（比如查看环境变量是否注入成功）|
|`kubectl exec -it <pod-name> -c <container-name> -- sh`|多容器 Pod 时，指定进入哪一个容器|
|`kubectl port-forward svc/<service-name> 8080:8080`|把集群内部 Service 的端口转发到本机 `localhost`，方便浏览器直接访问|
|`kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -- curl <url>`|起一个一次性 Pod，测试集群内部网络连通性（比如测试 DNS 名字能否解析到 Service）|

‍

### Namespace相关

`-n`​ / `--namespace`​ 用于指定某次命令要看哪个 namespace，不写默认是 `default`​。例：`kubectl get pods -n kube-system`​、`kubectl describe pod coredns-589f44dc88-7xm6v -n kube-system`​（注意：Pod 名字在前，`-n` 是补充参数，不能反过来写）。

若想让**当前 context 默认**就作用在某个 namespace 上（不用每次都加 `-n`）：

```zsh
kubectl config set-context --current --namespace=kube-system
```

‍

### 滚动更新

|命令|含义|
| ------| -------------------------------------------------------------------------------------------------------------|
|`kubectl rollout status deployment/<name>`|查看这次更新有没有完成|
|`kubectl rollout restart deployment/<name>`|强制触发一次滚动重启（比如改了 ConfigMap，Pod 不会自动感知，需要这条命令让 Deployment controller 重建 Pod）|
|`kubectl get replicaset`|滚动更新过程中能同时看到新旧两个 ReplicaSet|
|`kubectl rollout undo deployment/<name>`|回滚到上一个版本|

‍

### Kind专属

|命令|含义|
| ------| --------------------------------------------------------------------------------------------------------------------------|
|`kind load docker-image <image-name> --name kubedeploy`|把本机 Docker 构建好的镜像"塞进" kind 每个节点自己的 containerd 存储里，因为 kind 节点无法直接拉取本机镜像。配合 `imagePullPolicy: Never` 使用|

‍

### EKS/AWS 专属

|命令|含义|
| -----------| ---------------------------------------|
|`aws eks create-cluster --name <name> --role-arn <arn> --resources-vpc-config subnetIds=...`|创建 EKS 集群控制平面|
|`aws eks create-nodegroup --cluster-name <name> --node-role <arn> --subnets ... --scaling-config ...`|创建工作节点组|
|`aws eks describe-nodegroup --cluster-name <name> --nodegroup-name <ng-name>`|查看节点组健康状态|
|`aws ecr get-login-password \| docker login --username AWS --password-stdin <ecr-url>`|登录 ECR 镜像仓库|
|`docker tag <image-name> <ecr-url>/<image-name>`​ + `docker push`|把本地镜像推送到 ECR，供 EKS 节点拉取|

### 流程

目的：使用AWS的Elastic Kubernetes Service创建集群并在本地使用kubernete访问和管理。

1. 登陆AWS账号，启动会话[aws课程Leaner Lab](https://awsacademy.instructure.com/courses/177195/modules/items/17403498)。将AWS_Details下的Cloud Access内容复制到本地的\~/.aws/credentials文件中。终端中输入aws configure  配置地区为us-east-1等
2. 点击LearnerLab左上角AWS，进入us-east-1.console.aws.amazon.com，搜索EKS服务，创建集群MyECS
3. 生成 / 更新本地 kubeconfig，连到这个 EKS 集群

   ```zsh
   aws eks update-kubeconfig --region us-east-1 --name MyECS
   > Added new context arn:aws:eks:us-east-1:477296622190:cluster/MyEKS to /Users/owl/.kube/config
   ```

4. 在网页console中创建node group

5. 创建pod并部署服务

‍

---

## 杂项

### http请求

HTTP 请求的"我要访问哪个域名"这个信息，实际上是通过一个叫 `Host` 的请求头传递的，跟"实际连接到哪个 IP/地址"是两件独立的事

正常情况下，浏览器帮你自动完成两件事：

1. 用 DNS 把域名解析成一个真实 IP，连接过去
2. 在请求头里自动带上 `Host: <你输入的域名>`

`curl -H "Host: guestbook.local" "http://$GATEWAY_HOST/"`功能如下：

- 真实连接目标: $GATEWAY_HOST (AWS负载均衡器的真实地址)
- 请求头里写的: Host: guestbook.local (伪装成要访问这个域名)

‍
