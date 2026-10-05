#!/usr/bin/env python3
from __future__ import annotations

import os
import select
import signal
import sys
import time
from pathlib import Path


def request_connection(server_pid: int, timeout: float = 5.0) -> None:
    received = False

    def handler(_signum, _frame):
        nonlocal received
        received = True

    signal.signal(signal.SIGUSR2, handler)
    os.kill(server_pid, signal.SIGUSR1)
    deadline = time.monotonic() + timeout
    while not received and time.monotonic() < deadline:
        signal.pause()
    if not received:
        raise TimeoutError("server did not acknowledge connection")


def read_line(fd: int, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    data = bytearray()
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while time.monotonic() < deadline:
        events = poller.poll(max(0, int((deadline - time.monotonic()) * 1000)))
        if not events:
            continue
        chunk = os.read(fd, 1)
        if not chunk:
            time.sleep(0.01)
            continue
        data.extend(chunk)
        if chunk == b"\n":
            return data.decode(errors="replace").rstrip("\n")
    raise TimeoutError("timed out waiting for server response")


def write_all(fd: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        try:
            written += os.write(fd, payload[written:])
        except BlockingIOError:
            time.sleep(0.01)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: ./animate_client <server-pid>", file=sys.stderr)
        return 1
    server_pid = int(argv[1])
    client_pid = os.getpid()
    c2s = Path(f"FIFO_C2S_{client_pid}")
    s2c = Path(f"FIFO_S2C_{client_pid}")

    request_connection(server_pid)

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if c2s.exists() and s2c.exists():
            break
        time.sleep(0.01)
    else:
        raise TimeoutError("server did not create FIFOs")

    fd_read = os.open(s2c, os.O_RDONLY | os.O_NONBLOCK)
    fd_write = os.open(c2s, os.O_WRONLY | os.O_NONBLOCK)
    try:
        for line in sys.stdin:
            command = line.rstrip("\n")
            write_all(fd_write, command.encode() + b"\n")
            if command == "Disconnect":
                break
            print(read_line(fd_read), flush=True)
    finally:
        os.close(fd_read)
        os.close(fd_write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
