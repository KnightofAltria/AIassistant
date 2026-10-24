"""Integration tests use isolated temporary data; AI responses are mocked explicitly."""
import base64, io, json, sys, tempfile, threading, unittest, urllib.error, urllib.request, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class AppTests(unittest.TestCase):
    def setUp(self):
        test_root=Path(__file__).resolve().parents[1]/'test-results';test_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=test_root);server.KEY='';server.BUSY.clear();server.init(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_seed_and_hide_answers(self):
        s=server.public_state();self.assertEqual(len(s['courses']),4)
        self.assertEqual(sum(len(ch['questions']) for c in s['courses'] for ch in c['chapters']),36)
        self.assertNotIn('answer',s['courses'][0]['chapters'][0]['questions'][0])
        self.assertNotIn('key',json.dumps(s))
    def test_course_protection(self):
        with self.assertRaises(ValueError): server.action('course.delete',{'id':'ds'})
        c=server.action('course.create',{'name':'数据库'})
        server.action('chapter.save',{'course':c['id'],'title':'关系模型','body':'关系代数'})
        self.assertEqual(len(server.read_state()['courses'][-1]['chapters']),1)
        server.action('course.delete',{'id':c['id']});self.assertEqual(len(server.read_state()['courses']),4)
    def test_builtin_chapter_confirmation(self):
        with self.assertRaises(ValueError): server.action('chapter.delete',{'course':'ds','id':'ds-1'})
        server.action('chapter.delete',{'course':'ds','id':'ds-1','confirm':True})
        self.assertEqual(len(server.read_state()['courses'][0]['chapters']),2)
    def test_quiz_grade_idempotent_and_review(self):
        payload={'course':'ds','chapter':'ds-1','request':'test-request','answers':{'ds-1-q0':0,'ds-1-q1':0,'ds-1-q2':1}}
        result=server.action('quiz.submit',payload);self.assertEqual(result['correct'],2)
        again=server.action('quiz.submit',payload);self.assertEqual(result['id'],again['id'])
        s=server.read_state();self.assertEqual(len(s['attempts']),1);self.assertEqual(len(s['summaries']),1);self.assertEqual(len(s['mistakes']),1)
        r=server.action('mistake.retry',{'id':s['mistakes'][0]['id'],'answer':2});self.assertTrue(r['correct'])
        self.assertTrue(server.read_state()['mistakes'][0]['resolved'])
        self.assertTrue((server.DATA/'近期总结'/(s['summaries'][0]['id']+'.md')).exists())
    def test_incomplete_quiz_rejected(self):
        with self.assertRaises(ValueError): server.action('quiz.submit',{'course':'ds','chapter':'ds-1','request':'x','answers':{}})
        self.assertEqual(server.read_state()['attempts'],[])
    def test_file_import_move_delete_and_scope(self):
        r=server.action('resource.import',{'name':'../../hello.md','folder':'core','content':base64.b64encode('专属测试术语 zyxwvu'.encode()).decode()})
        item=server.find(server.read_state()['resources'],r['id']);self.assertTrue((server.DATA/'files'/item['filename']).is_file())
        self.assertNotIn('..',item['filename'])
        self.assertTrue(server.retrieve(server.read_state(),'zyxwvu','net'))
        server.action('resource.move',{'id':r['id'],'folder':'操作系统'})
        self.assertFalse(server.retrieve(server.read_state(),'zyxwvu','net'))
        self.assertTrue(server.retrieve(server.read_state(),'zyxwvu','os'))
        server.action('resource.delete',{'id':r['id']});self.assertFalse((server.DATA/'files'/item['filename']).exists())
    def test_bad_files(self):
        for name,content in [('x.exe',b'abc'),('x.pdf',b'invalid'),('x.docx',b'invalid'),('x.txt',b'')]:
            with self.assertRaises(ValueError): server.action('resource.import',{'name':name,'folder':'core','content':base64.b64encode(content).decode()})
    def test_docx_parser(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>测试讲义</w:t></w:r></w:p></w:body></w:document>')
        r=server.action('resource.import',{'name':'x.docx','folder':'core','content':base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(server.find(server.read_state()['resources'],r['id'])['text'],'测试讲义')
    def test_folder_and_source_deduplication(self):
        with self.assertRaises(ValueError):server.action('folder.delete',{'name':'core'})
        with self.assertRaises(ValueError):server.action('folder.delete',{'name':'数据结构'})
        a=server.action('source.collect',{'id':'ods'});b=server.action('source.collect',{'id':'ods'});self.assertEqual(a['id'],b['id'])
    def test_settings_key_not_exported(self):
        server.action('settings.save',{'key':'sk-test-only','model':'deepseek-flash','remember':True})
        self.assertTrue((server.DATA/'credentials.json').exists());self.assertNotIn('sk-test-only',json.dumps(server.public_state()))
        server.action('settings.save',{'model':'deepseek-flash','clear':True});self.assertFalse(server.KEY);self.assertFalse((server.DATA/'credentials.json').exists())
    def test_missing_key_chat_no_fake_message(self):
        chat=server.action('chat.create',{})
        with self.assertRaises(ValueError):server.action('chat.send',{'id':chat['id'],'message':'解释栈'})
        self.assertEqual(server.read_state()['chats'][0]['messages'],[]);self.assertFalse(server.BUSY)
    def test_chat_gateway_and_summary_mocked(self):
        chat=server.action('chat.create',{'course':'ds'})
        with patch.object(server,'llm',return_value='栈是后进先出。[资料1]') as mock:
            server.action('chat.send',{'id':chat['id'],'message':'栈和队列'})
            messages=mock.call_args.args[0];self.assertIn('资料1',messages[0]['content']);self.assertIn('学习目标',messages[0]['content'])
        self.assertEqual(len(server.read_state()['chats'][0]['messages']),2)
        with patch.object(server,'llm',return_value='## 今日回顾\n学习栈与队列。'):
            summary=server.action('summary.ai',{'id':chat['id']})
        self.assertTrue((server.DATA/'近期总结'/(summary['id']+'.md')).exists())
        server.action('summary.delete',{'id':summary['id']});self.assertFalse((server.DATA/'近期总结'/(summary['id']+'.md')).exists())
    def test_generated_chapter_validation(self):
        before=len(server.read_state()['courses'][0]['chapters'])
        with patch.object(server,'ai_json',return_value={'chapters':[{'title':'Bad','body':'Text','questions':[{'options':['x'],'answer':9}]}]}):
            with self.assertRaises(ValueError):server.action('chapter.generate',{'id':'ds','topic':'栈'})
        self.assertEqual(len(server.read_state()['courses'][0]['chapters']),before)
        with patch.object(server,'ai_json',return_value={'chapters':[{'title':'栈','body':'解释','questions':[{'stem':'测试','options':['a','b','c','d'],'answer':0,'explanation':'测试解析'}]}]}):
            server.action('chapter.generate',{'id':'ds','topic':'栈'})
        self.assertEqual(len(server.read_state()['courses'][0]['chapters']),before+1)
    def test_profile_snapshot_and_clear(self):
        with patch.object(server,'llm',return_value='记录有限，建议先做一章练习。'): result=server.action('profile.snapshot',{})
        self.assertTrue((server.DATA/'学习者档案'/(result['id']+'.md')).exists())
        with self.assertRaises(ValueError):server.action('history.clear',{'confirm':'wrong'})
        server.action('history.clear',{'confirm':'删除学习记录'});self.assertEqual(server.read_state()['summaries'],[])
        self.assertTrue(server.read_state()['resources'])
    def test_persistence_after_reinit(self):
        server.action('profile.save',{'name':'持久化测试','goal':'了解网络','avatar':'🌱'});server.init(self.temp.name)
        self.assertEqual(server.read_state()['profile']['name'],'持久化测试')
    def test_http_security(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{http.server_port}'
        try:
            with urllib.request.urlopen(base+'/api/state') as r:self.assertEqual(r.status,200)
            for headers in [{'Content-Type':'application/json'},{'X-CSLA-Token':server.TOKEN,'Origin':'https://evil.example'},{'Host':'evil.example'}]:
                req=urllib.request.Request(base+'/api/setup.skip',data=b'{}',headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code,403)
            req=urllib.request.Request(base+'/api/setup.skip',data=b'{}',headers={'X-CSLA-Token':server.TOKEN})
            with urllib.request.urlopen(req) as r:self.assertTrue(json.load(r)['ok'])
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+'/../../server.py')
        finally:http.shutdown();http.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
