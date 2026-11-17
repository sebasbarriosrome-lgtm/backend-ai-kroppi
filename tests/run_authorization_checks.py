"""Run backend tests with synthetic settings and real HTTP transports disabled."""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
os.environ.update(
    SUPABASE_URL='https://authorization-test.example.invalid',
    SUPABASE_SERVICE_ROLE_KEY='synthetic-service-key',
    SUPABASE_JWT_SECRET='synthetic-signing-secret-for-tests-only',
    GEMINI_API_KEY='', WOMPI_PRIVATE_KEY='', WOMPI_EVENTS_SECRET='',
    WOMPI_INTEGRITY_SECRET='', WOMPI_PUBLIC_KEY='',
    PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
)
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
import httpx
import urllib.request

def blocked(*args, **kwargs):
    raise AssertionError('External network requests are disabled in authorization tests.')

async def blocked_async(*args, **kwargs):
    return blocked()

httpx.HTTPTransport.handle_request = blocked
httpx.AsyncHTTPTransport.handle_async_request = blocked_async
urllib.request.urlopen = blocked

import pytest
raise SystemExit(pytest.main(sys.argv[1:] + ['-p', 'no:cacheprovider']))
