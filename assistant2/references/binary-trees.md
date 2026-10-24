# 二叉树 — Open Data Structures

作者：Pat Morin
来源：https://opendatastructures.org/ods-python/6_Binary_Trees.html
许可：Creative Commons Attribution（出版社说明：https://opendatastructures.org/ ）
收集方式：从作者公开 HTML 页面提取文字，保留公式图片的 alt 文本；移除网页脚本、样式和导航图像。公式可能仍含 LaTeX 标记，请对照原站。
收集时间：2026-10-24T13:56:17.616445+00:00

## 原文摘录

next
up
previous
contents
index
Next: 6.1 BinaryTree: A Basic
Up: Open Data Structures (in
Previous: 5.4 Discussion and Exercises
Contents
Index
6. Binary Trees
This chapter introduces one of the most fundamental structures in computer
science: binary trees. The use of the word tree
here comes from
the fact that, when we draw them, the resultant drawing often resembles
the trees found in a forest. There are many ways of ways of defining
binary trees. Mathematically, a binary tree is a connected,
undirected, finite graph with no cycles, and no vertex of degree greater
than three.
For most computer science applications, binary trees are rooted:
A special node,
$ \ensuremath{\ensuremath{\mathit{r}}}$, of degree at most two is called the root
of the tree. For every node,
$ \ensuremath{\ensuremath{\ensuremath{\mathit{u}}}}\neq \ensuremath{\ensuremath{\ensuremath{\mathit{r}}}}$, the second node on the
path from
$ \ensuremath{\ensuremath{\mathit{u}}}$ to
$ \ensuremath{\ensuremath{\mathit{r}}}$ is called the parent of
$ \ensuremath{\ensuremath{\mathit{u}}}$.
Each of the
other nodes adjacent to
$ \ensuremath{\ensuremath{\mathit{u}}}$ is called a child
of
$ \ensuremath{\ensuremath{\mathit{u}}}$. Most of the
binary trees we are interested in are ordered,
so we distinguish
between the left child and right child of
$ \ensuremath{\ensuremath{\mathit{u}}}$.
In illustrations, binary trees are usually drawn from the root
downward, with the root at the top of the drawing and the left and right
children respectively given by left and right positions in the drawing
(Figure 6.1). For example, Figure 6.2.a shows
a binary tree with nine nodes.
Figure 6.1:
The parent, left child, and right child of the node
$ \ensuremath{\ensuremath{\mathit{u}}}$
in a BinaryTree.
\includegraphics[scale=0.90909]{figs-python/bintree-traverse-1}
Figure 6.2:
A binary tree with (a) nine real nodes and (b) ten external nodes.
\includegraphics[width=\textwidth ]{figs-python/bintree-1}
\includegraphics[width=\textwidth ]{figs-python/bintree-2}
(a)
(b)
Because binary trees are so important, a certain terminology has developed
for them: The depth
of a node,
$ \ensuremath{\ensuremath{\mathit{u}}}$, in a binary tree is the
length of the path from
$ \ensuremath{\ensuremath{\mathit{u}}}$ to the root of the tree. If a node,
$ \ensuremath{\ensuremath{\mathit{w}}}$,
is on the path from
$ \ensuremath{\ensuremath{\mathit{u}}}$ to
$ \ensuremath{\ensuremath{\mathit{r}}}$, then
$ \ensuremath{\ensuremath{\mathit{w}}}$ is called an ancestor
of
$ \ensuremath{\ensuremath{\mathit{u}}}$ and
$ \ensuremath{\ensuremath{\mathit{u}}}$ a descendant
of
$ \ensuremath{\ensuremath{\mathit{w}}}$. The subtree of a
node,
$ \ensuremath{\ensuremath{\mathit{u}}}$, is the binary tree that is rooted at
$ \ensuremath{\ensuremath{\mathit{u}}}$ and contains all
of
$ \ensuremath{\ensuremath{\mathit{u}}}$'s descendants. The height
of a node,
$ \ensuremath{\ensuremath{\mathit{u}}}$, is the length
of the longest path from
$ \ensuremath{\ensuremath{\mathit{u}}}$ to one of its descendants. The height of
a tree is the height of its root.
A node,
$ \ensuremath{\ensuremath{\mathit{u}}}$, is a leaf
if it has no children.
We sometimes think of the tree as being augmented with external
nodes. Any node that does not have a left child has an external
node as its left child, and, correspondingly, any node that does
not have a right child has an external node as its right child (see
Figure 6.2.b). It is easy to verify, by induction, that a
binary tree with
$ \ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}\ge 1$ real nodes has
$ \ensuremath{\ensuremath{\ensuremath{\mathit{n}}}}+1$ external nodes.
Subsections
6.1 BinaryTree: A Basic Binary Tree
6.2 BinarySearchTree: An Unbalanced Binary Search Tree
6.3 Discussion and Exercises
next
up
previous
contents
index
Next: 6.1 BinaryTree: A Basic
Up: Open Data Structures (in
Previous: 5.4 Discussion and Exercises
Contents
Index
opendatastructures.org
