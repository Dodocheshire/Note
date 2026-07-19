---
title: Docker
date: 2026-07-09T11:53:57+08:00
lastmod: 2026-07-10T21:34:45+08:00
---

# Docker

### 端口映射

```zsh
docker run -p <主机端口>:<容器端口> image名
docker run -p 9090:8081 my-server:latest
```

含义：把容器内部监听的 9090 端口,映射到我这台电脑(主机)的 8081 端口上

为什么：容器默认是**网络隔离**的(容器的namespace里包括"独立的网络接口")——即使容器里的程序监听了 8081 端口,这个端口只在容器**内部**的网络里存在,除非显式地把它"打通"到主机上

> **前提**：Dockerfile中需要声明监听：`EXPOSE 8081`

‍

### Dockerfile

**dockerfile用于创建IMAGE**

```dockerfile
from golang:1.22-alphine as builder
workdir /app # 在容器中cd到指定工作目录
copy go.mod go.sum ./
run go mod download # 每个run会产生一个cache layer(checkpoint)
copy . . # copy [host_dir/host_file] [container_dir]
run CGO_ENABLED=0 go build -o backend . # CGO_ENABLED=0 不链接C的库(静态编译)

from alpine:3.19 # docker构建只保留最后一个‘from’的镜像
workdir /app
copy --from=builder /app/backend .
expose 8081 # 容器监听的端口
entrypoint ["./backend"] # 容器启动时执行的文件
```

‍

### 运行容器

```zsh
docker run --rm -e GREETING=Ahoy -p 9090:9090 my-server:v1
```

- --rm: 容器停止后（比如按 Ctrl+C 或者进程退出）自动删除
- -e: 传递环境变量
- -p [hostport:containerport] 端口映射，[containerport]必须是容器监听的端口
- 查看所有容器：docker ps -a 输出如下：

  |列|含义|
  | --------------| ------------------------------------------|
  |CONTAINER ID|容器的唯一 ID|
  |IMAGE|容器基于哪个镜像创建|
  |COMMAND|容器启动时执行的命令|
  |CREATED|创建时间|
  |STATUS|当前状态（`Up 5 minutes`​ 表示运行中，`Exited (0) 2 minutes ago` 表示已停止）|
  |PORTS|端口映射情况|
  |NAMES|容器名字|

- 使用docker rm [container id / name] 删除容器记录

‍

## Docker-Compose

**Docker Compose 是 Docker 官方自带的一个工具，专门用来在自己电脑这一台机器上，同时管理多个互相配合的容器**——不需要 Kubernetes 那一整套（没有 Deployment、没有 Service、没有协调循环），是更轻量级的"本地多容器编排"方案。

```yaml
services: # 声明这个应用由哪几个容器组成
  backend:
    build: ./backend        # 用 ./backend 目录下的 Dockerfile 构建镜像
    ports:
      - "8081:8081"          # 宿主机8081 → 容器8081
    environment:              # 传给容器的环境变量
      PORT: "8081"

  frontend:
    build: ./frontend
    ports:
      - "8080:8080"
    environment:
      PORT: "8080"
      PAGE_TITLE: "KubeDeploy Guestbook"
      APP_ENV: "local"
      API_URL: "http://backend:8081"   # ← 注意这里！
      API_KEY: "dev-secret"
    depends_on:
      - backend                # 声明"先启动 backend，再启动我"

```

> Docker Compose 会自动帮同一份 `docker-compose.yaml`​ 里的所有容器建一个共享的虚拟网络，容器之间可以**直接用 service 名字互相访问**

- docker compose up --build -d    # 根据这份文件，构建镜像并在后台启动所有容器  
  docker compose down               # 停止并清理所有容器

容器启动后，就可以在本机的浏览器中输入`http://127.0.0.1:8080`进行访问前端了！但是后端没有设置database url，数据存在内存中，没有持久化，所以下次重启容器时数据就消失了。
