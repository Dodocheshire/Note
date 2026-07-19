---
title: PyTorch 科研笔记
date: 2026-07-19T18:07:48+08:00
lastmod: 2026-07-19T18:16:34+08:00
---

# PyTorch 科研笔记

这套笔记整理自 `cbm-from-scratch`​——复现论文 *Concept Bottleneck Models* (Koh et al., 2020) 的过程

## 目录

|文档|关键词|
| --------------------------| ------------------------------------------------------------------------------|
|实验工程规范[^1]|dataclass Config、argparse 自动生成、YAML 覆盖优先级、可复现性、设备无关代码|
|Tensor基础与设备管理[^2]|torch.Size、索引 vs 切片、.to(device)、no_grad、train()/eval()|
|数据管道与预处理[^3]|Dataset/DataLoader、transforms、Normalize、类别不均衡|
|损失函数[^4]|CrossEntropyLoss、BCEWithLogitsLoss 的 pos_weight/weight/reduction|
|模型设计模式[^5]|train/eval 双态 forward、Inception aux logits 的坑|
|优化器与学习率调度[^6]|SGD、StepLR 无下限的坑、LambdaLR 自定义调度|
|多阶段训练与推理流水线[^7]|缓存中间产物、复合模型评估、topk/softmax 推理|
|附录·服务器与环境[^8]|ruff、日志、远程连接、pypi 镜像源|

## 项目背景

`cbm-from-scratch`​：手写实现 CBM 论文的四种训练方式（independent / sequential / joint / standard），backbone 用 Inception-v3 微调，数据集 CUB-200-2011。过程中通读了论文附录的实验细节和作者官方实现（`ConceptBottleneck/CUB`），逐项对比配置差异，修正了若干与官方不一致之处（aux logits、学习率下限、两阶段超参分离、concept loss 的 reduction 口径等）。这些修正过程就是下面几篇笔记的来源。

[^1]: # 实验工程规范

    这篇整理 `cbm-from-scratch/src/config.py` 里的几个好用的配置方法。

    ## dataclass 做配置，而不是裸 dict

    ```python
    from dataclasses import dataclass, fields, asdict

    @dataclass
    class Config:
        experiment: str = "joint"
        lr: float = 0.001
        weight_decay: float = 4e-4
        scheduler_step: int = 1000
        lambda_concept: float = 0.0
        num_epochs: int = 100
        seed: int = 0
        ...
    ```
    比 `dict`​ 或 `argparse.Namespace` 好在哪：

    - **有类型提示**：`cfg.lr`​ 编辑器能自动补全、能类型检查；`dict["lr"]` 打错 key 只有运行时才报错。
    - **有默认值**：新增字段只需给个默认值，老的调用点不用全部改。
    - **​`fields()`​**  ​ **可以反射**：下面这条自动生成 CLI 参数的技巧就是靠它。

    ## 用 dataclass 的字段自动生成 argparse 参数

    ```python
    def parse_config() -> Config:
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=Path, default=None)
        for f in fields(Config):
            parser.add_argument(f"--{f.name}", type=type(f.default), default=None)
        args = parser.parse_args()
        ...
    ```
    `fields(Config)`​ 拿到所有字段名和默认值的类型，自动生成 `--lr`​、`--weight_decay`​……**新增一个 Config 字段，命令行参数自动就有了**，不用每加一个超参就手写一行 `parser.add_argument`。

    > 注意：这里 `type=type(f.default)`​ 只对标量字段（str/int/float）好用；`Path`​ 字段这么写会失败（`type=Path`​ 需要单独处理），布尔字段也不适用（`type=bool`​ 对 argparse 是个经典坑，`"--flag False"`​ 会被解析成 `True`，因为非空字符串都是真值）。
    >

    ## 三层配置覆盖优先级

    ```python
    values = asdict(Config())        # 1. 默认值
    if args.config:
        values.update(yaml.safe_load(args.config.read_text()))  # 2. yaml 覆盖
    cli = {k: v for k, v in vars(args).items() if k != "config" and v is not None}
    values.update(cli)                # 3. 命令行显式传入的覆盖 yaml
    return Config(**values)
    ```
    `dict.update()`​ 的调用顺序就是优先级：**默认值 < yaml < 命令行**。这样可以有一份 `joint.yaml`​ 存着某个实验的完整配置，扫参脚本再用 `--lr 0.01 --seed 1` 覆盖某几个字段，不用为每个超参组合写一份 yaml。

    > **坑**：PyYAML 不会把 `1e-4`​ 这种没有小数点的科学计数法识别成 `float`​，会读成字符串 `"1e-4"`​。后续 `cfg.min_lr / cfg.lr`​ 这类运算会报 `TypeError: unsupported operand type(s) for /: 'str' and 'float'`​。两种修法：① yaml 里老实写成 `0.0001`​；② 在 `__post_init__` 里按字段声明类型统一强转。
    >

    ## 用 `__file__` 锚定项目根目录

    ```python
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    ```
    脚本经常要 `cd`​ 到某个子目录再跑（比如 `cd src && python main.py`​），如果用相对路径拼 `data/`​、`result/`​，产物就会随着"从哪个目录启动"到处乱跑。用 `__file__`​（当前文件自己的路径）往上锚定，不管从哪里调用，`PROJECT_ROOT` 永远指向同一个地方。

    ## 每个 run 落盘自己的 config.json——可复现性的关键

    ```python
    def prepare_run_dir(cfg: Config) -> Path:
        name = cfg.run_name or f"lr{cfg.lr:g}_wd{cfg.weight_decay:g}_seed{cfg.seed}"
        run_dir = cfg.output_dir / cfg.experiment / name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2, default=str))
        return run_dir
    ```
    - **目录名要能唯一区分超参组合**，否则扫参时不同配置的 run 会互相覆盖结果。
    - **​`asdict(cfg)`​**  ​ **把整个配置存成** **​`config.json`​**：记录本次run使用的配置

    ## 可复现性：`set_seed` 要覆盖所有随机源

    ```python
    def set_seed(seed: int):
        random.seed(seed)              # Python 自带 random
        np.random.seed(seed)           # numpy
        torch.manual_seed(seed)        # CPU 上模型初始化等
        torch.cuda.manual_seed_all(seed)  # 所有 CUDA 设备
    ```
    **只设** **​`torch.manual_seed`​**​ **是不够的**，因为随机数还可能来自 Python 自带的 `random`​（部分 transform 会用到）和 `numpy.random`。

    ### DataLoader 的随机性

    ```python
    def seed_worker(worker_id):
        worker_seed = torch.initial_seed() % 2**32
        np.random.seed(worker_seed)
        random.seed(worker_seed)

    def make_loader_generator(seed):
        g = torch.Generator()
        g.manual_seed(seed)
        return g

    DataLoader(dataset, shuffle=True, num_workers=4,
               worker_init_fn=seed_worker, generator=g)
    ```
    `num_workers > 0`​ 时，PyTorch 会 fork 出子进程去读数据，**子进程有自己独立的随机状态**，主进程调用 `set_seed` 不会传递过去。所以：

    - `generator`​ 控制 `shuffle=True` 时的打乱顺序；
    - `worker_init_fn` 负责给每个 worker 子进程单独播种。

    两个东西职责不同，**都要设，缺一个复现性就有漏洞**。

    ## 设备无关代码

    ```python
    def get_device() -> str:
        return "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    ```

[^2]: # Tensor基础与设备管理

    ## torch.Size

    `tuple`​ 的子类，是 `tensor.shape`​（或 `tensor.size()`）返回的对象类型，每个元素表示 tensor 在对应维度上的长度。可以像 tuple 一样被索引、遍历、和普通 tuple 比较相等，不可变。

    ## 索引与切片：形状不一样

    **tensor 索引出来的"标量"始终还是 0 维 tensor**（不是 Python 数值），需要 `.item()` 才能取出纯 Python 数值：

    ```python
    a = torch.arange(10, dtype=torch.float32)
    a[1].shape          # torch.Size([])       ← 0维，不是标量
    a[1].dtype          # torch.float32
    type(a[1].item())   # <class 'float'>      ← 只有 .item() 才是纯Python数
    ```
    **tensor 切片出来的是 1 维 tensor**，即使只切出一个元素：

    ```python
    a[1:2].shape   # torch.Size([1])   ← 索引0轴仍然存在，只是长度为1
    ```
    ## `.to(device)` 的坑：tensor 不是原地操作

    ```python
    images, labels, concepts = images.to(device), labels.to(device), concepts.to(device)
    ```
    `tensor.to(device)`​ **返回一个新 tensor**，不是原地修改，必须重新赋值接收；忘记赋值的话变量还留在原来的设备上，之后模型在 GPU、数据在 CPU，会直接报错 `Expected all tensors to be on the same device`。

    `model.to(device)`​ 则不同——**​`nn.Module.to()`​**  ​ **是原地的**（把所有参数和 buffer 搬过去），常见写法 `model.to(device)`​ 不接收返回值也没问题（虽然它也会返回 `self`，方便链式调用）。

    ## `torch.no_grad()`：推理/验证时关掉梯度记录

    ```python
    model.eval()
    with torch.no_grad():
        for images, labels in valid_loader:
            preds = model(images)
            ...
    ```
    训练时 PyTorch 会记录每一步运算，供 `.backward()`​ 反向传播用（这套机制叫 **autograd**）。验证/推理阶段不需要更新参数，`torch.no_grad()` 关掉这个记录，省显存、也省计算。

    ## `model.train()`​ / `model.eval()`：不只是一个标记

    调用 `model.train()`​ 或 `model.eval()`​ 会**递归**设置所有子模块（包括嵌套很深的 backbone）的 `self.training` 属性.

    - **Dropout** 在 train 模式下随机丢弃神经元，在 eval 模式下变成恒等映射；
    - **BatchNorm** 在 train 模式下用当前 batch 的统计量，在 eval 模式下用训练过程中累积的滑动平均统计量；
    - 某些模型的 `forward`​ 会**读** **​`self.training`​**​ **分支返回不同结构的输出**（比如 Inception-v3 训练时多返回一个 aux logits）


[^3]: # 数据管道与预处理

    ## PIL.Image → torch.Tensor

    ```python
    from PIL import Image
    from torchvision import transforms

    img = Image.open(path).convert("RGB")  # 灰度图先转RGB，保证通道数一致

    eval_transform = transforms.Compose([
        transforms.Resize(int(IMAGE_SIZE * 1.14)),
        transforms.CenterCrop(IMAGE_SIZE),   # 先放大一点再裁，保证裁到的是"中心"而不是被压缩变形
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])
    input_tensor = eval_transform(img).unsqueeze(0)   # 补上 batch 维
    ```
    `transforms.ToTensor()` 做两件事：

    1. 把 PIL 图片（0~255 整数像素）从 `(H, W, C)`​ 转成 `(C, H, W)`；
    2. 所有像素值除以 255，归一化到 `[0, 1]`。

    `torch.unsqueeze(input, dim)`​ 在指定位置新插入一个长度为 1 的轴——单张图推理时常用来补 batch 维（模型期望输入是 `(N, C, H, W)`）。

    ## Normalize：为什么是这几个数字

    ```python
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ```
    把每个颜色通道的像素值减均值、除标准差，让数值分布落在统一范围内。这组 `mean/std`​ 是在**整个 ImageNet 训练集**上，把像素缩放到 `[0,1]` 后按 R/G/B 三个通道分别统计出来的：

    $$
    \text{mean}_c = \frac{1}{N \cdot H \cdot W}\sum_{\text{所有图片，所有像素}} \text{pixel}_c
    $$

    **只有用 ImageNet 预训练的 backbone（ResNet、Inception 等）时，才应该套用这组现成的均值/方差**——它们和预训练权重是配套的，模型"习惯"看到这个分布的输入。如果从零训练或者换了完全不同的数据分布，重新统计自己数据集的均值方差可能更合适。

    > 官方 CBM 实现的 Inception-v3 用的是 `mean=[0.5,0.5,0.5], std=[2,2,2]`​ 配合 `transform_input=True`（模型内部再做一次反向变换），效果上和这里的 ImageNet 均值方差写法基本等价
    >

    ## 训练/验证要用不同的 transform

    ```python
    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.8, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])
    eval_transform = transforms.Compose([
        transforms.Resize(int(IMAGE_SIZE * 1.14)),
        transforms.CenterCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])
    ```
    训练集用随机裁剪/翻转/颜色抖动做数据增强，增加多样性、减少过拟合；**验证/测试集不能加这些随机增强**——否则同一张图每次验证结果都不一样，没法比较不同 epoch/超参的好坏。验证集只需要一个确定性的 resize+裁剪。

    ## 自定义 Dataset 三件套

    ```python
    class CUBDataset(Dataset):
        def __init__(self, image_ids, transformer, cub_dir, class_concepts):
            ...  # 读元数据（路径、标签），但不在这里读图片本身

        def __getitem__(self, index):
            image = Image.open(image_path).convert("RGB")
            image_tensor = self.transformer(image)
            label = torch.tensor(...)
            return (image_tensor, label, concept_vector)

        def __len__(self):
            return self.labels.size
    ```
    `__init__`​ 只读轻量的元数据（路径列表、标签数组），**真正的图片解码放在**   **​`__getitem__`​**  ​ **里、按需读取**——如果在 `__init__`​ 里把所有图片都读进内存，数据集稍微大一点就爆内存；`__getitem__`​ 配合 `DataLoader` 的多进程/预取，可以一边训练一边读下一批图。

    ## 类别不均衡：pos_weight

    多标签二分类任务（比如"预测 111 个概念哪些为真"）里，某些概念可能正例极少（比如某个属性只有 9% 的样本是正的）。模型很容易学到"全猜 0"这个捷径，因为这样平均损失也不高。解决办法是给正例项加权：

    ```python
    n_pos = per_image_concepts.sum(axis=0)          # 每个concept，训练集里正例的图片数
    n_neg = per_image_concepts.shape[0] - n_pos      # 负例数
    pos_weight = n_neg / np.clip(n_pos, 1, None)     # clip防止某个concept正例数为0时除0
    ```
    `pos_weight[i]`​ 越大，说明这个概念越稀有，模型预测错正例时的惩罚就越重——具体怎么用到 `BCEWithLogitsLoss` 里，见《损失函数》。

    ## 分层划分 train/val

    ```python
    from sklearn.model_selection import train_test_split
    train_ids, val_ids = train_test_split(
        trainval_ids, test_size=0.2, random_state=SPLIT_SEED,
        stratify=[img_id_to_label[i] for i in trainval_ids],
    )
    ```
    `stratify=`​ 保证切分后训练集和验证集里**每个类别的比例都和整体一致**，而不是简单随机切分可能导致某些类别在验证集里样本极少甚至没有。`random_state`​ 固定切分本身的随机性——**注意这个 seed 应该和"实验重复用的 seed"分开**：数据划分只应该在所有重复实验（不同 seed 的多次训练）之间保持一致，否则不同 seed 跑出来的结果没法直接比较（比较的是"训练随机性"还是"数据划分随机性"混在了一起）。


[^4]: # 损失函数

    ## CrossEntropyLoss：单标签多分类

    ```python
    loss_fn = nn.CrossEntropyLoss()
    loss = loss_fn(outputs, labels)
    ```
    - **​`outputs`​**​：模型直接吐出来的**原始 logits**，形状 `(batch_size, n_classes)`​，**不需要自己先 softmax**——`CrossEntropyLoss`​ 内部会做（等价于 `log_softmax`​ + `nll_loss`，比手动 softmax 再取 log 数值上更稳定）。
    - **​`labels`​**​：真实类别标签，形状 `(batch_size,)`​，每个是 `0 ~ n_classes-1` 的整数索引（不是 one-hot 向量，内部会自动按索引取对应位置）。
    - `label_smoothing` 参数（默认 0）：把 one-hot 标签"软化"，分量不会全集中在真实类别上，是常见的正则手段。

    ## BCEWithLogitsLoss：多标签/多概念二分类

    CBM 的"概念层"本质是 `n_concepts`​ 个独立的二分类问题（每个概念要么真要么假），用 `BCEWithLogitsLoss`​ 而不是 `CrossEntropyLoss`：

    ```python
    concept_loss = nn.BCEWithLogitsLoss(
        pos_weight=pos_weight.to(device),
        reduction="mean",
    )
    loss = concept_loss(concept_logits, concept_labels)  # (N, C) vs (N, C)
    ```
    `BCEWithLogitsLoss`​ = `sigmoid`​ + `BCELoss`​ 合并成一步，好处是**数值稳定**（用了 log-sum-exp 技巧，避免手动 `sigmoid()`​ 后取 `log(0)`​ 导致 `-inf`​）。永远优先用这个，而不是自己 `sigmoid(x)`​ 再喂给 `BCELoss`。

    ### `pos_weight`​ vs `weight`：容易混的两个参数

    $$
    l_{n,c} = -w_{n,c}\big[p_c\, y_{n,c}\log\sigma(x_{n,c}) + (1-y_{n,c})\log(1-\sigma(x_{n,c}))\big]
    $$

    - **​`weight`​**（对应上式 $w_{n,c}$）：乘在**整条**损失上，正例负例一起放大/缩小。
    - **​`pos_weight`​**（对应上式 $p_c$）：**只**乘在正例项 $y\log\sigma(x)$ 上，专门放大"正例判错"的惩罚。

    CBM 里概念的正例通常远少于负例（比如某属性只有 9% 图片为真），用 `pos_weight = n_neg/n_pos`​ 能让模型倾向于认真判别正例，而不是"全猜 0"就能拿到不错的平均损失。**这个语义正好对应论文里"按类别不均衡加权，让模型学会预测更稀有的正标签"**  ，所以选 `pos_weight`​ 是对的，不要和 `weight` 搞混。

    ### `reduction` 到底在算什么——以及它怎么悄悄改变了超参的含义

    `BCEWithLogitsLoss(logits, target)`​ 内部先算出一张**逐元素**的损失表 $L = \{l_1, \dots, l_N\}$——对 `(N, C)` 的输入，这张表就有 $N \times C$ 个数。`reduction`​ 决定这张表怎么塌缩成一个标量（因为 `.backward()` 只能对标量求导）：

    |reduction|做什么|
    | --------------| ------------------------|
    |`'none'`|不塌缩，返回 `(N, C)` 原始表|
    |`'sum'`|所有元素**相加**|
    |`'mean'`（默认）|和除以元素个数，即 `sum / (N×C)`|

    关键点：  **​`'mean'`​**  ​ **是对 batch 和 concept 两个维度一起平均**，不是只对 batch 平均。

    **这一点直接决定了"联合损失"里权重系数的实际大小。**   比如 CBM 的 joint 训练，总损失是 `task_loss + λ * concept_loss`：

    - 如果 `concept_loss`​ 用 `reduction='mean'`（对 $N \times C$ 全体平均，相当于 $\frac{1}{C}\sum_c \text{BCE}_c$），
    - 而参考实现/论文里的写法是对 concept **求和**（不除以 C），

    那么同一个 `λ`​，两边概念项实际相差了约 **C 倍**（C = 概念数）。复现论文时如果直接抄论文的 `λ`​ 数值，但 `reduction`​ 口径不同，跑出来的"最优 λ" 会和论文报告的数值差出一到两个数量级——**这不是代码错了，是两种实现对"概念损失的尺度"定义不同**，只需要把 `λ` 按概念数等比缩放（或者手动把 reduction 改成"对 concept 求和、对 batch 求平均"）就能对齐：

    ```python
    per = nn.BCEWithLogitsLoss(pos_weight=..., reduction='none')  # (N, C)
    concept_loss = per.sum(dim=1).mean()   # 对 concept 求和(×C)，再对 batch 平均——对齐"论文口径"
    ```
    **教训**：多个损失项加权求和时，先确认每一项的 `reduction` 口径是否一致，否则权重系数的"数值"和它实际的"影响力"对不上，会浪费大量时间在扫一个错误尺度的超参网格上。

    ## 辅助损失（auxiliary loss）：不只是主 loss

    Inception-v3 训练时会从网络中间层多引出一个辅助分类头（aux logits），充当额外的正则/梯度捷径：

    ```python
    main_loss = criterion(outputs, labels)
    aux_loss  = criterion(aux_outputs, labels)
    loss = main_loss + 0.4 * aux_loss   # 0.4 是常见的经验权重
    ```
    这个模式不只适用于分类任务的 `CrossEntropyLoss`​，同样适用于概念层的 `BCEWithLogitsLoss`——只要网络结构提供了 aux 输出，主/辅助损失都按同样的方式加权求和。具体网络结构层面怎么拿到这两路输出，见《模型设计模式》。


[^5]: # 模型设计模式

    ## 用 `self.training` 分支控制 forward 的返回结构

    `model.train()`​ / `model.eval()`​ 会递归设置所有子模块的 `self.training`​。这不只是个标记——很多模型的 `forward`​ 会**根据这个标记返回不同结构的输出**，最典型的例子是 torchvision 的 Inception-v3：

    - **训练模式**：`backbone(x)`​ 返回一个 `namedtuple`​：`InceptionOutputs(logits, aux_logits)`；
    - **eval 模式**：只返回主 logits（单个 tensor）。

    自己包装模型时，可以顺着这个约定走：

    ```python
    class XtoCModel(nn.Module):
        def __init__(self, n_concepts):
            super().__init__()
            self.backbone = inception_v3(weights=Inception_V3_Weights.DEFAULT)
            self.backbone.fc = nn.Linear(self.backbone.fc.in_features, n_concepts)
            self.backbone.AuxLogits.fc = nn.Linear(self.backbone.AuxLogits.fc.in_features, n_concepts)

        def forward(self, x):
            if self.training:
                out = self.backbone(x)              # InceptionOutputs(logits, aux_logits)
                return out.logits, out.aux_logits    # 训练: (主概念logits, aux概念logits)
            return self.backbone(x)                  # eval: 只返回主概念logits(单个tensor)
    ```
    好处：外层调用代码不用另外判断"现在是不是训练模式"，`self.training`​ 已经替它判断过了，`forward` 直接给出当前模式该有的输出形状。

    > `out = self.backbone(x),`​——行末多打了一个逗号。Python 会把 `out`​ 变成一个**只有一个元素的 tuple**，而不是 `InceptionOutputs`​，后面 `out.logits`​ 直接 `AttributeError`
    >

    ## 下游必须知道这个约定：`isinstance` 分支处理

    既然 `forward`​ 训练时可能返回 `(main, aux)` 元组、eval 时返回单个 tensor，调用它的 loss 函数就要能处理两种情况：

    ```python
    def _apply_loss(crit, pred, target):
        if isinstance(pred, tuple):
            main, aux = pred
            return crit(main, target) + 0.4 * crit(aux, target)
        return crit(pred, target)
    ```
    这是这种"输出结构随 `self.training`​ 变化"设计的代价：**好处是省去外部重复判断训练/验证，坏处是所有下游消费者（loss 函数、验证循环里的 accuracy 计算）都必须知道这个约定**，用 `isinstance` 或类似方式做兼容。

    ## 复合模型：把两个子模型的 aux 输出都接进下游

    Concept Bottleneck 的 joint 训练，是把 `x→c`​（backbone）和 `c→y`​（下游分类头）拼成一个整体训练。既然 backbone 训练时有 `(main, aux)`​ 两路概念输出，**这两路都要各自过一遍同一个下游模型**，和官方实现的 `End2EndModel.forward_stage2` 对齐：

    ```python
    class StandardModel(nn.Module):
        def __init__(self, n_concepts, n_classes):
            super().__init__()
            self.XtoCModel = XtoCModel(n_concepts=n_concepts)
            self.CtoYModel = CtoYModel(n_concepts=n_concepts, n_classes=n_classes)

        def forward(self, x):
            if self.training:
                c_main, c_aux = self.XtoCModel(x)
                return (self.CtoYModel(c_main), self.CtoYModel(c_aux)), (c_main, c_aux)
            c = self.XtoCModel(x)
            return self.CtoYModel(c), c
    ```
    关键是**同一个** **​`CtoYModel`​**​ **实例**被调用了两次（`c_main`​ 和 `c_aux`​ 各过一遍），而不是新建两个模型——两路概念共享同一套 `c→y` 参数，只是分别提供主/辅助两条梯度路径。

    ## smoke test：写完 forward 立刻验证形状和类型

    ```python
    model.train()
    y_pred, c_pred = model(dummy_x)
    assert isinstance(y_pred, tuple) and len(y_pred) == 2   # 训练模式该是元组
    loss = compute_loss(y_pred, c_pred, ...)
    loss.backward()   # 顺便验证梯度能正常回传，不会中途报错

    model.eval()
    with torch.no_grad():
        y_pred, c_pred = model(dummy_x)
    assert torch.is_tensor(y_pred)   # eval模式该是单个tensor
    ```

[^6]: # 优化器与学习率调度

    ## SGD + momentum + weight_decay：论文里最常见的标准配置

    ```python
    optimizer = optim.SGD(model.parameters(), lr=cfg.lr, momentum=cfg.momentum, weight_decay=cfg.weight_decay)
    ```
    复现论文时，`momentum=0.9`​、加一点 `weight_decay`​（L2 正则）几乎是 CNN 微调的标准起手式。跑之前直接抄论文 Appendix 里写的优化器超参——**优化器超参往往是作者调过的，随手换掉复现不出论文数字的概率很高**。

    ## StepLR 的坑：没有下限，衰减到接近 0

    ```python
    scheduler = StepLR(optimizer, step_size=20, gamma=0.1)
    ```
    每隔 `step_size`​ 个 epoch，学习率乘以 `gamma`​。问题是**没有下限**：训练 100 个 epoch、`step_size=10`​ 的话，lr 会经历 `0.01 → 1e-3 → 1e-4 → 1e-5 → … → 1e-8`——网络在后半程学习率已经小到几乎"冻住"

    ### 解决方案：用 LambdaLR 自定义"衰减但有下限"的调度

    ```python
    def lr_lambda(epoch):
        factor = scheduler_gamma ** (epoch // scheduler_step)
        return max(factor, min_lr / lr)     # 有效lr = max(lr·γ^(epoch//step), min_lr)，不会归零

    scheduler = LambdaLR(optimizer, lr_lambda=lr_lambda)
    ```
    `LambdaLR`​ 接受一个函数，输入当前 epoch，返回"当前学习率相对初始学习率的乘数因子"。用 `max(衰减因子, 下限/初始lr)`​ 就能保证有效学习率不会跌破 `min_lr`。

    一个数学上等价、但写法不同的版本（比如参考实现常见的写法）：算出学习率降到下限对应第几个 epoch（`stop_epoch`​），超过这个 epoch 就不再调用 `scheduler.step()`：

    ```python
    stop_epoch = int(math.log(min_lr/lr) / math.log(gamma)) * scheduler_step
    if epoch <= stop_epoch:
        scheduler.step()
    ```
    两种写法最终的学习率曲线完全一致，`LambdaLR`​ 的闭包写法更简洁、不用额外算 `stop_epoch`。

    ## 多阶段模型：不同阶段的超参不要共用一套网格

    如果模型分几个独立训练的阶段（比如先训一个大的 CNN backbone，再训一个小的线性分类头），**不要用同一套**   **​`(lr, weight_decay, scheduler_step)`​**  ​ **网格去扫两个阶段**：

    ```python
    # 大模型(backbone)阶段
    optimizer_g = optim.SGD(backbone.parameters(), lr=0.01, weight_decay=4e-5)
    # 小模型(线性头)阶段——完全独立的超参
    optimizer_f = optim.SGD(head.parameters(),     lr=0.001, weight_decay=5e-5)
    ```
    大模型和小模型对学习率的敏感度很可能不一致：一套"对大模型友好"的学习率，喂给小的线性层可能直接发散或者收敛得很慢；反过来"对小模型友好"的学习率，用来微调大 backbone 又太保守、浪费训练轮数。**给每个阶段单独的一套 Config 字段（比如加一个** **​`ctoy_lr`​**​  **、** ​**​`ctoy_weight_decay`​**​ **前缀区分两套超参），分别构造两个 optimizer**，扫参时也分开扫


[^7]: # 多阶段训练与推理流水线

    ## 为什么要缓存中间产物

    CBM 的 sequential 训练方式：先训一个 `g: x→c`​（图像 → 概念，很贵的 CNN 前向），再单独训一个 `f: c→y`​（概念 → 类别，一个线性层）。如果每训一个 epoch 的 `f`​，都要重新对整个数据集跑一遍 `g`​ 的前向，成本完全不成比例——`g`​ 是大模型、`f`​ 是线性层，`f`​ 收敛所需的 epoch 数通常比 `g` 多得多。

    解决办法：**用训练好并冻结的** **​`g`​**​  **，对整个数据集推理一遍，把输出缓存下来**，后续训练 `f` 直接吃缓存的张量，不用重复跑 CNN。

    ```python
    def _extract_concept_logits(g, image_loader):
        g.eval()
        all_logits, all_labels = [], []
        with torch.no_grad():
            for images, labels, _ in image_loader:
                all_logits.append(g(images).cpu())
                all_labels.append(labels)
        return torch.cat(all_logits, dim=0), torch.cat(all_labels, dim=0)
    ```
    `g.eval()`​ + `torch.no_grad()`​：既不需要更新 `g` 的参数，也不需要它的 dropout/BN 处于训练状态——这是纯推理，不是训练的一部分。

    ## 用 TensorDataset 把缓存的张量包装回普通监督学习接口

    ```python
    from torch.utils.data import TensorDataset, DataLoader

    logits, labels = _extract_concept_logits(g, image_loader)
    dataset = TensorDataset(logits, labels)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)
    ```
    `TensorDataset`​ 把几个形状匹配（第 0 维一致）的张量打包成一个 `Dataset`​，接口和自定义 `Dataset`​ 完全一样，可以直接塞进 `DataLoader`​。  **"缓存中间产物 + TensorDataset"这个组合，是任何"前面几层很贵、后面几层很便宜"的多阶段流水线都能用的模式**——不限于 CBM，任何"冻结的特征提取器 + 可训练的小头"场景都适用（比如线性探针 linear probing）。

    ## 复合模型的推理：手动拼接两个独立训练的子模型

    ```python
    def eval_composed(g, f, image_loader, apply_sigmoid: bool) -> float:
        g.eval(); f.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for images, labels, _ in image_loader:
                concepts = g(images)
                if apply_sigmoid:
                    concepts = torch.sigmoid(concepts)
                class_preds = f(concepts).argmax(dim=1)
                correct += (class_preds == labels).sum().item()
                total += labels.shape[0]
        return correct / total
    ```
    `g`​ 和 `f`​ 是两个完全独立训练出来的模型，推理时手动把 `g`​ 的输出接到 `f`​ 的输入上。`apply_sigmoid`​ 这个开关的意义：**​`f`​**​ **训练时"看到"的输入分布，要和推理时喂给它的输入分布对齐**——如果 `f`​ 训练时吃的是压缩到 `[0,1]`​ 的概率值（sigmoid 之后），推理时也要对 `g`​ 的输出做同样的 sigmoid，否则 `f`​ 会面对一个它从没见过的数值范围（比如 logits 可能是 `-5`​ 到 `5`​），预测直接失准。**这个"训练/推理输入分布必须一致"的原则，比"代码能跑起来"更容易被忽略。**

    ## 推理套路：logits → 概率 → 预测类别

    ```python
    with torch.no_grad():
        output = model(input_batch)              # (batch_size, n_classes) logits
    probabilities = torch.nn.functional.softmax(output, dim=1)  # 转成[0,1]概率，沿类别维做softmax

    values, indices = torch.topk(probabilities, k=5, dim=1)
    ```
    - `dim=1` 很关键——要在"类别"这一维上做 softmax/topk，而不是 batch 维。
    - `torch.topk`​ 返回一个二元组 `(values, indices)`​：`values`​ 是前 k 个最大数值本身，`indices`​ 是这些值在原 tensor 里沿 `dim`​ 的下标。两者形状都是 `(batch_size, k)`。
    - 其他参数：`largest: bool = True`​（默认取最大的 k 个，`False`​ 则是最小的）；`sorted: bool = True` 保证返回结果按顺序排列。

    如果只要最可能的一个类别，`argmax(dim=1)`​ 比 `topk(k=1)` 更直接：

    ```python
    class_preds = output.argmax(dim=1)   # 甚至不需要先算softmax——argmax(logits) == argmax(softmax(logits))
    ```
    **这里有个小优化点**：如果只要预测类别、不需要具体概率值，`softmax`​ 这一步可以省掉——`softmax`​ 是单调变换，不改变"哪个位置最大"，直接对 logits 取 `argmax` 结果完全一样，省一次不必要的计算。


[^8]: # 附录·服务器与环境

    ## 代码质量工具：Ruff

    ```zsh
    ruff check .
    ruff format .
    ```
    项目根目录存放 `pyproject.toml`：

    ```toml
    [tool.ruff]
    line-length = 88
    target-version = "py311"

    [tool.ruff.format]
    quote-style = "double"
    ```
    ## 配置文件组织：YAML

    `configs/` 目录下存放 yaml 文件：

    ```
    configs/
      ppo.yaml
      grpo.yaml
      sft.yaml
      reward.yaml
    ```
    把所有参数放到 `xxx.yaml` 中：

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
    `train.py` 里读取，是一个嵌套的字典：

    ```python
    cfg = load_yaml("config.yaml")
    batch_size = cfg["train"]["batch_size"]
    lr = cfg["train"]["lr"]
    ```
    （`cbm-from-scratch`​ 用 `dataclass` 代替了这种嵌套字典的写法，见《实验工程规范》——两种方式各有取舍：dataclass 有类型检查和自动 CLI 生成，嵌套字典更灵活、不用为每个新配置块单独定义类。）

    ### 搜索其他人仓库的依赖库

    ```zsh
    find . -name "*.py" | xargs grep "^import\|^from"
    ```
    ## 日志：loguru

    ```python
    from loguru import logger

    logger.info(
        f"epoch={epoch}, "
        f"loss={loss}, "
        f"acc={acc}"
    )
    ```
    控制台会输出 log 的时间，并保存到 `train.log` 中。之后想看某次实验的 loss 曲线，直接 grep 日志文件：

    ```zsh
    grep loss logs/train.log
    ```
    ## 命令行参数：argparse

    ```python
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/default.yaml", help="Path to config file")
    parser.add_argument("--seed", type=int)       # 不提供则 seed=None；提供但无法解析为int则报错
    parser.add_argument("--device", required=True)  # 必须提供

    args = parser.parse_args()
    ```
    ## 远程连接服务器

    - 开 VPN：

    ```zsh
    ./zju-connect -protocol atrust -username <username> -password <password> -client-data-file client_data.json
    ```
    - SSH config 配置：

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
    - rsync 传文件：

    ```zsh
    rsync -avzP \
      "本地路径/CUB_200_2011/" \
      ZJU:~/远程路径/CUB_200_2011/
    ```
    - pypi 镜像源：

    ```zsh
    pip install pandas scikit-learn tqdm -i https://pypi.tuna.tsinghua.edu.cn/simple
    pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
    ```
    ## SSL 证书禁用（服务器证书验证不通过时的临时手段）

    ```python
    import ssl

    try:
        _create_unverified_https_context = ssl._create_unverified_context
    except AttributeError:
        pass
    else:
        ssl._create_default_https_context = _create_unverified_https_context
        print("警告：已全局禁用 SSL 证书验证。这是不安全的。")
    ```
    > 全局禁用证书验证会让所有 HTTPS 请求都不校验对方身份
    >
