---
title: Tensor基础与设备管理
date: 2026-07-19T18:07:48+08:00
lastmod: 2026-07-19T18:07:48+08:00
---

# Tensor基础与设备管理

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
