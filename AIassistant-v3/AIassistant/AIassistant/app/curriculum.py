"""本科课程的覆盖清单。每个单元独立生成，避免整章被输出上限截断。"""
from __future__ import annotations

import re

# 每个条目：中文教学范围 | 用于检索英文开放教材的术语。
COVERAGE = {
    "数据表示与运算": [
        "进制、位权与整数/小数转换 | binary hexadecimal radix fractions",
        "无符号数、原码、反码、补码与表示范围 | unsigned signed magnitude ones twos complement",
        "符号扩展、截断、大小端与类型转换 | sign extension truncation endian conversion",
        "补码加减法、进位与有符号溢出 | addition subtraction carry overflow",
        "逻辑移位、算术移位与位运算 | logical arithmetic shift bitwise",
        "加法器、ALU与标志位 | adder arithmetic logic unit flags",
        "定点乘法、部分积与Booth算法 | multiplication partial product Booth",
        "定点除法、恢复余数与不恢复余数 | division restoring non restoring quotient remainder",
        "IEEE 754、偏置阶码与规格化数 | IEEE floating point exponent significand normalization",
        "浮点特殊值、精度、舍入与误差 | subnormal infinity NaN rounding precision",
        "浮点加减法、对阶、规格化及溢出 | floating point addition alignment normalization",
        "综合例题：编码、运算与结果检验 | representation arithmetic worked example",
    ],
    "存储系统": [
        "存储层次与局部性 | memory hierarchy locality",
        "SRAM、DRAM、地址译码与容量扩展 | SRAM DRAM address memory",
        "Cache直接映射、全相联与组相联 | cache direct associative",
        "Cache替换、写策略与一致性基础 | cache replacement write policy",
        "命中率、AMAT与性能计算 | average memory access time miss hit",
        "虚拟存储、页表与TLB | virtual memory page table TLB",
        "主存、辅存与数据访问全过程 | storage disk memory access",
    ],
    "指令系统": [
        "机器指令、操作码与指令格式 | instruction opcode format",
        "寻址方式与有效地址计算 | addressing effective address",
        "数据传送、运算与控制转移 | instruction branch load store",
        "RISC与CISC及设计权衡 | RISC CISC",
        "指令编码、汇编与机器码实例 | assembly machine code",
        "流水线、结构/数据/控制冒险 | pipeline structural data control hazard",
        "转发、停顿、分支处理与CPI | forwarding stall branch CPI",
    ],
    "CPU 与总线": [
        "CPU寄存器与取指执行周期 | CPU registers fetch execute",
        "单周期数据通路逐步分析 | datapath single cycle",
        "多周期与流水线数据通路 | multicycle pipeline datapath",
        "硬布线控制与微程序控制 | hardwired microprogram control",
        "总线组成、仲裁与定时 | bus arbitration timing",
        "异常、中断、优先级与响应 | interrupt exception",
        "程序查询、中断I/O与DMA | programmed IO interrupt DMA",
    ],
    "分层模型": [
        "通信需求、协议与服务 | protocol service",
        "OSI与TCP/IP层次 | OSI TCP IP layers",
        "封装解封装与协议数据单元 | encapsulation header packet",
        "地址、端口与端到端通信 | addressing ports end to end",
        "带宽、吞吐、时延与丢包 | bandwidth throughput latency loss",
        "一次网页请求的逐层全过程 | web request stack",
    ],
    "链路层与物理层": [
        "信号、编码、调制与介质 | signal encoding modulation",
        "奈奎斯特与香农容量计算 | Nyquist Shannon capacity",
        "成帧、检错、CRC与重传 | framing CRC error",
        "MAC地址与以太网帧 | Ethernet MAC frame",
        "共享介质、CSMA/CD与无线接入 | CSMA collision wireless",
        "交换机学习、转发、VLAN与生成树 | switch forwarding VLAN spanning tree",
        "链路层综合传输实例 | link layer transmission",
    ],
    "网络层": [
        "数据报、转发与路由 | datagram forwarding routing",
        "IPv4报文、TTL、分片与MTU | IPv4 fragmentation MTU",
        "子网、CIDR与地址计算 | subnet CIDR mask",
        "ARP、DHCP、ICMP与NAT | ARP DHCP ICMP NAT",
        "距离向量与链路状态算法 | distance vector link state",
        "最长前缀匹配与路由表实例 | longest prefix routing table",
        "IPv6及与IPv4的差异 | IPv6",
    ],
    "传输层": [
        "复用分用、端口、UDP与TCP | multiplex port UDP TCP",
        "可靠传输、确认、超时与重传 | acknowledgment timeout retransmission",
        "滑动窗口、GBN与选择重传 | sliding window selective repeat",
        "TCP连接建立、关闭与状态 | TCP handshake connection close",
        "序号、确认号与报文计算 | sequence acknowledgement segment",
        "流量控制与接收窗口 | flow control receive window",
        "拥塞控制、慢启动与拥塞避免 | congestion slow start avoidance",
        "吞吐、RTT与综合时序题 | throughput RTT timing",
    ],
    "应用层": [
        "应用模型与Socket | client server socket",
        "DNS记录、缓存与查询 | DNS resolver caching",
        "HTTP报文、方法与状态码 | HTTP request response status",
        "持久连接、缓存及HTTP版本 | HTTP persistent cache",
        "TLS握手、证书与HTTPS | TLS certificate HTTPS",
        "电子邮件与文件传输协议 | SMTP IMAP FTP",
        "浏览网页的应用层综合实例 | web browser request",
    ],
    "进程与线程": [
        "操作系统角色、特权级与系统调用 | kernel user system call",
        "进程、PCB、地址空间与状态 | process control block address space",
        "创建终止、fork与exec | process fork exec",
        "上下文切换与资源隔离 | context switch isolation",
        "线程资源共享与调度 | threads shared resource",
        "用户级/内核级线程与多核 | user kernel threads multicore",
        "进程间通信与典型场景 | IPC pipe shared memory",
    ],
    "调度": [
        "调度层次、抢占与性能指标 | scheduling preemption turnaround",
        "FCFS与SJF | first come shortest job",
        "SRTF与优先级调度 | shortest remaining priority",
        "时间片轮转与响应时间 | round robin response time",
        "多级反馈队列与饥饿 | multilevel feedback starvation",
        "多处理器与实时调度 | multiprocessor real time scheduling",
        "甘特图、周转时间与综合计算 | scheduling worked example",
    ],
    "同步与死锁": [
        "竞态、临界区与互斥条件 | race critical section mutual exclusion",
        "锁、原子指令与自旋 | lock atomic spin",
        "信号量、PV与条件变量 | semaphore condition variable",
        "生产者消费者与读者写者 | producer consumer readers writers",
        "哲学家就餐与同步分析 | dining philosophers",
        "死锁必要条件与资源图 | deadlock resource allocation",
        "预防、避免与银行家算法 | prevention avoidance banker",
        "检测恢复、安全序列与实例 | detection recovery safe sequence",
    ],
    "内存管理": [
        "地址空间、重定位与保护 | address space relocation protection",
        "连续分配与碎片 | allocation fragmentation",
        "分页、分段与地址转换 | paging segmentation translation",
        "多级页表、TLB与访存计算 | page table TLB access",
        "虚拟内存与缺页处理 | virtual memory page fault",
        "OPT、FIFO、LRU与Clock | replacement FIFO LRU clock",
        "工作集、抖动与Belady异常 | working set thrashing Belady",
        "页面置换与有效访问时间例题 | page replacement effective access",
    ],
    "文件系统": [
        "文件、目录、路径与权限 | file directory permission",
        "打开读写、文件描述符与inode | descriptor inode",
        "连续、链接与索引分配 | allocation linked indexed",
        "空闲空间管理 | free space bitmap",
        "磁盘结构与磁盘调度 | disk scheduling SCAN",
        "缓存、日志与崩溃一致性 | cache journal crash consistency",
        "文件访问、存储容量与综合实例 | filesystem worked example",
    ],
    "线性表": [
        "抽象数据类型与复杂度 | abstract data type complexity",
        "顺序表、容量与动态扩容 | array list resizing",
        "单链表、头结点与指针 | singly linked list pointer",
        "双链表与循环链表 | doubly circular linked list",
        "插入删除、查找与边界情况 | insert delete search boundary",
        "链表反转、合并与算法实现 | reverse merge list",
        "顺序与链式结构比较 | array linked list comparison",
    ],
    "栈与队列": [
        "栈的ADT、顺序栈与链栈 | stack array linked",
        "递归、调用栈与括号匹配 | recursion stack parentheses",
        "表达式转换与求值 | expression postfix evaluation",
        "队列、链队与循环队列 | queue circular",
        "判空判满、容量与双端队列 | deque capacity empty full",
        "两个栈实现队列及摊还复杂度 | two stacks queue amortized",
        "栈队列应用与完整代码 | stack queue implementation",
    ],
    "树": [
        "树的定义、度、高度与存储 | tree degree height representation",
        "二叉树性质与结点数计算 | binary tree properties",
        "前中后序及层序遍历 | traversal preorder inorder postorder",
        "二叉搜索树的查找插入删除 | binary search tree insert delete",
        "AVL与四类旋转 | AVL rotation",
        "堆、建堆与优先队列 | heap priority queue",
        "哈夫曼树与编码 | Huffman coding",
        "多路树、B树与应用 | B tree",
    ],
    "图": [
        "图的术语、邻接矩阵与邻接表 | graph adjacency matrix list",
        "DFS、BFS与连通分量 | depth breadth first connected",
        "拓扑排序与关键路径 | topological critical path",
        "Prim、Kruskal与最小生成树 | minimum spanning tree",
        "Dijkstra及适用条件 | Dijkstra shortest path",
        "Floyd与负权边处理 | Floyd Bellman Ford",
        "算法跟踪、复杂度与完整实现 | graph algorithm complexity",
    ],
    "排序与查找": [
        "排序指标、稳定性与比较下界 | sorting stability comparison",
        "直接插入、折半插入与希尔 | insertion shell sort",
        "冒泡与快速排序 | bubble quicksort partition",
        "选择与堆排序 | selection heap sort",
        "归并、基数与外部排序 | merge radix external sort",
        "顺序、折半与树形查找 | linear binary tree search",
        "散列函数、冲突与装填因子 | hash collision load factor",
        "算法追踪、ASL与复杂度对比 | average search length complexity",
    ],
}

# 将挤在同一节的关键算法拆开，并补上原覆盖清单中的空缺。
COVERAGE["数据表示与运算"] = [
    "进制与位权：二进制、八进制与十六进制 | radix binary octal hexadecimal",
    "整数进制转换与表示范围 | integer base conversion range",
    "小数进制转换、循环小数与精度 | fraction conversion precision",
    "无符号整数与模运算 | unsigned modulo",
    "原码与反码：双零、符号和范围 | sign magnitude ones complement",
    "补码编码、解码与最小负数 | twos complement minimum negative",
    "符号扩展、截断与类型转换 | sign extension truncation cast",
    "大小端、字节序与存储布局 | endian byte word address",
    "补码加法与逐位进位 | addition carry complement",
    "补码减法与取负边界 | subtraction negation",
    "进位标志与有符号溢出判定 | carry overflow flags",
    "逻辑移位、算术移位与舍入差异 | logical arithmetic shift",
    "与、或、异或、掩码与位字段 | bitwise mask XOR",
    "半加器、全加器与串行进位 | half full adder ripple carry",
    "先行进位、ALU与状态标志 | carry lookahead ALU flags",
    "原码乘法、部分积与结果位宽 | unsigned multiplication partial product",
    "补码乘法与Booth算法逐轮演算 | Booth signed multiplication",
    "恢复余数除法与商余验证 | restoring division quotient remainder",
    "不恢复余数除法与修正 | non restoring division",
    "IEEE 754字段与偏置阶码 | IEEE exponent bias significand",
    "规格化数与非规格化数 | normalized subnormal",
    "正负零、无穷大与NaN | signed zero infinity NaN",
    "舍入模式、保护位与机器精度 | rounding guard round sticky precision",
    "浮点加减：对阶、规格化与消去 | floating addition alignment cancellation",
    "浮点乘除、上溢与下溢 | floating multiplication division overflow underflow",
    "综合例题：整数与浮点编码结果检验 | representation worked example",
]
EXTRA_COVERAGE = {
    "存储系统": [
        "存储芯片位扩展与字扩展计算 | memory chip width depth expansion",
        "交叉编址与多体存储器 | interleaved memory banks",
        "Cache地址划分与映射逐步计算 | cache tag index offset",
        "缺失分类与组相联地址序列 | compulsory conflict capacity miss",
        "写直达、写回与写分配辨析 | write through back allocate",
        "TLB与Cache联合地址转换例题 | TLB cache virtual physical address",
        "磁盘容量、传输速率与RAID基础 | disk capacity RAID",
    ],
    "指令系统": [
        "定长与变长编码、扩展操作码 | fixed variable instruction expanding opcode",
        "零/一/二/三地址指令与表达式 | zero one two three address instruction",
        "基址、变址、相对与间接寻址比较 | base index relative indirect addressing",
        "指令与数据大小端实例 | instruction endian encoding",
        "流水线时空图与加速比 | pipeline timing speedup",
        "RAW、WAR、WAW与执行顺序 | read after write hazard dependency",
    ],
    "CPU 与总线": [
        "微操作、控制信号与寄存器传送 | micro operation register transfer control",
        "中断保存现场、返回与嵌套 | interrupt context return nesting",
        "同步总线与异步握手 | synchronous asynchronous bus handshake",
        "总线带宽、突发传输与利用率 | bus bandwidth burst utilization",
        "DMA周期挪用与CPU阻塞比较 | DMA cycle stealing burst",
        "时钟频率、CPI、CPU时间与加速比 | clock CPI CPU time Amdahl",
    ],
    "分层模型": [
        "电路、报文与分组交换比较 | circuit message packet switching",
        "存储转发与多跳端到端时延 | store forward delay hops",
        "带宽时延积与链路利用率 | bandwidth delay product utilization",
    ],
    "链路层与物理层": [
        "曼彻斯特、差分曼彻斯特与NRZ | Manchester differential NRZ",
        "码元速率、比特率与dB换算 | baud bit rate decibel SNR",
        "CRC多项式除法与余数检验 | CRC polynomial remainder",
        "海明码、校验位与纠错范围 | Hamming parity error correction",
        "停止等待与可靠链路利用率 | stop wait utilization",
        "GBN与SR序号空间边界 | GBN selective repeat sequence space",
        "CSMA/CD最小帧长与传播时延 | minimum frame collision propagation",
        "PPP、点对点链路与透明传输 | PPP framing transparency",
    ],
    "网络层": [
        "VLSM子网规划与可用主机数 | VLSM subnet hosts",
        "IPv4分片偏移、标志与长度计算 | fragmentation offset flags length",
        "路由汇总、最长前缀匹配逐项演算 | aggregation longest prefix",
        "RIP、OSPF与BGP适用范围 | RIP OSPF BGP",
        "ARP请求、网关MAC与跨网段通信 | ARP gateway MAC",
        "ICMP差错、ping与traceroute | ICMP ping traceroute",
    ],
    "传输层": [
        "TCP头部、MSS、首部长度与选项 | TCP header MSS options",
        "SYN与FIN序号消耗、累计ACK | SYN FIN sequence cumulative ACK",
        "超时估计、重复ACK与快重传 | RTO duplicate ACK fast retransmit",
        "接收窗口与拥塞窗口联合约束 | receive congestion window flight size",
        "TIME_WAIT与半关闭 | TIME WAIT half close",
    ],
    "应用层": [
        "DNS递归/迭代时序与资源记录 | DNS recursive iterative resource record",
        "HTTP条件请求、ETag与304 | HTTP conditional ETag 304",
        "FTP控制/数据连接与主被动模式 | FTP control data active passive",
        "SMTP转发与POP3/IMAP收信比较 | SMTP POP IMAP",
    ],
    "进程与线程": [
        "用户态/内核态与模式切换区别 | user kernel mode context switch",
        "僵尸进程、孤儿进程与wait | zombie orphan wait",
        "共享内存、消息传递与管道比较 | shared memory message pipe IPC",
        "线程安全、可重入与线程局部存储 | thread safety reentrant local storage",
    ],
    "调度": [
        "平均周转与带权周转时间逐项计算 | turnaround weighted normalized",
        "时间片边界与同时到达的约定 | round robin arrival quantum",
        "优先级反转与优先级继承 | priority inversion inheritance",
    ],
    "同步与死锁": [
        "PV操作顺序与缓冲区数量约束 | semaphore ordering bounded buffer",
        "管程、Mesa语义与while等待 | monitor Mesa condition while",
        "银行家算法Need矩阵与试分配 | banker need matrix request safe",
        "安全、不安全与死锁状态区分 | safe unsafe deadlock state",
        "资源有多实例时的死锁检测 | multiple resource deadlock detection",
    ],
    "内存管理": [
        "页号、页内偏移与页表容量 | page number offset table size",
        "分段分页与逻辑地址检查 | segmentation paging limit",
        "缺页率与有效访存时间 | page fault effective access time",
        "Clock改进、脏页与置换代价 | enhanced clock dirty page",
        "局部/全局置换与分配策略 | local global replacement allocation",
    ],
    "文件系统": [
        "直接、一级/二级间接索引容量 | direct single double indirect capacity",
        "硬链接、软链接与inode计数 | hard symbolic link inode",
        "FCFS、SSTF、SCAN与C-SCAN轨迹 | disk scheduling SCAN CSCAN SSTF",
        "设备独立性、缓冲与SPOOLing | device independence buffering spooling",
        "文件共享、访问控制与目录查找 | file access control directory lookup",
    ],
    "线性表": [
        "有序表合并、去重与交集 | sorted list merge unique intersection",
        "快慢指针、环检测与倒数第k项 | slow fast pointer cycle",
        "静态链表与游标管理 | static linked list cursor",
        "数组、矩阵与特殊矩阵压缩 | matrix symmetric triangular sparse",
        "串的ADT、朴素匹配与KMP | string naive KMP prefix",
    ],
    "栈与队列": [
        "递归消除与显式栈跟踪 | recursion elimination explicit stack",
        "双端队列输入输出限制 | restricted input output deque",
        "循环队列三种判满方法 | circular queue count flag spare",
        "数组下标、越界与操作序列验证 | stack queue boundary sequence",
    ],
    "树": [
        "线索二叉树与遍历后继 | threaded binary tree successor",
        "前序+中序重建与唯一性 | reconstruct preorder inorder uniqueness",
        "孩子兄弟表示与森林转换 | child sibling forest representation",
        "带权路径长度与哈夫曼合并过程 | weighted path length Huffman",
        "B树阶数、分裂、合并与B+树 | B tree order split merge B plus",
        "红黑树性质与平衡树比较 | red black balanced tree",
    ],
    "图": [
        "并查集、路径压缩与Kruskal实现 | union find path compression Kruskal",
        "AOE事件最早/最迟时间逐步计算 | activity edge earliest latest critical path",
        "最短路径负权限制与负环 | shortest path negative edge cycle",
        "邻接表次序对遍历结果的影响 | adjacency order traversal",
    ],
    "排序与查找": [
        "折半查找判定树与成功/失败ASL | binary search decision tree ASL",
        "散列查找成功/失败ASL逐项计算 | hash successful unsuccessful probes ASL",
        "快速排序划分、重复键与最坏情况 | quicksort partition duplicate worst",
        "堆调整方向与自底向上建堆 | heap sift down build",
        "多路归并、败者树与置换选择 | multiway merge loser tree replacement selection",
        "排序算法统一表：最佳/平均/最坏与稳定性 | sort best average worst stable",
    ],
}
for _title, _extra in EXTRA_COVERAGE.items():
    COVERAGE[_title].extend(_extra)


def units(chapter: dict) -> list[dict]:
    entries = COVERAGE.get(chapter["title"])
    if entries is None:
        outline = chapter.get("outline", "")
        entries = [line.strip(" -*#\t") for line in outline.splitlines()
                   if line.strip() and not line.startswith("##")]
        if not entries:
            entries = ["概念、前置知识与学习目标", "核心原理与工作过程",
                       "实现方法、公式与适用条件", "逐步例题与结果验证",
                       "边界情况、易错点与自测解析"]
    return [{"title": s.split("|")[0].strip(),
             "query": (s.replace("|", " ").strip() +
                       (" " + chapter["title"] if chapter.get("reference_material_id") else ""))}
            for s in entries]


def checklist(chapter: dict) -> str:
    return "\n".join(f"- {u['title']}" for u in units(chapter))


def valid_section(text: str, mock: bool = False) -> bool:
    """拒绝空回复、极短回复及不完整代码块；mock保持明确的演示标识。"""
    if mock:
        return bool(text.strip())
    headings = ("学习目标与前置知识", "概念与原理", "公式或实现步骤",
                "例题与逐步解析", "易错点与自测解析")
    return (len(re.sub(r"\s+", "", text)) >= 400 and text.count("```") % 2 == 0
            and all(re.search(r"(?m)^###\s+" + h, text) for h in headings))
