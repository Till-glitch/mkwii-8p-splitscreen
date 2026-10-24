"""Verify the precompiled Bluepad ABI and reject hidden global-library patches.

Runs in PlatformIO/SCons. The regular config uses a project-local PlatformIO core.
SS8_BTSTACK_ARCHIVE may select a separate pristine archive for cache-only builds;
its bytes must still match the pinned upstream library exactly.
"""

import hashlib
import json
import os
from pathlib import Path

Import("env")

FRAMEWORK_COMMIT = "e010351b2cafe3a872f18878cb2d3e08f167c650"
EXPECTED = {
    "libbluepad32.a": "21515f20403bea71f6dec720236b5dcf2d24321c",
    "libbluepad32_arduino.a": "e159aa1f8f63598824074c520a92cfa0729c57ad",
    "libbluepad32_arduino_bootstrap.a": "189861531ef3a28801f71dfc3eea14d4c9e433f4",
    "libbtstack.a": "da9e62629786700d5fd03fd5b61ed49cf8638499",
}


def blob_hash(path):
    content = path.read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


framework = Path(env.PioPlatform().get_package_dir("framework-arduinoespressif32"))
library_dir = framework / "tools" / "sdk" / "esp32" / "lib"
verified = {}
for name, expected in EXPECTED.items():
    path = library_dir / name
    override = os.environ.get("SS8_BTSTACK_ARCHIVE") if name == "libbtstack.a" else None
    if override:
        path = Path(override).resolve()
        if path.name != "libbtstack.a":
            raise RuntimeError("SS8_BTSTACK_ARCHIVE must name a pristine libbtstack.a")
        env.Prepend(LIBPATH=[str(path.parent)])
    actual = blob_hash(path)
    if actual != expected:
        raise RuntimeError(
            f"{name} differs from pinned framework {FRAMEWORK_COMMIT}: {actual}. "
            "Use the project's .pio/core and unmodified pinned framework. "
            "Controller connection resources are configured in source, not by patching archives."
        )
    verified[name] = actual

build_dir = Path(env.subst("$BUILD_DIR"))
build_dir.mkdir(parents=True, exist_ok=True)
(build_dir / "framework-manifest.json").write_text(
    json.dumps({"framework_commit": FRAMEWORK_COMMIT, "git_blob_sha1": verified}, indent=2) + "\n",
    encoding="utf-8",
)
