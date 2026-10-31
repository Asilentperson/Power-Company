"""《电力公司》主界面。

布局：
    顶栏   —— 回合、现金、负债、股价、市值、份额、政策
    左栏   —— 2D 格子地图 + 公司图例 + 选中地块信息 + 回合动态
    右栏   —— 经营 / 财报 / 交易所 / 政策日志 四个页签
    底栏   —— 结束回合 + 建造模式提示
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from .. import ma, paths
from ..company import Company
from ..constants import (
    ANTITRUST_SHARE,
    COMPANY_COLORS,
    DIVIDEND_MAX,
    INFRA_SPECS,
    LOAN_LIMIT_RATIO,
    PLANT_SPECS,
    POLICY_SCHEDULE,
    TERRAIN_INFO,
    UI_ACCENT,
    UI_BAD,
    UI_BG,
    UI_DIM,
    UI_GOOD,
    UI_PANEL,
    UI_TEXT,
    UI_WARN,
    money,
)
from ..engine import Game
from ..ma import MaError, ownership, player_stake
from . import mapview, scale
from .mapview import MapView, tile_tooltip

scale.enable_dpi_awareness()

FONT = "Microsoft YaHei UI"
BG2 = "#1b1e24"
TS_LOGICAL = 36          # 每格逻辑像素（乘 DPI 缩放）
WIN_W, WIN_H = 1240, 736


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        S = scale.init(self)
        mapview.TS = scale.px(TS_LOGICAL)
        self.title("电力公司 · Power Company —— 2D 电力经营 + 证券并购")
        self.geometry(f"{scale.px(WIN_W)}x{scale.px(WIN_H)}+0+0")
        self.minsize(scale.px(1120), scale.px(700))
        self.configure(bg=UI_BG)
        self.game = Game.new_game()
        self.build_mode: str | None = None
        self.selected: tuple[int, int] | None = None
        self._syncing = False
        self._toast_job = None
        self._log_rendered = 0
        self._style()
        self._menu()
        self._build_top()
        body = tk.Frame(self, bg=UI_BG)
        body.pack(fill="both", expand=True)
        self._build_left(body)
        self._build_right(body)
        self._build_bottom()
        self._bind_keys()
        self.refresh()
        if not os.environ.get("PWER_NO_INTRO"):
            self.after(200, self._intro)

    def _bind_keys(self) -> None:
        self.bind("<Control-Return>", lambda e: self.end_turn())
        self.bind("<Escape>", lambda e: self.cancel_build() if self.build_mode else None)
        for i, tab in enumerate((self.tab_ops, self.tab_fin, self.tab_mkt, self.tab_log), 1):
            self.bind(f"<Control-Key-{i}>", lambda e, t=tab: self.nb.select(t))

    # ------------------------------------------------------------ 样式
    def _style(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=UI_PANEL, foreground=UI_TEXT, font=(FONT, 9))
        st.configure("TFrame", background=UI_PANEL)
        st.configure("TNotebook", background=UI_BG, borderwidth=0)
        st.configure("TNotebook.Tab", background="#2c313a", foreground=UI_DIM,
                     padding=(scale.px(12), scale.px(6)), font=(FONT, 10))
        st.map("TNotebook.Tab", background=[("selected", UI_PANEL)],
               foreground=[("selected", UI_ACCENT)])
        st.configure("Treeview", background=BG2, fieldbackground=BG2,
                     foreground=UI_TEXT, rowheight=scale.px(20), borderwidth=0)
        st.configure("Treeview.Heading", background="#2c313a", foreground=UI_DIM,
                     font=(FONT, 9, "bold"))
        st.map("Treeview", background=[("selected", "#35507a")],
               foreground=[("selected", "#ffffff")])
        st.configure("TButton", background="#333a45", foreground=UI_TEXT,
                     padding=(scale.px(8), scale.px(4)))
        st.map("TButton", background=[("active", "#414a58")])
        st.configure("Accent.TButton", background="#2f6fb5", foreground="white",
                     padding=(scale.px(12), scale.px(7)), font=(FONT, 11, "bold"))
        st.map("Accent.TButton", background=[("active", "#3d86d6")])
        st.configure("Small.TButton", padding=(scale.px(4), scale.px(2)), font=(FONT, 8))
        st.configure("TLabel", background=UI_PANEL, foreground=UI_TEXT)
        st.configure("TSpinbox", fieldbackground=BG2, foreground=UI_TEXT,
                     background="#333a45", arrowcolor=UI_TEXT)
        st.configure("TScale", background=UI_PANEL, troughcolor="#2c313a")

    def _menu(self) -> None:
        bar = tk.Menu(self, bg=UI_PANEL, fg=UI_TEXT, tearoff=0)
        m = tk.Menu(bar, tearoff=0, bg=UI_PANEL, fg=UI_TEXT)
        m.add_command(label="新游戏", command=self.new_game)
        m.add_separator()
        m.add_command(label="保存进度", command=self.save_game)
        m.add_command(label="读取进度", command=self.load_game)
        m.add_separator()
        m.add_command(label="退出", command=self.destroy)
        bar.add_cascade(label="游戏", menu=m)
        h = tk.Menu(bar, tearoff=0, bg=UI_PANEL, fg=UI_TEXT)
        h.add_command(label="玩法与规则", command=self.show_rules)
        bar.add_cascade(label="帮助", menu=h)
        self.config(menu=bar)

    # ------------------------------------------------------------ 顶栏
    def _build_top(self) -> None:
        bar = tk.Frame(self, bg="#15181d", height=scale.px(48))
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self.lbl_turn = tk.Label(bar, text="", bg="#15181d", fg=UI_TEXT,
                                 font=(FONT, 13, "bold"))
        self.lbl_turn.pack(side="left", padx=scale.px(12))
        self.top_stats = {}
        for key, label, color in (
            ("cash", "现金", UI_TEXT), ("debt", "负债", UI_DIM),
            ("price", "股价", UI_ACCENT), ("cap", "市值", UI_GOOD),
            ("share", "市占", UI_WARN), ("policy", "监管阶段", UI_DIM),
        ):
            f = tk.Frame(bar, bg="#15181d")
            f.pack(side="left", padx=scale.px(9))
            tk.Label(f, text=label, bg="#15181d", fg="#6f7784",
                     font=(FONT, 8)).pack(anchor="w")
            lab = tk.Label(f, text="-", bg="#15181d", fg=color, font=(FONT, 11, "bold"))
            lab.pack(anchor="w")
            self.top_stats[key] = lab

    # ------------------------------------------------------------ 左栏
    def _build_left(self, parent) -> None:
        left = tk.Frame(parent, bg=UI_BG)
        left.pack(side="left", fill="both", expand=False, padx=(scale.px(6), 0),
                  pady=scale.px(6))
        self.map = MapView(left, self.on_tile_click, self.on_hover)
        self.map.pack(anchor="nw")
        # 图例
        self.legend = tk.Frame(left, bg=UI_PANEL)
        self.legend.pack(fill="x", pady=(scale.px(4), 0))
        self.legend_row = tk.Frame(self.legend, bg=UI_PANEL)
        self.legend_row.pack(fill="x", padx=scale.px(6), pady=scale.px(3))
        # 地块信息
        info = tk.Frame(left, bg=UI_PANEL)
        info.pack(fill="x", pady=(scale.px(4), 0))
        self.lbl_tile = tk.Label(info, text="点击地图查看地块", bg=UI_PANEL, fg=UI_DIM,
                                 anchor="w", justify="left",
                                 wraplength=mapview.TS * 18 - scale.px(12),
                                 font=(FONT, 9))
        self.lbl_tile.pack(fill="x", padx=scale.px(8), pady=scale.px(4))
        # 回合动态
        news = tk.Frame(left, bg=UI_PANEL)
        news.pack(fill="both", expand=True, pady=(scale.px(4), 0))
        tk.Label(news, text="回合动态", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=scale.px(8),
                                              pady=(scale.px(3), 0))
        self.log_list = tk.Listbox(news, bg=BG2, fg="#c9cfd8", bd=0, height=5,
                                   font=(FONT, 9), selectbackground="#35507a",
                                   highlightthickness=0, activestyle="none")
        self.log_list.pack(fill="both", expand=True, padx=scale.px(8),
                           pady=(scale.px(2), scale.px(6)))

    # ------------------------------------------------------------ 右栏
    def _build_right(self, parent) -> None:
        right = tk.Frame(parent, bg=UI_BG)
        right.pack(side="right", fill="both", expand=True,
                   padx=scale.px(6), pady=scale.px(6))
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_ops = tk.Frame(nb, bg=UI_PANEL)
        self.tab_fin = tk.Frame(nb, bg=UI_PANEL)
        self.tab_mkt = tk.Frame(nb, bg=UI_PANEL)
        self.tab_log = tk.Frame(nb, bg=UI_PANEL)
        nb.add(self.tab_ops, text=" 经营 ")
        nb.add(self.tab_fin, text=" 财报 ")
        nb.add(self.tab_mkt, text=" 交易所 ")
        nb.add(self.tab_log, text=" 政策·日志 ")
        self._build_ops(self.tab_ops)
        self._build_fin(self.tab_fin)
        self._build_mkt(self.tab_mkt)
        self._build_log(self.tab_log)

    # ------------------------------------------------------------ 经营页
    def _build_ops(self, root) -> None:
        P = scale.px
        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=(P(5), 0))
        tk.Label(box, text="资金与债务", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w")
        row = tk.Frame(box, bg=UI_PANEL)
        row.pack(fill="x", pady=P(1))
        self.lbl_funds = tk.Label(row, text="", bg=UI_PANEL, fg=UI_TEXT, font=(FONT, 9),
                                  anchor="w", justify="left")
        self.lbl_funds.pack(side="left")
        btns = tk.Frame(box, bg=UI_PANEL)
        btns.pack(fill="x")
        for label, cmd in (("借款 +2亿", lambda: self.do_borrow(20_000)),
                           ("还款 -2亿", lambda: self.do_repay(20_000)),
                           ("借满额度", self.do_borrow_max)):
            ttk.Button(btns, text=label, command=cmd,
                       style="Small.TButton").pack(side="left", padx=P(2))

        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=(P(4), 0))
        tk.Label(box, text="定价策略（元/MWh）", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w")
        self.var_res = tk.DoubleVar(value=500.0)
        self.var_ind = tk.DoubleVar(value=460.0)
        for label, var, hint in (("居民", self.var_res, "对涨价与停电极敏感"),
                                 ("工业", self.var_ind, "承受力强，适合放量")):
            row = tk.Frame(box, bg=UI_PANEL)
            row.pack(fill="x", pady=P(1))
            tk.Label(row, text=label, bg=UI_PANEL, fg=UI_TEXT, width=4,
                     font=(FONT, 9, "bold")).pack(side="left")
            tk.Scale(row, variable=var, from_=150, to=1200, resolution=5,
                     orient="horizontal", bg=UI_PANEL, fg=UI_TEXT, showvalue=0,
                     troughcolor="#3d4655", activebackground=UI_ACCENT,
                     sliderrelief="flat", highlightthickness=0, bd=0,
                     length=P(300), sliderlength=P(16),
                     command=lambda v: self.on_price_change()).pack(side="left", padx=P(3))
            tk.Label(row, textvariable=var, bg=UI_PANEL, fg=UI_ACCENT, width=4,
                     font=(FONT, 10, "bold")).pack(side="left", padx=P(4))
            tk.Label(row, text=hint, bg=UI_PANEL, fg="#6f7784",
                     font=(FONT, 8)).pack(side="left")
        self.lbl_cost = tk.Label(box, text="", bg=UI_PANEL, fg=UI_DIM, font=(FONT, 8),
                                 justify="left", anchor="w")
        self.lbl_cost.pack(fill="x")
        self.lbl_antitrust = tk.Label(box, text="", bg=UI_PANEL, fg=UI_WARN,
                                      font=(FONT, 8), justify="left", anchor="w")
        self.lbl_antitrust.pack(fill="x")

        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=(P(4), 0))
        tk.Label(box, text="电厂与在建工程", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w")
        cols = ("kind", "cap", "cf", "fixed", "gen", "status")
        self.tv_plants = ttk.Treeview(box, columns=cols, show="headings", height=4)
        for c, t, w in (("kind", "电厂", 100), ("cap", "容量", 55), ("cf", "出力", 50),
                        ("fixed", "固定成本/季", 85), ("gen", "本季发电", 80),
                        ("status", "状态", 80)):
            self.tv_plants.heading(c, text=t)
            self.tv_plants.column(c, width=P(w), anchor="center")
        self.tv_plants.pack(fill="x")
        self.tv_projects = ttk.Treeview(box, columns=("name", "left", "cost"),
                                        show="headings", height=2)
        for c, t, w in (("name", "在建工程", 140), ("left", "剩余工期", 70),
                        ("cost", "已投", 90)):
            self.tv_projects.heading(c, text=t)
            self.tv_projects.column(c, width=P(w), anchor="center")
        self.tv_projects.tag_configure("empty", foreground="#6f7784")
        self.tv_projects.pack(fill="x", pady=(P(3), 0))

        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=(P(4), 0))
        head = tk.Frame(box, bg=UI_PANEL)
        head.pack(fill="x")
        tk.Label(head, text="建造（先选类型，再点地图）", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(side="left")
        ttk.Button(head, text="取消", command=self.cancel_build,
                   style="Small.TButton").pack(side="right")
        grid = tk.Frame(box, bg=UI_PANEL)
        grid.pack(fill="x")
        self.build_buttons: dict[str, ttk.Button] = {}
        items = [(k, PLANT_SPECS[k]) for k in PLANT_SPECS] + \
                [(k, INFRA_SPECS[k]) for k in INFRA_SPECS]
        for i, (kind, spec) in enumerate(items):
            r, c = divmod(i, 4)
            cost = spec.capex if kind in INFRA_SPECS else spec.capex_per_mw * spec.cap
            b = ttk.Button(grid, text=f"{spec.name} {money(cost)}", width=13,
                           command=lambda k=kind: self.set_build(k))
            b.grid(row=r, column=c, padx=P(1), pady=P(1), sticky="ew")
            self.build_buttons[kind] = b
        for c in range(4):
            grid.columnconfigure(c, weight=1)
        # 内联校验：钱不够/没地块的类型直接置灰，并说明原因（不让玩家点了才报错）
        self.lbl_build_info = tk.Label(box, text="", bg=UI_PANEL, fg=UI_DIM,
                                       font=(FONT, 8), anchor="w", justify="left")
        self.lbl_build_info.pack(fill="x", pady=(P(2), 0))

        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=(P(4), P(8)))
        self.lbl_staff = tk.Label(box, text="", bg=UI_PANEL, fg=UI_TEXT,
                                  font=(FONT, 9), justify="left", anchor="w")
        self.lbl_staff.pack(fill="x")
        row = tk.Frame(box, bg=UI_PANEL)
        row.pack(fill="x", pady=P(1))
        for label, cmd in (("招运营 +2", lambda: self.do_hire(2, 0)),
                           ("招工程 +1", lambda: self.do_hire(0, 1)),
                           ("裁运营 -2", lambda: self.do_fire(2, 0))):
            ttk.Button(row, text=label, command=cmd,
                       style="Small.TButton").pack(side="left", padx=P(2))
        row2 = tk.Frame(box, bg=UI_PANEL)
        row2.pack(fill="x", pady=P(1))
        tk.Label(row2, text="分红率", bg=UI_PANEL, fg=UI_TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.var_payout = tk.DoubleVar(value=0.35)
        tk.Scale(row2, variable=self.var_payout, from_=0.0, to=DIVIDEND_MAX,
                 resolution=0.05, orient="horizontal", bg=UI_PANEL, fg=UI_TEXT,
                 showvalue=0, troughcolor="#3d4655", activebackground=UI_ACCENT,
                 sliderrelief="flat", highlightthickness=0, bd=0, length=P(200),
                 sliderlength=P(16),
                 command=lambda v: self.on_payout()).pack(side="left", padx=P(4))
        self.lbl_subsidy = tk.Label(row2, text="", bg=UI_PANEL, fg=UI_DIM,
                                    font=(FONT, 8))
        self.lbl_subsidy.pack(side="left")

    # ------------------------------------------------------------ 财报页
    def _build_fin(self, root) -> None:
        P = scale.px
        top = tk.Frame(root, bg=UI_PANEL)
        top.pack(fill="x", padx=P(8), pady=(P(6), 0))
        self.lbl_fin_head = tk.Label(top, text="", bg=UI_PANEL, fg=UI_ACCENT,
                                     font=(FONT, 11, "bold"), justify="left", anchor="w")
        self.lbl_fin_head.pack(fill="x")
        self.lbl_fin_kpi = tk.Label(top, text="", bg=UI_PANEL, fg=UI_TEXT,
                                    font=(FONT, 9), justify="left", anchor="w")
        self.lbl_fin_kpi.pack(fill="x", pady=(P(2), P(4)))
        self.tv_fin = ttk.Treeview(root, columns=("item", "val"), show="headings", height=13)
        self.tv_fin.heading("item", text="利润表科目（本季度）")
        self.tv_fin.heading("val", text="金额")
        self.tv_fin.column("item", width=P(240), anchor="w")
        self.tv_fin.column("val", width=P(150), anchor="e")
        self.tv_fin.pack(fill="both", expand=True, padx=P(8))
        self.tv_fin.tag_configure("cost", foreground="#d99a9a")
        self.tv_fin.tag_configure("sum", foreground="#ffffff", background="#2c313a")
        self.tv_fin.tag_configure("profit", foreground=UI_GOOD)

        box = tk.Frame(root, bg=UI_PANEL)
        box.pack(fill="x", padx=P(8), pady=P(6))
        tk.Label(box, text="季度净利润走势（近 12 季，单位：万元）", bg=UI_PANEL,
                 fg=UI_DIM, font=(FONT, 8)).pack(anchor="w")
        self.spark = tk.Canvas(box, height=P(56), bg=BG2, highlightthickness=0)
        self.spark.pack(fill="x", pady=(P(2), 0))

    # ------------------------------------------------------------ 交易所页
    def _build_mkt(self, root) -> None:
        P = scale.px
        head = tk.Frame(root, bg=UI_PANEL)
        head.pack(fill="x", padx=P(8), pady=(P(6), P(2)))
        self.lbl_ceo = tk.Label(head, text="", bg=UI_PANEL, fg=UI_TEXT,
                                font=(FONT, 10, "bold"), justify="left", anchor="w")
        self.lbl_ceo.pack(fill="x")
        cols = ("name", "price", "chg", "cap", "my", "equity", "debt", "np", "state")
        self.tv_mkt = ttk.Treeview(root, columns=cols, show="headings", height=5)
        for c, t, w in (("name", "公司", 78), ("price", "股价", 50), ("chg", "涨跌", 50),
                        ("cap", "市值", 64), ("my", "我的持股", 58), ("equity", "净资产", 64),
                        ("debt", "负债率", 46), ("np", "季度净利", 64), ("state", "状态", 54)):
            self.tv_mkt.heading(c, text=t)
            self.tv_mkt.column(c, width=P(w), anchor="center")
        self.tv_mkt.pack(fill="x", padx=P(8))
        self.tv_mkt.bind("<<TreeviewSelect>>", lambda e: self.refresh_mkt_controls())

        ctrl = tk.Frame(root, bg=UI_PANEL)
        ctrl.pack(fill="x", padx=P(8), pady=(P(6), 0))
        tk.Label(ctrl, text="数量（占总股本 %）", bg=UI_PANEL, fg=UI_TEXT,
                 font=(FONT, 9)).pack(side="left")
        self.var_qty = tk.StringVar(value="2")
        ttk.Spinbox(ctrl, from_=0.5, to=20, increment=0.5, width=5,
                    textvariable=self.var_qty).pack(side="left", padx=P(3))
        self.lbl_deal = tk.Label(ctrl, text="", bg=UI_PANEL, fg=UI_DIM, font=(FONT, 8))
        self.lbl_deal.pack(side="left", padx=P(4))

        row = tk.Frame(root, bg=UI_PANEL)
        row.pack(fill="x", padx=P(8), pady=P(3))
        for label, cmd in (
            ("公司账户买入", lambda: self.do_buy(company_fund=True)),
            ("CEO账户买入", lambda: self.do_buy(company_fund=False)),
            ("卖出", self.do_sell),
            ("回购自家", self.do_buyback),
            ("增发", self.do_issue),
        ):
            ttk.Button(row, text=label, command=cmd,
                       style="Small.TButton").pack(side="left", padx=P(2))

        row2 = tk.Frame(root, bg=UI_PANEL)
        row2.pack(fill="x", padx=P(8), pady=P(2))
        for label, cmd in (("控股接管 51%", self.do_take_control),
                           ("吸收合并 75%", self.do_merge),
                           ("强制全额分红", self.do_sweep)):
            ttk.Button(row2, text=label, command=cmd,
                       style="Small.TButton").pack(side="left", padx=P(2))

        self.lbl_stake = tk.Label(root, text="", bg=UI_PANEL, fg=UI_DIM,
                                  font=(FONT, 9), justify="left", anchor="w",
                                  wraplength=P(560))
        self.lbl_stake.pack(fill="x", padx=P(8), pady=(P(4), 0))

        tk.Label(root, text="控股子公司资产处置", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w", padx=P(8), pady=(P(6), P(2)))
        self.lb_subs = tk.Listbox(root, bg=BG2, fg=UI_TEXT, bd=0, height=4,
                                  font=(FONT, 9), highlightthickness=0)
        self.lb_subs.pack(fill="x", padx=P(8))
        btns = tk.Frame(root, bg=UI_PANEL)
        btns.pack(fill="x", padx=P(8), pady=P(4))
        ttk.Button(btns, text="淘汰选中机组（省固定成本）", command=self.do_retire,
                   style="Small.TButton").pack(side="left")
        tk.Label(root, text="对手情报（机组 / 电价 / 财务风险）", bg=UI_PANEL, fg=UI_ACCENT,
                 font=(FONT, 10, "bold")).pack(anchor="w", padx=P(8), pady=(P(4), P(2)))
        self.txt_intel = tk.Text(root, bg=BG2, fg="#c9cfd8", bd=0, height=7, wrap="word",
                                 font=(FONT, 9), highlightthickness=0, padx=P(6), pady=P(4))
        self.txt_intel.pack(fill="both", expand=True, padx=P(8), pady=(0, P(8)))
        self.txt_intel.configure(state="disabled")

    # ------------------------------------------------------------ 日志页
    def _build_log(self, root) -> None:
        P = scale.px
        top = tk.Frame(root, bg=UI_PANEL)
        top.pack(fill="x", padx=P(8), pady=(P(6), 0))
        self.lbl_policy = tk.Label(top, text="", bg=UI_PANEL, fg=UI_TEXT,
                                   font=(FONT, 9), justify="left", anchor="w")
        self.lbl_policy.pack(fill="x")
        self.lbl_market = tk.Label(top, text="", bg=UI_PANEL, fg=UI_TEXT,
                                   font=(FONT, 9), justify="left", anchor="w")
        self.lbl_market.pack(fill="x", pady=(P(2), P(2)))
        self.lbl_weather = tk.Label(top, text="", bg=UI_PANEL, fg=UI_DIM,
                                    font=(FONT, 9), justify="left", anchor="w")
        self.lbl_weather.pack(fill="x", pady=(0, P(4)))
        self.txt_log = tk.Text(root, bg=BG2, fg="#c9cfd8", bd=0, wrap="word",
                               font=(FONT, 9), highlightthickness=0,
                               padx=P(6), pady=P(4))
        self.txt_log.pack(fill="both", expand=True, padx=P(8), pady=(0, P(8)))
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------ 底栏
    def _build_bottom(self) -> None:
        P = scale.px
        bar = tk.Frame(self, bg="#15181d", height=P(46))
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.btn_end = ttk.Button(bar, text="结束回合  ▶", command=self.end_turn,
                                  style="Accent.TButton")
        self.btn_end.pack(side="right", padx=P(10), pady=P(7))
        self.lbl_hint = tk.Label(bar, text="选择建筑类型后点击地图建造；调好电价再结束回合",
                                 bg="#15181d", fg=UI_DIM, font=(FONT, 9), anchor="w")
        self.lbl_hint.pack(side="left", padx=P(12))
        self.lbl_short = tk.Label(bar, text="", bg="#15181d", fg=UI_TEXT,
                                  font=(FONT, 9), anchor="w")
        self.lbl_short.pack(side="left")

    # ------------------------------------------------------------ 交互：地图
    def toast(self, msg: str, bad: bool = False, ms: int = 2600) -> None:
        """就近反馈：底部状态条显示 2.6 秒后自动回到当前提示。"""
        self.lbl_hint.config(text=("✕ " if bad else "✓ ") + msg,
                             fg=UI_BAD if bad else UI_GOOD)
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except Exception:  # noqa: BLE001
                pass
        self._toast_job = self.after(ms, self._restore_hint)

    def _restore_hint(self) -> None:
        self._toast_job = None
        self.lbl_hint.config(text=self._idle_hint(), fg=UI_DIM)

    def _idle_hint(self) -> str:
        if self.build_mode:
            name = (PLANT_SPECS[self.build_mode].name if self.build_mode in PLANT_SPECS
                    else INFRA_SPECS[self.build_mode].name)
            n = len(self.map.valid_tiles)
            return f"建造模式：{name} · 可建 {n} 处（其余地块已变暗）· 点击地图确认，Esc 退出"
        return "选择建筑类型后点击地图建造；调好电价再结束回合"

    def on_tile_click(self, x: int, y: int) -> None:
        self.selected = (x, y)
        me = self.game.player
        if self.build_mode:
            kind = self.build_mode
            ok, why = self.game.can_build(me, kind, x, y)
            if ok and self.game.build(me, kind, x, y):
                self.map.draw(self.game)
                self.refresh()
                return
            self.toast(f"无法建造：{why}", bad=True)
            self.map.draw(self.game)
            return
        self.update_tile_label()
        self.map.draw(self.game)

    def on_hover(self, pos) -> None:
        if pos is None or self.game is None:
            return
        t = self.game.world.tile(*pos)
        if self.build_mode:
            kind = self.build_mode
            ok, why = self.game.world.check_build(kind, *pos)
            name = PLANT_SPECS[kind].name if kind in PLANT_SPECS else INFRA_SPECS[kind].name
            price = self.game.total_build_cost(self.game.player, kind, *pos)
            self.lbl_tile.config(
                text=f"({pos[0]},{pos[1]}) {TERRAIN_INFO[t.terrain].name} · {name} "
                     f"造价 {money(price)} · " + ("可建造，点击确认" if ok else f"不可建：{why}"),
                fg=UI_GOOD if ok else UI_BAD)
        elif t.kind == "city":
            self.lbl_tile.config(text=tile_tooltip(self.game, *pos), fg=UI_TEXT)

    def update_tile_label(self) -> None:
        if not self.selected:
            return
        self.lbl_tile.config(text=tile_tooltip(self.game, *self.selected), fg=UI_TEXT)

    def set_build(self, kind: str) -> None:
        self.build_mode = kind
        me = self.game.player
        valid = {(t.x, t.y) for t in self.game.world.iter_tiles()
                 if self.game.can_build(me, kind, t.x, t.y)[0]}
        self.map.build_mode = kind
        self.map.valid_tiles = valid
        self.map.draw(self.game)
        self._restore_hint()

    def cancel_build(self) -> None:
        self.build_mode = None
        self.map.build_mode = None
        self.map.valid_tiles = set()
        self.map.draw(self.game)
        self.lbl_hint.config(text=self._idle_hint(), fg=UI_DIM)

    # ------------------------------------------------------------ 交互：按钮
    def do_borrow(self, amount: float) -> None:
        try:
            self.game.borrow(self.game.player, amount)
        except ValueError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_borrow_max(self) -> None:
        me = self.game.player
        self.do_borrow(max(0.0, me.assets() * LOAN_LIMIT_RATIO - me.debt))

    def do_repay(self, amount: float) -> None:
        try:
            self.game.repay(self.game.player, amount)
        except ValueError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_hire(self, ops: int, eng: int) -> None:
        try:
            self.game.hire(self.game.player, ops, eng)
        except ValueError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_fire(self, ops: int, eng: int) -> None:
        try:
            self.game.fire(self.game.player, ops, eng)
        except ValueError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def on_price_change(self) -> None:
        if self._syncing:
            return
        me = self.game.player
        cap = self.game.policy.price_cap
        me.res_price = min(cap, float(self.var_res.get()))
        me.ind_price = min(cap, float(self.var_ind.get()))
        self.update_cost_label()

    def on_payout(self) -> None:
        if self._syncing:
            return
        self.game.player.payout = float(self.var_payout.get())
        self.refresh()

    def update_cost_label(self) -> None:
        me = self.game.player
        st = me.last_income
        mwh = max(1.0, st.served_mwh)
        var = st.fuel * 10_000.0 / mwh if st.fuel > 0 else 0.0
        fixed = (st.fixed + st.depreciation + st.labor + st.grid) * 10_000.0 / mwh
        unit = var + fixed
        self.lbl_cost.config(
            text=f"上季单位成本：可变 {var:.0f} + 固定 {fixed:.0f} = {unit:.0f} 元/MWh   "
                 f"营收 {money(st.revenue)}   净利 {money(st.net_profit)}")
        warn = ""
        if me.market_share > ANTITRUST_SHARE and (
                me.res_price < unit * 0.98 or me.ind_price < unit * 0.98):
            warn = "⚠ 市占率超过 55% 且低于成本价销售，反垄断风险上升（连续 3 回合触发处罚）"
        self.lbl_antitrust.config(text=warn)

    # ------------------------------------------------------------ 交互：股票
    def _sel_company(self) -> Company | None:
        sel = self.tv_mkt.selection()
        if not sel:
            return None
        return self.game.companies[int(sel[0])]

    def _qty(self, tgt: Company) -> float:
        try:
            pct = float(self.var_qty.get()) / 100.0
        except ValueError:
            pct = 0.02
        return tgt.shares * max(0.001, pct)

    def do_buy(self, company_fund: bool) -> None:
        tgt = self._sel_company()
        if not tgt:
            self.toast("先在表格里选中一家公司", bad=True)
            return
        me = self.game.player
        if tgt.idx == me.idx:
            self.toast("买自家股票请用【回购自家】", bad=True)
            return
        holder = me.idx if company_fund else "CEO"
        try:
            qty = self._qty(tgt)
            cost = ma.buy_cost(tgt, qty)
            ma.buy_shares(self.game, holder, tgt, qty)
            self.toast(f"买入 {tgt.name} {qty:,.0f}万股，花费 {money(cost)}")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_sell(self) -> None:
        tgt = self._sel_company()
        if not tgt:
            self.toast("先选中一家公司", bad=True)
            return
        me = self.game.player
        holder = me.idx if me.holdings.get(tgt.idx, 0) >= self.game.ceo_holdings.get(tgt.idx, 0) else "CEO"
        try:
            got = ma.sell_shares(self.game, holder, tgt, tgt.shares * 0.5)
            self.toast(f"卖出套现 {money(got)}")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_buyback(self) -> None:
        me = self.game.player
        try:
            ma.buyback(self.game, me, me.shares * 0.02)
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_issue(self) -> None:
        me = self.game.player
        try:
            cash = ma.issue_shares(self.game, me, me.shares * 0.06)
            self.toast(f"增发募资 {money(cash)}")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_take_control(self) -> None:
        tgt = self._sel_company()
        if not tgt:
            return
        try:
            ma.take_control(self.game, tgt)
            self.toast(f"已控股 {tgt.name}")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_merge(self) -> None:
        tgt = self._sel_company()
        if not tgt:
            return
        if not messagebox.askyesno("吸收合并",
                                   f"确认吸收合并 {tgt.name}？\n将接收其全部资产、电厂、矿权与负债，"
                                   f"并支付整合费。"):
            return
        try:
            ma.absorb_merge(self.game, tgt)
            self.toast(f"{tgt.name} 已并入你的集团")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_sweep(self) -> None:
        tgt = self._sel_company()
        if not tgt:
            return
        try:
            ma.force_dividend(self.game, tgt)
            self.toast(f"{tgt.name} 已改为全额分红")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    def do_retire(self) -> None:
        sel = self.lb_subs.curselection()
        if not sel:
            self.toast("先选中要淘汰的机组", bad=True)
            return
        try:
            key = self._sub_keys[sel[0]]
            idx, plant_id = (int(v) for v in key.split("|"))
        except (ValueError, IndexError):
            self.toast("无法解析机组", bad=True)
            return
        try:
            ma.retire_plant(self.game, self.game.companies[idx], plant_id, by_player=True)
            self.toast("机组已淘汰，固定成本下降")
        except MaError as e:
            self.toast(str(e), bad=True)
        self.refresh()

    # ------------------------------------------------------------ 回合
    def end_turn(self) -> None:
        if self.game.game_over:
            return
        self.build_mode = None
        self.map.build_mode = None
        self.game.end_turn()
        self.refresh()
        self.after(30, self._after_turn)

    def _after_turn(self) -> None:
        g = self.game
        if g.game_over:
            title = {"victory_dominance": "🏆 霸权结局",
                     "victory_green": "🌿 绿色转型结局",
                     "defeat": "💀 出局"}.get(g.result, "任期满")
            messagebox.showinfo(title, g.result_detail + "\n\n点击确定开始新游戏。")
            self.new_game()
            return
        self.lbl_hint.config(text=f"第 {g.turn} 回合开始 · {g.policy.summary()}", fg=UI_DIM)

    def new_game(self) -> None:
        self.game = Game.new_game()
        self.build_mode = None
        self.map.build_mode = None
        self.map.valid_tiles = set()
        self.selected = None
        self.refresh()

    def _intro(self) -> None:
        messagebox.showinfo(
            "开局提示",
            "你接手了一家地方电力公司（盛阳电力）。\n\n"
            "· 临江只有 300MW 需求，钢城 560MW 完全没人供电——先抢地盘。\n"
            "· 建厂前先看地形：火电要冷却水、水电只能沿河、核电要远离城市。\n"
            "· 电厂必须靠【变电站 + 输电线路】接到城市，否则电送不出去。\n"
            "· 固定成本每季度照扣，别盲目堆装机；电价太高丢客户，太低亏钱。\n"
            "· 对手财报变差时股价会跌——那就是你低价收购的机会。\n\n"
            "详细规则见菜单【帮助 → 玩法与规则】。")

    def save_game(self) -> None:
        import pickle
        path = paths.save_file()
        try:
            with open(path, "wb") as f:
                pickle.dump(self.game, f)
            self.toast(f"已保存到 {path}")
        except Exception as e:  # noqa: BLE001
            self.toast(f"保存失败：{e}", bad=True)

    def load_game(self) -> None:
        import pickle
        path = paths.save_file()
        if not path.exists():
            self.toast("没有找到存档", bad=True)
            return
        try:
            with open(path, "rb") as f:
                self.game = pickle.load(f)
            self.build_mode = None
            self.map.build_mode = None
            self.map.valid_tiles = set()
            self.selected = None
            self.refresh()
            self.toast(f"读取成功：{path}")
        except Exception as e:  # noqa: BLE001
            self.toast(f"读取失败：{e}", bad=True)

    def show_rules(self) -> None:
        win = tk.Toplevel(self)
        win.title("玩法与规则")
        win.geometry(f"{scale.px(760)}x{scale.px(640)}")
        win.configure(bg=UI_BG)
        txt = tk.Text(win, bg=BG2, fg=UI_TEXT, wrap="word", font=(FONT, 10),
                      padx=scale.px(12), pady=scale.px(10), bd=0)
        txt.pack(fill="both", expand=True, padx=scale.px(8), pady=scale.px(8))
        txt.insert("1.0", RULES)
        txt.configure(state="disabled")

    # ------------------------------------------------------------ 刷新
    def refresh(self) -> None:
        g = self.game
        me = g.player
        self._syncing = True
        P = scale.px

        self.lbl_turn.config(text=g.turn_label())
        self.top_stats["cash"].config(text=money(me.cash))
        self.top_stats["debt"].config(text=money(me.debt))
        pct = (me.price / me.price_prev - 1.0) * 100 if me.price_prev else 0.0
        arrow = "▲ " if pct > 0.05 else ("▼ " if pct < -0.05 else "")
        self.top_stats["price"].config(
            text=f"{arrow}{me.price:.2f}", fg=UI_GOOD if pct >= 0 else UI_BAD)
        self.top_stats["cap"].config(text=money(me.market_cap()))
        self.top_stats["share"].config(text=f"{g.player_share():.1%}")
        self.top_stats["policy"].config(text=g.policy.stage())

        self.var_res.set(round(me.res_price))
        self.var_ind.set(round(me.ind_price))
        self.var_payout.set(round(me.payout, 2))

        self.lbl_funds.config(
            text=f"现金 {money(me.cash)}    负债 {money(me.debt)}     "
                 f"负债率 {me.debt_ratio():.0%}（上限 {LOAN_LIMIT_RATIO:.0%}）    "
                 f"剩余额度 {money(max(0.0, me.assets() * LOAN_LIMIT_RATIO - me.debt))}")
        self.lbl_staff.config(
            text=f"运营班组 {me.ops_staff}/{me.staff_need()}（满足率 {me.staff_ratio():.0%}，缺人压出力）  "
                 f"工程队 {me.eng_teams}（在建 {len(me.projects)} 项）  声望 {me.reputation:.0f}")
        self.lbl_subsidy.config(text=f"新能源 {me.renewable_share():.0%}"
                                     f"/配额 {g.policy.renewable_quota:.0%}")
        self.update_cost_label()

        st = me.last_income
        tv = self.tv_plants
        tv.delete(*tv.get_children())
        short = me.staff_ratio() < 0.99
        for p in me.plants:
            if not p.online:
                status = "停机检修"
            elif short:
                status = f"缺人 · 出力×{max(0.55, me.staff_ratio()):.0%}"
            else:
                status = "运行"
            tv.insert("", "end", values=(
                p.name, f"{p.cap:.0f}MW", f"{p.cf_actual:.0%}",
                f"{p.fixed_q:,.0f}万", f"{p.dispatched_mwh:,.0f}", status))
        tp = self.tv_projects
        tp.delete(*tp.get_children())
        if not me.projects:
            tp.insert("", "end", values=("暂无在建工程", "—", "—"), tags=("empty",))
        for pr in me.projects:
            tp.insert("", "end", values=(pr.name, f"{pr.turns_left} 回合", f"{pr.spent:,.0f}万"))

        st = me.last_income
        self.lbl_fin_head.config(text=f"{me.name} · {g.year_of()}年 第{(g.turn - 1) % 4 + 1}季度 利润表")
        self.lbl_fin_kpi.config(
            text=f"净资产 {money(me.equity())}    总资产 {money(me.assets())}    "
                 f"季度净利 {money(st.net_profit)}    ROE {st.net_profit / max(1.0, me.equity()):.1%}/季    "
                 f"碳强度 {me.carbon_intensity() * 1000:.0f}g/kWh    新能源 {me.renewable_share():.0%}")
        tvf = self.tv_fin
        tvf.delete(*tvf.get_children())
        for name, val, is_cost in st.rows():
            if abs(val) < 0.5:
                continue
            tvf.insert("", "end", values=(name, money(val)), tags=("cost",) if is_cost else ())
        tvf.insert("", "end", values=("营业收入合计", money(st.revenue)), tags=("sum",))
        tvf.insert("", "end", values=("成本合计", money(-st.total_cost)), tags=("sum",))
        tvf.insert("", "end", values=("净利润", money(st.net_profit)), tags=("profit",))
        self._draw_spark()

        self.refresh_market()
        self.lbl_policy.config(
            text=f"政策阶段：{g.policy.stage()}    {g.policy.summary()}\n"
                 f"下一档：" + self._next_policy_text())
        self.lbl_market.config(
            text=f"大宗：煤 {g.market['coal']:,.0f} 元/吨（{g.commodity_mod['coal']:.2f}x）    "
                 f"铀 {g.market['uranium']:,.0f} 元/吨    外购电价 880 元/MWh")
        self.lbl_weather.config(
            text=f"本季天气：来水 {g.weather['rain']:.2f}   风 {g.weather['wind']:.2f}   "
                 f"光 {g.weather['solar']:.2f}   气温 {g.weather['heat']:.2f}   "
                 f"需求系数 {g.demand_shock:.2f}")
        self._refresh_log()
        self._refresh_legend()
        self.map.selected = self.selected
        if self.build_mode:
            self.set_build(self.build_mode)
        else:
            self.map.draw(g)
        if self.selected:
            self.update_tile_label()

        self._syncing = False
        self._sync_build_buttons()
        self.btn_end.config(state="disabled" if g.game_over else "normal")

    def _kind_cost(self, kind: str) -> float:
        """按钮上标注的基础造价（未含地形乘数，用作可负担性判断的下界）。"""
        if kind in PLANT_SPECS:
            spec = PLANT_SPECS[kind]
            return spec.capex_per_mw * spec.cap
        return INFRA_SPECS[kind].capex

    def _sync_build_buttons(self) -> None:
        """内联校验：不可行的建造类型直接置灰，并在下方说明原因。"""
        me = self.game.player
        ready = 0
        missing: dict[str, list[str]] = {}
        for kind, btn in self.build_buttons.items():
            cost = self._kind_cost(kind)
            name = (PLANT_SPECS[kind].name if kind in PLANT_SPECS
                    else INFRA_SPECS[kind].name)
            tiles = sum(1 for t in self.game.world.iter_tiles()
                        if self.game.world.check_build(kind, t.x, t.y)[0])
            approved = (kind != "nuclear") or self.game.policy.nuclear_approved
            can_pay = me.cash >= cost * 1.05
            ok = tiles > 0 and can_pay and approved
            btn.state(["!disabled"] if ok else ["disabled"])
            if ok:
                ready += 1
            elif not approved:
                missing.setdefault("核电待核准", []).append(name)
            elif tiles == 0:
                missing.setdefault("无地可建", []).append(name)
            else:
                missing.setdefault(f"缺 {money(cost - me.cash)}", []).append(name)
        if ready == len(self.build_buttons):
            text, color = f"当前 {ready}/{len(self.build_buttons)} 类可开工", UI_DIM
        else:
            parts = [f"{k}：{'/'.join(v)}" for k, v in missing.items()]
            text = (f"当前可开工 {ready}/{len(self.build_buttons)} · "
                    + "；".join(parts[:2]) + (f" 等 {len(parts)} 项" if len(parts) > 2 else ""))
            color = UI_WARN
        self.lbl_build_info.config(text=text, fg=color)

    def _next_policy_text(self) -> str:
        g = self.game
        for step in POLICY_SCHEDULE:
            if step.turn > g.turn:
                return (f"第 {step.turn} 回合起：碳税 {step.carbon_tax:.0f}元/t、"
                        f"新能源配额 {step.renewable_quota:.0%}、电价上限 {step.price_cap:.0f}")
        return "已到最终监管档位"

    def _refresh_legend(self) -> None:
        P = scale.px
        for w in self.legend_row.winfo_children():
            w.destroy()
        for i, co in enumerate(self.game.companies):
            if not co.alive:
                continue
            tk.Frame(self.legend_row, bg=COMPANY_COLORS[i % len(COMPANY_COLORS)],
                     width=P(11), height=P(11)).pack(side="left", padx=(P(4), P(2)))
            tag = "（你）" if co.is_player else ("（子公司）" if co.delisted else "")
            tk.Label(self.legend_row, text=f"{co.name}{tag}", bg=UI_PANEL, fg=UI_DIM,
                     font=(FONT, 8)).pack(side="left")

    def refresh_market(self) -> None:
        g = self.game
        tv = self.tv_mkt
        tv.delete(*tv.get_children())
        for co in g.companies:
            if not co.alive:
                continue
            chg = (co.price / co.price_prev - 1.0) * 100 if co.price_prev else 0.0
            my = player_stake(g, co)
            np_ = co.profit_history[-1] if co.profit_history else 0.0
            state = "你的公司" if co.is_player else (
                "已退市" if co.delisted else
                ("已控股" if co.controlled_by == g.player_idx else "对手"))
            tv.insert("", "end", iid=str(co.idx), values=(
                co.name, f"{co.price:.2f}", f"{chg:+.1f}%", money(co.market_cap()),
                f"{my:.1%}", money(co.equity()), f"{co.debt_ratio():.0%}",
                money(np_), state))
        self.lbl_ceo.config(
            text=f"CEO 个人账户：{money(g.ceo_cash)}（每季工资 220万 + 股利）    "
                 f"公司现金：{money(g.player.cash)}")
        self.lb_subs.delete(0, "end")
        self._sub_keys = []
        for co in g.companies:
            if co.controlled_by != g.player_idx or co.delisted or co.is_player:
                continue
            for p in co.plants:
                self.lb_subs.insert("end", f"{co.name} · {p.name} {p.cap:.0f}MW "
                                           f"固定 {p.fixed_q:,.0f}万/季 [{p.id}]")
                self._sub_keys.append(f"{co.idx}|{p.id}")
        if not self._sub_keys:
            self.lb_subs.insert("end", "尚未控股任何公司（持股 51% 后可在此处置其机组）")
            self.lb_subs.itemconfig(0, foreground="#6f7784")
        self._refresh_intel()
        self.refresh_mkt_controls()

    def refresh_mkt_controls(self) -> None:
        tgt = self._sel_company()
        if not tgt:
            self.lbl_stake.config(text="选中一家公司查看股权结构")
            return
        st = player_stake(self.game, tgt)
        own = ownership(self.game, tgt)
        parts = [f"{k} {v:.1%}" for k, v in own.items() if v > 0.001]
        qty = self._qty(tgt)
        self.lbl_stake.config(
            text=f"{tgt.name}：你的合计持股 {st:.1%}（51% 控股 / 75% 合并）    "
                 f"{qty:,.0f} 万股约需 {money(ma.buy_cost(tgt, qty))}\n"
                 f"股权结构：" + "   ".join(parts))

    def _refresh_intel(self) -> None:
        g = self.game
        lines = []
        for co in g.companies:
            if not co.alive or co.delisted or co.is_player:
                continue
            mix: dict[str, int] = {}
            for p in co.plants:
                mix[p.name] = mix.get(p.name, 0) + 1
            mix_s = "、".join(f"{k}×{v}" for k, v in mix.items()) or "无机组"
            np_ = co.profit_history[-1] if co.profit_history else 0.0
            pbr = co.price / max(0.01, co.book_per_share())
            risk = []
            if pbr < 0.6:
                risk.append("股价远低于净资产（收购窗口）")
            if co.debt_ratio() > 0.55:
                risk.append("高负债")
            if np_ < 0:
                risk.append("亏损")
            if co.controlled_by == g.player_idx:
                risk.append("已被你控股")
            lines.append(
                f"{co.name}　装机 {co.gen_capacity():.0f}MW　{mix_s}　"
                f"电价 {co.res_price:.0f}/{co.ind_price:.0f}　负债率 {co.debt_ratio():.0%}\n"
                f"　　现金 {money(co.cash)}　季度净利 {money(np_)}　"
                f"股价/净资产 {pbr:.2f}x　可交付 {co.grid_capacity:.0f}MW　市占 {co.market_share:.0%}\n"
                f"　　" + ("风险：" + "；".join(risk) if risk else "经营稳健"))
        self.txt_intel.configure(state="normal")
        self.txt_intel.delete("1.0", "end")
        self.txt_intel.insert("1.0", "\n".join(lines) if lines else "暂无对手")
        self.txt_intel.configure(state="disabled")

    def _draw_spark(self) -> None:
        c = self.spark
        c.delete("all")
        hist = self.game.player.profit_history[-12:]
        if not hist:
            return
        w = c.winfo_width() or scale.px(520)
        h = scale.px(56)
        lo = min(min(hist), 0.0)
        hi = max(max(hist), 1.0)
        rng = hi - lo or 1.0
        pts = []
        for i, v in enumerate(hist):
            x = scale.px(6) + (w - scale.px(12)) * i / max(1, len(hist) - 1)
            y = h - scale.px(8) - (v - lo) / rng * (h - scale.px(16))
            pts.append((x, y))
        zero_y = h - scale.px(8) - (0 - lo) / rng * (h - scale.px(16))
        c.create_line(0, zero_y, w, zero_y, fill="#3a3f47", dash=(2, 2))
        flat = [coord for p in pts for coord in p]
        if len(flat) >= 4:
            c.create_line(*flat, fill=UI_ACCENT, width=2, smooth=True)
        for (x, y), v in zip(pts, hist):
            r = scale.px(2)
            c.create_oval(x - r, y - r, x + r, y + r,
                          fill=UI_GOOD if v >= 0 else UI_BAD, outline="")

    def _refresh_log(self) -> None:
        """增量渲染日志：只追加新行，避免每次刷新重贴几百行（这是最容易被忽略的卡顿源）。"""
        lines = self.game.log_lines
        if len(lines) < self._log_rendered or self._log_rendered == 0:
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.insert("1.0", "\n".join(lines))
            self._log_rendered = len(lines)
        elif len(lines) > self._log_rendered:
            self.txt_log.configure(state="normal")
            for line in lines[self._log_rendered:]:
                self.txt_log.insert("end", "\n" + line)
            self._log_rendered = len(lines)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

        self.log_list.delete(0, "end")
        for line in lines[-40:]:
            self.log_list.insert("end", line)
        self.log_list.see("end")


RULES = """《电力公司》玩法与规则
================================================

一、核心闭环
  地形/资源 → 建电厂与电网 → 定电价抢客户 → 季度结算出财报
          → 财报决定股价 → 股价决定收购成本与风险 → 收购对手扩张

二、每回合你要做的四件事
  1. 看环境：需求、煤价/铀价、政策、对手财报与股价（政策·日志页）
  2. 调资产：建电厂/变电站/线路/矿，招人或裁员，借款或还款（经营页）
  3. 定电价：居民与工业分开定价（经营页）
  4. 股市：买对手、回购自家、控股后抽血或合并（交易所页）
  最后点【结束回合】。

三、必须理解的机制
  1. 固定成本照扣
     每座电厂每季度都要付折旧 + 运维，哪怕一度电都不发。产能过剩会直接吞掉利润。
  2. 电网不是摆设
     电厂必须和【城市半径 2 格内的变电站】通过【相邻的线路/电厂】连成一片，
     城市接口容量 = 半径内变电站(180MW) + 线路(120MW) 之和，线损随距离上升。
     送不出去的电 = 没有收入，但你依然付燃料和固定成本。
  3. 客户看两件事：电价 + 可靠性
     份额按「(市场均价/你的价)^弹性 × 口碑」分配，但每家拿到的份额不超过它的可交付容量。
     想抢份额，必须先建产能；只降价不建厂没有意义。
  4. 掠夺定价与反垄断
     把价格压到单位成本以下、同时份额超过 55%，连续 3 个回合会被罚 6000 万并禁止收购 2 回合。
  5. 财报 → 股价
     股价 = 滚动四季度 EPS × PE + 净资产锚定。市占率、负债率、口碑、事故会调整 PE。
     亏损会把股价打到净资产以下——那正是你被收购的窗口。
  6. 股权阶梯
     5% 举牌（对手警觉） / 20% 董事席位 / 51% 控股（强制分红抽血、淘汰其机组）
     / 75% 吸收合并（资产、债务、矿权、人力全部并入，对方退市）。
     对手 AI 也会用同样手段对付你，负债过高、连续亏损时最危险。

四、胜负
  胜利（任一）：
   · 霸权：全市场供电份额 ≥ 50% 且总市值第一
   · 绿色：新能源占比 ≥ 55%、碳强度 ≤ 180g/kWh、且碳税进入最高档
  失败：资不抵债破产 / 被 AI 持股超过 51%。

五、上手建议
  1. 先抢钢城：560MW 完全没人供电，建变电站 + 一座电厂就能吃下。
  2. 头 4 个季度没有碳税，抓紧用火电攒现金流，但别把装机堆到需求的 1.5 倍以上。
  3. 第 5 回合开始有碳税与新能源配额，提前铺光伏（荒漠/平原）。
  4. 看到对手股价跌到净资产 60% 以下就买；先到 51% 抽血，再到 75% 合并。
  5. 永远留一笔现金：风暴、罢工、煤价暴涨随时可能砸穿你的现金流。

六、快捷键
  Ctrl+Enter：结束回合
"""


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
