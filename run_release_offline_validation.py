"""Optional local regression for the shipped core and encryption tests, offline and synthetic."""
from __future__ import annotations
import os,socket,sys,unittest
from cryptography.fernet import Fernet
key=os.getenv('TECHMEDIC_CANDIDATE_JOURNAL_KEY')
if not key: os.environ['TECHMEDIC_CANDIDATE_JOURNAL_KEY']=Fernet.generate_key().decode('ascii')
def block(*args,**kwargs): raise RuntimeError('Offline tests cannot access the network')
socket.socket.connect=block
socket.socket.connect_ex=block
suite=unittest.defaultTestLoader.discover('tests',pattern='test_*.py')
r=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if r.wasSuccessful() else 1)
