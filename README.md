<img src="https://github.com/woovs-cg/CaretControl/blob/main/CaretControl_wide.png" width="960">

Decky Loader plugin for moving the text caret while typing on Steam Deck.

- The **left shoulder button** (L1, LB, or L) moves the caret left.
- The **right shoulder button** (R1, RB, or R) moves the caret right.
- The **right stick** on the active controller moves the caret in all four directions.
- Standard Linux gamepads are supported, including controllers exposed through
  Bluetooth D-input and USB XInput modes.
- Holding a bumper or the stick repeats the movement.
- Input is enabled only while Steam's on-screen keyboard and its text target are active.
- The original L1/R1 and right-stick navigation events are suppressed while caret controls are active, so an arrow key does not gain focus when the caret reaches a text boundary.

## Installation

1. Download a package from [Releases](https://github.com/woovs-cg/CaretControl/releases).
2. In Decky Loader, enable Developer Mode and choose **Install Plugin from ZIP File**.
3. Select `CaretControl-<version>.zip`.
4. Restart Steam once if Decky does not hot-reload the plugin.

## Permissions and implementation

Caret Control reads the built-in Steam Deck controls from its `/dev/hidraw*`
interface and external controllers from Linux `/dev/input/event*` (`evdev`). Both
input paths are normalized to the same caret actions. This is why the plugin
declares Decky's `_root` permission. Caret movement activates Steam's existing
on-screen keyboard arrow keys through the same virtual gamepad button path used
by built-in bindings such as R2 for Enter. Up and down reuse the shifted variants
of the Left/Right arrow tiles. It does not install system packages or create
services. While the Game Mode keyboard is open, it suppresses only the Gamepad UI
events that correspond to enabled caret controls; D-pad and left-stick keyboard
navigation remain available.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
