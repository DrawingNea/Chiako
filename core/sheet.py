"""Turns stored stats/skills/macros into something the dice engine can roll against."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from dice.engine import DiceError, DiceNotAllowed, RollResult, UnknownReference, evaluate_fixed, roll, split_label

from .db import Campaign, Character, Skill
from .i18n import t

_BARE_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
_NAME_CALL = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(\(.*\))?\s*$")  # stealth, pool(7)
# A dice count: numbers and names joined by + - & , or "and" in a few languages (and/und/et/y/e/en),
# e.g. "shooting & dex + 1", "schiessen und ge"
_COUNT_TEXT = re.compile(r"^[A-Za-z0-9_@\s&,+\-]+$")
COUNT_JOIN = re.compile(r"\s*(?:&|,|\b(?:and|und|et|y|e|en)\b)\s*", re.I)
_WORD = re.compile(r"(?<![@\w])([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class DiceRules:
    """A campaign's dice rules: dice-free checks like `/check shooting` roll that many of these dice."""
    sides: int
    explode: Optional[int] = None   # dice at or above this roll an extra die
    success: Optional[int] = None   # dice at or above this are successes; None = add the dice up
    cancel: Optional[int] = None    # dice at or below this cancel a success

    @classmethod
    def of(cls, campaign: Optional[Campaign]) -> Optional["DiceRules"]:
        if not campaign or not campaign.dice_sides:
            return None
        return cls(campaign.dice_sides, campaign.dice_explode, campaign.dice_success, campaign.dice_cancel)

    def expression(self, count: int) -> str:
        """DiceRules(10, 10, 8, 1).expression(5) -> '5d10!>=8f1'"""
        expr = f"{count}d{self.sides}"
        if self.explode:
            expr += "!" if self.explode == self.sides else f"!{self.explode}"
        if self.success:
            expr += f">={self.success}"
            if self.cancel:
                expr += f"f{self.cancel}"
        return expr

    def describe(self, lang: str = "en") -> str:
        parts = [t(lang, "d{sides}", sides=self.sides)]
        parts.append(t(lang, "success at ≥ {n}", n=self.success) if self.success else t(lang, "dice are added up"))
        if self.explode:
            parts.append(t(lang, "{n}+ explode", n=self.explode) if self.explode < self.sides
                         else t(lang, "{sides}s explode", sides=self.sides))
        if self.success and self.cancel:
            parts.append(t(lang, "≤ {n} cancels a success", n=self.cancel))
        return " · ".join(parts)


class Sheet:
    """A character's stats (numbers or derived formulas) and skills."""

    def __init__(self, character: Character, stats: dict[str, str], skills: dict[str, Skill]):
        self.character = character
        self.stats = stats
        self.skills = skills
        self._cache: dict[str, int] = {}
        self._resolving: set[str] = set()

    def resolve(self, name: str) -> int:
        name = name.lower()
        if name in self._cache:
            return self._cache[name]
        if name in self._resolving:
            raise DiceError(f"Circular formula: `{name}` ends up depending on itself.")
        if name not in self.stats:
            raise UnknownReference(f"**{self.character.name}** has no stat `{name}`. Add it with `/stat set`.")
        self._resolving.add(name)
        try:
            value = evaluate_fixed(self.stats[name], self.resolve)
        finally:
            self._resolving.discard(name)
        self._cache[name] = value
        return value

    def resolve_formula(self, formula: str) -> int:
        """Evaluate a dice-free formula against this sheet, e.g. a resource max like '@level + 1'."""
        return evaluate_fixed(formula, self.resolve)

    def is_derived(self, name: str) -> bool:
        return not re.fullmatch(r"\s*-?\d+\s*", self.stats[name])

    def display_values(self) -> list[tuple[str, str, Optional[str]]]:
        """(name, value or error, formula if derived)"""
        out = []
        for name, formula in self.stats.items():
            try:
                value = str(self.resolve(name))
            except DiceError as e:
                value = f"{e}"
            out.append((name, value, formula if self.is_derived(name) else None))
        return out


class RollEnv:
    """Everything a roll can reference: the active character's sheet and the user's macros."""

    def __init__(self, sheet: Optional[Sheet], macros: dict[str, str], rules: Optional[DiceRules] = None,
                 lang: str = "en"):
        self.sheet = sheet
        self.macros = macros
        self.rules = rules
        self.lang = lang  # the campaign's language for everything this roll shows

    @property
    def character(self) -> Optional[Character]:
        return self.sheet.character if self.sheet else None

    def resolve_stat(self, name: str) -> int:
        if not self.sheet:
            raise UnknownReference(f"`{name}` needs an active character here (`/char create` or `/char use`).")
        return self.sheet.resolve(name)

    def expand(self, name: str) -> Optional[str]:
        """What a bare name in a roll means: a skill, else a macro, else a stat (so `dex` works like `dex`)."""
        if self.sheet and name in self.sheet.skills:
            skill = self.sheet.skills[name]
            if skill.kind == "3d20":
                raise DiceError(f"`{name}` is a 3d20 check, roll it on its own (`/check {name}`).")
            return split_label(skill.formula)[0]
        if name in self.macros:
            return split_label(self.macros[name])[0]
        if self.sheet and name in self.sheet.stats:
            return f"@{name}"
        if self.sheet:
            raise UnknownReference(f"**{self.sheet.character.name}** has no stat, skill or macro called `{name}`. "
                                   f"Add a stat with `/stat set` or a skill with `/skill add`.")
        raise UnknownReference(f"I don't know `{name}`. Stats and skills need an active character here "
                               f"(`/char create` or `/char use`).")

    def label_for(self, name: str) -> str:
        """A macro's own '# label', or the prettified name."""
        source = self.macros.get(name)
        if self.sheet and name in self.sheet.skills:
            source = self.sheet.skills[name].formula
        label = split_label(source)[1] if source else None
        return label or name.replace("_", " ").title()

    def skill_3d20(self, text: str) -> Optional[Skill]:
        """If text is just the name of a 3d20 skill, return it."""
        m = _BARE_NAME.match(text.split("#", 1)[0])
        if m and self.sheet:
            skill = self.sheet.skills.get(m.group(1).lower())
            if skill and skill.kind == "3d20":
                return skill
        return None

    def dice_count(self, text: str, _seen: frozenset = frozenset()) -> Optional[int]:
        """
        How many dice a dice-free check means: '5', 'shooting', 'shooting & dex + 1'.
        Names are skills whose formula is a number, or stats. None if the text is a normal roll
        (dice, macros, skills with dice in them).
        """
        if not _COUNT_TEXT.match(text) or not re.search(r"[A-Za-z0-9]", text):
            return None
        if re.search(r"(?<![A-Za-z_])\d*d(\d|F\b|%)", text, re.I):  # dice notation like 5d10
            return None

        def name(m: re.Match) -> str:
            n = m.group(1).lower()
            if self.sheet and n in self.sheet.skills:
                skill = self.sheet.skills[n]
                if skill.kind != "formula" or n in _seen:
                    raise DiceNotAllowed(n)
                count = self.dice_count(split_label(skill.formula)[0], _seen | {n})
                if count is None:
                    raise DiceNotAllowed(n)
                return f"({count})"
            if n in self.macros and not (self.sheet and n in self.sheet.stats):
                raise DiceNotAllowed(n)
            return f"@{n}"

        try:
            expr = _WORD.sub(name, COUNT_JOIN.sub(" + ", text))
            return evaluate_fixed(expr, self.resolve_stat)
        except DiceNotAllowed:
            return None
        except UnknownReference:
            raise
        except DiceError:
            # Not a valid count (e.g. "checke 20"): let the normal roll report what's wrong with it
            return None

    def roll(self, text: str, advantage: Optional[str] = None) -> RollResult:
        result = roll(text, stat_resolver=self.resolve_stat, name_resolver=self.expand, advantage=advantage)
        m = _NAME_CALL.match(result.expression)
        if result.label is None and m:
            result.label = self.label_for(m.group(1).lower())
        return result
