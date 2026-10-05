"""
Safe dice parser and evaluator (no eval).

Grammar:
    expr   := term (('+' | '-') term)*
    term   := unary (('*' | '/') unary)*
    unary  := ('-' | '+') unary | atom
    atom   := number [dice] | '(' expr ')' [dice] | dice | '@' name | name ['(' expr (',' expr)* ')']
    dice   := 'd' (sides | '%' | 'F') modifier*
    modifier := kh N | kl N | k N | dh N | dl N | d N | r N | ! [N] | (>= | <= | > | < | =) N | f N

A bare name is a skill or macro and is expanded through `name_resolver`. A macro can take values:
'$1d10!>=8' saved as `pool` is rolled as `pool(7)`, which becomes '(7)d10!>=8'.
Division rounds down.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

_rng = random.SystemRandom()

MAX_LENGTH = 500
MAX_DICE = 100           # dice in one group, e.g. 100d6
MAX_TOTAL_DICE = 300     # all dice in one roll, explosions and rerolls included
MAX_EXPLOSIONS = 100     # extra dice from one exploding group
MAX_SIDES = 1000
MAX_DEPTH = 10           # skills/macros using other skills/macros
MAX_NAME_LEN = 32

StatResolver = Callable[[str], int]
NameResolver = Callable[[str], Optional[str]]


class DiceError(Exception):
    """Invalid roll or formula; the message is shown to the user."""


class UnknownReference(DiceError):
    """A stat, skill or macro that doesn't exist (yet)."""


class DiceNotAllowed(DiceError):
    """Dice in a formula that must be a fixed number (stats, dice counts)."""


# ------------------------------------------------------------------ names & labels

_NAME_RE = re.compile(r"[a-z_][a-z0-9_]*")
_DICE_LIKE = re.compile(r"[dw](\d.*|f|%)?")  # 'w' is the German 'd' (Würfel): 2W6
_IDENT_CHARS = re.compile(r"[A-Za-z0-9_]")


def validate_name(name: str, what: str = "name") -> str:
    """Normalise a stat/skill/macro name ('@Dex' -> 'dex') or raise DiceError."""
    n = (name or "").strip().lstrip("@").strip().lower()
    if not n:
        raise DiceError(f"The {what} can't be empty.")
    if len(n) > MAX_NAME_LEN:
        raise DiceError(f"The {what} can be at most {MAX_NAME_LEN} characters.")
    if not _NAME_RE.fullmatch(n):
        raise DiceError(f"`{n}` isn't a valid {what}. Use letters, digits and `_`, starting with a letter.")
    if _DICE_LIKE.fullmatch(n):
        raise DiceError(f"`{n}` looks like dice, so it can't be a {what}.")
    return n


_PARAM_RE = re.compile(r"\$([1-9])")


def macro_params(text: Optional[str]) -> int:
    """How many values a macro takes: '$1d10!>=$2' -> 2."""
    return max((int(n) for n in _PARAM_RE.findall(text or "")), default=0)


def example_call(name: str, params: int) -> str:
    """'pool', 2 -> 'pool(5, 5)'"""
    return f"{name}({', '.join(['5'] * params)})" if params else name


def split_label(text: Optional[str]) -> tuple[str, Optional[str]]:
    """'1d20+5 # attack' -> ('1d20+5', 'attack')"""
    expr, _, label = (text or "").partition("#")
    return expr.strip(), label.strip() or None


_FATE_LADDER = {8: "Legendary", 7: "Epic", 6: "Fantastic", 5: "Superb", 4: "Great", 3: "Good", 2: "Fair",
                1: "Average", 0: "Mediocre", -1: "Poor", -2: "Terrible", -3: "Catastrophic", -4: "Horrifying"}


def fate_ladder(total: int) -> str:
    return _FATE_LADDER[max(-4, min(8, total))]


# ------------------------------------------------------------------ results

@dataclass
class Die:
    value: int
    kept: bool = True
    rerolled: bool = False   # replaced by a reroll
    exploded: bool = False   # extra die from an explosion
    outcome: int = 0         # pools: +1 success, -1 cancels a success
    wave: int = 0            # 0 = rolled normally, 1 = from a first explosion, 2 = exploded again, ...


@dataclass
class DiceTerm:
    notation: str
    sides: int               # 0 = Fate dice
    dice: list[Die]
    total: int
    pool: bool = False
    compare: Optional[tuple[str, int]] = None  # pools: success rule, e.g. ('>=', 8)
    explode: Optional[int] = None              # dice at or above this roll an extra die
    fail: Optional[int] = None                 # pools: dice <= this cancel a success
    count: int = 0                             # dice rolled before explosions/rerolls
    keep: Optional[tuple[str, int]] = None     # ('kh'|'kl'|'dh'|'dl', n)
    reroll: Optional[int] = None               # dice <= this were rerolled once

    @property
    def fate(self) -> bool:
        return self.sides == 0


@dataclass
class RollResult:
    expression: str
    label: Optional[str]
    total: int
    breakdown: str
    terms: list[DiceTerm] = field(default_factory=list)
    advantage: Optional[str] = None
    advantage_applied: bool = False

    @property
    def is_pool(self) -> bool:
        return any(t.pool for t in self.terms)

    @property
    def has_fate(self) -> bool:
        return any(t.fate for t in self.terms)

    @property
    def natural_d20(self) -> Optional[int]:
        """The kept die of a single-d20 roll (incl. advantage), for crits and stats."""
        d20s = [t for t in self.terms if t.sides == 20 and not t.pool]
        if len(d20s) != 1:
            return None
        kept = [d for d in d20s[0].dice if d.kept]
        return kept[0].value if len(kept) == 1 else None


# ------------------------------------------------------------------ syntax tree

@dataclass
class _Num:
    value: int


@dataclass
class _Stat:
    name: str


@dataclass
class _Neg:
    node: "_Node"


@dataclass
class _BinOp:
    op: str
    left: "_Node"
    right: "_Node"


@dataclass
class _Group:
    node: "_Node"
    name: Optional[str] = None  # set when this is an expanded skill/macro


@dataclass
class _Dice:
    count: Optional["_Node"]    # None = implicit 1
    sides: int                  # 0 = Fate
    percent: bool = False
    keep: Optional[tuple[str, int]] = None   # ('kh'|'kl'|'dh'|'dl', n)
    reroll: Optional[int] = None
    explode: Optional[int] = None            # explode on this or higher
    compare: Optional[tuple[str, int]] = None
    fail: Optional[int] = None


_Node = Union[_Num, _Stat, _Neg, _BinOp, _Group, _Dice]

_MOD_RE = re.compile(r"(kh|kl|dh|dl|k|d|r|!|>=|<=|>|<|=|f)(\d*)", re.I)
_COMPARE = {">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t, ">": lambda v, t: v > t,
            "<": lambda v, t: v < t, "=": lambda v, t: v == t}


class _Parser:
    def __init__(self, text: str, name_resolver: Optional[NameResolver], *, fixed: bool = False,
                 stack: tuple[str, ...] = ()):
        self.s, self.i = text, 0
        self.name_resolver, self.fixed, self.stack = name_resolver, fixed, stack

    def parse(self) -> _Node:
        node = self.expr()
        if self.peek():
            raise DiceError(f"I don't understand `{self.s[self.i:].strip()}`.")
        return node

    # -------------------------------------------------------------- helpers

    def peek(self) -> str:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1
        return self.s[self.i] if self.i < len(self.s) else ""

    def char(self, offset: int = 0) -> str:
        j = self.i + offset
        return self.s[j] if j < len(self.s) else ""

    def read(self, pattern: str) -> str:
        m = re.compile(pattern).match(self.s, self.i)
        if not m:
            return ""
        self.i = m.end()
        return m.group(0)

    def at_dice(self) -> bool:
        """Is there a 'd' starting dice notation right here (no spaces)?"""
        if self.char() not in ("d", "D", "w", "W"):  # W = German Würfel
            return False
        nxt = self.char(1)
        if nxt.isdigit() or nxt == "%":
            return True
        return nxt in ("f", "F") and not _IDENT_CHARS.match(self.char(2) or " ")

    # -------------------------------------------------------------- grammar

    def expr(self) -> _Node:
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.s[self.i]
            self.i += 1
            node = _BinOp(op, node, self.term())
        return node

    def term(self) -> _Node:
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.s[self.i]
            self.i += 1
            node = _BinOp(op, node, self.unary())
        return node

    def unary(self) -> _Node:
        c = self.peek()
        if c == "-":
            self.i += 1
            return _Neg(self.unary())
        if c == "+":
            self.i += 1
            return self.unary()
        return self.atom()

    def atom(self) -> _Node:
        c = self.peek()
        if not c:
            raise DiceError("The roll ends too early: something is missing after the last operator.")
        if c.isdigit():
            node = _Num(int(self.read(r"\d{1,9}")))
            if self.char().isdigit():
                raise DiceError("That number is too big.")
            return self.dice(node) if self.at_dice() else node
        if c == "(":
            self.i += 1
            node = self.expr()
            if self.peek() != ")":
                raise DiceError("Missing `)`.")
            self.i += 1
            node = _Group(node)
            return self.dice(node) if self.at_dice() else node
        if self.at_dice():
            return self.dice(None)
        if c == "@":
            self.i += 1
            name = self.read(r"[A-Za-z_][A-Za-z0-9_]*")
            if not name:
                raise DiceError("`@` needs a stat name right after it, like `@dex`.")
            return _Stat(name.lower())
        if c.isalpha() or c == "_":
            name = self.read(r"[A-Za-z_][A-Za-z0-9_]*").lower()
            args = self.call_args(name) if self.char() == "(" else None
            return self.expand(name, args)
        raise DiceError(f"Unexpected `{c}`.")

    def call_args(self, name: str) -> list[str]:
        """The values in `pool(7, @dex)`, as text."""
        args, depth, start = [], 0, self.i + 1
        for j in range(self.i, len(self.s)):
            c = self.s[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    args.append(self.s[start:j].strip())
                    self.i = j + 1
                    break
            elif c == "," and depth == 1:
                args.append(self.s[start:j].strip())
                start = j + 1
        else:
            raise DiceError("Missing `)`.")
        if not all(args):
            raise DiceError(f"A value is missing in `{name}(…)`.")
        return args

    def expand(self, name: str, args: Optional[list[str]] = None) -> _Node:
        if _DICE_LIKE.fullmatch(name):
            raise DiceError(f"`{name}` isn't valid dice notation. Try something like `1d20` or `4d6kh3`.")
        if self.fixed:  # formulas like "10 + con * level": every name is a stat
            if args is not None:
                raise DiceError(f"`{name}` is a stat and can't take values in brackets.")
            return _Stat(name)
        if name in self.stack:
            raise DiceError(f"Circular macro: `{name}` ends up using itself.")
        if len(self.stack) >= MAX_DEPTH:
            raise DiceError("Skills and macros are nested too deeply.")
        text = self.name_resolver(name) if self.name_resolver else None
        if text is None:
            raise UnknownReference(f"I don't know `{name}`: it isn't a stat, skill or macro here.")
        if not text.strip():
            raise DiceError(f"`{name}` is empty.")
        need = macro_params(text)
        if args is None and need:
            raise DiceError(f"`{name}` needs {need} value{'s' if need > 1 else ''} in brackets, "
                            f"like `{example_call(name, need)}`.")
        if args is not None:
            if not need:
                raise DiceError(f"`{name}` doesn't take values in brackets. Roll it as just `{name}`.")
            if len(args) != need:
                raise DiceError(f"`{name}` needs {need} value{'s' if need > 1 else ''}, like "
                                f"`{example_call(name, need)}`, but got {len(args)}.")
            text = _PARAM_RE.sub(lambda m: f"({args[int(m.group(1)) - 1]})", text)
        sub = _Parser(text, self.name_resolver, stack=self.stack + (name,)).parse()
        return _Group(sub, name=name)

    def dice(self, count: Optional[_Node]) -> _Dice:
        if self.fixed:
            raise DiceNotAllowed("Dice aren't allowed here. Use a fixed number or a formula like `10 + con`; "
                            "put rolls in a skill or macro.")
        self.i += 1  # the 'd'
        c = self.char()
        node = _Dice(count, 0)
        if c == "%":
            self.i += 1
            node.sides, node.percent = 100, True
        elif c in ("f", "F"):
            self.i += 1
        else:
            node.sides = int(self.read(r"\d{1,9}"))
            if node.sides < 1:
                raise DiceError("Dice need at least 1 side.")
            if node.sides > MAX_SIDES:
                raise DiceError(f"Dice can have at most {MAX_SIDES} sides.")

        while True:
            m = _MOD_RE.match(self.s, self.i)
            if not m:
                break
            op, num = m.group(1).lower(), m.group(2)
            self.i = m.end()
            n = int(num) if num else None
            if op in ("kh", "kl", "dh", "dl", "k", "d"):
                if node.keep:
                    raise DiceError("Use only one keep/drop modifier per dice group.")
                if n == 0:
                    raise DiceError("Keep/drop needs a number of at least 1.")
                node.keep = ({"k": "kh", "d": "dl"}.get(op, op), n or 1)
            elif op == "r":
                node.reroll = 1 if n is None else n
            elif op == "!":
                node.explode = n if n is not None else max(node.sides, 1)  # plain `!`: highest side
            elif op == "f":
                if n is None:
                    raise DiceError("`f` needs a number, like `f1`.")
                node.fail = n
            else:
                if n is None:
                    raise DiceError(f"`{op}` needs a target number, like `{op}8`.")
                node.compare = (op, n)

        if node.sides == 0 and (node.explode or node.reroll is not None or node.compare):
            raise DiceError("Fate dice can't explode, be rerolled or count successes.")
        if node.explode and not 2 <= node.explode <= node.sides:
            raise DiceError(f"Exploding on {node.explode}+ doesn't work on a d{node.sides}: "
                            f"use a number from 2 to {node.sides}.")
        if node.reroll is not None and node.reroll >= node.sides:
            raise DiceError(f"Rerolling everything up to {node.reroll} on a d{node.sides} would never stop.")
        if node.fail is not None and not node.compare:
            raise DiceError("`f` (failures) only works with a success target, like `6d10>=8f1`.")
        return node


def _walk_dice(node: _Node):
    if isinstance(node, _Dice):
        if node.count is not None:
            yield from _walk_dice(node.count)
        yield node
    elif isinstance(node, (_Neg, _Group)):
        yield from _walk_dice(node.node)
    elif isinstance(node, _BinOp):
        yield from _walk_dice(node.left)
        yield from _walk_dice(node.right)


def _apply_advantage(root: _Node, advantage: str) -> bool:
    """Turn the single plain 1d20 into 2d20kh1 / 2d20kl1. Returns whether it worked."""
    d20s = [d for d in _walk_dice(root) if d.sides == 20]
    if len(d20s) != 1:
        return False
    d = d20s[0]
    single = d.count is None or (isinstance(d.count, _Num) and d.count.value == 1)
    if not single or d.keep or d.explode or d.reroll is not None or d.compare:
        return False
    d.count, d.keep = _Num(2), ("kh" if advantage == "adv" else "kl", 1)
    return True


# ------------------------------------------------------------------ evaluation

_FATE_FACES = {-1: "−", 0: "0", 1: "+"}
_OP_TEXT = {"+": "+", "-": "-", "*": "×", "/": "/"}


class _Evaluator:
    def __init__(self, stat_resolver: Optional[StatResolver], root: _Node):
        self.stat_resolver, self.root = stat_resolver, root
        self.terms: list[DiceTerm] = []
        self.dice_rolled = 0

    def eval(self, node: _Node) -> tuple[int, str]:
        if isinstance(node, _Num):
            return node.value, str(node.value)
        if isinstance(node, _Stat):
            if not self.stat_resolver:
                raise UnknownReference(f"`@{node.name}` needs an active character here.")
            value = int(self.stat_resolver(node.name))
            return value, f"{node.name}({value})"
        if isinstance(node, _Neg):
            value, text = self.eval(node.node)
            return -value, f"-{text}"
        if isinstance(node, _BinOp):
            lv, lt = self.eval(node.left)
            rv, rt = self.eval(node.right)
            if node.op == "+":
                value = lv + rv
            elif node.op == "-":
                value = lv - rv
            elif node.op == "*":
                value = lv * rv
            else:
                if rv == 0:
                    raise DiceError("Can't divide by zero.")
                value = lv // rv
            return value, f"{lt} {_OP_TEXT[node.op]} {rt}"
        if isinstance(node, _Group):
            value, text = self.eval(node.node)
            if node.name is None or (isinstance(node.node, _BinOp) and node is not self.root):
                text = f"({text})"
            return value, text
        return self.roll_dice(node)

    def one(self, sides: int) -> int:
        self.dice_rolled += 1
        if self.dice_rolled > MAX_TOTAL_DICE:
            raise DiceError(f"That's too many dice for one roll (max {MAX_TOTAL_DICE}).")
        return _rng.randint(-1, 1) if sides == 0 else _rng.randint(1, sides)

    def roll_dice(self, node: _Dice) -> tuple[int, str]:
        count = 1 if node.count is None else self.eval(node.count)[0]
        if count < 1:
            raise DiceError(f"Can't roll {count} dice.")
        if count > MAX_DICE:
            raise DiceError(f"That's too many dice (max {MAX_DICE} at once).")
        sides = node.sides

        dice: list[Die] = []
        explosions = 0
        for _ in range(count):
            value = self.one(sides)
            if node.reroll is not None and value <= node.reroll:
                dice.append(Die(value, kept=False, rerolled=True))
                value = self.one(sides)
            dice.append(Die(value))
            wave = 0
            while node.explode and value >= node.explode and explosions < MAX_EXPLOSIONS:
                explosions += 1
                wave += 1
                value = self.one(sides)
                dice.append(Die(value, exploded=True, wave=wave))

        if node.keep:
            mode, n = node.keep
            active = [d for d in dice if not d.rerolled]
            by_value = sorted(active, key=lambda d: d.value, reverse=mode in ("kh", "dl"))
            keep_n = n if mode in ("kh", "kl") else max(0, len(active) - n)
            for d in by_value[keep_n:]:
                d.kept = False

        kept = [d for d in dice if d.kept]
        if node.compare:
            op, target = node.compare
            for d in kept:
                if _COMPARE[op](d.value, target):
                    d.outcome = 1
                elif node.fail is not None and d.value <= node.fail:
                    d.outcome = -1
            total = sum(d.outcome for d in kept)
        else:
            total = sum(d.value for d in kept)

        notation = f"{count}d{'F' if sides == 0 else '%' if node.percent else sides}"
        if node.reroll is not None:
            notation += f"r{node.reroll}"
        if node.explode:
            notation += "!" if node.explode == sides else f"!{node.explode}"
        if node.keep:
            notation += f"{node.keep[0]}{node.keep[1]}"
        if node.compare:
            notation += f"{node.compare[0]}{node.compare[1]}"
        if node.fail is not None:
            notation += f"f{node.fail}"

        self.terms.append(DiceTerm(notation, sides, dice, total, pool=node.compare is not None,
                                   compare=node.compare, explode=node.explode, fail=node.fail, count=count,
                                   keep=node.keep, reroll=node.reroll))
        shown = ", ".join(self.show_die(d, node) for d in dice)
        return total, f"{notation} [{shown}]"

    @staticmethod
    def show_die(d: Die, node: _Dice) -> str:
        text = _FATE_FACES[d.value] if node.sides == 0 else str(d.value)
        if node.explode and d.value >= node.explode:
            text += "!"
        if not d.kept:
            return f"~~{text}~~"
        if d.outcome > 0:
            return f"**{text}**"
        if d.outcome < 0:
            return f"__{text}__"
        return text


# ------------------------------------------------------------------ public API

def roll(text: str, stat_resolver: Optional[StatResolver] = None, name_resolver: Optional[NameResolver] = None,
         advantage: Optional[str] = None) -> RollResult:
    """Roll an expression like '1d20+@dex # attack'. advantage is 'adv', 'dis' or None."""
    expr, label = split_label(text)
    if not expr:
        raise DiceError("Nothing to roll.")
    if len(expr) > MAX_LENGTH:
        raise DiceError(f"That roll is too long (max {MAX_LENGTH} characters).")
    root = _Parser(expr, name_resolver).parse()
    applied = _apply_advantage(root, advantage) if advantage in ("adv", "dis") else False
    ev = _Evaluator(stat_resolver, root)
    total, breakdown = ev.eval(root)
    return RollResult(expression=expr, label=label, total=total, breakdown=breakdown, terms=ev.terms,
                      advantage=advantage, advantage_applied=applied)


def evaluate_fixed(formula: str, stat_resolver: Optional[StatResolver] = None) -> int:
    """Evaluate a dice-free formula such as '10 + con * level'."""
    expr = (formula or "").strip()
    if not expr:
        raise DiceError("The formula is empty.")
    if len(expr) > MAX_LENGTH:
        raise DiceError(f"That formula is too long (max {MAX_LENGTH} characters).")
    root = _Parser(expr, None, fixed=True).parse()
    return _Evaluator(stat_resolver, root).eval(root)[0]
