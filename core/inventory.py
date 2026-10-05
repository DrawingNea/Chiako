"""Formatting inventories and purses (shared by /inventory and the character sheet card)."""
from __future__ import annotations

from typing import Optional

from .db import Item
from .i18n import t

MAX_ITEM_LINES = 25


def fmt_item(qty: int, name: str) -> str:
    """'Rope' for one, '3× Rope' for more."""
    return name if qty == 1 else f"{qty}× {name}"


def fmt_money(money: dict[str, int]) -> str:
    """{'gold': 45, 'silver': 3} -> '45 gold · 3 silver'"""
    return " · ".join(f"{amount:,} {currency}" for currency, amount in money.items())


def item_lines(items: list[Item], lang: str = "en", limit: Optional[int] = MAX_ITEM_LINES) -> list[str]:
    lines = [f"• **{fmt_item(i.qty, i.name)}**" + (f" · *{i.note}*" if i.note else "")
             for i in (items[:limit] if limit else items)]
    if limit and len(items) > limit:
        lines.append(t(lang, "…and {n} more", n=len(items) - limit))
    return lines
