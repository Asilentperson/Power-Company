# 03 · 研发模块（第四份数据契约）

> 状态：**设计契约 v1.0（全新，未实现）**
> 依赖：`company`（现金/工程池）、`constants`（型号数值）、`events`（研发修正）
> 上游：`pwer/engine.py`（新增 R 步）、`pwer/ai.py`（新增第 6 子步）、`pwer/ma.py`（收购继承）
> 本文定义：概率规则、成功率公式、8 个研发项目数值、状态机、人力双配额、AI 同规则、收购继承、配置 Schema、验收。

---

## 0. 五条设计原则（不可妥协）

1. **研究没有进度，只有时间累积提升概率**——UI 永远不出现进度条。
2. **立项即锁定现金与人力**——每回合刚性扣钱，失败不退。
3. **概率平缓递增且有硬上限**——高难度型号永远有失败可能（核电上限 14%）。
4. **撤项不归零**——技术积累（累计时长）在，人不在。
5. **配套条件是概率 buff，不是硬锁**——条件不满足也能硬研发，只是概率极低。

---

## 1. 七条核心规则

| # | 规则 | 落地 |
|---|---|---|
| R1 | 立项即锁定：固定每回合现金消耗 + 研发人力占用；无固定完成回合数，只有基础成功率 | `ResearchProject.state = RUNNING` 时每回合扣 `cash_cost_per_round` 与 `manpower_cost` |
| R2 | 每回合判定：`实际成功率 = 基础 + 时长加成 + 条件加成 − 风险修正`，封顶全局上限；成功解锁，失败累计时长 +1 | §2 公式 + §6 结算 |
| R3 | 时长加成线性递增有上限；全局硬上限保证高难度永远有失败率 | `min(累计回合×每回合增益, 最大时长加成)` + `min(global_max_rate, 0.65)` |
| R4 | 撤项沉没成本：经费不返还，累计时长保留；重启继承断点 | `accumulated_rounds` / `best_accumulated_rounds` 分离 |
| R5 | 配套条件是概率 buff：有同类低阶建筑/自有矿/高等级电网加成功率，不满足也能硬研发 | §3 `condition_list` |
| R6 | 人力双配额：工程总池拆【基建配额】+【研发配额】，回合开始锁定 | §5 |
| R7 | AI 同规则：同公式、同继承、按策略选方向；现金紧张暂停；长期失败烧亏现金流 | §9 |

---

## 2. 成功率公式（唯一实现，禁止第二份）

```python
dur_bonus  = min(accumulated_rounds * per_round_gain, max_duration_bonus)
cond_bonus = min(sum(c.bonus for c in conditions if c.satisfied), max_condition_bonus)
p_raw      = base_success_rate + dur_bonus + cond_bonus + modifier.flat_bonus
p          = clamp(p_raw, 0.01, min(global_max_rate, GLOBAL_RESEARCH_CAP))
if modifier.force_fail and (research_def.tags & modifier.tags_affected):
    p = 0.0
```

| 符号 | 含义 | 默认 |
|---|---|---|
| `base_success_rate` | 建筑固有难度决定的初始成功率 | 每项目配置 |
| `per_round_gain` | 每失败一回合的概率增益 | 0.008~0.030 |
| `max_duration_bonus` | 时长加成上限 | 0.08~0.26 |
| `max_condition_bonus` | 条件加成合计上限（全局） | **0.06** |
| `global_max_rate` | 单项目硬上限 | 0.14~0.60 |
| `GLOBAL_RESEARCH_CAP` | 全模块硬上限 | **0.65** |
| `modifier.flat_bonus` | 事件/政策的外部修正（可负） | 0 |
| `modifier.force_fail` | 强制失败（如"研发事故"） | False |

**判定顺序**（每一步都不可交换）：

```
立项（UI，阶段 2）→ 本回合 R 步：扣现金 → 扣人力 → 用"当前累计时长"算 p → roll
  ├─ 成功：state = UNLOCKED，target 加入 Company.unlocked，项目不再扣费
  └─ 失败：accumulated_rounds += 1，state 保持 RUNNING，继续扣费
```

> **关键语义**：`accumulated_rounds` 表示"已经失败了几回合"，因此**首回合按基础成功率判定**，
> 第 2 回合才吃到第 1 次时长加成。UI 上的"累计 5 回合（+12.5%）"= 5 次失败换来的加成。

**上限校验（配置加载时强制断言）**：

```
assert base + max_duration_bonus <= global_max_rate <= GLOBAL_RESEARCH_CAP
```

不满足直接抛异常——防止"上限形同虚设"。

---

## 3. 八个研发项目（数值表）

`cash` 单位万元/回合，`teams` 为研发人力占用。

| key | 名称 | 解锁型号 | 容量 | base | 每回合增益 | 时长上限 | 硬上限 | 现金/回合 | 人力 | 达顶回合* |
|---|---|---|---|---|---|---|---|---|---|---|
| `usc_coal` | 超临界燃煤 | `usc_coal` | 600MW | 0.18 | 0.025 | 0.22 | 0.50 | 1800 | 2 | 9 |
| `fclass_gas` | F 级燃气调峰 | `fclass_gas` | 400MW | 0.20 | 0.030 | 0.25 | 0.55 | 1400 | 2 | 9 |
| `dam_hydro` | 大型坝式水电 | `dam_hydro` | 1000MW | 0.12 | 0.020 | 0.20 | 0.38 | 2400 | 3 | 10 |
| `pwr1000` | 百万千瓦压水堆 | `pwr1000` | 1000MW | 0.03 | 0.008 | 0.08 | **0.14** | 5200 | 5 | 10 |
| `offshore_wind` | 海上风电 | `offshore_wind` | 500MW | 0.10 | 0.018 | 0.18 | 0.34 | 2600 | 3 | 10 |
| `big_solar` | 大型光伏 | `big_solar` | 300MW | 0.22 | 0.030 | 0.26 | 0.60 | 1200 | 2 | 9 |
| `bess` | 电化学储能 | `bess` | 200MW | 0.16 | 0.028 | 0.24 | 0.48 | 1500 | 2 | 9 |
| `uhv_sub` | 特高压变电站 | `uhv_sub` | 接口 +600MW | 0.08 | 0.015 | 0.16 | 0.30 | 3000 | 4 | 11 |

\* 达顶回合 = `ceil(max_duration_bonus / per_round_gain)`，到顶后概率不再增长。

**配套条件（`condition_list`）**

| 项目 | 条件与加成 |
|---|---|
| `usc_coal` | 有在运燃煤 +0.03；自有煤矿 +0.03；公司接口容量 ≥ 600MW +0.02 |
| `fclass_gas` | 有在运燃气 +0.03；应急组 ≥ 1 +0.02；接口容量 ≥ 300MW +0.02 |
| `dam_hydro` | 有在运水电 +0.03；地图河流格 ≥ 6 +0.02 |
| `pwr1000` | 有在运核电 +0.02；自有铀矿 +0.01；核电已核准 +0.01 |
| `offshore_wind` | 有在运风电 +0.02；近海格 ≥ 4 +0.02；接口容量 ≥ 800MW +0.02 |
| `big_solar` | 有在运光伏 +0.03；荒漠格 ≥ 5 +0.02；储能已解锁 +0.01 |
| `bess` | 新能源在运 ≥ 300MW +0.02；应急组 ≥ 2 +0.02 |
| `uhv_sub` | 变电站 ≥ 4 +0.03；接口容量 ≥ 600MW +0.03 |

条件合计被 `max_condition_bonus = 0.06` 截断（上表多项叠加时按配置顺序累加后截断）。

**解锁后的型号数值**（`PLANT_SPECS` 扩展，单位同 `constants.py`）

| 型号 | 容量 | 造价万/MW | 固定万/MW/季 | 可变元/MWh | 碳 t/MWh | 工期 | CF | 班组 | 工程队 |
|---|---|---|---|---|---|---|---|---|---|
| `usc_coal` | 600 | 290 | 6.8 | 205 | 0.78 | 2 | 0.82 | 12 | 3 |
| `fclass_gas` | 400 | 175 | 4.6 | 340 | 0.35 | 1 | 0.70 | 8 | 2 |
| `dam_hydro` | 1000 | 620 | 6.2 | 10 | 0 | 4 | 0.55 | 18 | 5 |
| `pwr1000` | 1000 | 780 | 11.5 | 58 | 0.02 | 6 | 0.92 | 30 | 6 |
| `offshore_wind` | 500 | 420 | 8.5 | 3 | 0 | 3 | 0.42 | 8 | 3 |
| `big_solar` | 300 | 260 | 6.0 | 1 | 0 | 1 | 0.22 | 4 | 2 |
| `bess` | 200 | 250 | 6.0 | 5 | 0 | 1 | 0.25 | 3 | 2 |
| `uhv_sub`（设施） | 接口 +600 | 32000 万 | — | — | — | 2 | — | 2 | 2 |

> `bess` 在本期按"CF 0.25 的调峰机组"结算（见 00 §8 C9），不做充放模型。
> `uhv_sub` 走 `INFRA_SPECS`，`gateway_mw = 600`，在 `grid._gateway_in` 里按 `t.kind == "uhv_sub"` 加 600。

---

## 4. 状态机（5 态）

```
                  start(钱够 & 配额够)
   NOT_STARTED ────────────────────────► RUNNING
        ▲                                  │  │
        │ cancel                            │  │ fail（时长+1，仍在研）
        │                                   │  └──► RUNNING
   CANCELLED（瞬态）◄── cancel ── PAUSED ◄──┘ pause（玩家/超配额/欠费）
        │                          ▲
        │ 处理完 → NOT_STARTED     │ resume（钱够 & 配额够）
        └──────────────────────────┘

   RUNNING ── success ──► UNLOCKED（终态，不可再动）
```

| 迁移 | 触发 | 副作用 |
|---|---|---|
| `NOT_STARTED → RUNNING` | 玩家/AI 立项 | 占用配额；**不预扣钱**（本回合 R 步才扣） |
| `RUNNING → RUNNING` | 判定失败 | 扣钱；`accumulated_rounds += 1` |
| `RUNNING → UNLOCKED` | 判定成功 | 扣钱；`unlocked.add(target)`；项目移出在研列表 |
| `RUNNING → PAUSED` | 玩家暂停 / 超配额 / 现金不足 | **不扣钱、不 roll、时长不变** |
| `PAUSED → RUNNING` | 恢复且配额/现金满足 | —— |
| `RUNNING / PAUSED → CANCELLED` | 撤项 | 不扣钱；`best = max(best, accumulated)`；`accumulated = 0` |
| `CANCELLED → NOT_STARTED` | 同步处理 | 项目留在列表，显示"已撤项 · 保留 N 回合积累" |
| 收购继承 | 见 §10 | 目标公司项目 → 继承方 `NOT_STARTED`（或直接 `RUNNING`） |

**非法迁移**（必须抛 `ResearchError`）：`UNLOCKED → 任何`、`NOT_STARTED → PAUSED`、`PAUSED → UNLOCKED`。

---

## 5. 人力双配额

```
Company.eng_teams = 工程总池                          # 现有字段，不变
Company.infra_quota + Company.research_quota = eng_teams   # 回合开始锁定
```

| 规则 | 说明 |
|---|---|
| 锁定时机 | `end_turn()` 开头读取，回合内**不可变**；UI 改动只影响下一回合 |
| 默认分配 | `research_quota = clamp(Σ 在研项目 manpower, 0, eng_teams - 1)`（至少留 1 队给基建） |
| 全划基建 | `research_quota = 0` → 全部在研项目 `PAUSED`（**不扣钱不 roll**，≠ 撤项） |
| 全划研发 | `infra_quota = 0` → `advance_projects` 的 `ratio = 0`，在建工程原地不动（不退款、不罚款） |
| 超配额 | 按 `priority`（小者优先）保留，其余强制 `PAUSED`，并写日志"研发人力不足，X 项目暂停" |
| 现金不足 | `cash < cash_cost_per_round` → 该项目 `PAUSED`（欠费停机），日志"研发经费不足" |

`advance_projects()` 的唯一改动：`ratio = min(1.0, co.infra_quota / need)`（原为 `co.eng_teams`）。

**研发只占工程池，不占运营人力**：`ops_staff`、`Company.staff_need()` 完全不受研发影响。

---

## 6. 结算时序与伪代码

插入位置：`end_turn()` 的 **C 生产结算之后、D 政策之前**（原因见 00 §2）。

```python
def settle_research(game) -> None:
    for co in game.companies:
        if not co.alive or co.delisted:
            continue
        st = co.last_income
        quota = co.research_quota

        # 1) 配额与现金体检（只降级，不扣钱）
        used = 0
        for p in sorted(co.research, key=lambda x: x.priority):
            if p.state != RUNNING:
                continue
            d = research_def(p.def_key)
            if used + d.manpower_cost > quota:
                p.state = PAUSED; p.pause_reason = "超配额"; continue
            if co.cash < d.cash_cost_per_round:
                p.state = PAUSED; p.pause_reason = "经费不足"; continue
            used += d.manpower_cost

        # 2) 扣钱 → 算概率 → 判定
        for p in co.research:
            if p.state != RUNNING:
                continue
            d = research_def(p.def_key)
            cost = d.cash_cost_per_round
            co.cash -= cost
            st.research += cost              # 费用化，进当期利润表
            p.total_spent += cost
            p.last_rate = research_rate(game, co, p)     # §2 公式
            if game.rng.random() < p.last_rate:
                p.state = UNLOCKED
                co.unlocked.add(d.target_kind)
                game.log(f"🔬 {co.name} 完成研发：{d.name}")
            else:
                p.accumulated_rounds += 1
                p.fail_count += 1
```

- 研发**不产生现金流入**，只有流出；成功也只解锁"可建"，建造另付 capex。
- `st.research` 计入 `IncomeStatement.operating_cost`，因此自动影响 `net_profit` → 现金流 → 股价。
- 研发费用**不进资产负债表**（不做资本化），这是"烧钱压利润→股价跌→被偷袭"的根。

---

## 7. 数据结构

```python
# ---- 静态配置（config/research_config.json → ResearchDef）
@dataclass(frozen=True)
class ResearchCondition:
    key: str            # "has_coal_plant" / "own_coal_mine" / "grid_mw_600" ...
    label: str          # "在运燃煤"
    bonus: float        # 0.03

@dataclass(frozen=True)
class ResearchDef:
    key: str
    name: str
    target_kind: str                       # 解锁后的 PLANT_SPECS / INFRA_SPECS key
    base_success_rate: float
    per_round_gain: float
    max_duration_bonus: float
    global_max_rate: float
    cash_cost_per_round: float             # 万元
    manpower_cost: int                     # 工程队
    condition_list: tuple[ResearchCondition, ...]
    tags: tuple[str, ...]                  # ("thermal","high_carbon") 供 modifier 匹配
    min_turn: int = 1                      # 最早可出现回合

# ---- 运行时
@dataclass
class ResearchProject:
    def_key: str
    state: str = "NOT_STARTED"             # NOT_STARTED/RUNNING/PAUSED/UNLOCKED/CANCELLED
    accumulated_rounds: int = 0
    best_accumulated_rounds: int = 0
    priority: int = 99
    started_turn: int = 0
    pause_reason: str = ""
    total_spent: float = 0.0
    fail_count: int = 0
    last_rate: float = 0.0                 # 上次判定用的概率（UI 只读）
    inherited: bool = False                # 收购继承标记

    @property
    def name(self) -> str:                     # 只读，取自 ResearchDef
        ...

# ---- Company 新增字段
unlocked: set[str] = field(default_factory=set)        # 已解锁型号 key
research: list[ResearchProject] = field(default_factory=list)
infra_quota: int = 0
research_quota: int = 0

# ---- IncomeStatement 新增字段
research: float = 0.0        # 研发费用（万元），计入 operating_cost
```

`IncomeStatement.rows()` 增加一行：`("研发费用", -self.research, True)`，位置在"固定成本(运维)"之后。

---

## 8. 配置 Schema（`config/research_config.json`）

```json
{
  "version": 1,
  "global_max_rate": 0.65,
  "max_condition_bonus": 0.06,
  "default_unlocked": ["coal", "gas", "hydro", "wind", "solar", "nuclear"],
  "projects": [
    {
      "key": "pwr1000",
      "name": "百万千瓦压水堆",
      "target_kind": "pwr1000",
      "base_success_rate": 0.03,
      "per_round_gain": 0.008,
      "max_duration_bonus": 0.08,
      "global_max_rate": 0.14,
      "cash_cost_per_round": 5200,
      "manpower_cost": 5,
      "condition_list": [
        {"key": "has_nuclear_plant", "label": "在运核电", "bonus": 0.02},
        {"key": "own_uranium_mine", "label": "自有铀矿", "bonus": 0.01},
        {"key": "nuclear_approved", "label": "核电已核准", "bonus": 0.01}
      ],
      "tags": ["nuclear", "high_tech"],
      "min_turn": 8
    }
  ]
}
```

- `default_unlocked` 是**唯一**的默认解锁入口，代码里不得出现 `if kind == "coal"` 这类硬编码。
- **`nuclear` 必须留在 `default_unlocked` 里**：它的门槛是政策核准（`policy.nuclear_approved` 事件），不是技术研发。
  否则"核电核准放开"事件发生后，玩家会永远建不了堆——这是 C3 裁决的直接后果。
- 字段名与本文/00 §7 逐字一致；加载时断言 `base + max_duration_bonus <= global_max_rate`。
- 新增建筑 = 往 `projects` 加一条 + 往 `PLANT_SPECS` 加一条，**不改代码逻辑**。

---

## 9. AI 同规则

`ai_turn()` 增加第 6 子步 `_ai_research(game, co)`，与玩家共用 `research_rate()` / 同一 `game.rng`。

| 维度 | 规则 |
|---|---|
| 配额 | `research_quota = min(eng_teams - 1, 1 + turn // 12)`；`infra_quota` 拿剩下的 |
| 方向偏好 | `turn < 9`：`usc_coal` → `fclass_gas`；`9 ≤ turn < 20`：`big_solar` → `offshore_wind` → `bess`；`turn ≥ 20`：`pwr1000` → `uhv_sub` → `dam_hydro` |
| 现金门槛 | 维持「2 回合固定成本 + 3 回合研发费」；不足则暂停全部在研 |
| 止损 | 连续 4 回合净利为负 → 撤掉现金最贵的在研项目（保留时长） |
| 失败容忍 | 同一项目失败 ≥ 12 回合仍继续（AI 不会聪明到会算期望，这是刻意的） |
| 情报 | **玩家不可见**：UI 只展示 AI 已建成的型号；在研项目、成功率、累计时长全部隐藏 |
| 后果 | 研发烧钱 → 利润下滑 → 股价下跌 → 成为玩家的猎物（无需额外代码，走现有估值链） |

AI 的 `ResearchProject` 与玩家同结构，存在 `co.research` 里；UI 层按 `co.is_player` 过滤。

---

## 10. 收购继承

| 项 | 规则 |
|---|---|
| 继承范围 | 目标公司 `state ∈ {RUNNING, PAUSED}` 的项目**逐项**询问（UI 勾选，默认全不选） |
| 时长 | **100% 继承**：`accumulated_rounds` 与 `best_accumulated_rounds` 原样搬过来 |
| 状态 | 继承后为 `NOT_STARTED`（`inherited=True`）；若配额与现金都够，可立即 `start` 恢复 |
| 人力 | **不继承工程队**：`eng_teams` 按 `ma.absorb_merge` 现有规则并入，缺口自己补 |
| 超配额 | 继承后 `Σ manpower > research_quota` → 超出的项目强制 `PAUSED` |
| 图纸 | **不继承已解锁型号**：`unlocked` 不并入（必须自己研发） |
| 已建建筑 | 已建成的高阶建筑可继续运行；但**新建同型号仍需自己研发** |
| 已撤项 | `best_accumulated_rounds > 0` 的项目也出现在继承列表（继承的是断点，不是项目） |

```python
# ma.absorb_merge 内新增
for p in target.research:
    if p.state in ("RUNNING", "PAUSED") or p.best_accumulated_rounds > 0:
        yield InheritableProject(p.def_key, p.accumulated_rounds, p.best_accumulated_rounds)
```

---

## 11. UI 契约（研发页签）

| 列 | 内容 | 约束 |
|---|---|---|
| 名称 | 型号名 + 容量 | 已解锁显示"已解锁"灰字，不可再操作 |
| 累计时长 | `5 回合（+12.5%）` | **不显示进度条/进度百分比** |
| 当前成功率 | `34%` | 用 §2 公式实时算，四舍五入到 1% |
| 配套条件 | `2/3` + 逐项 ✔/✘ | 悬停显示每项加成 |
| 每回合成本 | `1800万 / 2 队` | 现金不足标红 |
| 操作 | 立项 / 暂停 / 恢复 / 撤项 | 撤项二次确认："已投入 X 万不返还，保留 N 回合积累" |

顶部一行显示：`工程总池 6 队 = 基建 4 + 研发 2`（可拖拽调整，改动下一回合生效）。

---

## 12. 与主循环的接口 + 七条接口约定

### 12.1 代码接口

| 位置 | 变更 |
|---|---|
| `engine.end_turn` | C 之后插入 `settle_research(self)` |
| `engine.advance_projects` | `ratio` 分母改为 `co.infra_quota` |
| `engine.build` | 新项目下单前检查 `co.unlocked`（型号未解锁 → 拒绝并提示"需先研发"） |
| `ai.ai_turn` | 末尾追加 `_ai_research(game, co)` |
| `ma.absorb_merge` | 追加研发项目继承 |
| `company.IncomeStatement` | 新增 `research` 字段与行 |
| `ui/app.py` | 新增研发页签（§11） |

### 12.2 七条接口约定（与主文档对齐）

1. **费用化**：研发费用计入当期"研发费用"科目，**不进资产负债表**（不资本化），以强化烧钱压利润的张力。
2. **只占工程池**：研发只吃【研发配额】，不占运营人力，不影响 `staff_need()`。
3. **AI 情报不可见**：玩家只能从 AI 已建建筑反推其技术路线，看不到在研项目与成功率。
4. **收购继承**：继承 100% 累计时长，但研发人力自己养，超配额强制暂停，多项目逐项选择继承/放弃。
5. **默认解锁配置化**：用 `default_unlocked` 数组标记，禁止硬编码。
6. **双计时字段**：`accumulated_rounds`（当前断点）与 `best_accumulated_rounds`（历史最佳）分离，多次重启取最大值继承。
7. **单一修正源**：事件对研发的影响统一走 `game.research_modifier`（`flat_bonus` / `force_fail` / `tags_affected`），结算只读这一份，禁止第二套加减逻辑。

### 12.3 补充约定（实现时同样强制）

8. 结算点固定在 **C 之后、F 之前**（利润表重置问题）。
9. 立项/暂停/撤项只发生在**玩家操作段**（`end_turn` 之前），回合内不改状态机。
10. 所有新增字段有默认值，保证旧存档 `pickle` 可读。

---

## 13. 现状 vs 目标 与冲突裁决

| 项 | 现状 | 目标 |
|---|---|---|
| 解锁机制 | 无：6 种电源开局全可建 | 基础型号默认解锁（配置），8 个高阶型号需研发 |
| 工程人力 | 单一 `eng_teams` 池 | 拆 `infra_quota` / `research_quota` |
| 利润表 | 无研发科目 | `research` 科目 |
| AI | 只建厂/报价/抄底 | 追加研发决策 |
| 并购 | 只继承资产/人力 | 追加研发断点继承 |
| 事件 | 15 个纯外生冲击 | 追加 `research_modifier` 通道 |

**冲突裁决**（编号同 00 §8）：

- **C1**：文档里"小火电上限 50%"与"小型火电默认解锁"矛盾。裁决：本期 8 项不含小火电；`usc_coal` 的 0.50 上限承担"中低难度"角色。若将来要加"亚临界中型机组"，新增一条 `sub_coal`，cap 0.50。
- **C2**：`IncomeStatement` 无科目 → 新增 `research`。
- **C3**：现有 6 型号保留为默认解锁，研发只解锁新增型号（不回收玩家已有能力）。
- **C9**：储能/特高压按简化口径实现（见 §3 注）。

---

## 14. 验收不变量

1. **概率有界**：任意项目、任意回合，`0 ≤ p ≤ min(global_max_rate, 0.65)`；`pwr1000` 的 p 永远 ≤ 0.14。
2. **单调性**：其他条件不变时，`accumulated_rounds` 增加 → `p` 不减；到顶后不再增长。
3. **配置断言**：`base + max_duration_bonus ≤ global_max_rate` 在加载时校验，违反即启动失败。
4. **状态机封闭**：只允许 §4 表中的迁移；`UNLOCKED` 不可再迁移。
5. **先扣钱后判定**：每回合 RUNNING 项目 `cash` 减少额 == `Σ cash_cost_per_round` == 利润表 `research`。
6. **暂停零成本**：PAUSED 项目不扣钱、不 roll、`accumulated_rounds` 不变。
7. **欠费必停**：`cash < cash_cost_per_round` 时该项目当回合必为 PAUSED，且不产生负现金。
8. **撤项留痕**：`cancel` 后 `best == max(旧 best, 旧 accumulated)`，`accumulated == 0`；重启后 `accumulated == best`。
9. **继承完整**：收购继承后 `accumulated` 与 `best` 与目标公司一致（±0）。
10. **默认解锁免费**：`default_unlocked` 中的型号 `unlocked` 恒为真，且不出现在研发列表。
11. **AI 隔离**：UI 层对 AI 的 `research` 列表访问必须返回空。
12. **删除可运行**：注释掉 `settle_research` 调用，`sim.py 48` 仍能跑完（新系统是叠加层）。

---

## 15. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 8 项全开 1.91 亿/回合成吞金兽 | 玩家永远开不起第二个项目 | 门槛来自现金而非规则；`sim.py` 验证"1~2 项能否 20 回合出首个高阶型号" |
| 核电 14% 概率过于绝望 | 玩家 10 回合不出就放弃研发线 | 时长加成 10 回合到顶 + 条件 +0.04；配合"撤项保留断点"降低挫败 |
| 概率通胀 | 后期条件全满足，研发变成必然 | `max_condition_bonus=0.06` 截断 + `global_max_rate` 硬顶 |
| AI 研发不可见 → 玩家被偷家 | 对手突然掏出百万千瓦堆 | 可接受（这是博弈）；用"AI 已建高阶建筑"作为唯一反推信号 |
| 双配额理解成本 | 玩家不知道"全给研发"会停工 | UI 顶栏常显 `总池 = 基建 + 研发`，改动时弹出"本回合生效于下一回合" |
| 存档不兼容 | 旧档无 `unlocked`，全部型号变未解锁 | `unlocked` 默认值 = `default_unlocked`；`research` 默认空列表 |
| 与 bess/uhv 的实现复杂度 | 储能要充放、特高压要改 grid | 本期简化口径，写进风险表，V2.x 再补 |
