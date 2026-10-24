from pathlib import Path
import re,json,html,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'计算机课程学习助手_交付文档初稿'
OUT.mkdir(exist_ok=True)
files={}
def put(name,text): files[name]=text.strip()+'\n'
def doc(name,title,code,owner,body):
 put('项目文档/'+name,f'# {title}\n\n项目：计算机课程学习助手。标识：CSLA-{code}。版本：0.1。状态：初稿。日期：2026-10-24。主责：{owner}（姓名待填）。评审：待评审。\n\n版本历史：0.1 根据计算机专业范围与交付优先要求编写。\n\n'+body)

doc('07_K-1_系统测试计划.md','计算机课程学习助手系统测试计划','TEST-PLAN','C',r'''
## 1 测试范围与内容

覆盖FR-01至FR-12，重点验证问答引用、记录隔离、提交去重、错题、审核、两模型和安装。按课设裁剪九类测试，不做商业高并发、全面渗透审计或长期SLA证明。

## 2 测试方法

业务采用黑盒场景，评分、去重和权限采用必要单元/接口测试。空输入、超长输入和损坏文件测边界。手机实际操作，AI由人工对参考资料评价，不以模型自评分代替。

RAG验收40问，每课15道可回答、5道不足，标注必要来源。训练最终测试50条独立准备，不与40问、演示题库同题族泄漏。学习统计6场景：无记录、1次错、3题低正确率、重复提交、重做、切课。

## 3 环境和工具

两个学生账号、一个管理员、两课程、至少四份审核文字资料。执行前记录系统、浏览器、CPU/RAM/GPU、模型与嵌入版本、依赖版本。工具使用pytest、浏览器开发者工具及人工操作，最终只列实际使用工具。

普通页面20次调用；API与本地各10次单并发问答，记录输入输出长度、中位数和最大耗时。少量测试不用于声称全年可用率或稳定p95。

## 4 完成准则

24条功能用例均执行；核心流程通过，无未处理的越权、错误计分或审核绕过。普通遗留缺陷列出影响并由项目组和教师判断是否接受。

内部AI目标：30道可回答至少24道无关键错误；10道不足题至少8道合理说明限制；来源编号与定位真实。分课程报告分子分母。若未达标，修复资料提示或缩小范围并记录，不写全部正确。

微调要求真实数据划分、训练、可加载适配器和同测试集对照，允许负结果。未训练则FR-11未完成。教师指定标准优先。

## 5 人员与任务

| 人员 | 交叉验证 | 时间 |
|---|---|---|
| A | B的导入、更新和安装 | 第5周开始，第7周回归 |
| B | C的练习、统计和适配器加载 | 第4周开始，第7周回归 |
| C | A的问答、引用与手机 | 第3周开始，第7周回归 |

样本作者之外另一人先评，争议核对资料。第8周只做交付冒烟与必要回归。

## 6 缺陷管理与改错

新建→确认→修复→回归→关闭或重开。无法启动为阻断，泄漏/错计分/绕过审核为严重，显示问题为一般。记录BUG编号、TC、版本、步骤、预期、实际、证据、负责人、修复提交与回归人。示例缺陷不计入真实统计。

## 附录 审批意见

评审日期、人员、问题与结论待实际填写。当前不写批准或全部通过。
''')

tests=[
('01','FR-01','登录退出','学生A正确密码登录，再退出并请求历史','登录成功；退出后原会话不可访问'),
('02','FR-01','切换课程','数据结构提问后切数据库，查看历史和资料','仅显示本课内容，不拼另一课证据'),
('03','FR-02','正常导入','管理员导入两页栈与队列文字PDF，再查看资料','active且页码原文正确'),
('04','FR-02','异常文件','分别上传损坏PDF、无文字扫描件和超10MB文件','错误明确，未发布可检索内容'),
('05','FR-03','有依据问答','问已导入资料中的栈与队列顺序差异','有合理解释和可打开来源，编号属于本课'),
('06','FR-03','资料不足','问资料不包含且需要课程依据的问题','说明限制，不虚构来源和页码'),
('07','FR-03','输入边界','分别提交空白、1000字和1001字问题','空白超限拒绝，边界长度可处理'),
('08','FR-04','请求重试','同请求键同体重发，再修改问题复用该键','同体只保存一轮，异体返回409'),
('09','FR-04','模型超时','让模型不可达后提问，恢复后重试','明确失败并保留输入，不记成成功答案'),
('10','FR-05','单选评分','提交答案B的题，分别以正确和错误选择测试','服务端评分正确，未作答列表无答案'),
('11','FR-05','提交去重','同提交键双击并直接重复请求','只产生一条有效记录，不重复计数'),
('12','FR-06','错题重做','首次答错，再到错题重做答对','显示已复习，首次错误仍保留'),
('13','FR-07','证据不足','新账号无作答，再仅答错一道题','无记录或样本不足，不断言不掌握'),
('14','FR-07','复习建议','同知识点3道不同题首次只对1道','显示1/3和对应资料建议'),
('15','FR-08','更新去重','同来源同正文查两次，再更改正文查','同内容一候选，新内容新候选'),
('16','FR-08','审核发布','待审资料先查询，再批准并重复批准','审核前不检索，批准后可查且通知一次'),
('17','FR-08','拒绝撤回','拒绝一个候选，撤回另一已发布文档再查','拒绝不发布，撤回不被新引用'),
('18','FR-09','两种模型','API与本地各回答同一课程问题','两路线真实有结果并显示模式'),
('19','FR-09','本地不转云','本地模式禁网或停模型后提问','无远程模型调用，报错而非切API'),
('20','FR-10','手机操作','手机登录选课、提问看出处并完成单选','核心流程可用，无整体横向滚动'),
('21','FR-10','安装恢复','另一电脑照手册安装，在测试目录恢复备份','可启动且找回数据，留实际记录'),
('22','FR-11','适配器加载','训练后新进程加载同基座与adapter，执行固定测试','可推理且有版本日志对照，无产物标未完成'),
('23','FR-12','权限清除','A请求B历史，再清A记录并检查两账号','越权拒绝，仅A清除，B和公共资料保留'),
('24','FR-08','恶意目标与文本','尝试非白名单私网目标及含脚本指令的文档','非法抓取拦截，脚本不执行，文档不能批准自己')]
body='''## 0 文档介绍

依据需求与测试计划，提供可重复执行的步骤。当前24条全部未执行；预期不等于实测。

## 1 测试夹具

准备学生A/B和管理员三个账号、DS/DB两课程、栈队列与关系模型文字资料。预置单选“栈遵循何种规则”，正确选项B。每条执行前建立所需状态；新用户、请求键和提交键独立，不能沿用前例数据影响结论。

每条填写时间、执行人、软件提交、设备、实际结果及证据；失败关联BUG编号。不在真实账号做破坏性测试。

## 2 核心测试用例

'''
for tid,fr,title,steps,expected in tests:
 body+=f'### TC-{tid} {title}\n\n关联：{fr}。前置：测试服务可启动，使用上述夹具；故障按步骤设置。\n\n步骤：{steps}。\n\n预期：{expected}。\n\n实际：未执行。人员、时间、版本、证据、缺陷：待实际填写。\n\n'
body+='''## 3 分类和补充检查

接口路径TC-07/08/11/23；功能TC-01/02/03/05/10/12/14/16/18；健壮TC-04/09；界面TC-20；安全TC-19/23/24；可靠与安装TC-21。重复分类不重复计数。

性能另记普通页面20次、两模型各10次请求。压力只观察两人同时提交的繁忙提示，不承诺高并发。卸载只停止项目并按说明处理本项目目录，不删除共用环境。AI40问、学习6场景、训练50条测试单独统计。

## 附录 评审

评审待执行。实际结果不得复制预期，计划齐全不代表测试通过。
'''
doc('08_K-2_测试用例.md','计算机课程学习助手测试用例','TEST-CASE','全体',body)

doc('09_K-3_测试报告.md','计算机课程学习助手测试报告','TEST-REPORT','C',r'''
## 1 基本信息

测试计划CSLA-TEST-PLAN 0.1，用例CSLA-TEST-CASE 0.1。对象为拟开发的学习助手；被测软件版本、实际环境、执行人和日期待填写。当前仅有设计和用例，文档检查不等同于系统运行测试。

## 2 实况记录

| 项目 | 数量 | 说明 |
|---|---:|---|
| 总用例N | 24 | TC-01至TC-24 |
| 通过P | 0 | 尚未执行 |
| 失败F | 0 | 未执行不等于失败 |
| 阻塞B | 0 | 执行期遇到阻塞再记 |
| 未执行U | 24 | 等待软件就绪 |

N=P+F+B+U。当前已判定通过率P/(P+F)不适用，不是100%；执行比例0/24。AI计划40问、学习6组、微调测试50条，均未执行。

后续填每个TC的状态、实际、证据与缺陷。回归另记轮次，不重复计算唯一用例数。执行表位于工作记录。

## 3 分析与建议

当前不能给出系统合格或可交付结论。第7周按计划执行权限、评分、审核、两模式与安装，再形成结果。

结论填写示例格式：“执行X/24条，P通过、F失败、B阻塞、U未执行。遗留问题……，影响……，对已验收范围建议交付/暂不交付，未覆盖范围……。”数字须来自真实记录。

AI报告写“30道可回答中X道无关键错误”，分两课列计数。引用可打开与结论正确分开评价。微调无提升可写未观察到稳定改善，继续基础模型加RAG；不能只看loss下降就说学习效果提升。

## 4 缺陷修改记录

当前没有已确认的软件缺陷，不等于系统无缺陷。实际记录包括BUG、TC、步骤、原因、修复提交、回归人和结果。工作记录示例不计入统计。

## 附件

实际环境、用例结果、AI评价、手机截图、安装和恢复记录、训练与适配器证据均待产生。最终报告附对应文件和版本。
''')

put('工作记录/00_本次材料阅读与需求调整记录.md',r'''
# 本次材料阅读与需求调整记录

日期2026-10-24。本记录描述本次已进行的资料检查及用户要求，不代表小组已举行会议、开发或完成训练。

## 材料检查

枚举原目录全部文件。5份PDF共558页重新提取文字，与工作记录对应文本忽略空白和页分隔后吻合；课程安排重点核对任务、时间、评分与交付页面，并查看已有第37页图片。通用教学课件按文本和主题浏览，不声称逐页核验558页所有图像。

九份旧DOC模板通过文件夹已有提取文本阅读正文与表格结构，没有逐页复核原Word排版。阅读任务成果中的选题、填写与提交指南；注意其中提及的“情况说明”、海报和模板ZIP未出现在本次原目录，不能当作当前附件。

原方案16份Markdown、两份HTML、OpenAPI及校验和均已纳入检查。HTML为阅读/汇报呈现。OpenAPI 3.1含29路径、39个schema，内部引用未发现无法解析项；SHA256SUMS所列19个文件均匹配。这里只是文档检查，没有运行参考系统。

## 用户本次明确的要求

1. 阅读材料，说明需求、可行性、模型和训练数据规模。
2. 另建文件夹，按现有Markdown先填写项目文档和工作记录。
3. 团队三名大学生，只需保证计算机专业内容。
4. 功能具备即可，目标以交付为主。

## 本版建议调整

CHG-001：多学科改为计算机两课程小范围；复杂架构改单体SQLite；诊断改错题规则；更新限定来源；手机改响应式网页；微调一组小实验。具体章节、工时、模型配置及测试数量为本次建议，尚非教师批准。

已完成的是本次材料检查和文档编制。真实开发工时、成员会议和软件测试结果尚无证据，未填写成已发生。
''')

weeks=[
('范围与技术验证','A画问答和选课草图；B建数据与导入小样；C核实模型、GPU和20问基线','范围清单、环境记录、资料来源、20问原始输出','硬件不可用；资料来源不明确',24),
('基础业务','A登录选课页面；B账号、课程与导入；C题库和训练分组方案','登录导入演示、表结构、接口版本、样本分组表','解析失败；接口不一致',27),
('有出处问答','A问答历史与引用；B资料定位；C检索与引用核验','两课程问答、无资料提示、超时记录','引用错页；模型不可达',30),
('练习与错题','C评分与建议；A练习页面整合；B作答事务与去重','作答到错题重做完整流程、3题统计','重复计分；重做抬高正确率',27),
('审核更新','B来源检查和发布；A候选审核和更新页；C核对新增资料检索','未审不可查、批准可查、撤回演示','网络来源变化；重复发布',27),
('模型实验与冻结','C一组QLoRA和同集对照；B本地接入；A手机收尾','适配器、日志、两模式演示、功能冻结清单','无GPU；训练无提升',30),
('系统验证','全体交叉执行24例、40问和6场景；另一电脑安装','真实用例流水、AI评价、安装与手机证据','安装依赖遗漏；权限失败',27),
('交付与答辩','全体修复回归、补截图、整理九文档与手册、彩排','版本包、文档、讲评PPT、贡献和限制说明','文档与代码不一致；演示不稳定',24)]
for i,(goal,division,evidence,risk,hours) in enumerate(weeks,1):
 put(f'工作记录/周报/第{i:02d}周_预填计划.md',f'''
# 第{i}周项目周报预填计划

状态：未来工作预填，非已发生记录。实际日期、记录人和软件版本待填写。

## 本周计划

目标：{goal}。\n\n分工：{division}。\n\n预计三人合计{hours}人时，实际工时尚未发生。

## 实际成果

待执行后写具体完成项、负责人、提交号和证据。计划所需证据：{evidence}。目前没有完成证据，不预填完成率。

## 偏差与风险

重点关注：{risk}。发生后填写影响、负责人、补救及新日期；未发生不能写成真实缺陷。

## 下周安排

{'进入第'+str(i+1)+'周计划，未完成的核心工作优先补齐。' if i<8 else '按教师要求提交，保留交付版本与备份；不再临时扩功能。'}

## 会议与个人投入

教师指导日期与结论：待记录。小组例会日期和出席：待记录。A/B/C各自实际工时、代码、测试和文档贡献：待实际填写。
''')

put('工作记录/01_会议纪要预填.md',r'''
# 项目会议纪要预填

本页为拟议会议内容，不代表会议已经召开。日期、地点、主持、记录及实际出席人员待填写。三名成员用A/B/C代称。

## 拟议议题与建议决定

| 议题 | 建议决定 | 责任人与期限 |
|---|---|---|
| 范围 | 计算机课程，数据结构主课、数据库示例 | 全体第1周确认 |
| 技术 | Vue/FastAPI/SQLite，单进程演示 | B第1周跑小样 |
| 模型 | 4B指令基座，BGE检索，单次QLoRA | C第1周确认设备 |
| 分工 | A问答，B资料更新，C练习与模型 | 全体确认姓名 |
| 验收 | 24功能用例，40问，6统计场景 | C第2周冻结草案 |

## 会后实际记录

讨论意见：待会议发生后填。通过/修改/暂缓的事项：待填。不同意见及理由：待填。下一次检查时间：待填。教师是否认可范围：待填。
''')
put('工作记录/02_变更与风险台账.md',r'''
# 变更与风险台账

## 已知需求变更 CHG-001

日期2026-10-24。来源为用户本次说明。原方案面向多学科、较完整工程平台；现要求三名大学生、只保证计算机专业内容、功能有即可、以交付为主。对应文档已按新方向编制0.1版。具体技术方案尚待小组和教师评审。

影响：删减跨学科、复杂画像、可靠队列和离线PWA；保留问答、练习、更新、两模式、手机与一次实验。计划工时改为216人时估算，不是已承诺投入。

## 风险

| ID | 风险与触发 | 应对 | 责任人 | 当前状态 |
|---|---|---|---|---|
| R01 | 第1周无训练GPU | 提前借用或预算内短租，先完成API系统 | C | 待核实 |
| R02 | 资料或答案不可核对 | 缩章节，选可使用资料，人工交叉审核 | 全体 | 待核实 |
| R03 | 第3周问答尚不可演示 | 停装饰，先跑完整一问一答 | A | 预防项 |
| R04 | 第5周仍无更新闭环 | 只保留一个稳定来源和手动复测 | B | 预防项 |
| R05 | 微调无提升 | 保留负结果，系统使用基础加RAG | C | 允许结果 |
| R06 | 最后无法另机安装 | 第2周建立安装说明，第7周交叉安装 | B | 预防项 |

风险不是已经发生的缺陷。后续变更使用CHG-002起，记录范围、原因、工时影响、决定人和实际日期。
''')

exec((Path(__file__).parent/'supplement.py').read_text(encoding='utf-8'))

for name,text in files.items():
 path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')

from revise_scope import apply_scope_revision
apply_scope_revision(OUT)

def inline(s):
 s=html.escape(s)
 s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
 s=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
 def link(m):
  label,target=m.group(1),m.group(2)
  return f'<a href="{target}">{label}</a>'
 return re.sub(r'\[([^]]+)\]\(([^)]+)\)',link,s)

def render_md(t):
 lines=t.splitlines();out=[];i=0
 while i<len(lines):
  s=lines[i].strip()
  if not s:i+=1;continue
  if s.startswith('```'):
   buf=[];i+=1
   while i<len(lines) and not lines[i].strip().startswith('```'):buf.append(lines[i]);i+=1
   out.append('<pre>'+html.escape('\n'.join(buf))+'</pre>');i+=1;continue
  if s.startswith('|'):
   rows=[]
   while i<len(lines) and lines[i].strip().startswith('|'):
    row=[v.strip() for v in lines[i].strip().strip('|').split('|')]
    if not all(re.fullmatch(r'[:\- ]+',v) for v in row):rows.append(row)
    i+=1
   out.append('<div class="tablewrap"><table><thead><tr>'+''.join('<th>'+inline(x)+'</th>' for x in rows[0])+'</tr></thead><tbody>')
   out.extend('<tr>'+''.join('<td>'+inline(x)+'</td>' for x in row)+'</tr>' for row in rows[1:]);out.append('</tbody></table></div>');continue
  m=re.match(r'^(#{1,6}) (.*)',s)
  if m:out.append(f'<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>');i+=1;continue
  if re.match(r'^(- |\d+\. )',s):
   ordered=bool(re.match(r'^\d',s));tag='ol' if ordered else 'ul';out.append('<'+tag+'>')
   while i<len(lines) and re.match(r'^(- |\d+\. )',lines[i].strip()):
    out.append('<li>'+inline(re.sub(r'^(- |\d+\. )','',lines[i].strip()))+'</li>');i+=1
   out.append('</'+tag+'>');continue
  buf=[s];i+=1
  while i<len(lines) and lines[i].strip() and not re.match(r'^(#|\||```|- |\d+\. )',lines[i].strip()):buf.append(lines[i]);i+=1
  out.append('<p>'+inline(' '.join(buf))+'</p>')
 return '\n'.join(out)

mds=sorted(OUT.rglob('*.md'))
nav=[];sections=[]
for idx,p in enumerate(mds):
 rel=p.relative_to(OUT).as_posix();nav.append(f'<a href="#d{idx}">{html.escape(rel)}</a>')
 sections.append(f'<article id="d{idx}"><p class="path">{html.escape(rel)}</p>'+render_md(p.read_text(encoding='utf-8'))+'</article>')
css='''body{margin:0;background:#f6f7f9;color:#18212b;font:16px/1.75 "Microsoft YaHei",sans-serif}aside{position:fixed;inset:0 auto 0 0;width:270px;overflow:auto;background:#fff;padding:24px;box-sizing:border-box;border-right:1px solid #ddd}aside a{display:block;margin:10px 0;font-size:13px}main{margin-left:270px;padding:32px;max-width:1050px}article{background:white;padding:38px;margin-bottom:24px;border:1px solid #e0e3e8;border-radius:8px}h1{font-size:28px}h2{font-size:22px;margin-top:30px}h3{font-size:18px}h1,h2,h3{color:black;line-height:1.4}a{color:#2457ad}pre{background:#f3f5f8;padding:18px;overflow:auto;line-height:1.5;font-size:13px}code{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.65}th,td{border:1px solid #d9d9d9;padding:9px 12px;text-align:left;vertical-align:middle}th{background:#e9eff6;color:#111}tr:nth-child(even){background:#fafbfc}.tablewrap{overflow:auto}.path{color:#667;font-size:12px} @media(max-width:800px){aside{position:static;width:auto;max-height:260px}main{margin:0;padding:12px}article{padding:18px}table{min-width:580px}} @media print{body{background:white;font-size:10pt}aside{display:none}main{margin:0;padding:0;max-width:none}article{border:0;margin:0;padding:0;page-break-before:always}article:first-child{page-break-before:auto}h1,h2,h3{break-after:avoid}tr{break-inside:avoid}thead{display:table-header-group}pre{white-space:pre-wrap}.tablewrap{overflow:visible}}'''
(OUT/'阅读版.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>计算机课程学习助手交付文档初稿</title><style>'+css+'</style><aside><b>交付文档初稿</b>'+''.join(nav)+'</aside><main>'+''.join(sections)+'</main></html>',encoding='utf-8')
inventory=[]
for p in sorted(OUT.rglob('*')):
 if p.is_file() and p.name!='文件清单.json':inventory.append({'file':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(OUT/'文件清单.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(ROOT/'计算机课程学习助手_交付文档初稿.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(OUT.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(ROOT))
print(json.dumps({'folder':str(OUT),'markdown_files':len(mds),'all_files':len(inventory)+1,'tests':len(tests),'planned_hours':sum(x[4] for x in weeks)},ensure_ascii=False))
