"""Fetch an explicit allowlist of CC-BY Open Data Structures pages.

Run during delivery preparation or manually to update bundled references.
No arbitrary URLs, redirects, scripts, cookies, or credentials are used.
"""
import hashlib, json, re, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

PAGES=[('array-lists','顺序表与数组','2_Array_Based_Lists.html'),('linked-lists','链表','3_Linked_Lists.html'),('binary-trees','二叉树','6_Binary_Trees.html')]
BASE='https://opendatastructures.org/ods-python/'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.skip+=1
        if not self.skip and tag in ('p','br','div','h1','h2','h3','li','tr'):self.parts.append('\n')
        if tag=='img' and not self.skip:self.parts.append(dict(attrs).get('alt',''))
    def handle_endtag(self,tag):
        if tag in ('script','style','head'):self.skip=max(0,self.skip-1)
        if tag in ('p','li','tr','h1','h2','h3'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
def collect():
    out=Path(__file__).resolve().parent/'references';out.mkdir(exist_ok=True);manifest=[]
    opener=urllib.request.build_opener(NoRedirect())
    for ident,title,page in PAGES:
        url=BASE+page
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'CSLA-Educational-Reference/1.0'}),timeout=25) as res:
            raw=res.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('Source exceeds size limit')
        parser=Text();parser.feed(raw.decode('utf-8',errors='replace'));text='\n'.join(re.sub(r'\s+',' ',x).strip() for x in ''.join(parser.parts).splitlines() if x.strip())
        content=f'# {title} — Open Data Structures\n\n作者：Pat Morin\n来源：{url}\n许可：Creative Commons Attribution（出版社说明：https://opendatastructures.org/ ）\n收集方式：从作者公开 HTML 页面提取文字，保留公式图片的 alt 文本；移除网页脚本、样式和导航图像。公式可能仍含 LaTeX 标记，请对照原站。\n收集时间：{datetime.now(timezone.utc).isoformat()}\n\n## 原文摘录\n\n{text}\n'
        filename=ident+'.md';(out/filename).write_text(content,encoding='utf-8')
        manifest.append(dict(id=ident,title=title,filename=filename,source=url,sha256=hashlib.sha256(content.encode()).hexdigest()))
        print('Collected:',title,len(raw),'bytes')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':collect()
