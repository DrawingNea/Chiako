"""The /help chapters. Each chapter is one embed page; `{me}` is replaced with a mention of the bot."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    key: str
    emoji: str
    title: str
    summary: str  # shown in the chapter menu (max 100 characters)
    text: str


CHAPTERS: list[Chapter] = [
    Chapter("start", "", "Getting started", "Set up a campaign, create a character and make your first roll", """
Welcome! 🌸 I roll dice for your pen & paper games and keep track of characters, fights and sessions.
Use the menu below to jump to any chapter, or flip through them with ‹ Back and Next ›.

### 1. The GM creates a campaign
A **campaign** is your group's game, and it lives in one or more channels.
• `/campaign create name:Curse of Strahd` makes the current channel the campaign's home.
• `/campaign link` adds more channels. Threads automatically belong to their channel's campaign.

### 2. Everyone creates a character
• `/char create name:Lyra` creates a character and makes it your **active** character, the one your
  rolls belong to in this campaign.
• `/stat bulk entries: str=1, dex=4, con=2, level=1` fills in its numbers.

### 3. Roll!
• `/r 1d20+5` rolls anything.
• `/r 1d20+dex` adds your character's `dex` stat. Just write the stat's name.
• `/skill add name:stealth formula:1d20+dex` saves a roll, and `/check stealth` rolls it.
• No slash command needed: write {me} `roll 2d6` in the chat.

Your rolls appear under your character's name and picture, with a **Reroll** button.

### Who counts as GM?
The campaign's creator, anyone with the campaign's GM role (`/campaign gm-role`) and server admins.
Commands only the GM can use are marked **(GM)**.
"""),

    Chapter("dice", "", "Rolling dice", "Dice notation, labels, advantage, secret rolls and inline rolls", """
### Writing a roll
`XdY` means "roll **X** dice with **Y** sides and add them up". Math with `+ - * /` and brackets works too.

• `2d6+3` two six-sided dice, plus 3
• `d20` one twenty-sided die · `d%` one hundred-sided die
• `4d6kh3` roll four, **k**eep the **h**ighest three · `2d20kl1` keep the lowest one
• `4d6dl1` roll four, **d**rop the **l**owest one · `5d10dh2` drop the highest two
• `3d6!` **exploding dice**: every 6 adds another die · `5d10!9` 9s and 10s explode
• `2d6r1` **reroll** each 1 once
• `4dF` **Fate dice** (+, 0, −), with the result on the Fate ladder (Fair, Good, Great, …)
• `6d10>=8` **count successes** instead of adding up (see *Dice pools*)

### Labels
Add `# name` to a roll: `/r 1d20+5 # Longsword` shows **Longsword** on the result.

### Advantage & disadvantage
`/r 1d20+5 advantage:Advantage` rolls the d20 twice and keeps the higher result.
Disadvantage keeps the lower one.

### More ways to roll
• `/check` rolls one of your skills, with an optional `modifier`.
• `/secret` rolls so that **only the GM** sees the result. A player's secret roll is sent to the GM
  privately; a GM's own secret roll gets a **Reveal** button to show it to the table later.
• `[[1d20+3]]` anywhere in a message rolls on the spot (up to 5 per message).
• `/pbta` rolls 2d6 plus a stat for *Powered by the Apocalypse* moves: Strong hit, Weak hit or Miss.
• `/3d20` makes a DSA-style 3d20 check with plain numbers.

### Reading the result
The small line describes the roll in words, the large line shows every die, and the largest line is
the result. Crossed-out dice were dropped and don't count.
"""),

    Chapter("pools", "", "Dice pools & campaign rules", "Counting successes, exploding dice and the campaign's dice rules", """
In some games you don't add the dice up. You roll a handful and **count successes**: every die that
rolls high enough counts as one success.

### Rolling a pool yourself
• `/r 5d10>=8` rolls five ten-sided dice. Every die showing **8 or higher** is a success.
• `/r 5d10!>=8` does the same, but every 10 **explodes**: it adds another die, which can succeed and
  explode too.
• `/r 5d10!>=8f1` also lets every 1 **cancel** a success.
Successes are underlined, and dice from explosions appear after a `-`.

### Campaign dice rules (GM)
So nobody has to type all of that each time, the GM sets the rules once for the whole campaign:
`/campaign dice sides:10 success:8 explode:10 cancel:1`
• `sides` the die to roll, here a d10
• `success` the lowest result that counts as a success. Leave it out to add the dice up instead.
• `explode` the lowest result that adds another die. Leave it out for no exploding.
• `cancel` the highest result that cancels a success (optional)
`/campaign dice` on its own shows the current rules, and `sides:0` turns them off.

### Rolling with the campaign rules
Once the rules are set, a **number means a number of dice**:
• `/check 7` rolls seven dice using the campaign rules.
• A skill whose value is a number works as a dice count: `/skill add name:shooting formula:5`,
  then `/check shooting`.
• Combine skills and stats: `/check shooting & dex` rolls 5 dice plus your dex.
• `modifier` adds or removes dice: `/check shooting modifier:2`.
• In the chat: {me} `w7` or {me} `check shooting & dex`.
Skills with dice in them, like `1d20+dex`, still roll exactly as written.
"""),

    Chapter("chat", "", "Talking to the bot", "Roll by mentioning the bot in the chat instead of using slash commands", """
You don't need slash commands to roll: start a message by mentioning me, then write what to roll.

### Examples
• {me} `roll 2d6+3` · {me} `r 1d20+dex` · {me} `check stealth`
• {me} `roll for shooting & dex` · {me} `pool(7)`
• {me} `w5` rolls five dice with the campaign's dice rules
• {me} `help` shows a quick reminder

You get the same result as with `/r`, including the **Reroll** button, and the roll counts toward
your stats and achievements. I only respond when the message **starts** with the mention, so a
"thanks {me}!" won't trigger a roll.

### Other languages
The first word, and the words for "for" and "and", can be in several languages:
**English** `roll`, `check`, `throw` · `for` · `and`
**German** `würfel`, `würfle`, `wirf`, `prüfe` · `auf`, `für` · `und`
**French** `lance`, `jet` · `pour` · `et`
**Spanish** `tira`, `lanza` · `para` · `y`
**Italian** `tira`, `lancia` · `per` · `e`
**Dutch** `gooi`, `werp` · `voor` · `en`
**Portuguese** `rola`, `joga` · `para` · `e`
For example: {me} `Würfle auf schiessen und ge`

### Inline rolls
Put a roll in double square brackets anywhere in a message: `I swing my axe [[1d12+str]] and shout!`
"""),

    Chapter("chars", "", "Characters, stats & skills", "Characters, stats and formulas, skills, 3d20 checks, export and import", """
### Characters
• `/char create` creates a character, optionally with a link to a picture.
• `/char use` switches your active character and `/char list` shows all of yours.
• `/char show` shows your **character sheet card**: picture, HP, level, conditions, stats, skills,
  resources, inventory and money. Add `public:True` to show it to the table.
• `/char profile field:Age value:24` adds details to your card: age, hair, eyes, race, height, or
  anything your game needs. Leave out `value` to remove a field.
• `/char description` opens an editor for a short description, shown right under your name.
• `/char color` gives your card its own colour (`#8e44ad`, `purple`, …).
• `/char avatar`, `/char rename` and `/char delete` do what they say.
You can have several characters in a campaign and switch between them at any time.
The GM can arrange the card to match your game with `/campaign sheet` (see *Campaign settings*).

### Stats
Stats are the numbers on your character sheet: `/stat set name:dex value:3`.
• Use them in any roll by name: `1d20+dex`.
• `/stat bulk entries: str=1, dex=4, level=1` sets several at once.
• A stat can be a **formula** that keeps itself up to date: `/stat set name:max_hp value:10 + con * level`.
  Whenever `con` or `level` changes, `max_hp` follows.
If a skill or macro has the same name as a stat, the skill or macro wins. Write `@dex` to mean the stat.

### Skills
A skill is a roll you save once and reuse: `/skill add name:stealth formula:1d20+dex+prof`.
Roll it with `/check stealth` or `/r stealth`, or use it in a bigger roll like `/r stealth+2`.
With campaign dice rules, a skill can simply be a number of dice (see *Dice pools*).

**3d20 skills** (DSA style): `/skill add-3d20 name:climb attr1:mu attr2:ge attr3:kk points:6`,
then `/check climb`. The result shows the quality level, critical successes (two 1s) and botches
(two 20s).

### Export & import
`/char export` sends you a `.json` file with your character and its companions: stats, skills,
resources, HP, XP, inventory and money. `/char import` turns that file back into a character in any campaign or server,
with an optional new `name`. Perfect for backups or moving to a new campaign.
"""),

    Chapter("inventory", "", "Inventory & money", "Items, money and the shared party stash", """
Every character has an inventory and a purse, and the campaign has a shared **party stash** for loot
everyone can use.

### Items
• `/item add name:Rope amount:2 note:50 ft` puts items into your character's inventory.
• `/item remove name:Rope` takes them out again: used up, sold or lost. Leave out `amount` to remove all.
• `/item give name:Healing potion to:Grom` hands an item to another character.
• Add `stash:True` to add or remove items in the party stash instead.

### Money
Use any currency your game has: gold, credits, Nuyen, € …
• `/money add amount:30 currency:gold` · `/money spend amount:12`
• `/money give amount:10 to:Grom` pays another character.
Once you've used a currency, you can leave out `currency` and I'll pick yours.

### The party stash
• `/item give … to:Party stash` and `/money give … to:Party stash` put things in.
• `/item take name:Healing potion` and `/money take amount:20` take things out.
• Anyone in the campaign can use the stash, so share fairly!

### Looking inside
`/inventory` shows your items and money; pick another character or the party stash with `whose`.
Your inventory also appears on your character sheet card (`/char show`).

### For the GM
Hand out loot directly with `character:` on `/item add` and `/money add`, or put it into the party
stash with `stash:True` and let the players share it out.
"""),

    Chapter("macros", "", "Macros", "Your own roll shortcuts, macros with values and campaign macros", """
A **macro** is a shortcut for a roll you use often. Macros belong to *you* rather than to a character,
so they work in every campaign on the server.

### Saving and using macros
• `/macro save name:fireball expression:8d6 # Fireball`, then roll it with `/r fireball` or `[[fireball]]`.
• Macros can build on stats, skills and other macros: `/macro save name:sneak expression:stealth + 5`.
• `/macro list` shows your macros, and `/macro remove` deletes one.

### Macros with values
Write `$1` where you want to fill in a number each time you roll:
`/macro save name:pool expression:$1d10!>=8 # Pool`
Then roll `/r pool(5)`, `/r pool(8)` or `/r pool(dex+2)`.
Need more values? Use `$2`, `$3` and so on, and roll `pool(7, 9)`.

### Campaign macros (GM)
Add `campaign:True` to share a macro with everyone in the campaign:
`/macro save name:pool expression:$1d10!>=8 # Pool campaign:True`
Every player can now roll `pool(5)` with their own stats. A player's own macro with the same name
takes priority. `/macro remove name:pool campaign:True` removes it again.
"""),

    Chapter("combat", "", "Combat", "Initiative tracker, monsters, hit points, conditions, group checks", """
### Initiative
1. **GM:** `/init start` posts the turn tracker with **Join** and **Start combat** buttons.
2. **Players:** press **Join**. Your initiative uses your `initiative` skill if you have one,
   otherwise the campaign's formula (`/campaign init-formula 1d20+dex`).
3. **GM:** add monsters with `/init spawn template:Goblin count:3` or `/init add`.
4. **GM:** press **Start combat**. Whoever's turn it is gets pinged and presses **Next turn**
   when they're done.
More: `/init show` posts the tracker again at the bottom of the chat; `/init move`, `/init remove`
and `/init end` adjust or end the fight.

### Monster templates (GM)
`/monster save name:Goblin hp:2d6 initiative:1d20+2 ac:15` saves a monster you can spawn again and again.

### Hit points
• `/hp damage amount:2d6+3 target:Goblin 2` · `/hp heal` · `/hp temp` for temporary HP · `/hp show`
• Your maximum HP is your `max_hp` stat. The GM can correct HP with `/hp set`.
• Players only see how monsters are doing: Unhurt, Hurt, Bloodied or Down.

### Conditions
`/condition add name:Stunned target:Goblin 1 rounds:2` counts down at the end of each of the target's
turns, and I announce when it wears off. Leave out `rounds` for a condition that lasts until removed.

### Group checks (GM)
`/group-check roll:perception dc:15` lets everyone press **Roll** and collects all results in one
message. With a DC, the group succeeds if at least half of them pass. `secret:True` hides the results
from the players.

### Dashboard
`/dashboard` posts the party's HP and conditions and keeps it up to date. Pin it to the channel!
"""),

    Chapter("progress", "", "Progress & companions", "Resources, rests, XP and levels, companions", """
### Resources
Anything that gets used up: spell slots, ammunition, luck points…
• `/res add name:slots_1 max:level+1 reset:Long rest` creates one. The maximum can be a formula, so
  it grows as you level up.
• `/res use slots_1` spends one, `/res gain` gets some back and `/res list` shows them all.

### Rests
• `/rest kind:Short rest` refills everything that resets on a short rest.
• `/rest kind:Long rest` refills everything and restores your HP. Add `restore_hp:False` to skip the
  healing.
• The GM can rest the whole party at once with `party:True`.

### XP & levels
• **GM:** `/xp table dnd5e` picks a level table: `dnd5e`, `pathfinder`, your own numbers like
  `0, 1000, 3000`, or `none`.
• **GM:** `/xp award amount:300 reason:the goblin cave` gives XP to the whole party. `split:True`
  divides it between them instead.
• When someone levels up, I announce it and raise their `level` stat, so formulas such as
  `max_hp = 10 + level * 5` grow automatically.
• `/xp show` shows how far you are from the next level.

### Companions
Pets, familiars and hirelings are full characters that belong to yours:
• `/companion add Whiskers` creates one.
• `/companion roll name:Whiskers expression:1d20+2` rolls as the companion.
• `/companion join` brings it into a fight.
To change its stats, switch to it with `/char use Whiskers`, then back with `/char use Lyra`.
"""),

    Chapter("world", "", "World building", "Quick generators, random tables and campaign notes", """
### Quick generators
`/generate npc` · `name` · `tavern` · `loot` · `weather` · `complication`. Perfect for improvising!

### Random tables (GM)
`/table create name:Forest` opens an editor where you write one entry per line:
• `3* A pack of wolves` makes an entry three times as likely.
• `[[2d6]] goblins` rolls dice inside the entry.
• `{loot}` rolls on another table.
`/table roll Forest` picks a random entry. You can also `/table add`, `edit`, `show`, `list` and
`delete` tables. `/table edit npc` copies a built-in table into your campaign so you can adjust it.

### Notes
Keep track of NPCs, places, quests and more: `/note add title:Mayor Ulric category:NPC`.
Find them again with `/note show`, `/note search` and `/note list`; change them with `/note edit` or
`/note delete`.
GM-only notes (`gm_only:True`) stay invisible to players, even in search results. Only a note's
author or the GM can change or delete it.
"""),

    Chapter("sessions", "", "Sessions, stats & scheduling", "Session recaps, dice statistics, achievements and planning the next game", """
### Sessions (GM)
Start with `/session start title:The Goblin Cave` and finish with `/session end`.
I then post a recap: how long you played, the luckiest and unluckiest players, the biggest roll,
critical hits, defeated monsters, level-ups, and the highlights anyone saved with
`/session moment text:…` during the game. `/session recap` and `/session list` show earlier sessions.

### Dice statistics
• `/stats` shows how your dice behave, split up by how you roll:
  – **success pools**, one section per set of rules: successes per roll compared with what you'd
    expect, rolls without a success, your best roll and bonus dice from explosions;
  – **every die type** (d20, d10, d6, …): your average compared with the expected one, and how often
    the highest and lowest faces came up;
  – **3d20 checks** and your biggest total, plus a luck verdict over all your dice.
  Pick another `player` or a different `scope` (this session, this campaign or the whole server).
• `/halloffame` shows the leaderboards, including the luckiest and unluckiest players.
• `/achievements` shows which of the 17 achievements you (or another player) have unlocked.
Secret rolls never count, so they can't give anything away.

### Planning the next session
• **GM:** set the campaign's time zone once with `/campaign timezone Europe/Berlin`.
• **GM:** `/schedule set when:fri 19:30` sets the next session. `tomorrow 19:30`, `9.10. 19:30`
  and `2026-10-09 19:30` work too.
• The day before, I ping everyone: **"Tomorrow is session day!"**. More reminders follow an hour
  before and when the session starts.
Everyone sees the time in their own time zone. `/schedule show` shows the next session and
`/schedule cancel` cancels it. To agree on a date first, use Discord's built-in polls.
"""),

    Chapter("gm", "", "Campaign settings (GM)", "Everything the GM can set up for the campaign in one place", """
`/campaign info` shows every setting of the campaign in this channel.

### The campaign
• `/campaign create` starts a campaign in this channel.
• `/campaign language` switches what I say in this campaign between English and Deutsch.
• `/campaign link` adds this channel to an existing campaign; `/campaign unlink` removes it.
• `/campaign gm-role` gives a role GM powers, and `/campaign transfer` hands the campaign to a new GM.

### Rolling
• `/campaign dice sides:10 success:8 explode:10 cancel:1` sets the campaign's dice rules
  (see *Dice pools*).
• `/campaign init-formula 1d20+dex` sets how initiative is rolled for characters without an
  `initiative` skill.
• `/campaign webhooks` posts rolls under each character's name and picture. It's on by default and
  needs the **Manage Webhooks** permission.

### The character sheet
`/campaign sheet` opens an editor where you lay out the sheet card for your game, one section per line:
```
Attributes: str, dex, con, int, wis, cha
Combat: max_hp, ac, initiative
Talents: Climbing=climb, Stealth=stealth
```
Entries can be stats or skills, and `Label=name` shows your own label. Anything you leave out still
appears under *More*. `/campaign sheet reset:True` goes back to the automatic layout.

### Shared content
• `/macro save … campaign:True` macros for everyone
• `/monster save` monster templates · `/table create` random tables
• `/note add gm_only:True` secret notes · `/xp table` the level table

### Time
`/campaign timezone Europe/Berlin` sets the time zone for the dates you enter with `/schedule`.
"""),
]

BY_KEY = {c.key: c for c in CHAPTERS}
