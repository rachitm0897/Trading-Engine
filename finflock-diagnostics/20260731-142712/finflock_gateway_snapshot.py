import json, os, socket, traceback
import requests

SENSITIVE = ('password','secret','token','credential','authorization','api_key','encrypted')

def sensitive(name):
    text = str(name or '').lower()
    return any(part in text for part in SENSITIVE)

def safe(value, depth=0):
    if depth > 5: return '<max-depth>'
    if isinstance(value, dict): return {str(k): ('[REDACTED]' if sensitive(k) else safe(v, depth+1)) for k,v in value.items()}
    if isinstance(value, list):
        out = [safe(v, depth+1) for v in value[:100]]
        if len(value) > 100: out.append(f'<{len(value)-100} more>')
        return out
    if isinstance(value, str) and len(value) > 12000: return value[:12000] + '<truncated>'
    return value

def emit(title, payload):
    print(f'\n===== {title} =====')
    print(json.dumps(safe(payload), indent=2, sort_keys=True, default=str))

emit('GATEWAY ENVIRONMENT SUMMARY', {
    'BROKER_ADAPTER': os.getenv('BROKER_ADAPTER'), 'IBC_TRADING_MODE': os.getenv('IBC_TRADING_MODE'),
    'IBKR_CLIENT_ID': os.getenv('IBKR_CLIENT_ID'), 'PORT': os.getenv('PORT'),
    'has_gateway_service_token': bool(os.getenv('GATEWAY_SERVICE_TOKEN')),
    'has_ib_username': bool(os.getenv('IB_USERNAME')), 'has_ib_password': bool(os.getenv('IB_PASSWORD')),
    'has_novnc_password': bool(os.getenv('NOVNC_PASSWORD'))})

probes = {}
for port in (5900,6080,8001,8080,4001,4002):
    sock = socket.socket(); sock.settimeout(2)
    try:
        sock.connect(('127.0.0.1', port)); probes[str(port)] = 'OPEN'
    except Exception as exc: probes[str(port)] = f'CLOSED/FAILED: {exc!r}'
    finally: sock.close()
emit('LOCAL SOCKET PROBES', probes)

for url in ('http://127.0.0.1:6080/vnc.html','http://127.0.0.1:8001/healthz','http://127.0.0.1:8080/healthz','http://127.0.0.1:8080/readyz'):
    try:
        response = requests.get(url, timeout=5)
        emit(f'HTTP {url}', {'status_code': response.status_code, 'headers': dict(response.headers), 'body': response.text[:4000]})
    except Exception as exc: emit(f'HTTP FAILED {url}', {'error': repr(exc), 'traceback': traceback.format_exc()})

headers = {'Authorization': 'Bearer ' + os.getenv('GATEWAY_SERVICE_TOKEN','')}
for path in ('health/','diagnostics/','session/','accounts/','account-summary/','positions/','open-orders/','completed-orders/','executions/','events/'):
    try:
        response = requests.get('http://127.0.0.1:8080/api/v1/' + path, headers=headers, timeout=15)
        try: body = response.json()
        except Exception: body = response.text[:12000]
        if path == 'events/' and isinstance(body, dict) and isinstance(body.get('data'), list) and len(body['data']) > 100:
            body = dict(body); body['data'] = body['data'][-100:]; body.setdefault('meta', {})['collector_truncated_to_last'] = 100
        emit('GATEWAY API ' + path, {'status_code': response.status_code, 'body': body})
    except Exception as exc: emit('GATEWAY API FAILED ' + path, {'error': repr(exc), 'traceback': traceback.format_exc()})
