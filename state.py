"""Send the face its state over UDP (never blocks, even if the face isn't running)."""
import socket

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def set_state(state: str) -> None:
    try:
        _sock.sendto(f"state:{state}".encode(), ("127.0.0.1", 47474))
    except OSError:
        pass
