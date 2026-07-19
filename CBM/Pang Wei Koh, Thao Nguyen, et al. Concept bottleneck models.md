---
title: Pang Wei Koh, Thao Nguyen, et al. Concept bottleneck models
date: 2026-07-08T16:25:09+08:00
lastmod: 2026-07-18T23:18:36+08:00
tags:
  - 'CBM'
---

![image](../assets/elden_ring_3-20260708162608-ya4pf1w.jpg)

# Pang Wei Koh, Thao Nguyen, et al. Concept bottleneck models

[https://arxiv.org/abs/2007.04612](https://arxiv.org/abs/2007.04612)

### 模型结构

```python
Image x （Input Layer）

↓ 经过网络g

Concept c （Concept Layer）

has red head -> 1
has blue wing -> 1
has black tail -> 1

↓ 经过网络f

Bird Species y （Output Layer）
```

- 训练集为$\{(x^{(i)}, c^{(i)}, y^{(i)}\}$, 其中$c \in \mathcal{R}^k$, k是概念数目

- 模型所有的信息，必须经过Concept Layer，没有旁路

### 2种Accuracy

#### Task Accuarcy：

预测值 $\hat{y} = f(g(x))$ 与类别标签一致的比率

#### Concept Accuarcy：

概念预测值 $\hat{c} = g(x)$ 与概念标签(Concept Label)一致的比率

### 3种训练方式 + 1对照 + 1对照

|方法|训练方式|优点|缺点|
| ----------------------| -----------------------------------------------------------------------------------------| ---------------------------------------------| ----------------------------------------------------------|
|**Independent Bottleneck**|分别训练 g: ($x \rightarrow c$) 和 f: ($c \rightarrow y$)，这里的f使用真实标签c训练|Concept 学得最准确、模块独立|训练使用真实 Concept、测试使用预测 Concept，存在分布偏移|
|**Sequential Bottleneck**|先训练 ($x \rightarrow c$)，再用预测 Concept 训练 ($c \rightarrow y$)|训练与测试一致，更符合真实部署|第一阶段 Concept 错误会传递给第二阶段|
|**Joint Bottleneck**|整个网络联合优化，Loss \= Task Loss + λ × Concept Loss|分类性能通常最好，可共同优化 Concept 和任务|需要调节 λ；Concept 可能为提高任务性能而偏离真实语义|
|Standard(对照组)|网络结构与bottleneck网络一致(有概念层)，但是损失函数不考虑概念损失项，直接使用Task Loss|||
|NOBOTTLENECK(对照组)|没有中间概念层，backbone直接接一层FC到200类|||

> 测试时**Independent Bottleneck**使用预测的标签推理

### 训练配置和细节

实验采用了两个数据集 CUB 和 OAI，对应分类和回归模型，检测它们的task error（衡量**类别预测**准确程度）和concept error（衡量**概念预测**准确程度）。CUB和OAI均包含人工标注的概念标签和类别标签。

**CUB数据集**：200类鸟种分类，**分类**问题。n = 11788

- **概念**：k\=112个二元鸟类属性（翅膀颜色、喙形状等），因原始标注噪声大，用"多数投票"在类别级别去噪

**模型**：

**概念预测**g：x -> c    使用**Inception V3**（在ImageNet上预训练，除了全连接层），concept损失采用BCELoss

**类别预测**f:    c -> y 使用1层全连接，y损失采用CrossEntropyLoss

**预处理**：训练时随机颜色抖动、随机水平翻转、随机裁剪至299x299分辨率，推理时中心裁剪后resize到299×299

**训练方法：表1**

**超参数搜索**: 在验证集上搜索

- 学习率范围：[0.001, 0.01]
- 学习率调度：恒定不变，或每 [10,15,20] 个epoch衰减10倍直到降到1e-4
- 正则化强度：[0.0004, 0.00004]
- 找到最优超参数后，在train+validation合并数据集上重新训练直至收敛
- Batch size \= 64
- 对于**Joint Bottleneck训练方法，搜索超参数**​$\lambda$使得验证集上在保持较高的concept准确率的同时，最大化task accuarcy
- 优化器：SGD，momentum \= 0.9
- 对concept loss函数，每个概念对总概念损失的贡献权重相等，但每个概念的二元交叉熵损失会按该概念的类别不平衡比例（平均约1:9）加权归一化

---

**OAI数据集**：从膝关节X光片预测 KLG（4级骨关节炎严重程度评分），**回归**问题。n = 36369

- **概念**：k\=10个由放射科医生标注的临床概念（关节间隙变窄、骨刺、钙化等）

**模型**：

**概念预测** ResNet-18（ImageNet预训练，微调最后12个卷积层。最后接一个**单层全连接层**，回归到概念 c；**MSE计算概念损失**

**分数(KLG)预测**：一个3层MLP负责 c→y 输出单一的KLG标量预测值(**MSE计算Task损失**)

**训练方法：表1**

- Batch size \= 8
- 数据增强：随机水平/垂直平移
- 优化器：​**Adam**​（β₁\=0.9, β₂\=0.999）
- 初始学习率：网格搜索于 [0.00005, 0.0005, 0.005]
- 学习率调度：每10个epoch衰减2倍
- 对于**Joint Bottleneck训练方法，搜索超参数**​$\lambda$使得验证集上在保持较高的concept准确率的同时，最大化task accuarcy
- 训练30个epoch，配合早停
- 最终权重取验证集上KLG的RMSE最低的那个epoch

### Benchmark：任务精度与概念精度对比

‍

‍

‍

### Benchmarking post-hoc concept analysis

‍

‍

‍
