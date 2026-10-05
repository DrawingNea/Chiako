from core.combat import apply_damage, apply_heal, apply_temp, health_status, hp_bar, next_turn
from core.db import Combatant


def c(cid, init, hp=None, char=None):
    return Combatant(cid, 1, f"C{cid}", init, 0.5, char, None, hp, 10, 0, None)


def test_damage_and_temp():
    assert apply_damage(10, 0, 4) == (6, 0, 0)
    assert apply_damage(10, 5, 3) == (10, 2, 3)
    assert apply_damage(10, 5, 8) == (7, 0, 5)
    assert apply_damage(3, 0, 50) == (0, 0, 0)
    assert apply_damage(10, 0, -5) == (10, 0, 0)


def test_heal_and_temp():
    assert apply_heal(5, 10, 3) == 8
    assert apply_heal(5, 10, 30) == 10
    assert apply_heal(5, None, 30) == 35
    assert apply_temp(3, 5) == 5
    assert apply_temp(8, 5) == 8


def test_display():
    assert hp_bar(5, 10).startswith("▰▰▰▰▰▱")
    assert hp_bar(1, 100).startswith("▰▱")       # alive always shows a sliver
    assert hp_bar(0, 10).startswith("▱" * 10)
    assert hp_bar(None, 10) == "HP —"
    assert health_status(10, 10) == "Unhurt"
    assert health_status(6, 10) == "Hurt"
    assert health_status(5, 10) == "Bloodied"
    assert health_status(0, 10) == "Down"


def test_turn_order():
    order = [c(1, 20), c(2, 15), c(3, 10)]
    assert next_turn(order, None, 0) == (1, 1)        # combat starts
    assert next_turn(order, 1, 1) == (2, 1)
    assert next_turn(order, 3, 1) == (1, 2)           # wraps into round 2
    assert next_turn(order, 1, 1, skip={2}) == (3, 1)  # skips downed monster
    assert next_turn(order, 2, 1, skip={3}) == (1, 2)  # skip across the round boundary
    assert next_turn(order, 1, 1, skip={1, 2, 3}) == (2, 1)  # everyone skipped: just advance
    assert next_turn([], None, 0) == (None, 0)
