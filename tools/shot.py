"""截图冒烟测试：启动界面 → 跑几回合 → 截图 → 退出。

用法：python tools/shot.py [回合数] [输出目录]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["PWER_NO_INTRO"] = "1"

from PIL import ImageGrab  # noqa: E402

from pwer.ui.app import App  # noqa: E402

OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "shots"


def snap(app: App, name: str) -> None:
    app.update_idletasks()
    app.update()
    time.sleep(0.25)
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    OUT.mkdir(exist_ok=True)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path = OUT / name
    img.save(path)
    print("saved", path, img.size)


def main() -> None:
    turns = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    app = App()
    app.update_idletasks()
    app.lift()
    app.focus_force()
    snap(app, "01_start.png")
    for i in range(turns):
        app.end_turn()
        app.update()
        time.sleep(0.3)
        app.update()
    snap(app, "02_after_turns.png")
    # 切到交易所页
    app.nb.select(app.tab_mkt)
    snap(app, "03_market.png")
    app.nb.select(app.tab_fin)
    snap(app, "04_finance.png")
    app.build_mode = None
    app.destroy()


if __name__ == "__main__":
    main()
