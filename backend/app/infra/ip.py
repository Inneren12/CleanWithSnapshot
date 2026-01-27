from fastapi import Request


def get_tcp_peer_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
