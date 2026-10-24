# 顺序表与数组 — Open Data Structures

作者：Pat Morin
来源：https://opendatastructures.org/ods-python/2_Array_Based_Lists.html
许可：Creative Commons Attribution（出版社说明：https://opendatastructures.org/ ）
收集方式：从作者公开 HTML 页面提取文字，保留公式图片的 alt 文本；移除网页脚本、样式和导航图像。公式可能仍含 LaTeX 标记，请对照原站。
收集时间：2026-10-24T13:56:14.356565+00:00

## 原文摘录

next
up
previous
contents
index
Next: 2.1 ArrayStack: Fast Stack
Up: Open Data Structures (in
Previous: 1.8 Discussion and Exercises
Contents
Index
2. Array-Based Lists
In this chapter, we will study implementations of the List and Queue
interfaces where the underlying data is stored in an array, called the
backing array.
The following table summarizes the running times
of operations for the data structures presented in this chapter:
$ \ensuremath{\mathrm{get}(\ensuremath{\mathit{i}})}$/
$ \ensuremath{\mathrm{set}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$
$ \ensuremath{\mathrm{add}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$/
$ \ensuremath{\mathrm{remove}(\ensuremath{\mathit{i}})}$
ArrayStack
$ O(1)$
$ O(\ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}-\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}})$
ArrayDeque
$ O(1)$
$ O(\min\{\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}},\ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}-\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}}\})$
DualArrayDeque
$ O(1)$
$ O(\min\{\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}},\ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}-\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}}\})$
RootishArrayStack
$ O(1)$
$ O(\ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}-\ensuremath{\ensuremath{\ensuremath{\mathit{i}}}})$
Data structures that work by storing data in a single array have many
advantages and limitations in common:
Arrays offer constant time access to any value in the array.
This is what allows
$ \ensuremath{\mathrm{get}(\ensuremath{\mathit{i}})}$ and
$ \ensuremath{\mathrm{set}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$ to run in constant time.
Arrays are not very dynamic. Adding or removing an element
near the middle of a list means that a large number of elements in the
array need to be shifted to make room for the newly added element or
to fill in the gap created by the deleted element. This is why the
operations
$ \ensuremath{\mathrm{add}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$ and
$ \ensuremath{\mathrm{remove}(\ensuremath{\mathit{i}})}$ have running times that depend
on
$ \ensuremath{\ensuremath{\mathit{n}}}$ and
$ \ensuremath{\ensuremath{\mathit{i}}}$.
Arrays cannot expand or shrink. When the number of elements in
the data structure exceeds the size of the backing array, a new array needs
to be allocated and the data from the old array needs to be copied
into the new array. This is an expensive operation.
The third point is important. The running times cited in the table
above do not include the cost associated with growing and shrinking
the backing array. We will see that, if carefully managed, the cost of
growing and shrinking the backing array does not add much to the cost of
an average operation. More precisely, if we start with an empty
data structure, and perform any sequence of $ m$
$ \ensuremath{\mathrm{add}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$ or
$ \ensuremath{\mathrm{remove}(\ensuremath{\mathit{i}})}$
operations, then the total cost of growing and shrinking the backing
array, over the entire sequence of $ m$ operations is $ O(m)$. Although
some individual operations are more expensive, the amortized cost,
when amortized over all $ m$ operations, is only $ O(1)$ per operation.
Subsections
2.1 ArrayStack: Fast Stack Operations Using an Array
2.2 FastArrayStack: An Optimized ArrayStack
2.3 ArrayQueue: An Array-Based Queue
2.4 ArrayDeque: Fast Deque Operations Using an Array
2.5 DualArrayDeque: Building a Deque from Two Stacks
2.6 RootishArrayStack: A Space-Efficient Array Stack
2.7 Discussion and Exercises
next
up
previous
contents
index
Next: 2.1 ArrayStack: Fast Stack
Up: Open Data Structures (in
Previous: 1.8 Discussion and Exercises
Contents
Index
opendatastructures.org
