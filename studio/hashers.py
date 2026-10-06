"""Read-only compatibility for legacy PBKDF2 hashes; Django rehashes on login."""
import base64
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from lib.admin_backend import _verify_password
class LegacyPasswordHasher(BasePasswordHasher):
    algorithm='legacy_portfolio'
    def verify(self,password,encoded):
        try: return _verify_password(password,base64.b64decode(encoded.split('$',1)[1]).decode())
        except Exception: return False
    def encode(self,password,salt,**kwargs): raise NotImplementedError('Legacy hashes are read-only.')
    def safe_summary(self,encoded): return {'algorithm':self.algorithm,'hash':mask_hash(encoded)}
    def must_update(self,encoded): return True
    def harden_runtime(self,password,encoded): pass
