from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


sys.modules.setdefault(
    "decky",
    types.SimpleNamespace(
        logger=types.SimpleNamespace(
            info=lambda *args: None,
            warning=lambda *args: None,
            error=lambda *args: None,
        )
    ),
)

SPEC = importlib.util.spec_from_file_location(
    "caret_control_backend",
    Path(__file__).resolve().parents[1] / "main.py",
)
assert SPEC is not None and SPEC.loader is not None
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def deck_report() -> bytearray:
    report = bytearray(64)
    report[0] = 1
    report[1] = 0
    report[2] = 9
    return report


def set_s16(report: bytearray, offset: int, value: int) -> None:
    report[offset : offset + 2] = value.to_bytes(2, "little", signed=True)


class ControllerWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = backend.ControllerWorker()
        self.taps: list[str] = []
        self.worker._tap_locked = lambda direction: self.taps.append(direction) or True
        self.worker.configure({"repeatEnabled": False}, True, True)

    def test_bumpers_emit_left_and_right(self) -> None:
        report = deck_report()
        report[8] = backend.L1_MASK
        self.worker._handle_report(bytes(report))

        report[8] = 0
        self.worker._handle_report(bytes(report))
        report[8] = backend.R1_MASK
        self.worker._handle_report(bytes(report))

        self.assertEqual(self.taps, ["left", "right"])
        self.assertEqual(self.worker.last_input, "R1")

    def test_right_stick_emits_all_directions(self) -> None:
        movements = [
            (52, -30000, "left"),
            (52, 30000, "right"),
            (54, 30000, "up"),
            (54, -30000, "down"),
        ]
        for offset, value, _ in movements:
            centered = deck_report()
            self.worker._handle_report(bytes(centered))
            moved = deck_report()
            set_s16(moved, offset, value)
            self.worker._handle_report(bytes(moved))

        self.assertEqual(self.taps, [direction for _, _, direction in movements])

    def test_inactive_mode_observes_but_does_not_emit(self) -> None:
        self.worker.configure({}, False, False)
        report = deck_report()
        report[8] = backend.L1_MASK
        self.worker._handle_report(bytes(report))

        self.assertEqual(self.worker.last_input, "L1")
        self.assertEqual(self.worker.input_events, 1)
        self.assertEqual(self.taps, [])


if __name__ == "__main__":
    unittest.main()
