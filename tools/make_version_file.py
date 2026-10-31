"""生成 PyInstaller 用的 exe 版本资源（build/version_info.txt）。

作用：让 exe 的"属性 → 详细信息"里显示 产品名 / 版本号 / 文件说明，
而不是空白。版本号直接从 pwer/constants.py 读，避免两处不一致。

用法：python tools/make_version_file.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONST = ROOT / "pwer" / "constants.py"
OUT = ROOT / "build" / "version_info.txt"

APP_NAME = "电力公司"
COMPANY = "PowerCompany"
DESCRIPTION = "2D 电力经营 + 证券并购回合制单机小游戏"
COPYRIGHT = "个人业余作品，免费分享"


def read_const(name: str, default: str = "") -> str:
    """从 constants.py 里抓 `NAME = "..."`，不 import（避免拉起 tkinter）。"""
    try:
        text = CONST.read_text(encoding="utf-8")
    except OSError:
        return default
    m = re.search(rf'^{name}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else default


def as_tuple(version: str) -> tuple[int, int, int, int]:
    parts: list[int] = []
    for chunk in version.split(".")[:4]:
        digits = re.sub(r"\D", "", chunk)
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def main() -> int:
    version = read_const("VERSION", "0.0.0")
    build = read_const("BUILD", "")
    nums = as_tuple(version)
    ver_str = ".".join(str(n) for n in nums)

    # 语言 2052（简体中文）+ 代码页 1200 → StringTable 键 "080404B0"
    text = f"""# 自动生成，请勿手改：python tools/make_version_file.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums},
    prodvers={nums},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [
          StringStruct('CompanyName', '{COMPANY}'),
          StringStruct('FileDescription', '{DESCRIPTION}'),
          StringStruct('FileVersion', '{ver_str}'),
          StringStruct('InternalName', '{APP_NAME}'),
          StringStruct('LegalCopyright', '{COPYRIGHT}'),
          StringStruct('OriginalFilename', '{APP_NAME}.exe'),
          StringStruct('ProductName', '{APP_NAME}'),
          StringStruct('ProductVersion', '{ver_str}'),
          StringStruct('Comments', 'BUILD {build}'),
        ],
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])]),
  ],
)
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"已生成 {OUT}（{APP_NAME} v{ver_str} · BUILD {build}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
