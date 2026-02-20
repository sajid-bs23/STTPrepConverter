import pytest
from app.utils.security import is_safe_url
from app.config import settings

def test_ssrf_blocked_private_ip(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_IPS", False)
    # 127.0.0.1 is loopback
    assert is_safe_url("http://127.0.0.1/callback") is False
    # 192.168.x.x is private
    # Note: socket.gethostbyname might fail in some envs if not connected, 
    # but 127.0.0.1 should work.
    
def test_ssrf_allowed_public_ip(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_IPS", False)
    # Using a common public IP (Google DNS)
    assert is_safe_url("https://8.8.8.8/callback") is True

def test_ssrf_blocked_http(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(settings, "ALLOW_HTTP_CALLBACKS", False)
    assert is_safe_url("http://8.8.8.8/callback") is False

def test_ssrf_allowed_http_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(settings, "ALLOW_HTTP_CALLBACKS", True)
    assert is_safe_url("http://8.8.8.8/callback") is True
