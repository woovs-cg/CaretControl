from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_FOLDER = "CaretControl"
REQUIRED_FILES = (
    Path("dist/index.js"),
    Path("main.py"),
    Path("package.json"),
    Path("plugin.json"),
    Path("README.md"),
    Path("LICENSE"),
)


def main() -> None:
    package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    version = package["version"]
    output_dir = PROJECT_ROOT / "release"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"CaretControl-{version}.zip"

    missing = [str(path) for path in REQUIRED_FILES if not (PROJECT_ROOT / path).is_file()]
    if missing:
        raise SystemExit(f"Cannot package plugin; missing files: {', '.join(missing)}")

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative_path in REQUIRED_FILES:
            source = PROJECT_ROOT / relative_path
            archive_name = f"{PLUGIN_FOLDER}/{relative_path.as_posix()}"
            archive.write(source, archive_name)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest().upper()
    print(output_path)
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
