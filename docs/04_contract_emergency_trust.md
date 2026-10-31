# 04 · 合同 / 应急组 / 隐藏信誉（第五份数据契约）

> 状态：**设计契约 v1.0（全新，未实现）**
> 依赖：02（城市区块与 `supply_rate`）、`dispatch`（断电数据）、`events`（灾害）
> 上游：`engine.end_turn`（新增 S 步）、`ai`（信誉共享）、`ui`（合同·应急页签）
> 本文定义：三个新对象、合同判定、应急响应、灾害接入、信誉模型、单一数据源、配置与验收。

---

## 0. 定位与闭环

三个系统只服务一件事：**让"供电可靠性"变成可定价、可失败、可惩罚的资产**。

```
应急组投入 ──► 灾害断电时长↓ ──► 信誉侵蚀↓ ──► 合同履约率↑ ──► 高价值合同（AI 数据中心）拿得到
    ▲                                                                        │
    └──────────── 合同收入稳 ──► 财报好 ──► 股价高 ◄─────────────────────────┘
                                              │
                                    被收购风险↓ / 收购对手能力↑

反面：省应急组维护费 → 灾害断电久 → 信誉崩 → 违约罚款 + 客户流失 → 财报恶化 → 股价跌 → 被 AI 收购
```

三个系统的分工：

| 系统 | 一句话 | 不可替代性 |
|---|---|---|
| 合同 | 把"我能稳定供电"换成长期现金流 | 让可靠性有**变现出口** |
| 应急组 | 把"灾难"从纯惩罚变成可管理风险 | 给玩家**主动操作空间** |
| 信誉 | 把"长期稳定"变成隐性资产 | 一次断电的代价**延迟但复利**地兑现 |

---

## 1. 三个新对象

```python
@dataclass
class Contract:
    cid: int
    type: str                  # industrial / ai_datacenter / gov_emergency / green_direct
    client_name: str
    city_idx: int
    client_load_mw: float      # 切片负荷（≤ 该城 demand_mw × 0.6）
    required_reliability: float
    price_cap_ratio: float     # 合同电价上限 = 市场均价 × 该系数（见 §2 注）
    duration_rounds: int
    signed_turn: int
    expires_turn: int
    penalty_per_breach: float  # 万元
    trust_penalty_per_breach: float
    reward_bonus: float        # 电价溢价（0.15 = +15%）
    tags: tuple[str, ...]
    breach_count: int = 0
    status: str = "active"     # active / breached / expired / terminated

@dataclass
class EmergencyTeam:
    tid: int
    city_idx: int              # 部署城市（-1 = 未部署，仍在维护）
    count: int = 1             # 同城可叠 1~2 队
    # 属性从 emergency_team_config 读，不逐队存

@dataclass
class TrustBook:               # 挂在 Company 上（玩家与 AI 都有，AI 的不可见）
    value: float = 50.0        # 隐藏 0~100
    last_delta: float = 0.0
    consecutive_good_rounds: int = 0
    breach_count_total: int = 0
    recent_signals: list[str] = field(default_factory=list)   # 最近 5 条间接信号
```

`Company` 新增：`trust: TrustBook`、`contracts: list[Contract]`、`teams: list[EmergencyTeam]`、
`outage_hours_by_city: dict[int, float]`、`reputation_target: float = 60.0`（口碑回归目标，**不动**现有 `reputation` 语义）。

---

## 2. 合同类型

| type | 客户 | 切片负荷 | 时长 | 电价口径 | 违约罚款 | 信誉惩罚 | 签约硬门槛 |
|---|---|---|---|---|---|---|---|
| `industrial` | 工业大户 | 60~120 MW | 4~8 回合 | 市场均价 × **0.95** | 1200 万 | −6 | trust ≥ 45；近 4 回合供电率 ≥ 0.95 |
| `ai_datacenter` | AI 数据中心 | 300~800 MW | 8 回合 | 市场均价 × **1.15**（对电价不敏感） | **5000 万** | **−15** | trust ≥ 70；应急组 ≥ 2；近 4 回合供电率 ≥ 0.98；城市有 `special` 区块 |
| `gov_emergency` | 政府保供 | 100~300 MW | 1~2 回合 | 政策定价 × **1.00** | 3000 万 | −12 | trust ≥ 55；应急组 ≥ 1；灾害事件触发 |
| `green_direct` | 绿电大客户 | 80~200 MW | 6 回合 | 市场均价 × **1.12** | 1500 万 | −8 | trust ≥ 60；新能源占比 ≥ 30%；碳强度 ≤ 300g/kWh |
| （隐式）居民 | 居民区块 | —— | —— | 不签约，按电价+可靠性自动迁移 | 迁移即流失 | —— | —— |

**注（重要）**：原始设计里的 `price_cap: 95` 与现网电价（460~520 元/MWh）不在同一量纲。
裁决：**合同电价一律用"市场均价 × 系数"表达**，绝对值由 `game.market` 现价推出。
理由见 00 §8 C11——写死绝对值会让合同在游戏第一回合就永远违约。

`required_reliability`：`industrial 0.98` / `ai_datacenter **0.999**` / `gov_emergency 0.99` / `green_direct 0.99`。

---

## 3. 签约判定

### 3.1 合同生成（不是玩家点出来的，是条件满足才出现）

```
每回合 _advance_turn 末，对每个城市检查：
  ① 城市有对应区块（special → ai_datacenter；ind 多 → industrial；新能源达标 → green_direct）
  ② 该城已有合同的 client_load 总和 ≤ city.demand_mw × 0.6
  ③ 满足该类型的硬门槛（§2 表）
  ④ 每城每类最多 1 份 + 全公司最多 4 份
满足 → 在合同面板生成一份"可签"合同（带截止回合，3 回合内不签则消失）
```

### 3.2 签约概率

```
p_sign = clamp(0.35 + (trust.value - min_trust) / 60, 0, 0.95)
roll: rng.random() < p_sign → 签约成功；否则拒绝并写信号"对方对贵公司履约能力存疑"
```

- 硬门槛不满足 → **合同根本不出现**（避免玩家看到签不了的东西）。
- 签约成功后：`signed_turn = turn`、`expires_turn = turn + duration_rounds`、合同收入下回合开始计。

---

## 4. 履约判定

每回合 S 步，对每份 `status == "active"` 的合同判定：

```
① 供电量：actual_mw ≥ client_load_mw × 0.98
   actual_mw = 该公司在该城的 served_mw × (client_load_mw / city.demand_mw)
② 断电时长：outage_hours(co, city) ≤ (1 - required_reliability) × HOURS_PER_TURN
   例：0.999 → 允许 ≤ 2.19 小时；0.98 → 允许 ≤ 43.8 小时
③ 电价：合同电价 = min(该公司工业电价, 市场均价 × price_cap_ratio)
④ 信誉：trust.value ≥ min_trust（不足时走概率判定，见下）
```

**第 ④ 条的概率化**（信誉低不是直接失败，而是"更容易失败"）：

```
if trust.value >= min_trust:  p_ok = 1.0
else:                         p_ok = clamp(0.90 - (min_trust - trust.value) * 0.02, 0.30, 0.90)
```

**结果分支**：

| 结果 | 收款 | 惩罚 | 信誉 | 计数 |
|---|---|---|---|---|
| 全部满足 且 `rng < p_ok` | `energy × price × (1 + reward_bonus)` | —— | **+1** | —— |
| 任一条不满足 / `rng ≥ p_ok` | 0 | `penalty_per_breach` | `−trust_penalty` | `breach_count += 1` |

`breach_count ≥ 3` → 合同 `terminated`，该客户进入黑名单（同类型合同 4 回合内不再生成），信誉额外 −5。

**记账**：

```
st.contract_revenue += 收款
st.contract_penalty += 罚款
```

两个科目**单独列示**（不用 `fines`），让玩家一眼看清合同是赚是亏。

---

## 5. 应急组

### 5.1 属性

| 属性 | 默认 | 说明 |
|---|---|---|
| 建造费 | 9000 万/队 | 一次性，进现金流（资本开支） |
| 维护费 | **300 万/回合** | 刚性，进运营成本（§11 第 2 条） |
| 上限 | 6 队 | 防无脑堆 |
| 响应速度 `response_speed` | 0.60 | 断电时长 × (1 − 0.60) = 0.40 |
| 覆盖半径 | 6 格 | 以部署城市为中心（切比雪夫） |
| 人员安全 `personnel_safety_bonus` | 0.80 | 伤亡概率 × (1 − 0.80) = 0.20 |
| 临时保供 | 200 MW | 灾害期给该城 `special` 客户兜底，稳合同 |
| 班组占用 | 2 班组/队 | 占运营人力，缺人时响应速度打折 |

### 5.2 部署与维护

- 部署在**城市**上（`city_idx`），覆盖半径 6 格；跨城覆盖按"距离衰减"：`coverage = max(0, 1 - dist/12)`。
- 未部署的队仍在维护（钱照扣），但不提供任何减免——逼玩家想清楚"买来干嘛"。
- 维护费 `Σ count × 300 万 / 回合`，进 `st.emergency`。

### 5.3 响应公式

```
coverage      = 1.0（部署城） / max(0, 1 - 格距/12)（跨城） / 0（无队）
response      = response_speed × staff_ratio × coverage        # staff_ratio 见 company.py
final_hours   = base_hours × terrain_factor × (1 - response)
final_hours   = min(final_hours, 48)                            # 单次灾害上限 48h
```

---

## 6. 灾害接入（阶段 6）

### 6.1 灾害表（`events.py` 新增 5 条事件，`EVENTS` 追加）

| 事件 | base_hours | severity | 受影响地形标签 | 权重 | 最早回合 |
|---|---|---|---|---|---|
| 风暴 | 8 | 1 | coast / plain | 10 | 2 |
| 洪水 | 18 | 2 | river / plain | 7 | 3 |
| 地震 | 24 | 3 | all | 3 | 8 |
| 极端高温 | 12 | 2 | all | 9 | 1 |
| 寒潮 | 10 | 1 | all | 8 | 1 |

`terrain_factor`：`plain 1.0 / hill 1.15 / desert 1.1 / coast 1.2 / river 1.3`。

### 6.2 单一数据源 `disaster_result`

```python
@dataclass
class DisasterResult:
    event_key: str
    city_idx: int
    base_hours: float
    terrain_factor: float
    coverage: float          # 应急组覆盖率 0~1
    final_hours: float       # 断电时长
    casualties: int          # 0/1
    fine: float              # 伤亡罚款（万元）
```

**写入点只有一个**：灾害事件的 `apply()` 末尾。信誉、合同、城市**只读**这个对象。

### 6.3 结算流程

```
灾害发生 → 选受影响城市（地形标签匹配）
  ↓
final_hours = base_hours × terrain_factor × (1 - response)
  ↓
写入 game.disaster_result（只写这一个对象，不写 City、不扣信誉）
  ↓
人员安全：p_casualty = severity × 0.06 × (1 - 0.80 × coverage)
  casualties → 罚款 3000 万（进利润表 fines）+ 信誉 −10（由 S 步统一扣）
  ↓
城市扩张结算（J 步，不变）
```

> 「断电时长 → 信誉侵蚀」**不在事件里算**，而是在下一回合 S 步统一算（见 §7）。
> 事件只产生事实（`disaster_result`），结算只做积分；`disaster_result` 被 S 步消费后立即清空，
> 避免同一场灾害跨回合重复扣信誉。

---

## 7. 隐藏信誉

### 7.1 原则

- 玩家**看不到数值**，只看到 5 档文字与间接信号。
- 与断电强绑定：断电越久、越频繁，侵蚀越重。
- 是合同判定的核心输入，不是独立摆设。

### 7.2 每回合变化

```python
erosion_i = 0.5 * min(outage_hours(co, city), 24) * importance_i
erosion   = min(EROSION_CAP, Σ erosion_i)              # 单回合上限 15
delta     = bonus - erosion - breach_terms - accident_terms

if delta >= 0:
    trust += delta + (50.0 - trust) * 0.03             # 慢回归，3%/回合
else:
    trust += delta                                     # 惩罚立即生效

trust = clamp(trust, 0, 100)
```

| 项 | 值 |
|---|---|
| 侵蚀系数 | **0.5 / 小时**（配置项 `erosion_per_hour`） |
| 单客户时长上限 | `min(outage_hours, 24)` |
| 单回合侵蚀上限 `EROSION_CAP` | **15** |
| 慢回归 | 向 50 回归 3%/回合（仅在 `delta ≥ 0` 时） |
| 干净回合奖励 | 无违约且 `outage_hours ≤ 1` → **+1.0** |
| 连续稳定奖励 | 连续 4 回合 `supply_rate ≥ 0.99` → **+1.5** |
| 应急有效响应 | 本回合有 ≥1 次 `coverage > 0.5` 的灾害响应 → **+0.5** |
| 违约 | `−trust_penalty_per_breach`（−6 ~ −15） |
| 伤亡事故 | **−10**；核事故 **−25** |

`importance_i`（客户重要性）：`res 1.0 / com 1.2 / ind 1.4 / special 2.0 / ai_datacenter 3.0`。
城市级取区块加权平均：`importance = Σ(block.load / city.base_mw × importance(block.type))`。

**算例**（与设计原意一致）：

| 场景 | 计算 | 侵蚀 |
|---|---|---|
| 一回合断电 10h，只影响普通居民 | `0.5 × 10 × 1.0` | **5 点** |
| 一回合断电 10h，只影响 AI 数据中心 | `0.5 × 10 × 3.0` | **15 点**（打满单回合上限） |

> **数值提醒**：0.5/小时 × 季度 2190 小时意味着"5% 缺供就会打满单回合上限"。
> `EROSION_CAP=15` 是兜底；若实测过重，优先降 `erosion_per_hour` 到 0.15，**不要**动上限逻辑。

### 7.3 五档映射（UI 唯一可见部分）

| 档位 | `trust` | UI 文案 |
|---|---|---|
| 优秀 | ≥ 80 | 信誉状态：优秀 |
| 良好 | 65 ~ 80 | 信誉状态：良好 |
| 一般 | 45 ~ 65 | 信誉状态：一般 |
| 较差 | 30 ~ 45 | 信誉状态：较差 |
| 极差 | < 30 | 信誉状态：极差 |

### 7.4 作用点

| 作用点 | 机制 | 实现 |
|---|---|---|
| 合同签约 | `p_sign = 0.35 + (trust − min)/60` | §3 |
| 合同履约 | `trust < min` → `p_ok` 降到 0.30~0.90 | §4 |
| 客户迁移 | **口碑回归目标 = 45 + 0.30 × trust**，口碑驱动份额 | 改 `_advance_turn` 一行 |
| AI 合作/收购 | 信誉高的公司，AI 更愿意接受换股/白衣骑士；信誉低易被敌意收购 | `ai._ai_stock` 里乘系数 |
| 政府合同 | `trust < 55` → 不生成 `gov_emergency` | §3 硬门槛 |
| 银行融资（可选） | `trust < 40` → 借款利率 +0.3%/季 | `engine.borrow`，本期不做 |

**口碑耦合是这套系统的关键设计**：信任不是独立数值，它通过"口碑回归目标"影响现有份额模型，
因此**不需要在 `dispatch._score` 里加新参数**——一处改动，全局生效。

### 7.5 间接感知（文案库，随机取 1~2 条写入 `recent_signals`）

| 场景 | 文案 |
|---|---|
| 断电偏多 | "近期断电较多，部分客户正在考虑更换供应商" |
| 合同正常 | "合同履约正常，客户续约意愿良好" |
| 信誉低 | "业内对贵公司的供电稳定性提出质疑" |
| 灾害响应好 | "应急抢修及时，地方政府致电表扬" |
| 违约后 | "因供电未达标，客户已启动违约索赔程序" |
| AI 公告 | "XX 公司近期供电稳定性受质疑"（AI 的 `recent_signals` 对玩家可见一档） |

---

## 8. 结算时序（S 步，C 之后 F 之前）

```python
def settle_contracts(game):
    for co in game.companies:
        if not co.alive or co.delisted: continue
        st = co.last_income

        # 1) 合同履约
        for c in co.contracts:
            if c.status != "active": continue
            ok = fulfill(game, co, c)          # §4 四条件 + p_ok
            if ok:
                st.contract_revenue += revenue
                co.trust.value = min(100, co.trust.value + 1)
            else:
                st.contract_penalty += c.penalty_per_breach
                co.trust.value = max(0, co.trust.value - c.trust_penalty_per_breach)
                c.breach_count += 1
                co.trust.breach_count_total += 1
            if game.turn >= c.expires_turn or c.breach_count >= 3:
                c.status = "expired" if c.breach_count < 3 else "terminated"

        # 2) 断电统计（读 C 步写好的 outage_hours_by_city + disaster_result）
        # 3) 信誉更新（§7.2）
        # 4) 应急维护费
        st.emergency = sum(t.count for t in co.teams) * 300.0
        # 5) 信誉 → 口碑回归目标
        co.reputation_target = 45.0 + 0.30 * co.trust.value
```

`_advance_turn` 里把 `co.reputation += (60.0 - co.reputation) * 0.06`
改为 `co.reputation += (co.reputation_target - co.reputation) * 0.06`。

---

## 9. 断电时长：单一数据源

断电时长由**两个写入点、一个合成点**组成，合成点在 S 步：

```python
# ── C 步（settle_production 末尾）：只写"缺供"部分
city_short = city.outage_mw / max(1.0, city.demand_mw)          # 全城缺供比例
co_short   = co.last_income.outage_mwh / max(1.0, co.last_income.served_mwh)
base_hours = clamp(city_short + co_short, 0.0, 1.0) * HOURS_PER_TURN   # ≤ 2190h
co.outage_hours_by_city[city.idx] = base_hours
city.outage_hours = base_hours

# ── S 步（settle_contracts）：合成灾害部分，消费后清空
dis   = game.disaster_result
extra = dis.final_hours if (dis and dis.city_idx == city.idx) else 0.0
hours = co.outage_hours_by_city[city.idx] + extra
# 之后的信誉侵蚀与合同判定都用 hours
...
game.disaster_result = None          # 消费即清空，避免下回合重复计
```

> 为什么不在 C 步就叠加灾害：`disaster_result` 由 I 步（事件）产生，而 C 早于 I。
> 让它跨到下一回合的 S 步消费，正好对应"灾害当回合发生、次回合反映到信誉"。
> **清空是强制的**——否则同一场灾害会每回合扣一次信誉。

| 消费者 | 读什么 |
|---|---|
| 信誉系统 | `hours`（C 缺供 + S 灾害） |
| 合同系统 | 同一 `hours`，按 `contract.city_idx` 取 |
| 城市扩张 | `city.supply_history`（由 C 步一并写入） |
| UI | 同字段 |

**禁止**：`events.py` 直接扣信誉；`dispatch.py` 再算一遍小时数；合同自己算缺供比例；
`disaster_result` 不清空。

---

## 10. 配置清单

### 10.1 `config/contract_config.json`

```json
{
  "version": 1,
  "types": {
    "industrial":    {"load_mw": [60, 120],  "duration": [4, 8], "price_ratio": 0.95,
                      "reliability": 0.98,  "penalty": 1200, "trust_penalty": 6,
                      "min_trust": 45, "min_teams": 0, "min_supply_rate_4": 0.95,
                      "reward_bonus": 0.00, "tags": ["steady"]},
    "ai_datacenter": {"load_mw": [300, 800], "duration": [8, 8], "price_ratio": 1.15,
                      "reliability": 0.999, "penalty": 5000, "trust_penalty": 15,
                      "min_trust": 70, "min_teams": 2, "min_supply_rate_4": 0.98,
                      "reward_bonus": 0.15, "tags": ["high_load", "high_reliability"]},
    "gov_emergency": {"load_mw": [100, 300], "duration": [1, 2], "price_ratio": 1.00,
                      "reliability": 0.99,  "penalty": 3000, "trust_penalty": 12,
                      "min_trust": 55, "min_teams": 1, "tags": ["disaster"]},
    "green_direct":  {"load_mw": [80, 200],  "duration": [6, 6], "price_ratio": 1.12,
                      "reliability": 0.99,  "penalty": 1500, "trust_penalty": 8,
                      "min_trust": 60, "min_teams": 0, "min_renewable": 0.30,
                      "reward_bonus": 0.12, "tags": ["green"]}
  },
  "max_contracts_per_company": 4,
  "max_client_share_of_city": 0.60,
  "offer_ttl_rounds": 3,
  "breach_limit": 3,
  "blacklist_rounds": 4
}
```

### 10.2 `config/emergency_team_config.json`

```json
{
  "version": 1,
  "build_cost": 9000,
  "maintenance_per_round": 300,
  "max_teams": 6,
  "per_city_max": 2,
  "staff_per_team": 2,
  "response_speed": 0.60,
  "coverage_radius": 6,
  "personnel_safety_bonus": 0.80,
  "temp_supply_capacity": 200,
  "max_outage_hours": 48
}
```

### 10.3 `config/reputation_config.json`

```json
{
  "version": 1,
  "initial": 50.0,
  "erosion_per_hour": 0.5,
  "erosion_hour_cap": 24,
  "erosion_round_cap": 15,
  "mean_revert": 0.03,
  "revert_target": 50.0,
  "clean_round_bonus": 1.0,
  "stable_bonus": 1.5,
  "stable_rounds": 4,
  "stable_supply_rate": 0.99,
  "emergency_bonus": 0.5,
  "casualty_penalty": 10.0,
  "nuclear_penalty": 25.0,
  "tiers": {"优秀": 80, "良好": 65, "一般": 45, "较差": 30, "极差": 0},
  "importance": {"res": 1.0, "com": 1.2, "ind": 1.4, "special": 2.0, "ai_datacenter": 3.0},
  "reputation_target_base": 45.0,
  "reputation_target_trust": 0.30
}
```

### 10.4 灾害事件表新增字段

`base_outage_hours` / `severity` / `affected_tags` / `terrain_factor`，与 `events.EventDef` 并列。

---

## 11. 七条接口约定

1. **合同收入/罚款单独科目**：`st.contract_revenue` 与 `st.contract_penalty` 独立列示，不并进 `fines`。
2. **应急维护费进运营成本**：`st.emergency` 作为刚性支出与工资、运维并列，进 `operating_cost`。
3. **信誉与 AI 共享**：AI 也有 `trust`（隐藏），玩家只能通过 AI 的合同履约、客户流失间接推断。
4. **断电时长单一数据源**：`outage_hours_by_city` 由 `settle_production` 统一输出，合同与信誉都读这一份。
5. **灾害修正单一数据源**：应急组响应结果写入 `disaster_result`，信誉/合同/城市都读它。
6. **AI 数据中心合同后期才出现**：`turn ≥ 18` + 城市 `special` 区块 + `trust ≥ 70` + 应急组 ≥ 2。
7. **信誉不可见但存档要存**：`trust.value` 落盘，UI 只显示档位，调试模式（`--debug`）显示数值。

---

## 12. 现状 vs 目标 与冲突裁决

| 项 | 现状 | 目标 |
|---|---|---|
| 客户 | 按份额自动迁移，无合同 | 4 类合同 + 居民隐式 |
| 可靠性 | 只有"限电罚款 + 掉口碑" | 断电时长 → 信誉 → 合同 → 财报 |
| 灾害 | 15 个事件，直接改系数/停机 | 灾害写 `disaster_result`，不再直接扣口碑 |
| 应急 | 无 | 可建造/部署，刚维护费 |
| 信誉 | 只有可见 `reputation` | 隐藏 `trust` + 口碑回归目标耦合 |
| 财报 | 无合同/应急科目 | 新增 3~4 行 |

**冲突裁决**（编号同 00 §8）：

- **C5**：`reputation`（口碑，可见，快变量）与 `trust`（信誉，隐藏，慢变量）双变量并存；耦合点只有"口碑回归目标 = 45 + 0.30 × trust"。
- **C10**：合同不改分流算法。合同客户 = 城市负荷的切片，实际供电 = 该公司在该城份额 × 切片负荷。
- **C11**：`price_cap: 95` 与现价 460~520 不同量纲 → 改为"市场均价 × 系数"。
- **C12**：现有 `_ev_storm` 既停机又直接 `reputation −4`。裁决：保留停机效果，**删除直接扣口碑**，改由 `disaster_result → 信誉` 统一计算，避免双重惩罚。

---

## 13. 验收不变量

1. **合同不重叠**：同城同类型合同数 ≤ 1；全公司 active 合同 ≤ 4；`Σ client_load ≤ 城市需求 × 0.6`。
2. **判定可复现**：同一 `game.rng` 状态下，履约判定结果一致（不得用全局 `random`）。
3. **记账闭合**：`st.contract_revenue` 只在履约成功时增加，`st.contract_penalty` 只在失败时增加。
4. **断电单源**：`outage_hours_by_city` 只在 `settle_production` 写入一次；全仓库无第二处赋值。
5. **灾害单源**：`disaster_result` 只在灾害事件里写入；S 步消费后必须置 `None`；信誉/合同不直接读事件对象。
6. **信誉有界**：`0 ≤ trust ≤ 100`；单回合变化幅度 ≤ 30（防止一次事故直接归零）。
7. **不可见**：非调试模式下，UI 任何位置不得显示 `trust.value` 数字。
8. **门槛有效**：`turn < 18` 时不存在 `ai_datacenter` 合同；`Σ teams < 2` 时该合同不出现。
9. **黑名单生效**：同类型违约 3 次后 4 回合内不再生成该类型合同。
10. **存档完整**：`trust`、`contracts`、`teams`、`outage_hours_by_city` 均落盘，读档后判定结果一致。

---

## 14. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 信誉一崩到底 | 一次 5% 缺供 → 侵蚀打满 15 → 合同全违约 → 螺旋 | `erosion_round_cap=15` + 单回合变化 ≤30 + 慢回归 3% |
| 合同变成白送钱 | 工业合同稳赚不赔 | 电价上限 ×0.95 压毛利 + 断电硬条件 |
| 应急组无脑堆 | 6 队 1800 万/回合，玩家照买 | 维护费刚性 + 上限 6 + 缺人时响应打折 |
| AI 数据中心不可达 | 门槛太高，玩家永远签不到 | 门槛是后期目标；工业/绿电合同提供中期现金流 |
| 与现有 `storm` 事件重复惩罚 | 同一灾害扣两次口碑 | C12：删除事件内直接扣口碑 |
| 断电时长为 0 导致信誉只涨不跌 | 完美供电公司信誉封顶 | 上限 100 + 慢回归到 50（不追求 100 也能吃到档位红利） |
| 数值过重 | 信誉侵蚀让中期无法经营 | `tools/sim.py 48` 回归；优先调 `erosion_per_hour`，不动结构 |
