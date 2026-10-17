"""Anthropic recipient safety: real SDK/HTTP client, intercepted transport only.

No database, migrations, real image, credential or external socket is used.
"""
from dataclasses import replace
import importlib
import json
import socket
from types import SimpleNamespace

import anthropic
import pytest

from app.services import receiving_ai as RA
from app.services.ai_requirement import Requirement, DISCLOSURE_ID, DISPATCH_ID

ORIGIN = 'https://api.anthropic.com'
MESSAGES = ORIGIN + '/v1/messages'


def target():
    return Requirement(7, 'active', 'anthropic', 'synthetic-model', 1,
                       DISCLOSURE_ID, 2, DISPATCH_ID, 'synthetic-test-key')


@pytest.fixture()
def wire(monkeypatch):
    # Real SDK-native backend (httpx in older SDKs; httpx2 in SDK 1.15).
    native = next(base for base in anthropic.DefaultHttpxClient.__mro__
                  if base.__name__ == 'Client' and base.__module__.split('.')[0] in ('httpx', 'httpx2'))
    http = importlib.import_module(native.__module__.split('.')[0])
    state = SimpleNamespace(requests=[], checks=[], clients=[], http=http, native=native,
                            status=200, location='https://unapproved.invalid/stolen')
    guard = RA._check_anthropic_request
    def observe_guard(request):
        state.checks.append(str(request.url))
        guard(request)
    monkeypatch.setattr(RA, '_check_anthropic_request', observe_guard)
    for name in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_CUSTOM_HEADERS', 'ANTHROPIC_AUTH_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    def no_socket(*args, **kwargs):
        raise AssertionError('External sockets are prohibited in endpoint tests')
    monkeypatch.setattr(socket.socket, 'connect', no_socket)
    monkeypatch.setattr(socket.socket, 'connect_ex', no_socket)

    def send(self, request):
        state.requests.append(request)
        if state.status != 200:
            return http.Response(state.status, headers={'location': state.location},
                                 json={'type':'error','error':{'type':'api_error','message':'synthetic'}},
                                 request=request)
        return http.Response(200, json={
            'id':'msg_synthetic', 'type':'message','role':'assistant','model':'synthetic-model',
            'content':[{'type':'text','text':'[]'}], 'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':1,'output_tokens':1}}, request=request)
    monkeypatch.setattr(http.HTTPTransport, 'handle_request', send)
    sdk_class = anthropic.Anthropic
    state.sdk_class = sdk_class
    def observe(**kwargs):
        client = sdk_class(**kwargs)
        state.clients.append(client)
        return client
    monkeypatch.setattr(anthropic, 'Anthropic', observe)
    return state


@pytest.mark.parametrize('override',[None, 'https://other.invalid', ORIGIN, 'http://api.anthropic.com'])
def test_explicit_endpoint_overrides_environment(wire,monkeypatch,override):
    if override is not None:
        monkeypatch.setenv('ANTHROPIC_BASE_URL', override)
    assert RA._read_claude('AQID','image/jpeg','synthetic',target()) == []
    assert [str(r.url) for r in wire.requests] == [MESSAGES]
    assert wire.requests[0].headers['x-api-key'] == 'synthetic-test-key'
    body=json.loads(wire.requests[0].content)
    assert body['model']=='synthetic-model'
    assert body['messages'][0]['content'][0]['source']['data']=='AQID'
    client=wire.clients[0]
    assert str(client.base_url).rstrip('/') == ORIGIN
    assert type(client._client) is wire.native
    assert client._client.follow_redirects is False and client._client.trust_env is False
    assert client._client.is_closed


@pytest.mark.parametrize('code',[301,302,303,307,308])
def test_redirect_never_forwards_image(wire,code):
    wire.status=code
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:')
    assert [str(r.url) for r in wire.requests] == [MESSAGES]
    assert wire.clients[0]._client.is_closed


@pytest.mark.parametrize('wrong',[
    'https://other.invalid', 'http://api.anthropic.com',
    ORIGIN+'/other', ORIGIN+':444', 'https://api.anthropic.com.other.invalid'])
def test_effective_endpoint_mismatch_blocks_before_transport(wire,monkeypatch,wrong):
    def incorrect_sdk(**kwargs):
        kwargs['base_url']=wrong
        client=wire.sdk_class(**kwargs)
        wire.clients.append(client)
        return client
    monkeypatch.setattr(anthropic,'Anthropic',incorrect_sdk)
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:')
    assert wire.requests==[] and wire.clients[0]._client.is_closed


def test_revision_unchanged_cannot_change_recipient_via_env(wire,monkeypatch):
    snapshot=target()
    for endpoint in ('https://first.invalid','https://second.invalid'):
        monkeypatch.setenv('ANTHROPIC_BASE_URL',endpoint)
        assert RA.read_invoice('AQID','image/jpeg',[],snapshot) == ([], 'ai')
    assert snapshot.revision==7 and snapshot.dispatch_id==DISPATCH_ID
    assert [str(r.url) for r in wire.requests] == [MESSAGES,MESSAGES]


@pytest.mark.parametrize('changes',[{'provider':'gemini'}, {'dispatch_id':'other'},
                                   {'protocol_version':1}, {'mode':'paused'}])
def test_incompatible_canonical_identity_never_dispatches(wire,changes):
    with pytest.raises(RA._UpstreamError):
        RA._read_claude('AQID','image/jpeg','synthetic',replace(target(),**changes))
    assert wire.requests==[] and wire.clients==[]


def test_environment_proxy_and_host_header_cannot_redirect_transport(wire,monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://proxy.invalid:9999')
    monkeypatch.setenv('HTTP_PROXY','http://proxy.invalid:9999')
    monkeypatch.setenv('ALL_PROXY','http://proxy.invalid:9999')
    assert RA._read_claude('AQID','image/jpeg','synthetic',target()) == []
    assert wire.clients[0]._client.trust_env is False
    assert not wire.clients[0]._client._mounts
    assert [str(r.url) for r in wire.requests] == [MESSAGES]
    wire.requests.clear()
    monkeypatch.setenv('ANTHROPIC_CUSTOM_HEADERS','Host:other.invalid')
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:') and wire.requests==[]


@pytest.mark.parametrize('wrong',[ORIGIN+'/other', 'https://other.invalid'])
def test_late_sdk_url_mutation_blocked_at_send(wire,monkeypatch,wrong):
    def late_change(**kwargs):
        client=wire.sdk_class(**kwargs)
        original=client.messages.create
        def changed(**body):
            client.base_url=wrong
            return original(**body)
        client.messages.create=changed
        wire.clients.append(client)
        return client
    monkeypatch.setattr(anthropic,'Anthropic',late_change)
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:')
    assert wire.requests==[] and wire.clients[0]._client.is_closed


def test_redirect_guard_still_blocks_if_client_follow_policy_drifts(wire,monkeypatch):
    wire.status=307
    def altered_client(**kwargs):
        client=wire.sdk_class(**kwargs)
        client._client.follow_redirects=True
        wire.clients.append(client)
        return client
    monkeypatch.setattr(anthropic,'Anthropic',altered_client)
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:')
    assert [str(r.url) for r in wire.requests] == [MESSAGES]
    assert wire.checks == [MESSAGES, wire.location]


def test_unknown_sdk_http_backend_fails_closed(wire,monkeypatch):
    class Unknown:
        pass
    monkeypatch.setattr(anthropic,'DefaultHttpxClient',Unknown)
    rows,source=RA.read_invoice('AQID','image/jpeg',[],target())
    assert rows==[] and source.startswith('error:')
    assert wire.requests==[] and wire.clients==[]


def test_sdk_default_wrapper_cannot_inject_a_custom_transport(wire,monkeypatch):
    class CustomDefault(wire.native):
        def __init__(self,**kwargs):
            pytest.fail('SDK wrapper/custom transport must not be constructed')
    monkeypatch.setattr(anthropic,'DefaultHttpxClient',CustomDefault)
    assert RA._read_claude('AQID','image/jpeg','synthetic',target()) == []
    assert type(wire.clients[0]._client) is wire.native
    assert [str(r.url) for r in wire.requests] == [MESSAGES]
