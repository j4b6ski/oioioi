from urllib2 import Request, urlopen
from urllib import urlencode
from django.conf import settings
from django.core.exceptions import PermissionDenied
import json

def validate_grecaptcha_response(grecaptcha_response):
    req =  Request('https://www.google.com/recaptcha/api/siteverify', data=urlencode({
        'secret': settings.GOOGLE_RECAPTCHA_SECRET_KEY,
        'response': grecaptcha_response
    }).encode())
    resp = json.load(urlopen(req))
    if not (resp['success'] and resp['score'] > 0.4):
        raise PermissionDenied("Please stop acting like a robot and try again. If the problem persists, please contact the admins.")
