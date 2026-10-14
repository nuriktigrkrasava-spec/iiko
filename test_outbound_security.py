import asyncio
import httpx
import pytest
import outbound_security as security

@pytest.mark.parametrize('url',[
 'http://docs.google.com/x','https://127.0.0.1/x','https://169.254.169.254/latest',
 'https://localhost/x','https://docs.google.com.evil.test/x',
 'https://user:pass@docs.google.com/x','https://docs.google.com:444/x',
 'https://docs.google.com/x#fragment','https://docs.google.com/\nx',
])
def test_reject_untrusted_target(url):
    with pytest.raises(ValueError):security.trusted_url(url,'csv')

def test_explicit_operator_hosts_only(monkeypatch):
    monkeypatch.setenv('IIKO_TRUSTED_HOSTS','iiko.example.test')
    assert security.trusted_url('https://iiko.example.test/resto','iiko')
    with pytest.raises(ValueError):security.trusted_url('https://evil.iiko.example.test/resto','iiko')

def test_redirect_revalidated_before_request(monkeypatch):
    seen=[];original=httpx.AsyncClient
    def handler(request):
        seen.append(str(request.url));return httpx.Response(302,headers={'location':'http://169.254.169.254/latest'})
    monkeypatch.setattr(security.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ValueError):asyncio.run(security.fetch_csv('https://docs.google.com/x'))
    assert seen==['https://docs.google.com/x']

def test_csv_size_bound(monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(security,'MAX_CSV_BYTES',8)
    monkeypatch.setattr(security.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'123456789')),**kw))
    with pytest.raises(ValueError):asyncio.run(security.fetch_csv('https://docs.google.com/x'))

def test_compressed_csv_is_decoded_once(monkeypatch):
    import gzip
    original=httpx.AsyncClient
    body='Филиал,План\nТочка,100\n'.encode()
    def handler(request):return httpx.Response(200,headers={'content-encoding':'gzip','content-type':'text/csv; charset=utf-8'},content=gzip.compress(body))
    monkeypatch.setattr(security.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    response=asyncio.run(security.fetch_csv('https://docs.google.com/x'))
    assert response.content==body
    assert 'content-encoding' not in response.headers
