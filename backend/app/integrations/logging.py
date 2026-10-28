"""Uvicorn otherwise records the OAuth callback's authorization code in its query string."""

import logging
import re

CALLBACK_PATH = "/api/v1/integrations/gmail/oauth/callback"


class OAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.split("?", 1)[0]
                if isinstance(arg, str) and CALLBACK_PATH in arg
                else arg
                for arg in record.args
            )
        return True


def install_oauth_log_filter():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthAccessLogFilter) for item in logger.filters):
        logger.addFilter(OAuthAccessLogFilter())


class ProviderURLLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'https://(?:gmail.googleapis.com|api.apify.com|api.apollo.io)/[^\s"]+',
                            '[provider-url-redacted]', record.getMessage())
        record.args = ()
        return True


def install_provider_log_filter():
    for name in ("httpx", "httpcore", "httpcore.http11"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, ProviderURLLogFilter) for item in logger.filters):
            logger.addFilter(ProviderURLLogFilter())
