"""Conservative guard against definitive claims in unverified case responses.

Lexical guard only. It is not a comprehensive semantic classifier.
"""
from __future__ import annotations
import re

_CLOSURE = re.compile(
    r'\b(resolution verified|(?:the\s+)?(?:issue|problem)\s+(?:is\s+)?resolved|'
    r'problem\s+(?:is\s+)?fully\s+fixed|no\s+further\s+troubleshooting\s+(?:is\s+)?needed)\b',
    re.IGNORECASE)
_NEGATION = re.compile(r'\b(not|isn.t|never|unverified|without)\b',re.IGNORECASE)

def unsupported_closure(text:str, status:str)->bool:
    if status=='resolution_verified' or not isinstance(text,str):
        return False
    for match in _CLOSURE.finditer(text):
        # Avoid e.g. "resolution verified is NOT established" by inspecting
        # only the phrase's immediately adjacent context. Ambiguities must
        # be reviewed manually in Pass 16.
        context=text[max(0,match.start()-24):min(len(text),match.end()+20)]
        if not _NEGATION.search(context):
            return True
    return False
