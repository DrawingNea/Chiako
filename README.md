# 🎲 Pen & Paper Dice Bot

A system-agnostic Discord dice bot in Python: campaigns, characters with custom and derived stats,
skills, macros, secret GM rolls, inline rolls, reroll buttons, and rolls posted as your character.
Phase 2 adds an initiative tracker, HP, timed conditions, monster templates, group checks, and a
live party dashboard. Phase 3 adds resources and rests, XP with automatic leveling, companions,
character export/import, random tables and generators, and campaign notes. Phase 4 adds session
recaps, dice statistics, achievements, a Hall of Fame, and session scheduling with reminders.

## Setup

1. **Create the bot.** At https://discord.com/developers/applications, click *New Application*, then go to
   *Bot* and *Reset Token* and copy the token. On the same page, enable **Message Content Intent**
   (needed for inline `[[rolls]]`).
2. **Invite it.** Under *OAuth2 → URL Generator*, pick the scopes `bot` and `applications.commands`, and the
   permissions *Send Messages*, *Embed Links*, *Read Message History*, *Manage Webhooks*, and
   *Send Messages in Threads*. Open the generated URL and add the bot to your server.
3. **Install and run** (Python 3.10+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # then paste your token into .env
   python bot.py
   ```
   Tip: put your server's ID in `DEV_GUILD_ID` so new commands appear instantly
   (right-click server → Copy Server ID, with Developer Mode on).
   Database: by default everything is stored in a local SQLite file (`DATABASE_PATH`). To use
   MySQL/MariaDB instead, fill in `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS` and `DB_NAME`; the
   tables are created on first start.
4. **Run the tests** (optional): `python -m pytest`. To watch simulated sessions print out in your
   terminal, run `python -m tests.test_session` (rolling and characters),
   `python -m tests.test_combat_session` (a full fight), `python -m tests.test_phase3_session`
   (progress, companions, tables, and notes, plus a check of every autocomplete), or
   `python -m tests.test_phase4_session` (achievements, recaps, stats, scheduling, and reminders).

**Upgrading from an earlier phase:** just replace the files and restart. Your existing database is
upgraded automatically, and all characters, stats, and macros are kept.

## Quick start at the table

```
GM:      /campaign create name:Curse of Strahd
Player:  /char create name:Thorin avatar_url:https://…/thorin.png
         /stat bulk entries: str=3, dex=2, con=2, level=1, prof=2, max_hp=10+con*level
         /skill add name:stealth formula:1d20+dex+prof
         /skill add name:longsword formula:1d20+str+prof
         /macro save name:greataxe expression:1d12+str # Greataxe hit
         /r stealth                    → rolls 1d20+2+2, posted as Thorin
         /check stealth advantage:Advantage
         I swing! [[longsword]] and hit for [[greataxe]]
```

## Dice notation

| Notation | Meaning |
|---|---|
| `2d6+3`, `d20`, `d%` | basic dice, d20 = 1d20, d% = d100 |
| `2W6+3`, `W20` | the same with the German `W` (Würfel) |
| `4d6kh3` / `4d6k3` | keep highest 3 |
| `2d20kl1` | keep lowest 1 |
| `4d6dl1` / `4d6d1`, `5d10dh2` | drop lowest / highest |
| `3d6!` | exploding dice |
| `2d6r1` | reroll dice ≤ 1 once |
| `6d10>=8` | dice pool: count successes (`>`, `<`, `<=`, `=` work too) |
| `6d10>=8f1` | dice ≤ 1 cancel a success |
| `4dF+2` | Fate dice, result shown on the Fate ladder |
| `(str+athletics)d10` | dice count from stats |
| `dex` (or `@dex`) | a stat of your active character. If a skill or macro has the same name, it wins; `@dex` always means the stat |
| `stealth`, `fireball` | a skill or macro |
| `1d20+5 # attack` | label shown on the roll |
| `5d10!9>=8` | explode on 9 or higher (plain `!` explodes on the highest side) |
| `pool(7)` | macro with values: `$1d10!>=8` saved as `pool` rolls `7d10!>=8` |

Math with `+ - * / ( )` works everywhere; division rounds down.

## Commands

**Rolling:**
`/r` rolls anything (with an optional advantage/disadvantage); `/check` rolls a skill with autocomplete
and a modifier; `/secret` shows the result only to the GM (a player's roll goes to the GM by DM, while
a GM's roll is private and gets a *Reveal* button); `/pbta` makes a 2d6 + stat move with an outcome tier;
`/3d20` does a DSA-style check with raw numbers. `[[1d20+3]]` anywhere in a message rolls inline (up to 5).
Every public roll has a 🎲 *Reroll* button.

**Characters:**
`/char create | use | list | show | profile | description | color | avatar | rename | delete`. Each player can have several characters
per campaign and switch between them. `/char show` posts the character sheet card (see *Character sheet card*).

**Stats:**
`/stat set dex 3` sets a plain value, while `/stat set max_hp 10 + con * level` sets a **derived stat**
that recalculates automatically when `con` or `level` changes. Circular formulas are detected.
`/stat bulk str=3, dex=2` sets many at once, and `/stat remove` deletes one.

**Skills:**
`/skill add stealth 1d20+dex+2` adds a formula skill, and `/skill add-3d20 climb mu ge kk 6` adds a 3d20 skill
(three attributes plus skill points; the result shows the quality level, crits on double 1s, and
botches on double 20s). `/skill remove` deletes a skill.

**Macros:**
`/macro save | remove | list`. Macros are personal per server, work across campaigns, and can use stats,
skills, and other macros. Put `$1`, `$2`, … in a macro for values you choose each roll: save `pool` as
`$1d10!>=8 # Pool`, then roll `/r pool(5)`, `/r pool(7)` or `/r pool(dex+2)`.
The GM can share a macro with everyone in the campaign: `/macro save pool $1d10!>=8 # Pool campaign:True`
(and `/macro remove pool campaign:True`). A player's own macro with the same name takes priority, and
`/macro list` shows both.

**Campaigns:**
`/campaign create | link | unlink | info | gm-role | transfer | webhooks | dice`. A campaign spans one or more
channels, and threads inherit their parent's campaign. Server admins (Manage Server) always count as GM.

**Campaign dice rules:**
`/campaign dice sides:10 success:8 explode:10 cancel:1` (GM) sets the campaign's dice: which die to roll, what
counts as a success (leave `success` out, or set it to 0, to add the dice up instead), which results explode into
an extra die, and which cancel a success. Then a skill whose value is a number is a dice count:
`/skill add shooting 5` and `/check shooting` rolls `5d10!>=8f1`. `/check shooting & dex` adds a skill and a stat,
`/check 7` rolls seven dice, and `modifier` adds or removes dice. Skills with dice in them (`1d20+dex`) still roll
as written. `/campaign dice` without options shows the rules, and `sides:0` turns them off.

**Talking to the bot:**
Start a message with a mention of the bot instead of using a slash command: `@Bot roll shooting & dex`,
`@Bot roll for shooting und dex`, `@Bot w5` (five dice with the campaign rules), `@Bot 2d6+3`, `@Bot pool(7)`,
or `@Bot help`. The reply has the same card and Reroll button as `/r`. Messages that only mention the bot
somewhere in the middle are ignored.
The starting word can be English, German, French, Spanish, Italian, Dutch or Portuguese (`roll`, `check`, `throw`,
`würfel`/`würfle`/`wirf`/`prüfe`, `lance`/`jet`, `tira`/`lanza`/`lancia`, `gooi`/`werp`, `rola`/`joga`), optionally
followed by "for" (`for`, `auf`, `für`, `pour`, `para`, `per`, `voor`). Skills and stats can be joined with `&`, `,`,
`and`, `und`, `et`, `y`, `e` or `en`: `@Bot würfel auf schiessen und ge`, `@Bot check 10`, `@Bot lance 5`.
`help` works as `hilfe`, `aide`, `ayuda`, `aiuto`, `hulp` or `ajuda` too.

**Character webhooks:** when enabled (the default), rolls made with an active character are posted under the
character's name and avatar. This needs the *Manage Webhooks* permission; without it, the bot posts normally.

## Combat (Phase 2)

```
GM:      /monster save name:Goblin hp:2d6 initiative:1d20+2 ac:15
         /init start                      → posts the tracker with Join / Start buttons
Players: press 🎲 Join                    → rolls initiative for your active character
GM:      /init spawn template:Goblin count:3
         press Start combat               → round 1, the first player gets pinged
Anyone:  /hp damage amount:2d6+3 target:Goblin 2
         /condition add name:Stunned target:Goblin 1 rounds:1
Player:  press Next turn when you're done
```

**Initiative:**
`/init start | join | add | spawn | next | move | remove | show | end`. The tracker message updates
itself, and its buttons keep working after a bot restart. Initiative uses your character's `initiative`
skill if it has one; otherwise it uses the campaign formula (`/campaign init-formula 1d20+dex`,
default `1d20`), or the number or roll you pass to `/init join`. Monsters at 0 HP are skipped
automatically. `/init show` re-posts the tracker at the bottom of the chat, and
`/init show details:True` privately gives the GM exact monster HP and AC.

**HP:**
`/hp damage | heal | temp | set | show`. Amounts can be rolls (`2d6+str`). Temp HP absorbs damage
first and doesn't stack, healing stops at max HP, and HP never drops below 0. A character's max HP is
their `max_hp` stat, and their HP is kept between fights. Players only see a monster's health as a
status (Unhurt, Hurt, Bloodied, Down). Anyone can deal damage or heal; only the owner or
the GM can `/hp set` a character, and only the GM can set monster HP.

**Conditions:**
`/condition add | remove`, using common names (with autocomplete) or anything you like, plus an
optional note. With `rounds`, a condition counts down at the end of the target's turn and is announced
when it wears off. If it's applied during the target's own turn, the countdown starts at their next turn,
so "2 rounds" always means two full rounds.

**Monster templates (GM):**
`/monster save | list | remove`. Each template stores HP and initiative (as rolls or numbers), AC, and
notes, and `/init spawn` numbers the copies automatically (Goblin 1, Goblin 2, …).

**Group checks (GM):**
`/group-check roll:perception dc:15`. Everyone presses 🎲 Roll and the results are collected in one
message. With a DC, each roll shows pass or fail, and the group succeeds if half or more pass.
`secret:True` hides the results from players, and the GM views them with *Results (GM)*.

**Dashboard:**
`/dashboard` posts the party's HP and conditions plus the combat status, and updates itself whenever
something changes. Pin it.

## Progress, companions & world building (Phase 3)

```
Player:  /res add name:slots_1 max:level+1 reset:Long rest
         /res use slots_1                 → "Lyra uses 1 slots_1 → 1/2"
GM:      /xp table dnd5e
         /xp award 300 reason:the goblin cave     → level-ups are announced, `level` updates
         /rest kind:Long rest party:True
Player:  /companion add Whiskers
         /companion roll Whiskers 1d20+2  → posted as Whiskers
GM:      /generate npc · /table create name:Forest · /note add title:Mayor Ulric gm_only:True
```

**Resources:**
`/res add | use | gain | set | remove | list`. The max can be a formula (`level + 1`), so it grows
when you level up. Each resource refills on a short rest, a long rest, or never (manual).

**Rests:**
`/rest kind:Short rest` refills short-rest resources, and `kind:Long rest` refills everything and
restores HP to `max_hp` (switch that off with `restore_hp:False`). Companions rest along with their
owner, and the GM can rest the whole party with `party:True`.

**XP & levels:**
`/xp award | set | show | table`. Pick a level table with `/xp table dnd5e`, `pathfinder`, your own
numbers (`0, 1000, 3000, 6000`), or `none` for XP without levels. Crossing a threshold announces the
level-up and updates the character's `level` stat, so derived stats like `max_hp = 10 + level*5`
grow automatically. A `level` stat that's a formula is never overwritten. `award` goes to the whole
party by default, `split:True` divides the amount, and companions don't get XP.

**Companions:**
`/companion add | list | roll | join | remove`. A companion is a full character with its own stats,
skills, HP, conditions, and resources, and it's posted under its own name and avatar. To edit it,
switch with `/char use Whiskers` and back with `/char use Lyra`; everything else works without
switching. Companions show up on the dashboard and can be targeted by `/hp` and `/condition`.

**Export/import:**
`/char export` gives you a JSON file of the character and its companions (stats, skills, resources,
HP, XP, inventory, money, profile, description, and the card colour). `/char import` takes that file into any campaign or server, with `name:` to rename it.
The file is fully validated before anything is written.

**Random tables:**
`/table create | edit | add | roll | show | list | delete`. Leave out `entries` to get a proper
multi-line editor. One entry goes per line, `3* text` gives an entry weight 3, `[[1d6]]` is rolled,
and `{other_table}` rolls on another table (nested up to 5 levels). Built-in tables are `npc`,
`name`, `tavern`, `loot`, `weather`, and `complication`, plus their parts; `/table edit npc` copies a
built-in into your campaign so you can customise it. `/generate` is a quick shortcut for the built-ins.

**Notes:**
`/note add | edit | show | search | list | delete`. Categories are NPC, Place, Quest, Item, Faction,
Lore, and Session. GM-only notes are invisible to players, including in search and autocomplete.
Leave out `text` to get the big editor, and use `public:True` to share a note with the table. Only a
note's author or the GM can edit or delete it.

## Sessions, stats & scheduling (Phase 4)

```
GM:      /campaign timezone Europe/Berlin
         /schedule set when:fri 19:30                     → "Tomorrow is session day!" the day before,
                                                            reminders 1h before and at the start
         /session start title:The Goblin Cave
Anyone:  /session moment text:Grom tried to seduce the dragon
GM:      /session end                                     → posts the recap
Anyone:  /stats · /halloffame · /achievements
```

**Sessions:**
`/session start | end | moment | recap | list`. The recap shows the length, dice totals, the luckiest
and unluckiest players, the biggest roll, and a timeline of key moments: natural 20s and 1s,
monsters defeated, characters dropping and getting back up, level-ups, fights, and your own
`/session moment` notes. It also shows the XP awarded and who was at the table. Starting a session
clears its schedule and stops the reminders.

**Stats:**
`/stats [player] [scope]` is split up by how you roll. **Success pools** get one section per set of
rules (e.g. "d10 · success at ≥ 8 · 10s explode"): successes per roll compared with the expected
number for those rules, rolls without a success, the best roll, and bonus dice from explosions.
**Every die type** you rolled (d20, d10, d6, Fate…) gets its average compared with the expected one
and how often its highest and lowest faces came up. 3d20 checks, the biggest total and a chart of your
most-rolled die follow. The luck verdict looks at every die you rolled, so it works for any system.
The scope is this session, this campaign, or the whole server.

**Hall of Fame:**
`/halloffame` has leaderboards for the most natural 20s and 1s, the luckiest and unluckiest players
(by how far above or below average all their dice land; 20+ dice needed), the biggest rolls, monster
slayers, and achievements. Session recaps name the luckiest and unluckiest player the same way.

**Achievements:**
`/achievements [player]` lists 17 achievements, from "Let's Roll" and "Natural Talent" through
"Cursed Dice" (three 1s in a row) to "Living Legend" (level 10). They're announced in the channel the
moment you earn one.

**Secret rolls never count** toward stats, achievements, recaps, or the Hall of Fame, since that
would give away a hidden natural 20.

**Scheduling:**
`/schedule set | show | cancel`. You can type dates like `fri 19:30`, `tomorrow 19:30`,
`9.10. 19:30`, `09.10.2026 19:30`, or `2026-10-09 19:30`, in the campaign's time zone (`/campaign
timezone`, with any capitalisation). Every player sees times in their own time zone, and
daylight-saving changes are handled. The day before, the bot posts "Tomorrow is session day!";
more reminders follow 1 hour before and at the start. They ping the GM, every player with a
character, and the GM role. A session set less than a day ahead skips the day-before reminder (the
announcement already did that job). If the bot was offline at session time, it skips the late
reminder instead of posting it hours after the fact. To agree on a date first, use Discord's built-in polls.

## Language, inventory & character sheets (Phase 5)

```
GM:      /campaign language Deutsch                → everything players see is now in German
         /campaign sheet                           → lay out the sheet card for your game
Player:  /item add name:Seil amount:2 note:15 m     /money add amount:30 currency:Dukaten
         /item give name:Heiltrank to:Grom          /money give amount:10 to:Gruppeninventar
         /char color purple · /char show public:True
```

**Language:**
`/campaign language English | Deutsch` (GM) switches what the bot says in that campaign: roll cards and
inline sentences, pools and dice rules, mention replies, reminders, `/help` (fully translated), inventory
messages and the character sheet card. Outside a campaign, `/help` follows the language of the player's
Discord app. German players can write dice as `2W6`, and `/schedule set` understands German dates
(`fr 19:30`, `Freitag 19:30 Uhr`, `morgen 18:00`, `heute 20:00`). Error messages, GM tools (combat tracker,
statistics, recaps, achievements) and slash command names are still English. Translations live in
`core/i18n.py` with the English text as the key, so adding more is easy.

**Inventory & money:**
`/item add | remove | give | take`, `/money add | spend | give | take` and `/inventory`. Every character has
items (with amounts and optional notes) and money in any currencies you like; leave out `currency` and the
bot uses the one you already have. The campaign's **party stash** (`stash:True`, or `to:Party stash`) is
shared by everyone. The GM can hand out loot to any character with `character:`. Companions have their own
inventories, and deleting a character removes its inventory.

**Character sheet card:**
`/char show` shows a card with the portrait, the card colour (`/char color #8e44ad` or `purple`), HP bar,
XP and level, conditions, a short description (`/char description` opens an editor), a profile with any
details you like (`/char profile field:Age value:24`, `field:Hair value:silver`; common fields are
suggested, in German for German campaigns), stats, skills, resources, inventory and money. Sections with
many entries are shown as a three-column grid. The GM shapes it for their game with
`/campaign sheet`, one section per line:
```
Attributes: str, dex, con, int, wis, cha
Combat: max_hp, ac, initiative
Talents: Climbing=climb, Stealth=stealth
```
Entries are stats or skills (number skills show their value); `Label=name` sets your own label. Anything
the layout doesn't mention still appears under *More* and *Skills*. Without a layout the card shows base
stats and derived stats. `/campaign sheet reset:True` goes back to automatic.

## Style

Replies are plain text with at most one emoji per message, from a small set: ✨ success, 🍀 luck
(natural 20s, critical successes), 💤 misses and botches, 🌸 friendly notices (welcome, reminders),
and 🎲 rolling. The dice buttons (Reroll, Join, Roll) carry a 🎲; other buttons are text only.

## Project structure

```
bot.py              entry point, loads cogs, syncs slash commands
dice/engine.py      safe dice parser and evaluator (no eval)
dice/systems.py     3d20 checks, PbtA outcomes
core/db.py          schema and queries for SQLite (aiosqlite) or MySQL/MariaDB (aiomysql)
core/sheet.py       stat/derived-stat resolution, skill and macro expansion
core/helpers.py     embeds, errors, campaign lookup, webhook posting
core/rolls.py       shared roll → embed builder (used by /r, inline rolls, group checks)
core/combat.py      combat rules: damage, healing, health status, turn order
core/table.py       targets, HP storage, live tracker and dashboard rendering
core/progress.py    XP/level tables, resources, rests
core/randtables.py  random table engine and built-in generators
core/transfer.py    character export/import with validation
core/clock.py       single source of "now" (lets tests fast-forward time)
core/stats.py       dice statistics, luck verdicts, histograms, leaderboards
core/achievements.py  achievement definitions and the unlock/announce service
core/recap.py       session recap builder
core/scheduling.py  date parsing in the campaign's time zone (English and German)
core/i18n.py        translations (English text as key) and the campaign language list
core/helptext.py    the /help chapters; core/helptext_de.py the German ones
core/inventory.py   item and money formatting
core/sheetcard.py   the character sheet card and the GM's sheet layout
cogs/rolling.py     /r /check /secret /pbta /3d20 /help, inline rolls, buttons
cogs/characters.py  /char /stat /skill /macro
cogs/campaigns.py   /campaign
cogs/combat.py      /init /monster, persistent tracker buttons
cogs/health.py      /hp /condition /dashboard
cogs/groupcheck.py  /group-check
cogs/progress.py    /res /rest /xp
cogs/companions.py  /companion
cogs/lore.py        /table /generate /note
cogs/sessions.py    /session /stats /halloffame /achievements
cogs/schedule.py    /schedule and the reminder loop
cogs/inventory.py   /item /money /inventory, party stash
tests/              engine, sheet and database tests
```

Every roll is written to the `roll_log` table, so stats and achievements include your full history,
back to your first roll in Phase 1.

## Roadmap

- ~~Phase 2 (Combat)~~ done
- ~~Phase 3 (Progression & content)~~ done
- ~~Phase 4 (Session tools)~~ done
- ~~Phase 5 (Language, inventory & character sheets)~~ done
