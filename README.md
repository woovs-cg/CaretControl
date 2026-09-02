# Caret Control

Decky Loader plugin for moving the text caret while typing on Steam Deck.

- **L1** moves the caret left.
- **R1** moves the caret right.
- The **right stick** moves the caret left, right, up, and down.
- Holding a bumper or the stick repeats the movement.
- Input is enabled only while Steam's on-screen keyboard and its text target are active.
- The original L1/R1 and right-stick navigation events are suppressed while caret controls are active, so an arrow key does not gain focus when the caret reaches a text boundary.

## Build and package

Requirements: Node.js 16.14 or newer and pnpm 9.

```sh
pnpm install
pnpm run build
python scripts/package_plugin.py
```

The compiled frontend is written to `dist/index.js`. The packaging script creates a Decky-compatible ZIP with forward-slash paths in `release/`.

## Installation

1. Build and package the plugin using the commands above.
2. In Decky Loader, enable Developer Mode and choose **Install Plugin from ZIP File**.
3. Select `release/CaretControl-<version>.zip`.
4. Restart Steam once if Decky does not hot-reload the plugin.

## Permissions and implementation

The plugin declares Decky's `_root` permission only to read the Steam Deck's physical controller reports from `/dev/hidraw*`. Caret movement activates Steam's existing on-screen keyboard arrow keys through the same virtual gamepad button path used by built-in bindings such as R2 for Enter. Up and down reuse the shifted variants of the Left/Right arrow tiles. It does not install system packages or create services. While the Game Mode keyboard is open, it suppresses only the Gamepad UI events that correspond to enabled caret controls; D-pad and left-stick keyboard navigation remain available.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
