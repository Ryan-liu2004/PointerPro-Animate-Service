#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import os
import queue
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Dict, Optional, Set


MAX_COMMAND = 1024
USERNAME_MAX_LEN = 32
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1
SSIZE_MIN = -(1 << 63)
SSIZE_MAX = (1 << 63) - 1


class AnimateLib:
    def __init__(self) -> None:
        root = Path(__file__).resolve().parent
        self.lib = ctypes.CDLL(str(root / "libanimate_bridge.so"))
        void_p = ctypes.c_void_p
        size_t = ctypes.c_size_t
        ssize_t = ctypes.c_ssize_t

        self.lib.bridge_create_canvas.argtypes = [size_t, size_t, ctypes.c_uint32]
        self.lib.bridge_create_canvas.restype = void_p
        self.lib.bridge_destroy_canvas.argtypes = [void_p]
        self.lib.bridge_destroy_canvas.restype = None

        self.lib.bridge_create_sprite.argtypes = [ctypes.c_char_p]
        self.lib.bridge_create_sprite.restype = void_p
        self.lib.bridge_create_rectangle.argtypes = [
            size_t,
            size_t,
            ctypes.c_uint32,
            ctypes.c_bool,
        ]
        self.lib.bridge_create_rectangle.restype = void_p
        self.lib.bridge_create_circle.argtypes = [
            size_t,
            ctypes.c_uint32,
            ctypes.c_bool,
        ]
        self.lib.bridge_create_circle.restype = void_p
        self.lib.bridge_destroy_sprite.argtypes = [void_p]
        self.lib.bridge_destroy_sprite.restype = ctypes.c_int

        self.lib.bridge_place_sprite.argtypes = [void_p, void_p, ssize_t, ssize_t]
        self.lib.bridge_place_sprite.restype = void_p
        self.lib.bridge_destroy_placement.argtypes = [void_p]
        self.lib.bridge_destroy_placement.restype = None
        for name in (
            "bridge_placement_up",
            "bridge_placement_down",
            "bridge_placement_top",
            "bridge_placement_bottom",
        ):
            func = getattr(self.lib, name)
            func.argtypes = [void_p]
            func.restype = None
        self.lib.bridge_set_animation_params.argtypes = [
            void_p,
            ssize_t,
            ssize_t,
            ssize_t,
            ssize_t,
        ]
        self.lib.bridge_set_animation_params.restype = None
        self.lib.bridge_frame_size_bytes.argtypes = [void_p]
        self.lib.bridge_frame_size_bytes.restype = size_t
        self.lib.bridge_generate_frame.argtypes = [void_p, size_t, size_t, void_p]
        self.lib.bridge_generate_frame.restype = None


ANIMATE = AnimateLib()


@dataclass
class CanvasState:
    width: int
    height: int
    participants: Set[int] = field(default_factory=set)
    placements: list["Resource"] = field(default_factory=list)
    waiters: Set[int] = field(default_factory=set)
    lock: threading.RLock = field(default_factory=threading.RLock)
    canvas_lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class Resource:
    resource_id: int
    owner_client_id: int
    kind: str
    ptr: Optional[int]
    deleted: bool = False
    sprite_ref_count: int = 0
    canvas_state: Optional[CanvasState] = None
    canvas_resource: Optional["Resource"] = None
    sprite_resource: Optional["Resource"] = None
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class ClientData:
    client_id: int
    pid: int
    fd_read: int
    fd_write: int
    c2s_name: str
    s2c_name: str
    username: str = ""
    logged_in: bool = False
    rejected: bool = False
    alive: bool = True
    padding: bytes = b""
    resources: list[Resource] = field(default_factory=list)
    accessible_canvas: list[Resource] = field(default_factory=list)
    ready: Deque[str] = field(default_factory=deque)
    processing: bool = False
    blocked_on_barrier: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class Server:
    def __init__(self, threads: int) -> None:
        self.threads = threads
        self.selector = selectors.DefaultSelector()
        self.executor = None
        self.clients: list[Optional[ClientData]] = [None]
        self.fd_to_client: Dict[int, ClientData] = {}
        self.state_lock = threading.RLock()
        self.new_clients: "queue.Queue[int]" = queue.Queue()
        self.wake_read, self.wake_write = os.pipe()
        os.set_blocking(self.wake_read, False)
        os.set_blocking(self.wake_write, False)
        self.selector.register(self.wake_read, selectors.EVENT_READ, None)
        self.running = True

    def run(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
        self.executor = ThreadPoolExecutor(max_workers=self.threads)
        threading.Thread(target=self.signal_thread, daemon=True).start()
        print(f"Server PID: {os.getpid()}.", flush=True)

        while self.running:
            for key, _mask in self.selector.select(timeout=0.5):
                if key.data is None:
                    self.drain_wake_pipe()
                    self.accept_queued_clients()
                else:
                    self.read_client(key.data)

    def signal_thread(self) -> None:
        while True:
            info = signal.sigwaitinfo({signal.SIGUSR1})
            self.new_clients.put(info.si_pid)
            try:
                os.write(self.wake_write, b"x")
            except BlockingIOError:
                pass

    def drain_wake_pipe(self) -> None:
        while True:
            try:
                if not os.read(self.wake_read, 4096):
                    return
            except BlockingIOError:
                return

    def accept_queued_clients(self) -> None:
        while True:
            try:
                pid = self.new_clients.get_nowait()
            except queue.Empty:
                return
            self.connect_client(pid)

    def connect_client(self, pid: int) -> None:
        c2s = f"FIFO_C2S_{pid}"
        s2c = f"FIFO_S2C_{pid}"
        for name in (c2s, s2c):
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
        try:
            os.mkfifo(c2s, 0o666)
            os.mkfifo(s2c, 0o666)
            os.kill(pid, signal.SIGUSR2)
            fd_read = os.open(c2s, os.O_RDONLY | os.O_NONBLOCK)
            fd_write = os.open(s2c, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            for name in (c2s, s2c):
                try:
                    os.unlink(name)
                except FileNotFoundError:
                    pass
            return

        with self.state_lock:
            client_id = len(self.clients)
            data = ClientData(client_id, pid, fd_read, fd_write, c2s, s2c)
            self.clients.append(data)
            self.fd_to_client[fd_read] = data
        self.selector.register(fd_read, selectors.EVENT_READ, data)

    def read_client(self, data: ClientData) -> None:
        chunks = []
        while True:
            try:
                chunk = os.read(data.fd_read, 4096)
            except BlockingIOError:
                break
            except OSError:
                self.request_client_destroy(data)
                return
            if not chunk:
                self.request_client_destroy(data)
                return
            chunks.append(chunk)
            if len(chunk) < 4096:
                break
        if not chunks:
            return

        with data.lock:
            buffer = data.padding + b"".join(chunks)
            lines = buffer.split(b"\n")
            data.padding = lines.pop()
            if len(data.padding) > MAX_COMMAND:
                data.padding = b""
            for line in lines:
                if not line:
                    continue
                data.ready.append(line.decode(errors="replace"))
            self.schedule_client_locked(data)

    def schedule_client_locked(self, data: ClientData) -> None:
        if not data.alive or data.processing or data.blocked_on_barrier:
            return
        if not data.ready:
            return
        data.processing = True
        assert self.executor is not None
        self.executor.submit(self.process_client, data)

    def process_client(self, data: ClientData) -> None:
        while True:
            with data.lock:
                if not data.alive or data.blocked_on_barrier or not data.ready:
                    data.processing = False
                    return
                command = data.ready.popleft()

            tokens = command.split()
            if not tokens:
                continue

            if data.logged_in or data.rejected:
                response, pending = self.handle_rpc(data, tokens)
                if response is not None:
                    self.write_response(data, response)
                if pending:
                    with data.lock:
                        data.processing = False
                    return
                continue

            keep = self.handle_login(data, tokens)
            if not keep:
                timer = threading.Timer(1.0, self.request_client_destroy, (data,))
                timer.daemon = True
                timer.start()
                with data.lock:
                    data.processing = False
                return

    def write_response(self, data: ClientData, response: str) -> None:
        payload = response.encode() + b"\n"
        written = 0
        while written < len(payload):
            try:
                written += os.write(data.fd_write, payload[written:])
            except BlockingIOError:
                time.sleep(0.001)
            except OSError:
                return

    def handle_login(self, data: ClientData, tokens: list[str]) -> bool:
        if len(tokens) != 2 or tokens[0] != "Login":
            self.write_response(data, "Not logged in")
            return True

        username = tokens[1]
        found = False
        balance = 0
        try:
            with open("users.txt", "r", encoding="utf-8") as users:
                for line in users:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == username:
                        found = True
                        try:
                            balance = int(parts[1])
                        except ValueError:
                            balance = 0
                        break
        except OSError:
            found = False

        with data.lock:
            if found and balance > 0:
                data.logged_in = True
                data.username = username[: USERNAME_MAX_LEN - 1]
                response = str(balance)
            elif found:
                data.rejected = True
                response = "Reject BALANCE"
            else:
                data.rejected = True
                response = "Reject UNAUTHORISED"
        self.write_response(data, response)
        return found and balance > 0

    def handle_rpc(self, data: ClientData, tokens: list[str]) -> tuple[Optional[str], bool]:
        command = tokens[0]
        handlers: Dict[str, Callable[[ClientData, list[str]], str]] = {
            "create_canvas": self.rpc_create_canvas,
            "create_sprite": self.rpc_create_sprite,
            "create_rectangle": self.rpc_create_rectangle,
            "create_circle": self.rpc_create_circle,
            "place_sprite": self.rpc_place_sprite,
            "placement_up": lambda d, t: self.rpc_move_placement(
                d, t, ANIMATE.lib.bridge_placement_up
            ),
            "placement_down": lambda d, t: self.rpc_move_placement(
                d, t, ANIMATE.lib.bridge_placement_down
            ),
            "placement_top": lambda d, t: self.rpc_move_placement(
                d, t, ANIMATE.lib.bridge_placement_top
            ),
            "placement_bottom": lambda d, t: self.rpc_move_placement(
                d, t, ANIMATE.lib.bridge_placement_bottom
            ),
            "set_animation_params": self.rpc_set_animation_params,
            "destroy_canvas": self.rpc_destroy_canvas,
            "destroy_sprite": self.rpc_destroy_sprite,
            "destroy_placement": self.rpc_destroy_placement,
            "generate": self.rpc_generate,
            "share_canvas": self.rpc_share_canvas,
        }
        if command == "Disconnect":
            self.request_client_destroy(data)
            return None, False
        if command == "barrier":
            return self.rpc_barrier(data, tokens)
        handler = handlers.get(command)
        if handler is None:
            return "-1", False
        return handler(data, tokens), False

    def request_client_destroy(self, data: ClientData) -> None:
        with data.lock:
            if not data.alive:
                return
            data.alive = False
            data.blocked_on_barrier = False
        try:
            self.selector.unregister(data.fd_read)
        except Exception:
            pass
        with self.state_lock:
            self.fd_to_client.pop(data.fd_read, None)
        self.cleanup_client_resources(data)
        for fd in (data.fd_read, data.fd_write):
            try:
                os.close(fd)
            except OSError:
                pass
        for name in (data.c2s_name, data.s2c_name):
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
        with data.lock:
            data.ready.clear()
            data.padding = b""

    def parse_u64(self, token: str) -> Optional[int]:
        if not token or token[0] in "+-":
            return None
        if len(token) > 1 and token[0] == "0":
            return None
        if not token.isdigit():
            return None
        value = int(token)
        if value > UINT64_MAX:
            return None
        return value

    def parse_size(self, token: str) -> Optional[int]:
        return self.parse_u64(token)

    def parse_color(self, token: str) -> Optional[int]:
        value = self.parse_u64(token)
        if value is None or value > UINT32_MAX:
            return None
        return value

    def parse_bool(self, token: str) -> Optional[bool]:
        value = self.parse_u64(token)
        if value is None or value > 1:
            return None
        return bool(value)

    def parse_ssize(self, token: str) -> Optional[int]:
        if not token:
            return None
        digits = token[1:] if token[0] in "+-" else token
        if not digits or (len(digits) > 1 and digits[0] == "0"):
            return None
        if not digits.isdigit():
            return None
        value = int(token)
        if value < SSIZE_MIN or value > SSIZE_MAX:
            return None
        return value

    def encode_handle(self, data: ClientData, resource: Resource) -> int:
        return ((data.client_id & UINT32_MAX) << 32) | (resource.resource_id & UINT32_MAX)

    def decode_handle(self, handle: int) -> tuple[int, int]:
        return (handle >> 32) & UINT32_MAX, handle & UINT32_MAX

    def finish_created_resource(self, data: ClientData, resource: Resource) -> str:
        with data.lock:
            resource.resource_id = len(data.resources)
            resource.owner_client_id = data.client_id
            data.resources.append(resource)
            if resource.kind == "Canvas":
                data.accessible_canvas.append(resource)
                assert resource.canvas_state is not None
                with resource.canvas_state.lock:
                    resource.canvas_state.participants.add(data.client_id)
            handle = self.encode_handle(data, resource)
        return f"0 {handle}"

    def find_client(self, client_id: int) -> Optional[ClientData]:
        with self.state_lock:
            if client_id <= 0 or client_id >= len(self.clients):
                return None
            return self.clients[client_id]

    def get_resource_from_handle(self, handle: int, expected_kind: str) -> Optional[Resource]:
        client_id, resource_id = self.decode_handle(handle)
        owner = self.find_client(client_id)
        if owner is None:
            return None
        with owner.lock:
            if resource_id >= len(owner.resources):
                return None
            resource = owner.resources[resource_id]
        with resource.lock:
            if (
                resource.kind != expected_kind
                or resource.resource_id != resource_id
                or resource.deleted
                or not resource.ptr
            ):
                return None
        return resource

    def handle_belongs_to_client(self, handle: int, data: ClientData) -> bool:
        client_id, _resource_id = self.decode_handle(handle)
        return client_id == data.client_id

    def has_canvas_access(self, data: ClientData, canvas_resource: Resource) -> bool:
        with data.lock:
            return canvas_resource in data.accessible_canvas

    def client_is_online(self, client_id: int) -> bool:
        client = self.find_client(client_id)
        if client is None:
            return False
        with client.lock:
            return client.alive and client.logged_in

    def online_participant_count(self, state: CanvasState) -> int:
        return sum(1 for client_id in state.participants if self.client_is_online(client_id))

    def rpc_create_canvas(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 4:
            return "-1"
        height = self.parse_size(tokens[1])
        width = self.parse_size(tokens[2])
        color = self.parse_color(tokens[3])
        if height is None or width is None or color is None:
            return "-2"
        ptr = ANIMATE.lib.bridge_create_canvas(height, width, color)
        if not ptr:
            return "-3"
        state = CanvasState(width=width, height=height)
        return self.finish_created_resource(
            data, Resource(-1, -1, "Canvas", ptr, canvas_state=state)
        )

    def rpc_create_sprite(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 2:
            return "-1"
        ptr = ANIMATE.lib.bridge_create_sprite(tokens[1].encode())
        if not ptr:
            return "-3"
        return self.finish_created_resource(data, Resource(-1, -1, "Sprite", ptr))

    def rpc_create_rectangle(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 5:
            return "-1"
        width = self.parse_size(tokens[1])
        height = self.parse_size(tokens[2])
        color = self.parse_color(tokens[3])
        filled = self.parse_bool(tokens[4])
        if width is None or height is None or color is None or filled is None:
            return "-2"
        ptr = ANIMATE.lib.bridge_create_rectangle(width, height, color, filled)
        if not ptr:
            return "-3"
        return self.finish_created_resource(data, Resource(-1, -1, "Sprite", ptr))

    def rpc_create_circle(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 4:
            return "-1"
        radius = self.parse_size(tokens[1])
        color = self.parse_color(tokens[2])
        filled = self.parse_bool(tokens[3])
        if radius is None or color is None or filled is None:
            return "-2"
        ptr = ANIMATE.lib.bridge_create_circle(radius, color, filled)
        if not ptr:
            return "-3"
        return self.finish_created_resource(data, Resource(-1, -1, "Sprite", ptr))

    def rpc_place_sprite(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 5:
            return "-1"
        canvas_handle = self.parse_u64(tokens[1])
        sprite_handle = self.parse_u64(tokens[2])
        x = self.parse_ssize(tokens[3])
        y = self.parse_ssize(tokens[4])
        if canvas_handle is None or sprite_handle is None or x is None or y is None:
            return "-2"
        canvas_resource = self.get_resource_from_handle(canvas_handle, "Canvas")
        sprite_resource = self.get_resource_from_handle(sprite_handle, "Sprite")
        if (
            canvas_resource is None
            or sprite_resource is None
            or not self.has_canvas_access(data, canvas_resource)
            or not self.handle_belongs_to_client(sprite_handle, data)
        ):
            return "-2"
        assert canvas_resource.canvas_state is not None
        with canvas_resource.canvas_state.canvas_lock:
            ptr = ANIMATE.lib.bridge_place_sprite(canvas_resource.ptr, sprite_resource.ptr, x, y)
        if not ptr:
            return "-3"
        placement_resource = Resource(
            -1,
            -1,
            "Sprite_Placement",
            ptr,
            canvas_resource=canvas_resource,
            sprite_resource=sprite_resource,
        )
        with sprite_resource.lock:
            sprite_resource.sprite_ref_count += 1
        with canvas_resource.canvas_state.lock:
            canvas_resource.canvas_state.placements.append(placement_resource)
        return self.finish_created_resource(data, placement_resource)

    def get_accessible_placement(self, data: ClientData, handle: int) -> Optional[Resource]:
        placement = self.get_resource_from_handle(handle, "Sprite_Placement")
        if placement is None or not self.handle_belongs_to_client(handle, data):
            return None
        return placement

    def rpc_move_placement(
        self,
        data: ClientData,
        tokens: list[str],
        move_func: Callable[[int], None],
    ) -> str:
        if len(tokens) != 2:
            return "-1"
        placement_handle = self.parse_u64(tokens[1])
        if placement_handle is None:
            return "-2"
        placement = self.get_accessible_placement(data, placement_handle)
        if placement is None or placement.canvas_resource is None:
            return "-2"
        state = placement.canvas_resource.canvas_state
        assert state is not None
        with state.canvas_lock:
            move_func(placement.ptr)
        return "0"

    def rpc_set_animation_params(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 6:
            return "-1"
        placement_handle = self.parse_u64(tokens[1])
        values = [self.parse_ssize(token) for token in tokens[2:]]
        if placement_handle is None or any(value is None for value in values):
            return "-2"
        placement = self.get_accessible_placement(data, placement_handle)
        if placement is None or placement.canvas_resource is None:
            return "-2"
        state = placement.canvas_resource.canvas_state
        assert state is not None
        with state.canvas_lock:
            ANIMATE.lib.bridge_set_animation_params(placement.ptr, *values)
        return "0"

    def mark_placement_deleted(self, placement: Resource) -> None:
        with placement.lock:
            ptr = placement.ptr
            placement.ptr = None
            placement.deleted = True
        if ptr:
            ANIMATE.lib.bridge_destroy_placement(ptr)
            if placement.sprite_resource is not None:
                with placement.sprite_resource.lock:
                    if placement.sprite_resource.sprite_ref_count > 0:
                        placement.sprite_resource.sprite_ref_count -= 1

    def destroy_canvas_resource(self, canvas_resource: Resource) -> None:
        state = canvas_resource.canvas_state
        if state is None:
            return
        with state.canvas_lock:
            for placement in list(state.placements):
                self.mark_placement_deleted(placement)
            state.placements.clear()
            with canvas_resource.lock:
                ptr = canvas_resource.ptr
                canvas_resource.ptr = None
                canvas_resource.deleted = True
            if ptr:
                ANIMATE.lib.bridge_destroy_canvas(ptr)

    def rpc_destroy_canvas(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 2:
            return "-1"
        canvas_handle = self.parse_u64(tokens[1])
        if canvas_handle is None:
            return "-2"
        canvas_resource = self.get_resource_from_handle(canvas_handle, "Canvas")
        if canvas_resource is None or not self.has_canvas_access(data, canvas_resource):
            return "-2"
        state = canvas_resource.canvas_state
        assert state is not None
        with state.lock:
            if self.online_participant_count(state) > 1:
                return "-2"
            self.destroy_canvas_resource(canvas_resource)
        return "0"

    def cleanup_sprite_resource(self, sprite_resource: Resource) -> None:
        with sprite_resource.lock:
            if sprite_resource.sprite_ref_count > 0 or sprite_resource.deleted:
                return
            ptr = sprite_resource.ptr
        if ptr and ANIMATE.lib.bridge_destroy_sprite(ptr) == 0:
            with sprite_resource.lock:
                sprite_resource.ptr = None
                sprite_resource.deleted = True

    def rpc_destroy_sprite(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 2:
            return "-1"
        sprite_handle = self.parse_u64(tokens[1])
        if sprite_handle is None:
            return "-2"
        sprite_resource = self.get_resource_from_handle(sprite_handle, "Sprite")
        if sprite_resource is None or not self.handle_belongs_to_client(sprite_handle, data):
            return "-2"
        with sprite_resource.lock:
            if sprite_resource.sprite_ref_count > 0:
                return "0 1"
            ptr = sprite_resource.ptr
        if not ptr:
            return "-2"
        result = ANIMATE.lib.bridge_destroy_sprite(ptr)
        if result == 0:
            with sprite_resource.lock:
                sprite_resource.ptr = None
                sprite_resource.deleted = True
        return f"0 {result}"

    def destroy_placement_resource(self, placement: Resource) -> None:
        canvas_resource = placement.canvas_resource
        state = canvas_resource.canvas_state if canvas_resource else None
        if state is not None:
            with state.lock, state.canvas_lock:
                self.mark_placement_deleted(placement)
                if placement in state.placements:
                    state.placements.remove(placement)
        else:
            self.mark_placement_deleted(placement)

    def rpc_destroy_placement(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 2:
            return "-1"
        placement_handle = self.parse_u64(tokens[1])
        if placement_handle is None:
            return "-2"
        placement = self.get_accessible_placement(data, placement_handle)
        if placement is None:
            return "-2"
        self.destroy_placement_resource(placement)
        return "0"

    def rpc_generate(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 6:
            return "-1"
        canvas_handle = self.parse_u64(tokens[1])
        filename = tokens[2]
        start = self.parse_size(tokens[3])
        end = self.parse_size(tokens[4])
        frame_rate = self.parse_size(tokens[5])
        if (
            canvas_handle is None
            or start is None
            or end is None
            or frame_rate is None
            or frame_rate == 0
            or start > end
            or not filename
        ):
            return "-2"
        canvas_resource = self.get_resource_from_handle(canvas_handle, "Canvas")
        if canvas_resource is None or not self.has_canvas_access(data, canvas_resource):
            return "-2"
        state = canvas_resource.canvas_state
        assert state is not None

        dat_path = f"{filename}.dat"
        mp4_path = f"{filename}.mp4"
        log_path = f"{filename}.log"
        try:
            with state.canvas_lock:
                if not canvas_resource.ptr:
                    return "-2"
                frame_size = ANIMATE.lib.bridge_frame_size_bytes(canvas_resource.ptr)
                with open(dat_path, "wb") as output:
                    for frame in range(start, end + 1):
                        buffer = ctypes.create_string_buffer(frame_size)
                        ANIMATE.lib.bridge_generate_frame(
                            canvas_resource.ptr,
                            frame,
                            frame_rate,
                            buffer,
                        )
                        output.write(buffer.raw)
        except OSError:
            return "0 -1"
        except MemoryError:
            return "-3"

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return "0 0 -1"
        with open(log_path, "wb") as log:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "argb",
                    "-video_size",
                    f"{state.width}x{state.height}",
                    "-framerate",
                    str(frame_rate),
                    "-i",
                    dat_path,
                    mp4_path,
                ],
                stdout=log,
                stderr=log,
                check=False,
            )
        return "0 0 0" if completed.returncode == 0 else "0 0 -1"

    def find_logged_in_client_by_username(self, username: str) -> Optional[ClientData]:
        with self.state_lock:
            clients = list(self.clients)
        for client in clients:
            if client is None:
                continue
            with client.lock:
                if client.alive and client.logged_in and client.username == username:
                    return client
        return None

    def rpc_share_canvas(self, data: ClientData, tokens: list[str]) -> str:
        if len(tokens) != 3:
            return "-1"
        canvas_handle = self.parse_u64(tokens[1])
        username = tokens[2]
        if canvas_handle is None or not username:
            return "-2"
        peer = self.find_logged_in_client_by_username(username)
        canvas_resource = self.get_resource_from_handle(canvas_handle, "Canvas")
        if peer is None or peer is data or canvas_resource is None:
            return "-2"
        state = canvas_resource.canvas_state
        assert state is not None
        with state.lock:
            current_has_access = data.client_id in state.participants
            peer_has_access = peer.client_id in state.participants
            if current_has_access:
                client_to_add = peer
            elif peer_has_access:
                client_to_add = data
            else:
                return "-2"
            state.participants.add(client_to_add.client_id)
        with client_to_add.lock:
            if canvas_resource not in client_to_add.accessible_canvas:
                client_to_add.accessible_canvas.append(canvas_resource)
        return "0"

    def all_online_participants_waiting(self, state: CanvasState) -> bool:
        online = [
            client_id for client_id in state.participants
            if self.client_is_online(client_id)
        ]
        return bool(online) and all(client_id in state.waiters for client_id in online)

    def release_barrier_waiters(self, canvas_resource: Resource) -> None:
        state = canvas_resource.canvas_state
        if state is None:
            return
        with state.lock:
            if not self.all_online_participants_waiting(state):
                return
            released_ids = list(state.waiters)
            state.waiters.clear()
        for client_id in released_ids:
            client = self.find_client(client_id)
            if client is None:
                continue
            should_schedule = False
            with client.lock:
                if client.alive and client.logged_in:
                    client.blocked_on_barrier = False
                    should_schedule = bool(client.ready) and not client.processing
                    if should_schedule:
                        client.processing = True
            self.write_response(client, "0")
            if should_schedule:
                assert self.executor is not None
                self.executor.submit(self.process_client, client)

    def rpc_barrier(self, data: ClientData, tokens: list[str]) -> tuple[Optional[str], bool]:
        if len(tokens) != 2:
            return "-1", False
        canvas_handle = self.parse_u64(tokens[1])
        if canvas_handle is None:
            return "-2", False
        canvas_resource = self.get_resource_from_handle(canvas_handle, "Canvas")
        if canvas_resource is None or not self.has_canvas_access(data, canvas_resource):
            return "-2", False
        state = canvas_resource.canvas_state
        assert state is not None
        with state.lock:
            if data.client_id not in state.participants:
                return "-2", False
            state.waiters.add(data.client_id)
            if not self.all_online_participants_waiting(state):
                with data.lock:
                    data.blocked_on_barrier = True
                return None, True
        self.release_barrier_waiters(canvas_resource)
        return None, False

    def cleanup_client_resources(self, data: ClientData) -> None:
        with data.lock:
            canvases = list(data.accessible_canvas)
            resources = list(data.resources)
        for canvas_resource in canvases:
            self.release_barrier_waiters(canvas_resource)
            state = canvas_resource.canvas_state
            if state is None:
                continue
            with state.lock:
                if self.online_participant_count(state) == 0:
                    self.destroy_canvas_resource(canvas_resource)
        for resource in resources:
            if resource.kind == "Sprite_Placement":
                state = (
                    resource.canvas_resource.canvas_state
                    if resource.canvas_resource is not None
                    else None
                )
                canvas_still_used = False
                if state is not None:
                    with state.lock:
                        canvas_still_used = self.online_participant_count(state) > 0
                if not canvas_still_used:
                    self.destroy_placement_resource(resource)
        for resource in resources:
            if resource.kind == "Sprite":
                self.cleanup_sprite_resource(resource)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("[Server] Usage: ./animate_server <num_threads>", file=sys.stderr)
        return 1
    try:
        threads = int(argv[1])
    except ValueError:
        threads = 0
    if threads <= 0:
        print("[Server] Invalid number of threads", file=sys.stderr)
        return 1

    server = Server(threads)
    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
