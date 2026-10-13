import os,tempfile
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest
from techmedic import config,database
os.environ['TECHMEDIC_CANDIDATE_JOURNAL_KEY']=Fernet.generate_key().decode()
os.environ.pop('TECHMEDIC_V156_ALLOW_LIVE',None)
with tempfile.TemporaryDirectory() as td, patch.object(config,'PROJECT_ROOT',Path(td)):
 app=AppTest.from_file('app.py',default_timeout=30).run()
 assert not app.exception,app.exception
 assert not app.error,app.error
 app.text_area[0].set_value('Fictional Windows laptop cannot connect to Wi-Fi')
 next(b for b in app.button if b.label=='Start Diagnosis').click().run()
 assert not app.exception,app.exception
 assert not app.error,app.error
 db=Path(td)/'data'/'techmedic_v1_5_6.sqlcipher'
 cases=database.list_cases(db)
 assert len(cases)==1
 assert len(database.get_turns(db,cases[0]['id']))==1
 app.chat_input[0].set_value('Fictional follow-up: another device can connect').run()
 assert not app.exception,app.exception
 assert len(database.get_turns(db,cases[0]['id']))==2
 print('Streamlit AppTest: startup and two synthetic turns PASS')
 with database._connect(db) as c:
  print('SQLCipher',c.execute('PRAGMA cipher_version').fetchone()[0])
  print('Integrity',c.execute('PRAGMA integrity_check').fetchone()[0])

# Pagination and expired-worker recovery use a separate disposable app session.
from techmedic import candidate_journal as journal
with tempfile.TemporaryDirectory() as td, patch.object(config,'PROJECT_ROOT',Path(td)):
 db=Path(td)/'data'/'techmedic_v1_5_6.sqlcipher'
 journal.ensure(db)
 cid=database.create_case(db,'SYNTHETIC large history')
 with database._connect(db) as c:
  for n in range(122):
   c.execute("INSERT INTO turns(case_id,user_text,diagnostic_state_json,jev_result_json,safety_json,assistant_text,created_at) VALUES(?,?,?,?,?,?,?)",(cid,str(n),'{}','{}','{}','answer','now'))
 app=AppTest.from_file('app.py',default_timeout=30)
 app.session_state['active_case_id']=cid
 with patch.object(database,'get_turns',wraps=database.get_turns) as reads:
  app.run()
  assert not app.exception,app.exception
  assert len(app.chat_message)==100
  assert reads.call_count==1 and reads.call_args.kwargs=={'limit':51}
 next(b for b in app.button if b.label=='Load older messages').click().run()
 assert not app.exception,app.exception
 assert len(app.chat_message)==200
 next(b for b in app.button if b.label=='Load older messages').click().run()
 assert len(app.chat_message)==244
 assert not any(b.label=='Load older messages' for b in app.button)
 with patch.object(database,'get_turns',wraps=database.get_turns) as reads:
  next(b for b in app.button if b.label=='Diagnostic Options').click().run()
  assert not app.exception,app.exception
  assert any(not call.kwargs for call in reads.call_args_list), 'Export must request complete history'
 journal.capture(db,cid,'stale','Fictional recovery input')
 journal.claim(db,cid,'stale',now=0)
 app.run()
 next(b for b in app.button if b.label=='Retry saved submission').click().run()
 assert not app.exception,app.exception
 assert len(database.get_turns(db,cid))==123
 print('Streamlit AppTest: bounded history, load older, full export, expired-worker retry PASS')
