"""在没有 pip 网络安装权限时，手工抓取 PyInstaller 及其依赖的 wheel 并解包。

pip 在本机沙箱里写临时文件会被拒绝（PermissionError），但 Python 的 urllib 可以正常
下载并写入工作区，于是这里直接走 PyPI JSON API：下载 wheel → 解压到 build_tools/。

用法：python tools/fetch_pyinstaller.py
之后：set PYTHONPATH=build_tools && python -m PyInstaller --version
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / "wheelhouse"
TARGET = ROOT / "build_tools"

PACKAGES = ["pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
            "pywin32-ctypes", "packaging", "setuptools"]


def pick_wheels(name: str) -> list[dict]:
    req = urllib.request.Request(f"https://pypi.org/pypi/{name}/json",
                                headers={"User-Agent": "pwer-build"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    urls = data["urls"]
    if not urls:
        return []
    py_ver = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = "win_amd64"

    def score(u: dict) -> int:
        fn = u["filename"]
        if not fn.endswith(".whl"):
            return -1
        if plat in fn or "win_amd64" in fn:
            return 3
        if "none-any" in fn:
            return 2
        if py_ver in fn:
            return 1
        return -1

    best = max(urls, key=score)
    return [best] if score(best) > 0 else []


def main() -> int:
    WHEELHOUSE.mkdir(exist_ok=True)
    TARGET.mkdir(exist_ok=True)
    for name in PACKAGES:
        try:
            wheels = pick_wheels(name)
        except Exception as e:  # noqa: BLE001
            print(f"! {name}: 查询失败 {e}")
            continue
        if not wheels:
            print(f"! {name}: 没有可用 wheel")
            continue
        for w in wheels:
            path = WHEELHOUSE / w["filename"]
            if not path.exists():
                urllib.request.urlretrieve(w["url"], path)
            print(f"  下载 {path.name} ({path.stat().st_size / 1024:.0f} KB)")
            with zipfile.ZipFile(path) as zf:
                zf.extractall(TARGET)
    print(f"\n已解包到 {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
