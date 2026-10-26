"""Connect to a caller-validated numeric address, retaining hostname TLS checks.

Policy, DNS validation and response limits belong to the calling worker. This
module imports no application configuration or credentials and never resolves a
second hostname. auto_open=0 prevents an implicit unpinned reconnect.
"""

import http.client
import ipaddress
import socket
import ssl


def connect_pinned(host, address, port=443, *, tls=True, context=None, timeout=5):
    ipaddress.ip_address(address)
    connection = (
        http.client.HTTPSConnection(host, port, timeout=timeout)
        if tls
        else http.client.HTTPConnection(host, port, timeout=timeout)
    )
    connection.auto_open = 0
    sock = socket.create_connection((address, port), timeout=timeout)
    try:
        connection.sock = (
            (context or ssl.create_default_context()).wrap_socket(
                sock, server_hostname=host
            )
            if tls
            else sock
        )
    except BaseException:
        sock.close()
        raise
    return connection
