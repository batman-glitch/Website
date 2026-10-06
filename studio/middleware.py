from urllib.parse import parse_qsl, urlencode
from django.http import JsonResponse
from django.shortcuts import redirect
class VercelPathMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        if request.path == '/api/index' and '__path' in request.GET:
            path=request.GET['__path']
            if not path.startswith('/') or path.startswith('//'):
                return JsonResponse({'error':'Invalid route.'},status=400)
            request.path=request.path_info=path
            request.META['PATH_INFO']=path
            request.META['QUERY_STRING']=urlencode([(k,v) for k,v in parse_qsl(request.META.get('QUERY_STRING','')) if k!='__path'])
            request.__dict__.pop('GET',None)
        return self.get_response(request)
class AccountSecurityMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        if request.user.is_authenticated and not request.user.is_active:
            from django.contrib.auth import logout
            logout(request)
        response=self.get_response(request)
        if request.path.startswith(('/login','/register','/password','/client/','/dashboard/','/admin/','/api/')):
            response['Cache-Control']='no-store, max-age=0'
        return response
