---
title: Kaggle
date: 2026-07-02T23:00:12+08:00
lastmod: 2026-07-16T11:14:01+08:00
---

![image](../assets/witcher_1-20260707232914-4iu51np.jpg)

# Kaggle

## EDA

首先需要对数据进行Exploratory Data Analysis，通常流程：

1. pandas载入数据
2. 使用matplotlib和seaborn进行绘图

   1. Box Plot查看数值型变量，Scatter Plot查看坐标类数据分布。
   2. 对于分类问题，可以根据Label不同使用不同颜色绘制数据，有助于Feature构造
   3. 绘制变量两两之间的分布和相关度图表

### 可视化例子

[Iris Species 可视化](https://www.kaggle.com/code/benhamner/python-data-visualizations)

Iris数据集可视化[^1]

‍

‍

‍

## 附录

### 代码质量工具

  使用Ruff

```zsh
ruff check .
ruff format.
```

项目根目录存放pyproject.toml，例如：

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.format]
quote-style = "double"
```

‍

### 配置文件

  使用YAML

configs目录下存放yaml文件，例如

```
configs/

  ppo.yaml

  grpo.yaml

  sft.yaml

  reward.yaml
```

把所有参数都放到**xxx.yaml**中，例如：

```yaml
train:
  batch_size: 32
  epochs: 100
  lr: 0.0001

dataset:
  name: cifar10

model:
  hidden_dim: 512
```

**train.py:**

```python
cfg = load_yaml("config.yaml") # 是一个嵌套的字典

batch_size = cfg["train"]["batch_size"]
lr = cfg["train"]["lr"]
```

‍

#### 搜索其他人仓库的依赖库：

```zsh
find . -name "*.py" | xargs grep "^import\|^from"
```

### 日志

```python
from loguru import logger

logger.info(
    f"epoch={epoch}, "
    f"loss={loss}, "
    f"acc={acc}"
)
```

>  控制台会输出log的时间，并保存到train.log中

‍

之后获取loss数据可以grep日志文件中的"loss"：

```zsh
grep loss logs/train.log
```

‍

### 命令行参数传递

**argparse**

```python
import argparse

parser = argparse.ArgumentParser()

parser.add_argument(
    "--config",
    type=str,
    default="configs/default.yaml",
    help="Path to config file"
)
# 如果没提供seed参数，`seed`= None; 如果提供了seed参数，但无法解析为int，程序报错
parser.add_argument("--seed", type=int) 
parser.add_argument("--device", required=True) # 必须提供

args = parser.parse_args()
print(args.seed)
cfg = load_yaml(args.config)
```

‍

### 远程连接

- 开rvpn

```zsh
./zju-connect -protocol atrust -username 3230105115 -password Sherlock1 -client-data-file client_data.json
```

- ssh config 配置

```config
Host ZJU
    HostName 10.130.138.53
    Port 8022
    User wck
    ProxyCommand nc -x 127.0.0.1:1080 %h %p
    ServerAliveInterval 60
    Compression yes
    TCPKeepAlive yes
```

- rsync文件

```zsh
rsync -avzP \
  "/Users/owl/Documents/Study/计划/毕业设计/cbm-from-scratch/data/CUB_200_2011/" \
  ZJU:~/PengCheng/CBM-v1/data/CUB_200_2011/
```

- pypi镜像源

```zsh
pip install pandas scikit-learn tqdm -i https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

- ssl禁用(防止服务器ssl证书验证不通过)

```python
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    # 旧版 Python 默认不验证 HTTPS 证书
    pass
else:
    # 创建一个未经验证的 SSL context
    ssl._create_default_https_context = _create_unverified_https_context
    print("警告：已全局禁用 SSL 证书验证。这是不安全的。")
```

[^1]: # Iris数据集可视化

    ```cpp
    ‍```cpp
    #include <iostream>

    int add(int a, int b) {
        // comment
        std::string s = "Hello";
        return a + b + 42;
        
    }
    ‍```
    ```
