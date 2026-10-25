"""地图、地形、地块与建造权限。

设计意图（对应设计文档"地形与地块系统"）：
格子只承载 4 个属性 —— 地形类型、水系标记、风光系数、矿产资源。
它们只影响三件事：能不能建、建造成本乘数、出力效率。不做潮流/流体模拟。
"限制即乐趣"：没有河流不能造水电，荒漠建不了大型火电，城市附近不能上核电。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .constants import (
    INFRA_SPECS,
    LAND_COST,
    MINE_RESERVE,
    PLANT_SPECS,
    TERRAIN_INFO,
    Terrain,
)

GRID_W = 18
GRID_H = 12
CITY_RADIUS = 2          # 城市供电接入半径（切比雪夫距离）
NUCLEAR_CITY_GAP = 2     # 核电站与城市的最小距离


@dataclass
class Tile:
    x: int
    y: int
    terrain: Terrain
    wind: float = 1.0
    solar: float = 1.0
    coal: float = 0.0        # 剩余可采储量（吨）
    uranium: float = 0.0
    owner: int = -1          # 占用地块的公司下标
    kind: str = ""           # 占用建筑类型键（电源 key / 设施 key）
    ref: int = -1            # 对应对象 id（plant.id / mine.id / project.id）

    @property
    def occupied(self) -> bool:
        return bool(self.kind)

    @property
    def buildable_land(self) -> bool:
        return self.terrain is not Terrain.CITY


@dataclass
class City:
    idx: int
    name: str
    x: int
    y: int
    base_mw: float
    growth: float = 0.012
    demand_mw: float = 0.0
    residential: float = 0.0
    industrial: float = 0.0
    served: dict[int, float] = field(default_factory=dict)   # 公司 -> 实际供电 MW
    share: dict[int, float] = field(default_factory=dict)    # 公司 -> 份额
    outage_mw: float = 0.0

    def refresh_split(self, res_ratio: float) -> None:
        self.residential = self.demand_mw * res_ratio
        self.industrial = self.demand_mw * (1.0 - res_ratio)


def chebyshev(x1: int, y1: int, x2: int, y2: int) -> int:
    return max(abs(x1 - x2), abs(y1 - y2))


class WorldMap:
    def __init__(self, w: int = GRID_W, h: int = GRID_H):
        self.w = w
        self.h = h
        self.tiles: list[list[Tile]] = []
        self.cities: list[City] = []

    # ------------------------------------------------------------ 基础访问
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def tile(self, x: int, y: int) -> Tile:
        return self.tiles[y][x]

    def iter_tiles(self) -> Iterable[Tile]:
        for row in self.tiles:
            yield from row

    def neighbors4(self, x: int, y: int) -> Iterable[tuple[int, int]]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny

    def has_water_adjacent(self, x: int, y: int) -> bool:
        """本格或相邻格是河流/近海 —— 冷却水判定。"""
        t = self.tile(x, y)
        if t.terrain in (Terrain.RIVER, Terrain.COAST):
            return True
        for nx, ny in self.neighbors4(x, y):
            if self.tile(nx, ny).terrain in (Terrain.RIVER, Terrain.COAST):
                return True
        return False

    def near_city(self, x: int, y: int, radius: int) -> bool:
        return any(chebyshev(x, y, c.x, c.y) <= radius for c in self.cities)

    def city_at(self, x: int, y: int) -> Optional[City]:
        for c in self.cities:
            if c.x == x and c.y == y:
                return c
        return None

    # ------------------------------------------------------------ 生成
    @classmethod
    def generate(cls, seed: int = 20240501) -> "WorldMap":
        rng = random.Random(seed)
        wm = cls()
        w, h = wm.w, wm.h
        wm.tiles = [[Tile(x, y, Terrain.PLAIN) for x in range(w)] for y in range(h)]

        # 东侧近海
        for y in range(h):
            for x in range(w - 2, w):
                wm.tiles[y][x].terrain = Terrain.COAST
        # 右上方荒漠
        for y in range(0, 5):
            for x in range(12, w - 2):
                wm.tiles[y][x].terrain = Terrain.DESERT
        # 两片丘陵
        for cx, cy, rad in ((3, 7, 2.4), (11, 10, 2.0), (13, 4, 1.6)):
            for y in range(h):
                for x in range(w):
                    if math.hypot(x - cx, (y - cy) * 1.1) <= rad:
                        if wm.tiles[y][x].terrain is Terrain.PLAIN:
                            wm.tiles[y][x].terrain = Terrain.HILL

        # 一条从内陆流向近海的河
        x, y = 3, 1
        while x < w - 2:
            wm.tiles[y][x].terrain = Terrain.RIVER
            if rng.random() < 0.45 and y > 1:
                y -= 1
                wm.tiles[y][x].terrain = Terrain.RIVER
            elif rng.random() < 0.45 and y < h - 2:
                y += 1
                wm.tiles[y][x].terrain = Terrain.RIVER
            x += 1
            y = max(1, min(h - 2, y))

        # 支流：从干流南下，流经钢城（给内陆工业城市留出冷却水与水电条件）
        x, y = 7, 2
        while y < h - 2:
            wm.tiles[y][x].terrain = Terrain.RIVER
            y += 1
            if rng.random() < 0.28:
                x = max(2, min(w - 2, x + rng.choice((-1, 1))))

        # 四个城市（保证落在陆地平原上）
        city_defs = [
            ("临江", 4, 3, 300.0),
            ("北岭", 9, 2, 420.0),
            ("钢城", 6, 9, 560.0),
            ("滨海", 12, 9, 700.0),
        ]
        for idx, (name, cx, cy, mw) in enumerate(city_defs):
            t = wm.tiles[cy][cx]
            t.terrain = Terrain.PLAIN
            t.wind = t.solar = 1.0
            t.owner = -1
            t.kind = "city"
            c = City(idx, name, cx, cy, mw)
            c.demand_mw = mw
            wm.cities.append(c)

        # 矿脉：煤靠西/南（近老工业），铀靠北/东
        coal_spots = [(6, 5), (3, 8), (8, 10)]
        uranium_spots = [(11, 3), (14, 6), (10, 11)]
        for (mx, my) in coal_spots:
            if wm.tiles[my][mx].kind in ("", "city") and wm.tiles[my][mx].kind != "city":
                wm.tiles[my][mx].coal = MINE_RESERVE["coal_mine"] * (0.8 + 0.4 * rng.random())
        for (mx, my) in uranium_spots:
            if wm.tiles[my][mx].kind == "":
                wm.tiles[my][mx].uranium = MINE_RESERVE["uranium_mine"] * (0.8 + 0.4 * rng.random())

        # 风光系数
        for t in wm.iter_tiles():
            info = TERRAIN_INFO[t.terrain]
            jitter = lambda: 0.82 + 0.42 * rng.random()  # noqa: E731
            t.wind = round(info.wind * jitter(), 2)
            t.solar = round(info.solar * jitter(), 2)

        for c in wm.cities:
            c.refresh_split(0.42)
        return wm

    # ------------------------------------------------------------ 建造权限
    def check_build(self, kind: str, x: int, y: int) -> tuple[bool, str]:
        """返回 (是否可建, 不可建原因)。这里只管"地形/占位"，不管钱和审批。"""
        if not self.in_bounds(x, y):
            return False, "超出地图"
        t = self.tile(x, y)
        if t.terrain is Terrain.CITY:
            return False, "城市地块不可建设"
        if t.occupied:
            return False, "该地块已被占用"

        if kind in PLANT_SPECS:
            spec = PLANT_SPECS[kind]
            if t.terrain not in spec.terrains:
                names = "/".join(TERRAIN_INFO[tt].name for tt in spec.terrains)
                return False, f"{spec.name}只能建在：{names}"
            if spec.water and not self.has_water_adjacent(x, y):
                return False, "缺少冷却水源（需临河或近海）"
            if kind == "hydro" and t.terrain is not Terrain.RIVER:
                return False, "水电站必须建在河流地块"
            if kind == "nuclear":
                if self.near_city(x, y, NUCLEAR_CITY_GAP):
                    return False, f"核电站需距城市 {NUCLEAR_CITY_GAP + 1} 格以上"
                if t.wind < 0:  # 占位，保持分支一致
                    return False, "不可建"
            if kind == "wind" and t.wind < 0.8:
                return False, "该处风资源不足"
            if kind == "solar" and t.solar < 0.8:
                return False, "该处光照资源不足"
            return True, ""

        if kind in INFRA_SPECS:
            if kind == "coal_mine":
                if t.coal <= 0:
                    return False, "此处没有可采煤矿"
                return True, ""
            if kind == "uranium_mine":
                if t.uranium <= 0:
                    return False, "此处没有可采铀矿"
                return True, ""
            if kind == "substation":
                if not self.near_city(x, y, CITY_RADIUS):
                    return False, f"变电站必须建在城市 {CITY_RADIUS} 格内才能接网"
                return True, ""
            if kind == "line":
                return True, ""
        return False, "未知建筑类型"

    # ------------------------------------------------------------ 造价
    def build_cost(self, kind: str, x: int, y: int) -> float:
        t = self.tile(x, y)
        mult = TERRAIN_INFO[t.terrain].cost_mult
        if kind in PLANT_SPECS:
            spec = PLANT_SPECS[kind]
            return spec.capex_per_mw * spec.cap * mult
        if kind in INFRA_SPECS:
            return INFRA_SPECS[kind].capex * mult
        return 0.0

    def land_cost(self, x: int, y: int) -> float:
        t = self.tile(x, y)
        return LAND_COST * TERRAIN_INFO[t.terrain].cost_mult

    def find_tiles(self, kind: str, limit: int = 9999) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for t in self.iter_tiles():
            ok, _ = self.check_build(kind, t.x, t.y)
            if ok:
                out.append((t.x, t.y))
                if len(out) >= limit:
                    break
        return out
