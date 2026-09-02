"""Generic Linux gamepad input for external Caret Control devices."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import glob
import os
import select
import struct
import threading
import time
from typing import Any

import decky

try:
    import fcntl
except ImportError:  # The unit tests also run on Windows.
    fcntl = None  # type: ignore[assignment]


EV_SYN = 0
EV_KEY = 1
EV_ABS = 3
SYN_REPORT = 0

BTN_TL = 0x136
BTN_TR = 0x137
BTN_TOP2 = 0x124
BTN_PINKIE = 0x125

SHOULDER_BUTTON_PAIRS = (
    (BTN_TL, BTN_TR),
    # Older DirectInput HID descriptors can expose button indices 4 and 5
    # through the legacy joystick button range instead of BTN_TL/BTN_TR.
    (BTN_TOP2, BTN_PINKIE),
)

ABS_Z = 0x02
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05

RIGHT_STICK_AXIS_PAIRS = (
    (ABS_RX, ABS_RY),
    (ABS_Z, ABS_RZ),
    (ABS_Z, ABS_RX),
    (ABS_RX, ABS_RZ),
)

INPUT_EVENT = struct.Struct("@llHHi")
ABS_INFO = struct.Struct("@iiiiii")

REPEAT_DELAY_SECONDS = 0.36
REPEAT_INTERVAL_SECONDS = 0.072
SCAN_INTERVAL_SECONDS = 1.0

VALID_DIRECTIONS = {"left", "right", "up", "down"}


def _ioc_read(request_type: int, number: int, size: int) -> int:
    return (2 << 30) | (size << 16) | (request_type << 8) | number


def _eviocgbit(event_type: int, size: int) -> int:
    return _ioc_read(ord("E"), 0x20 + event_type, size)


def _eviocgabs(axis: int) -> int:
    return _ioc_read(ord("E"), 0x40 + axis, ABS_INFO.size)


def _bit_is_set(bits: bytes | bytearray, code: int) -> bool:
    byte_index = code // 8
    return byte_index < len(bits) and (bits[byte_index] & (1 << (code % 8))) != 0


@dataclass(frozen=True)
class AxisCalibration:
    minimum: int
    maximum: int
    flat: int = 0

    def normalize(self, value: int) -> int:
        center = (self.minimum + self.maximum) / 2
        distance = value - center
        if abs(distance) <= self.flat:
            return 0
        extent = self.maximum - center if distance >= 0 else center - self.minimum
        if extent <= 0:
            return 0
        return round(max(-1.0, min(1.0, distance / extent)) * 32767)


@dataclass
class EvdevGamepad:
    path: str
    fd: int
    name: str
    x_axis: int
    y_axis: int
    x_calibration: AxisCalibration
    y_calibration: AxisCalibration
    left_button: int = BTN_TL
    right_button: int = BTN_TR
    x_value: int = 0
    y_value: int = 0
    left_bumper: bool = False
    right_bumper: bool = False
    last_bumper_direction: str | None = None
    stick_direction: str | None = None
    pending: bytearray = field(default_factory=bytearray)


class EvdevControllerWorker:
    """Reads standard Linux gamepad events without depending on a device brand."""

    def __init__(self, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.event_loop = event_loop
        self.settings: dict[str, Any] = {
            "enabled": True,
            "bumpersEnabled": True,
            "stickEnabled": True,
            "stickDeadzonePercent": 55,
            "repeatEnabled": True,
        }
        self.keyboard_open = False
        self.keyboard_target_ready = False
        self.devices: dict[str, EvdevGamepad] = {}
        self.last_error: str | None = None
        self.last_input = "None"
        self.last_output = "None"
        self.input_events = 0
        self.repeat_path: str | None = None
        self.repeat_kind: str | None = None
        self.repeat_direction: str | None = None
        self.next_repeat_at = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name="caret-control-evdev",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.5)
        with self.lock:
            for device in self.devices.values():
                self._close_fd(device.fd)
            self.devices.clear()

    def configure(
        self,
        settings: dict[str, Any],
        keyboard_open: bool,
        keyboard_target_ready: bool,
    ) -> None:
        with self.lock:
            self.settings.update(settings)
            self.keyboard_open = bool(keyboard_open)
            self.keyboard_target_ready = bool(keyboard_target_ready)
            self._clear_repeat_locked()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "externalControllers": [device.name for device in self.devices.values()],
                "externalControllerPaths": list(self.devices),
                "externalLastInput": self.last_input,
                "externalLastOutput": self.last_output,
                "externalInputEvents": self.input_events,
                "externalError": self.last_error,
            }

    def _run(self) -> None:
        next_scan_at = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= next_scan_at:
                self._refresh_devices()
                next_scan_at = now + SCAN_INTERVAL_SECONDS

            with self.lock:
                devices_by_fd = {device.fd: device for device in self.devices.values()}
            if not devices_by_fd:
                self.stop_event.wait(0.1)
                continue

            try:
                readable, _, _ = select.select(list(devices_by_fd), [], [], 0.03)
            except (OSError, ValueError) as error:
                with self.lock:
                    self.last_error = f"Could not poll external controllers: {error}"
                self.stop_event.wait(0.1)
                continue

            for fd in readable:
                device = devices_by_fd.get(fd)
                if device is not None and not self._read_device(device):
                    self._remove_device(device.path)
            self._handle_repeat()

    def _refresh_devices(self) -> None:
        available = set(glob.glob("/dev/input/event*"))
        with self.lock:
            known = set(self.devices)
        for path in known - available:
            self._remove_device(path)
        for path in sorted(available - known):
            device = self._open_gamepad(path)
            if device is None:
                continue
            with self.lock:
                self.devices[path] = device
                self.last_error = None
            decky.logger.info(
                f"Caret Control external controller: {device.name} on {path} "
                f"(right stick ABS_{device.x_axis}/ABS_{device.y_axis})"
            )

    def _open_gamepad(self, path: str) -> EvdevGamepad | None:
        if fcntl is None:
            return None
        event_name = os.path.basename(path)
        sysfs = f"/sys/class/input/{event_name}/device"
        name = self._read_text(f"{sysfs}/name") or event_name
        vendor = (self._read_text(f"{sysfs}/id/vendor") or "").lower()
        if vendor == "28de" or "steam deck" in name.lower():
            return None

        fd: int | None = None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            key_bits = self._read_bits(fd, EV_KEY, 96)
            abs_bits = self._read_bits(fd, EV_ABS, 8)
            shoulder_buttons = next(
                (
                    pair
                    for pair in SHOULDER_BUTTON_PAIRS
                    if _bit_is_set(key_bits, pair[0]) and _bit_is_set(key_bits, pair[1])
                ),
                None,
            )
            if shoulder_buttons is None:
                self._close_fd(fd)
                return None

            axes = self._choose_right_stick_axes(fd, abs_bits)
            if axes is None:
                self._close_fd(fd)
                return None
            x_axis, y_axis, x_info, y_info, x_value, y_value = axes
            return EvdevGamepad(
                path=path,
                fd=fd,
                name=name,
                x_axis=x_axis,
                y_axis=y_axis,
                x_calibration=x_info,
                y_calibration=y_info,
                left_button=shoulder_buttons[0],
                right_button=shoulder_buttons[1],
                x_value=x_value,
                y_value=y_value,
            )
        except OSError:
            if fd is not None:
                self._close_fd(fd)
            return None

    def _choose_right_stick_axes(
        self,
        fd: int,
        abs_bits: bytes,
    ) -> tuple[int, int, AxisCalibration, AxisCalibration, int, int] | None:
        fallback: tuple[int, int, AxisCalibration, AxisCalibration, int, int] | None = None
        for x_axis, y_axis in RIGHT_STICK_AXIS_PAIRS:
            if not (_bit_is_set(abs_bits, x_axis) and _bit_is_set(abs_bits, y_axis)):
                continue
            x_info, x_value = self._read_abs_info(fd, x_axis)
            y_info, y_value = self._read_abs_info(fd, y_axis)
            candidate = (x_axis, y_axis, x_info, y_info, x_value, y_value)
            if fallback is None:
                fallback = candidate
            if abs(x_info.normalize(x_value)) < 8192 and abs(y_info.normalize(y_value)) < 8192:
                return candidate
        return fallback

    def _read_device(self, device: EvdevGamepad) -> bool:
        try:
            chunk = os.read(device.fd, INPUT_EVENT.size * 32)
        except BlockingIOError:
            return True
        except OSError:
            return False
        if not chunk:
            return False

        with self.lock:
            device.pending.extend(chunk)
            while len(device.pending) >= INPUT_EVENT.size:
                raw = bytes(device.pending[: INPUT_EVENT.size])
                del device.pending[: INPUT_EVENT.size]
                _, _, event_type, code, value = INPUT_EVENT.unpack(raw)
                self._process_event_locked(device, event_type, code, value)
        return True

    def _process_event_locked(
        self,
        device: EvdevGamepad,
        event_type: int,
        code: int,
        value: int,
    ) -> None:
        if event_type == EV_KEY and code in (device.left_button, device.right_button):
            self._process_bumper_locked(device, code, value)
        elif event_type == EV_ABS:
            if code == device.x_axis:
                device.x_value = value
            elif code == device.y_axis:
                device.y_value = value
        elif event_type == EV_SYN and code == SYN_REPORT:
            self._process_stick_locked(device)

    def _process_bumper_locked(self, device: EvdevGamepad, code: int, value: int) -> None:
        if value == 2:
            return
        pressed = value != 0
        if code == device.left_button:
            previous = device.left_bumper
            device.left_bumper = pressed
            direction = "left"
        else:
            previous = device.right_bumper
            device.right_bumper = pressed
            direction = "right"

        if pressed and not previous:
            device.last_bumper_direction = direction
            self._record_input_locked(
                f"{device.name}: {'L/LB' if code == device.left_button else 'R/RB'}"
            )
            if self.settings.get("bumpersEnabled", True) and self._is_active_locked():
                self._tap_locked(direction)
                self._start_repeat_locked(device.path, "bumper", direction)
        elif not pressed:
            if device.last_bumper_direction == "left":
                device.last_bumper_direction = "right" if device.right_bumper else None
            elif device.last_bumper_direction == "right":
                device.last_bumper_direction = "left" if device.left_bumper else None
            self._reconcile_repeat_locked(device)

    def _process_stick_locked(self, device: EvdevGamepad) -> None:
        x = device.x_calibration.normalize(device.x_value)
        # Linux ABS Y axes increase downwards; the Steam keyboard uses positive Y for up.
        y = -device.y_calibration.normalize(device.y_value)
        previous = device.stick_direction
        device.stick_direction = self._read_stick_direction_locked(x, y, previous)
        if device.stick_direction != previous and device.stick_direction is not None:
            direction = device.stick_direction
            self._record_input_locked(f"{device.name}: right stick {direction}")
            if self.settings.get("stickEnabled", True) and self._is_active_locked():
                self._tap_locked(direction)
                self._start_repeat_locked(device.path, "stick", direction)
        elif device.stick_direction != previous:
            self._reconcile_repeat_locked(device)

    def _read_stick_direction_locked(
        self,
        x: int,
        y: int,
        current: str | None,
    ) -> str | None:
        activation = int(
            max(25, min(85, float(self.settings.get("stickDeadzonePercent", 55))))
            / 100
            * 32767
        )
        release = int(activation * 0.72)
        magnitude_squared = x * x + y * y
        threshold = release if current is not None else activation
        if magnitude_squared < threshold * threshold:
            return None
        if abs(x) > abs(y):
            return "left" if x < 0 else "right"
        return "up" if y > 0 else "down"

    def _record_input_locked(self, label: str) -> None:
        self.input_events += 1
        self.last_input = label

    def _start_repeat_locked(self, path: str, kind: str, direction: str) -> None:
        if not self.settings.get("repeatEnabled", True):
            return
        self.repeat_path = path
        self.repeat_kind = kind
        self.repeat_direction = direction
        self.next_repeat_at = time.monotonic() + REPEAT_DELAY_SECONDS

    def _reconcile_repeat_locked(self, device: EvdevGamepad) -> None:
        if self.repeat_path != device.path:
            return
        if self.settings.get("stickEnabled", True) and device.stick_direction is not None:
            next_kind = "stick"
            next_direction = device.stick_direction
        elif (
            self.settings.get("bumpersEnabled", True)
            and device.last_bumper_direction is not None
        ):
            next_kind = "bumper"
            next_direction = device.last_bumper_direction
        else:
            self._clear_repeat_locked()
            return
        if next_kind != self.repeat_kind or next_direction != self.repeat_direction:
            self._start_repeat_locked(device.path, next_kind, next_direction)

    def _handle_repeat(self) -> None:
        with self.lock:
            if (
                self.repeat_path is None
                or self.repeat_direction is None
                or not self.settings.get("repeatEnabled", True)
                or not self._is_active_locked()
            ):
                return
            device = self.devices.get(self.repeat_path)
            if device is None:
                self._clear_repeat_locked()
                return
            now = time.monotonic()
            if now < self.next_repeat_at:
                return
            self._tap_locked(self.repeat_direction)
            self.next_repeat_at = now + REPEAT_INTERVAL_SECONDS

    def _clear_repeat_locked(self) -> None:
        self.repeat_path = None
        self.repeat_kind = None
        self.repeat_direction = None
        self.next_repeat_at = 0.0

    def _is_active_locked(self) -> bool:
        return bool(
            self.settings.get("enabled", True)
            and self.keyboard_open
            and self.keyboard_target_ready
        )

    def _tap_locked(self, direction: str) -> bool:
        if (
            direction not in VALID_DIRECTIONS
            or not self._is_active_locked()
            or self.event_loop is None
            or self.event_loop.is_closed()
        ):
            return False
        try:
            asyncio.run_coroutine_threadsafe(
                decky.emit("caret_direction", direction),
                self.event_loop,
            )
            self.last_output = f"Steam keyboard: {direction}"
            self.last_error = None
            return True
        except Exception as error:
            self.last_error = f"Could not send {direction} to frontend: {error}"
            decky.logger.error(self.last_error)
            return False

    def _remove_device(self, path: str) -> None:
        with self.lock:
            device = self.devices.pop(path, None)
            if self.repeat_path == path:
                self._clear_repeat_locked()
        if device is not None:
            self._close_fd(device.fd)
            decky.logger.info(f"Caret Control external controller disconnected: {device.name}")

    @staticmethod
    def _read_bits(fd: int, event_type: int, size: int) -> bytes:
        if fcntl is None:
            raise OSError("fcntl is unavailable")
        bits = bytearray(size)
        fcntl.ioctl(fd, _eviocgbit(event_type, size), bits, True)
        return bytes(bits)

    @staticmethod
    def _read_abs_info(fd: int, axis: int) -> tuple[AxisCalibration, int]:
        if fcntl is None:
            raise OSError("fcntl is unavailable")
        data = bytearray(ABS_INFO.size)
        fcntl.ioctl(fd, _eviocgabs(axis), data, True)
        value, minimum, maximum, _fuzz, flat, _resolution = ABS_INFO.unpack(data)
        return AxisCalibration(minimum, maximum, max(0, flat)), value

    @staticmethod
    def _read_text(path: str) -> str | None:
        try:
            with open(path, encoding="utf-8") as source:
                return source.read().strip()
        except OSError:
            return None

    @staticmethod
    def _close_fd(fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            pass
