import ipaddress
import socket
from urllib.parse import urlparse
from app.config import settings
from app.utils.logging import logger

def is_safe_url(url: str) -> bool:
    """
    Validates if a URL is safe for outgoing requests (SSRF protection).
    Rejects private, loopback, and link-local addresses unless explicitly allowed.
    """
    logger.debug("ssrf_check_start", url=url, allow_private=settings.ALLOW_PRIVATE_IPS, allow_http=settings.ALLOW_HTTP_CALLBACKS)
    if settings.ALLOW_PRIVATE_IPS:
        return True

    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            return False
        
        if not settings.ALLOW_HTTP_CALLBACKS and parsed_url.scheme == "http":
            logger.warning("ssrf_blocked_http", url=url)
            return False

        hostname = parsed_url.hostname
        if not hostname:
            return False

        # Resolve hostname to IP
        ip_address = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_address)

        if ip.is_private or ip.is_loopback or ip.is_link_local:
            logger.warning("ssrf_blocked_private_ip", url=url, ip=ip_address)
            return False
        
        return True
    except Exception as e:
        logger.error("ssrf_check_failed", url=url, error=str(e))
        return False
