"""DPI 与像素缩放。

Windows 高分屏下 tkinter 默认被系统拉伸（发虚），这里显式声明 DPI 感知，
再按实际 DPI 计算缩放系数 S，所有像素尺寸乘 S；面板字号用点(pt)自动跟随，
canvas 内的字号用负值(像素)按格子尺寸推导。
"""
from __future__ import annotations

import ctypes

S: float = 1.0


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def init(root) -> float:
    global S
    try:
        S = max(1.0, min(3.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        S = 1.0
    return S


def px(v: float) -> int:
    return int(round(v * S))
