import os
import requests
from django.core.mail.backends.base import BaseEmailBackend
class ResendBackend(BaseEmailBackend):
    def send_messages(self,email_messages):
        count=0
        for message in email_messages:
            result=requests.post('https://api.resend.com/emails',headers={'Authorization':'Bearer '+os.environ['RESEND_API_KEY']},json={'from':message.from_email,'to':message.to,'subject':message.subject,'text':message.body},timeout=15)
            result.raise_for_status()
            count+=1
        return count
