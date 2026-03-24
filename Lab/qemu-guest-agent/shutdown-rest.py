#!/usr/bin/env python3
"""Shut down RouterOS via REST API."""
import urllib.request, base64, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9195
url = f'http://localhost:{port}/rest/system/shutdown'
req = urllib.request.Request(url, method='POST', data=b'{}')
req.add_header('Authorization', 'Basic ' + base64.b64encode(b'admin:').decode())
req.add_header('Content-Type', 'application/json')
try:
    r = urllib.request.urlopen(req, timeout=5)
    print(f'Shutdown response: {r.status} {r.read().decode()}')
except Exception as e:
    print(f'Shutdown request: {e}')
    print('(This is expected - the connection will be dropped during shutdown)')
