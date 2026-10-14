"""Restrict user-controlled outbound targets to operator-approved HTTPS services.

Custom CSV/iiko hosts must be explicitly trusted by the operator. No wildcard
from a user's URL is accepted; every CSV redirect is checked before requesting.
"""
import os
from urllib.parse import urlsplit
import httpx

MAX_CSV_BYTES=5*1024*1024

def trusted_url(value,kind):
    try:
        u=urlsplit(value)
        host=(u.hostname or '').lower()
        if (u.scheme!='https' or not host or u.username or u.password or u.fragment
                or u.port not in (None,443) or any(ord(c)<33 for c in value)):
            raise ValueError()
        configured={s.strip().lower() for s in os.getenv('CSV_TRUSTED_HOSTS' if kind=='csv' else 'IIKO_TRUSTED_HOSTS','').split(',') if s.strip()}
        builtin=(host=='docs.google.com' or host=='docs.googleusercontent.com' or host.endswith('.googleusercontent.com')) if kind=='csv' else (host.endswith('.iiko.it'))
        if not builtin and host not in configured:raise ValueError()
        return value
    except (ValueError,TypeError):
        raise ValueError('Адрес не разрешён. Нужен HTTPS-сервис из списка доверенных серверов.') from None

async def fetch_csv(value):
    current=trusted_url(value,'csv')
    async with httpx.AsyncClient(timeout=30.0,follow_redirects=False,trust_env=False) as client:
        for _ in range(5):
            async with client.stream('GET',current) as response:
                if response.is_redirect:
                    location=response.headers.get('location')
                    if not location:raise ValueError('Нет адреса перенаправления таблицы.')
                    current=trusted_url(str(response.url.join(location)),'csv')
                    continue
                response.raise_for_status()
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>MAX_CSV_BYTES:raise ValueError('Таблица превышает 5 МБ.')
                # aiter_bytes already decompresses; retaining Content-Encoding would decode twice.
                headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length')}
                return httpx.Response(response.status_code,headers=headers,content=bytes(data),request=response.request)
    raise ValueError('Слишком много перенаправлений таблицы.')
