---
title: Torch
date: 2026-07-12T16:51:33+08:00
lastmod: 2026-07-12T17:01:53+08:00
---

# Torch

## Tensor

### 基础

#### torch.Size

定义：`tuple`​的子类，它是`tensor.shape`​（或`tensor.size()`​）返回的对象类型，**每个元素表示tensor在对应维度上的长度**。

> 可以像tuple一样被索引，遍历，和普通tuple比较相等，不可变。

#### 索引与切片

- **tensor索引出来的"标量"始终还是tensor，0维（axis=0不存在）**

需要用`item()`取出纯Python数值

```python
a = torch.arange(10, dtype=torch.float32)
print('a[1].shape:', a[1].shape)
# a[1].shape: torch.Size([])
print('a[1].dtype:', a[1].dtype)
# a[1].dtype: torch.float32
print('a[1].item() type:', type(a[1].item()))
# a[1].item() type: <class 'float'>
```

- tensor切片出来的是1维tensor，例如：`a[1:2].shape: torch.Size([1])`axis=0存在，但是长度为1.

‍
