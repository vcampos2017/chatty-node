"""
Chatty's face for the Pi screen (pygame).

Listens on UDP 127.0.0.1:47474 for small text messages from the voice node:
    state:idle | listening | thinking | speaking | puzzled | sleepy
    level:0.0-1.0        (mouth openness while speaking)

Runs at 30 fps while something is moving and ~8 fps when idle, so it stays
light on the Pi. Press Esc or Q to quit. Use --windowed for a desktop window.
"""
from __future__ import annotations

import os
import socket
import sys
import time

import pygame

sys.path.insert(0, os.path.dirname(__file__))
from face_model import FaceModel  # noqa: E402

FACE_PORT = int(os.getenv("CHATTY_FACE_PORT", "47474"))
FAST_FPS = 30
SLOW_FPS = 8


class PygameCanvas:
    """The small drawing interface face_model expects, backed by pygame."""

    def __init__(self, surface):
        self.s = surface
        self._fonts = {}

    def fill(self, color):
        self.s.fill(color)

    def rrect(self, color, rect, radius):
        pygame.draw.rect(self.s, color, pygame.Rect(*map(round, rect)), border_radius=max(0, round(radius)))

    def ellipse(self, color, rect, width=0):
        pygame.draw.ellipse(self.s, color, pygame.Rect(*map(round, rect)), width)

    def arc(self, color, rect, start, stop, width):
        pygame.draw.arc(self.s, color, pygame.Rect(*map(round, rect)), start, stop, width)

    def line(self, color, p1, p2, width):
        pygame.draw.line(self.s, color, p1, p2, width)
        # round the ends so thick lines look soft
        r = width / 2
        for p in (p1, p2):
            pygame.draw.circle(self.s, color, (round(p[0]), round(p[1])), r)

    def text(self, txt, pos, size, color):
        font = self._fonts.get(size)
        if font is None:
            font = self._fonts[size] = pygame.font.Font(None, size)
        self.s.blit(font.render(txt, True, color), pos)


def open_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", FACE_PORT))
    sock.setblocking(False)
    return sock


def read_messages(sock, face: FaceModel):
    while True:
        try:
            data, _ = sock.recvfrom(256)
        except BlockingIOError:
            return
        except OSError:
            return
        for line in data.decode("utf-8", "ignore").splitlines():
            key, _, value = line.strip().partition(":")
            if key == "state":
                face.set_state(value.strip().lower())
            elif key == "level":
                try:
                    face.set_level(float(value))
                except ValueError:
                    pass


def main():
    windowed = "--windowed" in sys.argv
    pygame.display.init()
    pygame.font.init()
    if windowed:
        screen = pygame.display.set_mode((800, 480))
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("Chatty")

    w, h = screen.get_size()
    face = FaceModel(w, h)
    canvas = PygameCanvas(screen)
    sock = open_socket()
    clock = pygame.time.Clock()
    print(f"Chatty face running at {w}x{h}, listening on UDP {FACE_PORT}", flush=True)

    last = time.time()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                return

        read_messages(sock, face)
        now = time.time()
        face.update(now - last, now)
        last = now
        face.draw(canvas, now)
        pygame.display.flip()
        clock.tick(FAST_FPS if face.busy() else SLOW_FPS)


if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.quit()
