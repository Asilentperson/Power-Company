"""生成展示用截图：用无头自动玩家推进若干回合，再截界面。

用法：python tools/demo_shot.py [回合数]
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
from tools.sim import auto_play_player  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


def snap(app: App, name: str) -> None:
    app.update_idletasks()
    app.update()
    time.sleep(0.35)
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    OUT.mkdir(exist_ok=True)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(OUT / name)
    print("saved", OUT / name)


def main() -> None:
    turns = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    app = App()
    app.update()
    app.lift()
    app.focus_force()
    for _ in range(turns):
        auto_play_player(app.game)
        app.end_turn()
        app.update()
    # 让玩家持有一些对手股票，展示股权列
    from pwer import ma
    tgt = min([c for c in app.game.listed() if c.idx != app.game.player_idx],
              key=lambda c: c.market_cap())
    try:
        ma.buy_shares(app.game, app.game.player_idx, tgt, tgt.shares * 0.08)
    except Exception:  # noqa: BLE001
        pass
    app.refresh()
    snap(app, "10_ops.png")
    app.toggle_panel("company"); app.show_company_tab("fin")
    snap(app, "11_finance.png")
    app.toggle_panel("stock")
    app.tv_mkt.selection_set(str(tgt.idx))
    app.refresh_mkt_controls()
    snap(app, "12_market.png")
    app.toggle_panel("policy")
    snap(app, "13_log.png")
    g = app.game
    print(f"回合 {g.turn} 现金 {g.player.cash:,.0f} 份额 {g.player_share():.2%} "
          f"股价 {g.player.price:.2f}")
    app.destroy()


if __name__ == "__main__":
    main()
