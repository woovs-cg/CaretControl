from __future__ import annotations

import sys
from pathlib import Path
import types
import unittest


sys.modules.setdefault(
    "decky",
    types.SimpleNamespace(
        emit=lambda *args: None,
        logger=types.SimpleNamespace(
            info=lambda *args: None,
            warning=lambda *args: None,
            error=lambda *args: None,
        ),
    ),
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evdev_input as evdev


def gamepad(
    left_button: int = evdev.BTN_TL,
    right_button: int = evdev.BTN_TR,
) -> evdev.EvdevGamepad:
    calibration = evdev.AxisCalibration(-32768, 32767)
    return evdev.EvdevGamepad(
        path="/dev/input/event-test",
        fd=-1,
        name="8BitDo test controller",
        x_axis=evdev.ABS_RX,
        y_axis=evdev.ABS_RY,
        x_calibration=calibration,
        y_calibration=calibration,
        left_button=left_button,
        right_button=right_button,
    )


class AxisCalibrationTests(unittest.TestCase):
    def test_signed_axis_is_normalized(self) -> None:
        calibration = evdev.AxisCalibration(-32768, 32767)

        self.assertLessEqual(calibration.normalize(-32768), -32766)
        self.assertEqual(calibration.normalize(0), 0)
        self.assertGreaterEqual(calibration.normalize(32767), 32766)


class EvdevControllerWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = evdev.EvdevControllerWorker()
        self.taps: list[str] = []
        self.worker._tap_locked = lambda direction: self.taps.append(direction) or True
        self.worker.configure({"repeatEnabled": False}, True, True)

    def test_standard_shoulders_emit_left_and_right(self) -> None:
        device = gamepad()

        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TL, 1)
        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TL, 0)
        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TR, 1)

        self.assertEqual(self.taps, ["left", "right"])

    def test_legacy_directinput_shoulders_emit_left_and_right(self) -> None:
        device = gamepad(evdev.BTN_TOP2, evdev.BTN_PINKIE)

        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TOP2, 1)
        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TOP2, 0)
        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_PINKIE, 1)

        self.assertEqual(self.taps, ["left", "right"])

    def test_right_stick_emits_all_directions(self) -> None:
        device = gamepad()
        movements = [
            (evdev.ABS_RX, -30000, "left"),
            (evdev.ABS_RX, 30000, "right"),
            (evdev.ABS_RY, -30000, "up"),
            (evdev.ABS_RY, 30000, "down"),
        ]
        for axis, value, _direction in movements:
            self.worker._process_event_locked(device, evdev.EV_ABS, axis, 0)
            other_axis = evdev.ABS_RY if axis == evdev.ABS_RX else evdev.ABS_RX
            self.worker._process_event_locked(device, evdev.EV_ABS, other_axis, 0)
            self.worker._process_event_locked(device, evdev.EV_SYN, evdev.SYN_REPORT, 0)
            self.worker._process_event_locked(device, evdev.EV_ABS, axis, value)
            self.worker._process_event_locked(device, evdev.EV_SYN, evdev.SYN_REPORT, 0)

        self.assertEqual(self.taps, [direction for _, _, direction in movements])

    def test_inactive_keyboard_observes_without_emitting(self) -> None:
        self.worker.configure({}, False, False)
        device = gamepad()

        self.worker._process_event_locked(device, evdev.EV_KEY, evdev.BTN_TL, 1)

        self.assertIn("8BitDo", self.worker.last_input)
        self.assertEqual(self.taps, [])


if __name__ == "__main__":
    unittest.main()
