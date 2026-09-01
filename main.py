"""Decky backend for reading Steam Deck controls and emitting arrow keys."""

from __future__ import annotations

import asyncio
import glob
import os
import select
import threading
import time
from typing import Any

import decky


STEAM_DECK_HID_ID = "0003:000028DE:00001205"
STEAM_DECK_INTERFACE = "/input2"
REPORT_SIZE = 64
REPORT_TYPE_DECK_STATE = 9

L1_MASK = 1 << 3
R1_MASK = 1 << 2
RIGHT_STICK_X_OFFSET = 52
RIGHT_STICK_Y_OFFSET = 54

VALID_DIRECTIONS = {"left", "right", "up", "down"}

REPEAT_DELAY_SECONDS = 0.36
REPEAT_INTERVAL_SECONDS = 0.072

class ControllerWorker:
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
        self.controller_path: str | None = None
        self.last_error: str | None = None
        self.last_input = "None"
        self.last_output = "None"
        self.input_events = 0
        self.input_reports = 0

        self.l1_pressed = False
        self.r1_pressed = False
        self.last_bumper_direction: str | None = None
        self.stick_direction: str | None = None
        self.repeat_direction: str | None = None
        self.next_repeat_at = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name="caret-control-input",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.5)

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
            if not self._is_active_locked():
                self.repeat_direction = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "backendReady": self.thread is not None and self.thread.is_alive(),
                "controllerConnected": self.controller_path is not None,
                "controllerPath": self.controller_path,
                "directInputReady": self.keyboard_target_ready,
                "keyboardDetected": self.keyboard_open,
                "active": self._is_active_locked(),
                "lastInput": self.last_input,
                "lastOutput": self.last_output,
                "inputEvents": self.input_events,
                "inputReports": self.input_reports,
                "error": self.last_error,
            }

    def test_key(self, direction: str) -> bool:
        if direction not in VALID_DIRECTIONS:
            raise ValueError("unknown direction")
        return self._tap(direction)

    def _is_active_locked(self) -> bool:
        return bool(
            self.settings.get("enabled", True)
            and self.keyboard_open
            and self.keyboard_target_ready
        )

    def _run(self) -> None:
        while not self.stop_event.is_set():
            path = self._find_steam_deck_hidraw()
            if path is None:
                with self.lock:
                    self.controller_path = None
                    self.last_error = "Steam Deck raw controller interface not found"
                self.stop_event.wait(1.0)
                continue

            fd: int | None = None
            try:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                with self.lock:
                    self.controller_path = path
                    self.last_error = None
                decky.logger.info(f"Caret Control listening on {path}")
                self._listen(fd)
            except Exception as error:
                with self.lock:
                    self.controller_path = None
                    self.last_error = f"Could not read {path}: {error}"
                decky.logger.warning(self.last_error)
                self.stop_event.wait(0.75)
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _listen(self, fd: int) -> None:
        while not self.stop_event.is_set():
            readable, _, _ = select.select([fd], [], [], 0.03)
            if readable:
                report = os.read(fd, REPORT_SIZE)
                if not report:
                    raise OSError("controller disconnected")
                self._handle_report(report)
            self._handle_repeat()

    @staticmethod
    def _find_steam_deck_hidraw() -> str | None:
        for path in glob.glob("/dev/hidraw*"):
            name = os.path.basename(path)
            uevent_path = f"/sys/class/hidraw/{name}/device/uevent"
            try:
                with open(uevent_path, encoding="utf-8") as uevent_file:
                    properties = dict(
                        line.rstrip().split("=", 1)
                        for line in uevent_file
                        if "=" in line
                    )
                if (
                    properties.get("HID_ID") == STEAM_DECK_HID_ID
                    and properties.get("HID_PHYS", "").endswith(STEAM_DECK_INTERFACE)
                ):
                    return path
            except (OSError, ValueError):
                continue
        return None

    def _handle_report(self, report: bytes) -> None:
        if (
            len(report) != REPORT_SIZE
            or report[0] != 1
            or report[1] != 0
            or report[2] != REPORT_TYPE_DECK_STATE
        ):
            return

        l1 = bool(report[8] & L1_MASK)
        r1 = bool(report[8] & R1_MASK)
        x = int.from_bytes(
            report[RIGHT_STICK_X_OFFSET : RIGHT_STICK_X_OFFSET + 2],
            "little",
            signed=True,
        )
        y = int.from_bytes(
            report[RIGHT_STICK_Y_OFFSET : RIGHT_STICK_Y_OFFSET + 2],
            "little",
            signed=True,
        )

        with self.lock:
            self.input_reports += 1
            previous_l1 = self.l1_pressed
            previous_r1 = self.r1_pressed
            previous_stick = self.stick_direction
            self.l1_pressed = l1
            self.r1_pressed = r1
            self.stick_direction = self._read_stick_direction_locked(x, y, previous_stick)

            if l1 and not previous_l1:
                self._record_input_locked("L1")
                self.last_bumper_direction = "left"
                if self.settings.get("bumpersEnabled", True) and self._is_active_locked():
                    self._tap_locked("left")
            if r1 and not previous_r1:
                self._record_input_locked("R1")
                self.last_bumper_direction = "right"
                if self.settings.get("bumpersEnabled", True) and self._is_active_locked():
                    self._tap_locked("right")

            if not l1 and self.last_bumper_direction == "left":
                self.last_bumper_direction = "right" if r1 else None
            if not r1 and self.last_bumper_direction == "right":
                self.last_bumper_direction = "left" if l1 else None

            if self.stick_direction != previous_stick and self.stick_direction is not None:
                self._record_input_locked(f"Right stick {self.stick_direction}")
                if self.settings.get("stickEnabled", True) and self._is_active_locked():
                    self._tap_locked(self.stick_direction)

            self._refresh_repeat_locked(time.monotonic())

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

        if current == "left" and x < -release:
            return current
        if current == "right" and x > release:
            return current
        if current == "up" and y > release:
            return current
        if current == "down" and y < -release:
            return current
        if max(abs(x), abs(y)) < activation:
            return None
        if abs(x) > abs(y):
            return "left" if x < 0 else "right"
        return "up" if y > 0 else "down"

    def _record_input_locked(self, label: str) -> None:
        self.input_events += 1
        self.last_input = label

    def _refresh_repeat_locked(self, now: float) -> None:
        direction: str | None = None
        if self.settings.get("stickEnabled", True) and self.stick_direction is not None:
            direction = self.stick_direction
        elif self.settings.get("bumpersEnabled", True):
            direction = self.last_bumper_direction

        if not self._is_active_locked() or not self.settings.get("repeatEnabled", True):
            direction = None

        if direction != self.repeat_direction:
            self.repeat_direction = direction
            self.next_repeat_at = now + REPEAT_DELAY_SECONDS

    def _handle_repeat(self) -> None:
        with self.lock:
            now = time.monotonic()
            if self.repeat_direction is None or now < self.next_repeat_at:
                return
            self._tap_locked(self.repeat_direction)
            self.next_repeat_at = now + REPEAT_INTERVAL_SECONDS

    def _tap_locked(self, direction: str) -> bool:
        if not self._is_active_locked() or self.event_loop is None or self.event_loop.is_closed():
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

    def _tap(self, direction: str) -> bool:
        with self.lock:
            return self._tap_locked(direction)


class Plugin:
    worker: ControllerWorker | None = None

    async def _main(self) -> None:
        self.worker = ControllerWorker(asyncio.get_running_loop())
        self.worker.start()
        decky.logger.info("Caret Control backend loaded")

    async def _unload(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        decky.logger.info("Caret Control backend unloaded")

    async def configure(
        self,
        settings: dict[str, Any],
        keyboard_open: bool,
        keyboard_target_ready: bool,
    ) -> dict[str, Any]:
        if self.worker is None:
            return {"backendReady": False, "error": "Backend has not started"}
        self.worker.configure(settings, keyboard_open, keyboard_target_ready)
        return self.worker.status()

    async def get_status(self) -> dict[str, Any]:
        if self.worker is None:
            return {"backendReady": False, "error": "Backend has not started"}
        return self.worker.status()

    async def test_key(self, direction: str) -> bool:
        if self.worker is None:
            return False
        return self.worker.test_key(direction)
