"""平衡验证：让一个"比较会玩"的机器人跑多局，看能否在任期（48 回合）内达成胜利。

用法：python tools/balance.py [局数]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pwer import ma  # noqa: E402
from pwer.constants import money  # noqa: E402
from pwer.engine import Game  # noqa: E402
from pwer.ma import MaError  # noqa: E402
from pwer.world import CITY_RADIUS, chebyshev  # noqa: E402


def bot(g: Game) -> None:
    me = g.player
    P = g.policy

    # 1) 人力跟上
    need = me.staff_need()
    if me.ops_staff < need and me.cash > 15_000:
        g.hire(me, ops=min(need - me.ops_staff, 6))
    if len(me.projects) > me.eng_teams and me.cash > 40_000:
        g.hire(me, eng=min(len(me.projects) - me.eng_teams, 2))

    # 2) 定价：全成本 +12%，绝不低于可变成本 1.4 倍
    st = me.last_income
    mwh = max(1.0, st.served_mwh)
    unit = st.total_cost * 10_000.0 / mwh if mwh > 1000 else 440.0
    var = st.fuel * 10_000.0 / mwh if st.fuel > 0 else 150.0
    price = min(P.price_cap * 0.97, max(var * 1.40, unit * 1.12, 330.0))
    me.res_price = round(price * 1.02, 1)
    me.ind_price = round(price * 0.97, 1)

    # 3) 扩张：找缺口最大的城市，先变电站再电厂（贴着变电站建，保证连通）
    best_city, best_gap = None, 0.0
    for c in g.world.cities:
        cap = g.city_cap.get(me.idx, {}).get(c.idx, 0.0)
        gap = c.demand_mw * 0.9 - cap
        if gap > best_gap:
            best_city, best_gap = c, gap
    if best_city is not None and len(me.projects) < 3 and me.cash > 30_000:
        subs = [t for t in g.world.iter_tiles()
                if chebyshev(t.x, t.y, best_city.x, best_city.y) <= CITY_RADIUS
                and t.owner == me.idx and t.kind == "substation"]
        if not subs:
            spots = [t for t in g.world.iter_tiles()
                     if chebyshev(t.x, t.y, best_city.x, best_city.y) <= CITY_RADIUS
                     and g.can_build(me, "substation", t.x, t.y)[0]]
            if spots:
                g.build(me, "substation", spots[0].x, spots[0].y)
        else:
            kinds = ("solar", "wind") if me.renewable_share() < P.renewable_quota + 0.03 \
                else ("coal", "gas", "wind", "solar")
            built = False
            for kind in kinds:
                spots = []
                for st_t in subs:
                    for nx, ny in g.world.neighbors4(st_t.x, st_t.y):
                        if g.can_build(me, kind, nx, ny)[0]:
                            spots.append((nx, ny))
                if not spots:
                    continue
                x, y = spots[0]
                if me.cash < g.total_build_cost(me, kind, x, y) * 1.05:
                    continue
                if g.build(me, kind, x, y):
                    built = True
                    break
            if not built:
                for t in g.world.iter_tiles():
                    if chebyshev(t.x, t.y, best_city.x, best_city.y) <= CITY_RADIUS \
                            and g.can_build(me, "line", t.x, t.y)[0] and me.cash > 8_000:
                        g.build(me, "line", t.x, t.y)
                        break

    # 4) 借款补充
    if me.cash < 25_000:
        try:
            g.borrow(me, 30_000)
        except ValueError:
            pass

    # 5) 并购：吃掉股价最便宜的对手，一直到 75% 再合并
    rivals = [c for c in g.listed() if c.idx != me.idx]
    if rivals:
        tgt = min(rivals, key=lambda c: c.price / max(0.01, c.book_per_share()))
        stake = ma.player_stake(g, tgt)
        if stake < 0.76 and me.cash > 35_000 and me.banned_acq_turns == 0:
            qty = tgt.shares * 0.05
            if ma.buy_cost(tgt, qty) < me.cash * 0.5:
                try:
                    ma.buy_shares(g, me.idx, tgt, qty)
                except MaError:
                    pass
        if stake >= 0.51 and tgt.controlled_by != me.idx:
            try:
                ma.take_control(g, tgt)
            except MaError:
                pass
        if stake >= 0.76 and not tgt.delisted:
            try:
                ma.absorb_merge(g, tgt)
            except MaError:
                pass


def run(seed: int) -> tuple[str, int, float, str]:
    g = Game.new_game(seed)
    for _ in range(48):
        if g.game_over:
            break
        bot(g)
        g.end_turn()
    return g.result or "timeout", g.turn, g.player_share(), g.player.name


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    wins = 0
    for i in range(n):
        seed = 2024 + i * 137
        result, turn, share, _ = run(seed)
        ok = result.startswith("victory")
        wins += ok
        print(f"seed {seed:5d}  {result:<18} 第{turn:2d}回合  份额 {share:5.1%}  "
              f"市值 {money(Game.new_game(seed).player.market_cap()) if False else ''}")
    print(f"\n胜率 {wins}/{n}")


if __name__ == "__main__":
    main()
