# 链表 — Open Data Structures

作者：Pat Morin
来源：https://opendatastructures.org/ods-python/3_Linked_Lists.html
许可：Creative Commons Attribution（出版社说明：https://opendatastructures.org/ ）
收集方式：从作者公开 HTML 页面提取文字，保留公式图片的 alt 文本；移除网页脚本、样式和导航图像。公式可能仍含 LaTeX 标记，请对照原站。
收集时间：2026-10-24T13:56:15.625796+00:00

## 原文摘录

next
up
previous
contents
index
Next: 3.1 SLList: A Singly-Linked
Up: Open Data Structures (in
Previous: 2.7 Discussion and Exercises
Contents
Index
3. Linked Lists
In this chapter, we continue to study implementations of the List
interface, this time using pointer-based data structures rather than
arrays. The structures in this chapter are made up of nodes that
contain the list items. Using references (pointers), the nodes are
linked together into a sequence. We first study singly-linked lists,
which can implement Stack and (FIFO) Queue operations in constant
time per operation and then move on to doubly-linked lists, which can
implement Deque operations in constant time.
Linked lists have advantages and disadvantages when compared to array-based
implementations of the List interface. The primary disadvantage is that
we lose the ability to access any element using
$ \ensuremath{\mathrm{get}(\ensuremath{\mathit{i}})}$ or
$ \ensuremath{\mathrm{set}(\ensuremath{\mathit{i}},\ensuremath{\mathit{x}})}$
in constant time. Instead, we have to walk through the list, one element
at a time, until we reach the
$ \ensuremath{\ensuremath{\mathit{i}}}$th element. The primary advantage is
that they are more dynamic: Given a reference to any list node
$ \ensuremath{\ensuremath{\mathit{u}}}$, we
can delete
$ \ensuremath{\ensuremath{\mathit{u}}}$ or insert a node adjacent to
$ \ensuremath{\ensuremath{\mathit{u}}}$ in constant time. This
is true no matter where
$ \ensuremath{\ensuremath{\mathit{u}}}$ is in the list.
Subsections
3.1 SLList: A Singly-Linked List
3.2 DLList: A Doubly-Linked List
3.3 SEList: A Space-Efficient Linked List
3.4 Discussion and Exercises
next
up
previous
contents
index
Next: 3.1 SLList: A Singly-Linked
Up: Open Data Structures (in
Previous: 2.7 Discussion and Exercises
Contents
Index
opendatastructures.org
