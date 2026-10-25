"""《电力公司》启动入口。

    python main.py                 # 启动图形界面（tkinter，无第三方依赖）
    python main.py --seed 2026     # 指定地图/随机种子
    python main.py --selftest      # 无窗口自检（打包后验证 exe 是否完整）
"""
from __future__ import annotations

import os
import sys


def selftest() -> int:
    """不打开窗口，验证引擎与 tkinter 都在打包产物里。

    注意：PyInstaller --windowed 打包后没有控制台，sys.stdout 可能为 None，
    所以结果同时写到 exe 同目录的 selftest.log。
    """
    lines: list[str] = []
    code = 0
    os.environ["PWER_NO_INTRO"] = "1"

    def say(msg: str) -> None:
        lines.append(msg)
        try:
            print(msg)
        except Exception:  # noqa: BLE001
            pass

    say(f"python {sys.version.split()[0]}  frozen={getattr(sys, 'frozen', False)}")
    try:
        import tkinter
        say(f"tkinter ok, Tcl/Tk {tkinter.TkVersion}")
    except Exception as e:  # noqa: BLE001
        say(f"tkinter 缺失：{e}")
        code = 2
    try:
        from pwer import paths
        from pwer.engine import Game
        g = Game.new_game(7)
        for _ in range(5):
            g.end_turn()
        say(f"engine ok: {g.turn_label()}  股价 {g.player.price:.2f}  "
            f"现金 {g.player.cash:,.0f} 万  份额 {g.player_share():.1%}")
        say(f"存档目录：{paths.data_dir()}")
        if code == 0:
            say("引擎自检通过")
    except Exception as e:  # noqa: BLE001
        import traceback
        say(f"引擎自检失败：{e}")
        lines.append(traceback.format_exc())
        code = 3

    # 真正建一次界面：验证 tcl/tk 数据文件是否被完整打包
    if code == 0:
        try:
            from pwer.ui.app import App
            app = App()
            app.update()
            say(f"界面自检通过：窗口 {app.winfo_width()}x{app.winfo_height()}，"
                f"地图 {app.map.canvas.winfo_width()}x{app.map.canvas.winfo_height()}")
            app.destroy()
            say("自检通过")
        except Exception as e:  # noqa: BLE001
            import traceback
            say(f"界面自检失败：{e}")
            lines.append(traceback.format_exc())
            code = 4

    try:
        from pwer import paths
        log = paths.app_dir() / "selftest.log"
        log.write_text("\n".join(lines), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return code


def main() -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    if "--selftest" in sys.argv:
        return selftest()

    from pwer.ui.app import App

    app = App()
    if "--seed" in sys.argv:
        try:
            seed = int(sys.argv[sys.argv.index("--seed") + 1])
            from pwer.engine import Game
            app.game = Game.new_game(seed)
            app.refresh()
        except (IndexError, ValueError):
            pass
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
