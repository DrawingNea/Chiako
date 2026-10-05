"""
Async storage for campaigns, characters, stats, skills, macros and the roll log.

Runs on SQLite (a local file) or MySQL/MariaDB. Queries are written in SQLite syntax and
translated for MySQL by _to_mysql().
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite

try:
    import aiomysql
    import pymysql
except ImportError:  # MySQL support is optional
    aiomysql = pymysql = None

from . import clock

# Raised on duplicate names etc. by either backend
IntegrityError: tuple = (aiosqlite.IntegrityError,) + ((pymysql.err.IntegrityError,) if pymysql else ())

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS campaigns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    name          TEXT    NOT NULL COLLATE NOCASE,
    gm_user_id    INTEGER NOT NULL,
    gm_role_id    INTEGER,
    use_webhooks  INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL,
    UNIQUE (guild_id, name)
);

CREATE TABLE IF NOT EXISTS campaign_channels (
    channel_id   INTEGER PRIMARY KEY,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS characters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    owner_id     INTEGER NOT NULL,
    name         TEXT    NOT NULL COLLATE NOCASE,
    avatar_url   TEXT,
    created_at   INTEGER NOT NULL,
    UNIQUE (campaign_id, owner_id, name)
);

CREATE TABLE IF NOT EXISTS active_characters (
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL,
    character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, user_id)
);

-- A stat is a fixed number or a dice-free formula (derived stat), e.g. "10 + @con * @level"
CREATE TABLE IF NOT EXISTS stats (
    character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    formula       TEXT    NOT NULL,
    PRIMARY KEY (character_id, name)
);

-- kind 'formula': formula like "1d20 + @dex + 2"
-- kind '3d20'   : attributes = JSON list of 3 stat names, points = skill value
CREATE TABLE IF NOT EXISTS skills (
    character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'formula',
    formula       TEXT,
    attributes    TEXT,
    points        INTEGER,
    PRIMARY KEY (character_id, name)
);

CREATE TABLE IF NOT EXISTS macros (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    expression  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id, name)
);

-- Every roll is logged; used later for dice stats, achievements and session recaps.
CREATE TABLE IF NOT EXISTS roll_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER,
    channel_id    INTEGER,
    campaign_id   INTEGER,
    user_id       INTEGER NOT NULL,
    character_id  INTEGER,
    expression    TEXT    NOT NULL,
    label         TEXT,
    total         INTEGER,
    natural       INTEGER,
    secret        INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roll_log_campaign ON roll_log (campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_roll_log_user ON roll_log (guild_id, user_id);

-- Phase 2 ---------------------------------------------------------------

-- Persistent HP of player characters (max HP is the character's `max_hp` stat)
CREATE TABLE IF NOT EXISTS character_state (
    character_id  INTEGER PRIMARY KEY REFERENCES characters(id) ON DELETE CASCADE,
    hp            INTEGER,
    temp_hp       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS encounters (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id         INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    channel_id          INTEGER NOT NULL,
    tracker_message_id  INTEGER,
    round               INTEGER NOT NULL DEFAULT 0,   -- 0 = still rolling initiative
    current_id          INTEGER,                      -- combatant whose turn it is
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_encounter ON encounters (campaign_id) WHERE active = 1;

-- Characters in combat use character_state for HP; monsters keep HP here
CREATE TABLE IF NOT EXISTS combatants (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id  INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL COLLATE NOCASE,
    initiative    INTEGER NOT NULL,
    tiebreak      REAL    NOT NULL,
    character_id  INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    owner_id      INTEGER,
    hp            INTEGER,
    max_hp        INTEGER,
    temp_hp       INTEGER NOT NULL DEFAULT 0,
    ac            INTEGER,
    UNIQUE (encounter_id, name)
);

-- A condition sits on a character (persistent) or on a monster combatant
CREATE TABLE IF NOT EXISTS conditions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id  INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    combatant_id  INTEGER REFERENCES combatants(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL COLLATE NOCASE,
    rounds_left   INTEGER,                            -- NULL = until removed
    note          TEXT,
    CHECK ((character_id IS NULL) != (combatant_id IS NULL))
);

CREATE TABLE IF NOT EXISTS monster_templates (
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL COLLATE NOCASE,
    hp           TEXT,
    initiative   TEXT    NOT NULL DEFAULT '1d20',
    ac           INTEGER,
    notes        TEXT,
    PRIMARY KEY (campaign_id, name)
);
"""

# Phase 3 tables are appended to SCHEMA below.
SCHEMA += """
-- Phase 3 ---------------------------------------------------------------

-- Spell slots, ammo, ki, luck... max may be a formula like "@level + 1"
CREATE TABLE IF NOT EXISTS resources (
    character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    current       INTEGER NOT NULL,
    max_formula   TEXT    NOT NULL,
    reset         TEXT    NOT NULL DEFAULT 'long',   -- short | long | never
    PRIMARY KEY (character_id, name)
);

-- entries = JSON list of [weight, text]
CREATE TABLE IF NOT EXISTS random_tables (
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL COLLATE NOCASE,
    entries      TEXT    NOT NULL,
    PRIMARY KEY (campaign_id, name)
);

CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL COLLATE NOCASE,
    category     TEXT    NOT NULL DEFAULT 'Lore',
    content      TEXT    NOT NULL,
    gm_only      INTEGER NOT NULL DEFAULT 0,
    author_id    INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    UNIQUE (campaign_id, title)
);
"""

SCHEMA += """
-- Phase 4 ---------------------------------------------------------------

-- Memorable things for session recaps: crits, level-ups, knockouts, fights, manual moments
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    guild_id     INTEGER NOT NULL,
    kind         TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    user_id      INTEGER,
    value        INTEGER,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_campaign ON events (campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events (guild_id, user_id, kind);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    number       INTEGER NOT NULL,
    title        TEXT,
    channel_id   INTEGER NOT NULL,
    started_at   INTEGER NOT NULL,
    ended_at     INTEGER,
    UNIQUE (campaign_id, number)
);

CREATE TABLE IF NOT EXISTS achievements (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    key          TEXT    NOT NULL,
    unlocked_at  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, key)
);

-- One upcoming session per campaign. reminded: bitmask 1 = 24h, 2 = 1h, 4 = start
CREATE TABLE IF NOT EXISTS scheduled_sessions (
    campaign_id  INTEGER PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
    channel_id   INTEGER NOT NULL,
    starts_at    INTEGER NOT NULL,
    title        TEXT,
    reminded     INTEGER NOT NULL DEFAULT 0
);


-- Inventory and money. character_id NULL = the campaign's shared party stash.
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    character_id  INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL COLLATE NOCASE,
    qty           INTEGER NOT NULL DEFAULT 1,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_owner ON items (campaign_id, character_id);

CREATE TABLE IF NOT EXISTS money (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    character_id  INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    currency      TEXT    NOT NULL COLLATE NOCASE,
    amount        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_money_owner ON money (campaign_id, character_id);

-- Macros the GM sets for everyone in the campaign; a player's own macro with the same name wins
CREATE TABLE IF NOT EXISTS campaign_macros (
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    expression   TEXT    NOT NULL,
    PRIMARY KEY (campaign_id, name)
);
"""

# Columns added after Phase 1; added automatically to existing databases.
MIGRATIONS = [
    ("campaigns", "init_formula", "TEXT NOT NULL DEFAULT '1d20'"),
    ("campaigns", "dashboard_channel_id", "INTEGER"),
    ("campaigns", "dashboard_message_id", "INTEGER"),
    # 1 = added during the target's own turn, so that turn's end doesn't count down yet
    ("conditions", "fresh", "INTEGER NOT NULL DEFAULT 0"),
    # Phase 3
    ("characters", "parent_id", "INTEGER REFERENCES characters(id) ON DELETE CASCADE"),  # companions
    ("character_state", "xp", "INTEGER NOT NULL DEFAULT 0"),
    ("campaigns", "xp_table", "TEXT"),  # JSON list of XP thresholds, NULL = no levels
    # Phase 4
    ("campaigns", "timezone", "TEXT NOT NULL DEFAULT 'UTC'"),
    # Campaign dice rules for /check and dice counts (NULL = off): roll d<sides>, explode on >= explode,
    # count dice >= success as successes (NULL = add up), dice <= cancel remove a success
    ("campaigns", "dice_sides", "INTEGER"),
    ("campaigns", "dice_explode", "INTEGER"),
    ("campaigns", "dice_success", "INTEGER"),
    ("campaigns", "dice_cancel", "INTEGER"),
    # Dice statistics: what kind of roll ('sum', 'pool', 'fate', '3d20'), the pool's rules (e.g. 'd10>=8!10f1'),
    # every die face rolled as JSON {"20": [14], "6": [3, 5]}, and the expected number of successes for pools
    ("roll_log", "kind", "TEXT"),
    ("roll_log", "setting", "TEXT"),
    ("roll_log", "faces", "MEDIUMTEXT"),
    ("roll_log", "expected", "REAL"),
    ("campaigns", "language", "TEXT NOT NULL DEFAULT 'en'"),   # 'en' or 'de'
    ("campaigns", "sheet_layout", "TEXT"),                     # the GM's character sheet layout, see core/sheetcard
    ("characters", "color", "INTEGER"),                        # the character card's accent colour
    ("characters", "profile", "MEDIUMTEXT"),                   # JSON [[field, value], ...]: age, hair, eyes…
    ("characters", "bio", "MEDIUMTEXT"),                       # a short description
]

# The same tables for MySQL/MariaDB, including every column from MIGRATIONS.
# Discord IDs need BIGINT; names that are part of a key are VARCHAR; "ci" collations are case-insensitive
# like SQLite's NOCASE. `key` and `natural` are reserved words in MySQL, so queries quote them.
MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS campaigns (
        id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
        guild_id              BIGINT NOT NULL,
        name                  VARCHAR(255) NOT NULL,
        gm_user_id            BIGINT NOT NULL,
        gm_role_id            BIGINT,
        use_webhooks          INT NOT NULL DEFAULT 1,
        created_at            BIGINT NOT NULL,
        init_formula          VARCHAR(500) NOT NULL DEFAULT '1d20',
        dashboard_channel_id  BIGINT,
        dashboard_message_id  BIGINT,
        xp_table              TEXT,
        timezone              VARCHAR(64) NOT NULL DEFAULT 'UTC',
        dice_sides            INT,
        dice_explode          INT,
        dice_success          INT,
        dice_cancel           INT,
        language              VARCHAR(8) NOT NULL DEFAULT 'en',
        sheet_layout          TEXT,
        UNIQUE (guild_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_channels (
        channel_id   BIGINT PRIMARY KEY,
        campaign_id  BIGINT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS characters (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id  BIGINT NOT NULL,
        owner_id     BIGINT NOT NULL,
        name         VARCHAR(255) NOT NULL,
        avatar_url   TEXT,
        created_at   BIGINT NOT NULL,
        parent_id    BIGINT,
        color        BIGINT,
        profile      MEDIUMTEXT,
        bio          MEDIUMTEXT,
        UNIQUE (campaign_id, owner_id, name),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (parent_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS active_characters (
        campaign_id   BIGINT NOT NULL,
        user_id       BIGINT NOT NULL,
        character_id  BIGINT NOT NULL,
        PRIMARY KEY (campaign_id, user_id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS stats (
        character_id  BIGINT NOT NULL,
        name          VARCHAR(255) NOT NULL,
        formula       TEXT NOT NULL,
        PRIMARY KEY (character_id, name),
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS skills (
        character_id  BIGINT NOT NULL,
        name          VARCHAR(255) NOT NULL,
        kind          VARCHAR(16) NOT NULL DEFAULT 'formula',
        formula       TEXT,
        attributes    TEXT,
        points        INT,
        PRIMARY KEY (character_id, name),
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS macros (
        guild_id    BIGINT NOT NULL,
        user_id     BIGINT NOT NULL,
        name        VARCHAR(255) NOT NULL,
        expression  TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS roll_log (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        guild_id      BIGINT,
        channel_id    BIGINT,
        campaign_id   BIGINT,
        user_id       BIGINT NOT NULL,
        character_id  BIGINT,
        expression    TEXT NOT NULL,
        label         TEXT,
        total         BIGINT,
        `natural`     INT,
        secret        INT NOT NULL DEFAULT 0,
        kind          VARCHAR(16),
        setting       VARCHAR(64),
        faces         MEDIUMTEXT,
        expected      DOUBLE,
        created_at    BIGINT NOT NULL,
        INDEX idx_roll_log_campaign (campaign_id, created_at),
        INDEX idx_roll_log_user (guild_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS character_state (
        character_id  BIGINT PRIMARY KEY,
        hp            INT,
        temp_hp       INT NOT NULL DEFAULT 0,
        xp            BIGINT NOT NULL DEFAULT 0,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    # active_campaign replaces SQLite's partial unique index: at most one active encounter per campaign
    """CREATE TABLE IF NOT EXISTS encounters (
        id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id         BIGINT NOT NULL,
        channel_id          BIGINT NOT NULL,
        tracker_message_id  BIGINT,
        round               INT NOT NULL DEFAULT 0,
        current_id          BIGINT,
        active              INT NOT NULL DEFAULT 1,
        created_at          BIGINT NOT NULL,
        active_campaign     BIGINT AS (IF(active = 1, campaign_id, NULL)) STORED,
        UNIQUE (active_campaign),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS combatants (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        encounter_id  BIGINT NOT NULL,
        name          VARCHAR(255) NOT NULL,
        initiative    INT NOT NULL,
        tiebreak      DOUBLE NOT NULL,
        character_id  BIGINT,
        owner_id      BIGINT,
        hp            INT,
        max_hp        INT,
        temp_hp       INT NOT NULL DEFAULT 0,
        ac            INT,
        UNIQUE (encounter_id, name),
        FOREIGN KEY (encounter_id) REFERENCES encounters(id) ON DELETE CASCADE,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS conditions (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        character_id  BIGINT,
        combatant_id  BIGINT,
        name          VARCHAR(255) NOT NULL,
        rounds_left   INT,
        note          TEXT,
        fresh         INT NOT NULL DEFAULT 0,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
        FOREIGN KEY (combatant_id) REFERENCES combatants(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS monster_templates (
        campaign_id  BIGINT NOT NULL,
        name         VARCHAR(255) NOT NULL,
        hp           VARCHAR(500),
        initiative   VARCHAR(500) NOT NULL DEFAULT '1d20',
        ac           INT,
        notes        TEXT,
        PRIMARY KEY (campaign_id, name),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS resources (
        character_id  BIGINT NOT NULL,
        name          VARCHAR(255) NOT NULL,
        current       INT NOT NULL,
        max_formula   TEXT NOT NULL,
        reset         VARCHAR(16) NOT NULL DEFAULT 'long',
        PRIMARY KEY (character_id, name),
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS random_tables (
        campaign_id  BIGINT NOT NULL,
        name         VARCHAR(255) NOT NULL,
        entries      MEDIUMTEXT NOT NULL,
        PRIMARY KEY (campaign_id, name),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS notes (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id  BIGINT NOT NULL,
        title        VARCHAR(255) NOT NULL,
        category     VARCHAR(32) NOT NULL DEFAULT 'Lore',
        content      MEDIUMTEXT NOT NULL,
        gm_only      INT NOT NULL DEFAULT 0,
        author_id    BIGINT NOT NULL,
        created_at   BIGINT NOT NULL,
        updated_at   BIGINT NOT NULL,
        UNIQUE (campaign_id, title),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id  BIGINT,
        guild_id     BIGINT NOT NULL,
        kind         VARCHAR(32) NOT NULL,
        text         TEXT NOT NULL,
        user_id      BIGINT,
        value        BIGINT,
        created_at   BIGINT NOT NULL,
        INDEX idx_events_campaign (campaign_id, created_at),
        INDEX idx_events_user (guild_id, user_id, kind),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id           BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id  BIGINT NOT NULL,
        number       INT NOT NULL,
        title        TEXT,
        channel_id   BIGINT NOT NULL,
        started_at   BIGINT NOT NULL,
        ended_at     BIGINT,
        UNIQUE (campaign_id, number),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS achievements (
        guild_id     BIGINT NOT NULL,
        user_id      BIGINT NOT NULL,
        `key`        VARCHAR(64) NOT NULL,
        unlocked_at  BIGINT NOT NULL,
        PRIMARY KEY (guild_id, user_id, `key`)
    )""",
    """CREATE TABLE IF NOT EXISTS scheduled_sessions (
        campaign_id  BIGINT PRIMARY KEY,
        channel_id   BIGINT NOT NULL,
        starts_at    BIGINT NOT NULL,
        title        TEXT,
        reminded     INT NOT NULL DEFAULT 0,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS items (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id   BIGINT NOT NULL,
        character_id  BIGINT,
        name          VARCHAR(255) NOT NULL,
        qty           BIGINT NOT NULL DEFAULT 1,
        note          TEXT,
        INDEX idx_items_owner (campaign_id, character_id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS money (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        campaign_id   BIGINT NOT NULL,
        character_id  BIGINT,
        currency      VARCHAR(64) NOT NULL,
        amount        BIGINT NOT NULL DEFAULT 0,
        INDEX idx_money_owner (campaign_id, character_id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_macros (
        campaign_id  BIGINT NOT NULL,
        name         VARCHAR(255) NOT NULL,
        expression   TEXT NOT NULL,
        PRIMARY KEY (campaign_id, name),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )""",
]
MYSQL_TABLE_OPTIONS = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"


@functools.lru_cache(maxsize=None)
def _to_mysql(sql: str) -> str:
    """Translate the SQLite dialect used in this file to MySQL/MariaDB."""
    sql = sql.replace("?", "%s")
    sql = sql.replace(" ESCAPE '\\'", "")  # backslash is already MySQL's LIKE escape
    sql = sql.replace("INSERT OR IGNORE", "INSERT IGNORE")
    sql = re.sub(r"ON CONFLICT\s*\([^)]*\)\s*DO UPDATE SET", "ON DUPLICATE KEY UPDATE", sql)
    return re.sub(r"\bexcluded\.(\w+)", r"VALUES(\1)", sql)


def _mysql_column(decl: str) -> str:
    """A MIGRATIONS column declaration in MySQL types (foreign keys are left out)."""
    decl = re.sub(r"\s*REFERENCES .*", "", decl)
    decl = re.sub(r"\bINTEGER\b", "BIGINT", decl)
    return re.sub(r"\bTEXT\b", "VARCHAR(500)", decl)


@dataclass
class Campaign:
    id: int
    guild_id: int
    name: str
    gm_user_id: int
    gm_role_id: Optional[int]
    use_webhooks: bool
    init_formula: str = "1d20"
    dashboard_channel_id: Optional[int] = None
    dashboard_message_id: Optional[int] = None
    xp_table: Optional[list[int]] = None
    timezone: str = "UTC"
    dice_sides: Optional[int] = None     # campaign dice rules, see MIGRATIONS
    dice_explode: Optional[int] = None
    dice_success: Optional[int] = None
    dice_cancel: Optional[int] = None
    language: str = "en"                 # 'en' or 'de'
    sheet_layout: Optional[str] = None   # GM's character sheet layout


@dataclass
class Item:
    id: int
    campaign_id: int
    character_id: Optional[int]   # None = party stash
    name: str
    qty: int
    note: Optional[str]


@dataclass
class Character:
    id: int
    campaign_id: int
    owner_id: int
    name: str
    avatar_url: Optional[str]
    parent_id: Optional[int] = None   # set for companions
    color: Optional[int] = None       # accent colour of the character card
    profile: list = field(default_factory=list)   # [[field, value], ...] in the player's order
    bio: Optional[str] = None         # short description

    @property
    def is_companion(self) -> bool:
        return self.parent_id is not None


@dataclass
class Skill:
    name: str
    kind: str  # 'formula' or '3d20'
    formula: Optional[str] = None
    attributes: Optional[list[str]] = None
    points: Optional[int] = None

    def describe(self) -> str:
        if self.kind == "3d20":
            return f"3d20 vs {'/'.join(self.attributes or [])} · {self.points} pts"
        return self.formula or ""


@dataclass
class Encounter:
    id: int
    campaign_id: int
    channel_id: int
    tracker_message_id: Optional[int]
    round: int
    current_id: Optional[int]
    active: bool


@dataclass
class Combatant:
    id: int
    encounter_id: int
    name: str
    initiative: int
    tiebreak: float
    character_id: Optional[int]
    owner_id: Optional[int]
    hp: Optional[int]
    max_hp: Optional[int]
    temp_hp: int
    ac: Optional[int]

    @property
    def is_monster(self) -> bool:
        return self.character_id is None


@dataclass
class Condition:
    id: int
    character_id: Optional[int]
    combatant_id: Optional[int]
    name: str
    rounds_left: Optional[int]
    note: Optional[str]
    fresh: int = 0

    def label(self) -> str:
        text = self.name
        if self.rounds_left is not None:
            text += f" ({self.rounds_left})"
        return text


@dataclass
class Resource:
    character_id: int
    name: str
    current: int
    max_formula: str
    reset: str


@dataclass
class Note:
    id: int
    campaign_id: int
    title: str
    category: str
    content: str
    gm_only: int
    author_id: int
    created_at: int
    updated_at: int


@dataclass
class Session:
    id: int
    campaign_id: int
    number: int
    title: Optional[str]
    channel_id: int
    started_at: int
    ended_at: Optional[int]


@dataclass
class Event:
    id: int
    campaign_id: Optional[int]
    guild_id: int
    kind: str
    text: str
    user_id: Optional[int]
    value: Optional[int]
    created_at: int


@dataclass
class RollRow:
    user_id: int
    character_id: Optional[int]
    expression: str
    label: Optional[str]
    total: Optional[int]
    natural: Optional[int]
    created_at: int
    kind: Optional[str] = None       # 'sum', 'pool', 'fate', '3d20'; None for rolls logged before this existed
    setting: Optional[str] = None    # pools: their rules, e.g. 'd10>=8!10f1'
    faces: Optional[str] = None      # JSON {"sides": [faces]} of every die rolled
    expected: Optional[float] = None  # pools: expected successes

    @property
    def dice(self) -> dict[str, list[int]]:
        return json.loads(self.faces) if self.faces else {}


@dataclass
class Scheduled:
    campaign_id: int
    channel_id: int
    starts_at: int
    title: Optional[str]
    reminded: int


@dataclass
class MonsterTemplate:
    campaign_id: int
    name: str
    hp: Optional[str]
    initiative: str
    ac: Optional[int]
    notes: Optional[str]


def _row(cls, row):
    return None if row is None else cls(**{k: row[k] for k in row.keys()})


def _campaign(row) -> Optional[Campaign]:
    if row is None:
        return None
    return Campaign(row["id"], row["guild_id"], row["name"], row["gm_user_id"], row["gm_role_id"],
                    bool(row["use_webhooks"]), row["init_formula"], row["dashboard_channel_id"],
                    row["dashboard_message_id"], json.loads(row["xp_table"]) if row["xp_table"] else None,
                    row["timezone"], row["dice_sides"], row["dice_explode"], row["dice_success"],
                    row["dice_cancel"], row["language"] or "en", row["sheet_layout"])


def _character(row) -> Optional[Character]:
    if row is None:
        return None
    keys = row.keys()
    profile = json.loads(row["profile"]) if "profile" in keys and row["profile"] else []
    return Character(row["id"], row["campaign_id"], row["owner_id"], row["name"], row["avatar_url"],
                     row["parent_id"] if "parent_id" in keys else None, row["color"] if "color" in keys else None,
                     profile, row["bio"] if "bio" in keys else None)


class Database:
    """
    Database("dicebot.db") stores everything in a local SQLite file.
    Database(mysql={"host": ..., "port": ..., "user": ..., "password": ..., "db": ...}) uses MySQL/MariaDB.
    """

    def __init__(self, path: Optional[str] = None, *, mysql: Optional[dict] = None):
        if mysql is None and path is None:
            raise ValueError("give a SQLite path or MySQL settings")
        self.path = path
        self.mysql = mysql
        self.conn: Optional[aiosqlite.Connection] = None   # SQLite
        self.pool = None                                   # MySQL connection pool

    @property
    def backend(self) -> str:
        return "mysql" if self.mysql else "sqlite"

    async def connect(self):
        if self.mysql:
            await self._connect_mysql()
            return
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        for table, column, decl in MIGRATIONS:
            cols = [r["name"] for r in await self._all(f"PRAGMA table_info({table})")]
            if column not in cols:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        await self.conn.commit()

    async def _connect_mysql(self):
        if aiomysql is None:
            raise RuntimeError("MySQL needs the aiomysql package: pip install aiomysql")
        # pool_recycle reconnects before the server drops idle connections ("MySQL server has gone away")
        self.pool = await aiomysql.create_pool(
            minsize=1, maxsize=5, autocommit=True, charset="utf8mb4", pool_recycle=1800,
            cursorclass=aiomysql.DictCursor, **self.mysql,
        )
        # Only create missing tables: "IF NOT EXISTS" on existing ones makes MySQL print a warning per table
        existing = {r["TABLE_NAME"].lower() for r in await self._mysql(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()", (), "all")}
        for statement in MYSQL_SCHEMA:
            table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement).group(1)
            if table not in existing:
                await self._mysql(statement + MYSQL_TABLE_OPTIONS, (), "none")
        for table, column, decl in MIGRATIONS:
            exists = await self._mysql(
                "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = %s AND COLUMN_NAME = %s", (table, column), "one")
            if not exists:
                await self._mysql(f"ALTER TABLE {table} ADD COLUMN {column} {_mysql_column(decl)}", (), "none")

    async def close(self):
        if self.conn:
            await self.conn.close()
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def _mysql(self, sql: str, args: tuple, want: str):
        """Run one statement on MySQL. want: 'one', 'all', 'lastrowid', 'rowcount' or 'none'."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args or None)
                if want == "one":
                    return await cur.fetchone()
                if want == "all":
                    return await cur.fetchall()
                if want == "lastrowid":
                    return cur.lastrowid
                if want == "rowcount":
                    return cur.rowcount
                return None

    async def _one(self, sql, *args):
        if self.pool:
            return await self._mysql(_to_mysql(sql), args, "one")
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _all(self, sql, *args):
        if self.pool:
            return await self._mysql(_to_mysql(sql), args, "all")
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def _run(self, sql, *args) -> int:
        """Run a write; returns the new row id."""
        if self.pool:
            return await self._mysql(_to_mysql(sql), args, "lastrowid")
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.lastrowid

    async def _changed(self, sql, *args) -> bool:
        """Run a write; returns whether any row was changed."""
        if self.pool:
            return await self._mysql(_to_mysql(sql), args, "rowcount") > 0
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ campaigns
    async def create_campaign(self, guild_id: int, name: str, gm_user_id: int, channel_id: int) -> Campaign:
        cid = await self._run(
            "INSERT INTO campaigns (guild_id, name, gm_user_id, created_at) VALUES (?, ?, ?, ?)",
            guild_id, name, gm_user_id, clock.now(),
        )
        await self.link_channel(channel_id, cid)
        return await self.get_campaign(cid)

    async def get_campaign(self, campaign_id: int) -> Optional[Campaign]:
        return _campaign(await self._one("SELECT * FROM campaigns WHERE id = ?", campaign_id))

    async def get_campaign_by_name(self, guild_id: int, name: str) -> Optional[Campaign]:
        return _campaign(await self._one("SELECT * FROM campaigns WHERE guild_id = ? AND name = ?", guild_id, name))

    async def get_campaign_by_channel(self, channel_id: int) -> Optional[Campaign]:
        return _campaign(await self._one(
            "SELECT c.* FROM campaigns c JOIN campaign_channels cc ON cc.campaign_id = c.id WHERE cc.channel_id = ?",
            channel_id,
        ))

    async def list_campaigns(self, guild_id: int) -> list[Campaign]:
        return [_campaign(r) for r in await self._all("SELECT * FROM campaigns WHERE guild_id = ? ORDER BY name", guild_id)]

    async def link_channel(self, channel_id: int, campaign_id: int):
        await self._run(
            "INSERT INTO campaign_channels (channel_id, campaign_id) VALUES (?, ?) "
            "ON CONFLICT(channel_id) DO UPDATE SET campaign_id = excluded.campaign_id",
            channel_id, campaign_id,
        )

    async def unlink_channel(self, channel_id: int):
        await self._run("DELETE FROM campaign_channels WHERE channel_id = ?", channel_id)

    async def campaign_channels(self, campaign_id: int) -> list[int]:
        return [r["channel_id"] for r in await self._all("SELECT channel_id FROM campaign_channels WHERE campaign_id = ?", campaign_id)]

    async def update_campaign(self, campaign_id: int, **fields):
        allowed = {"gm_user_id", "gm_role_id", "use_webhooks", "name", "init_formula",
                   "dashboard_channel_id", "dashboard_message_id", "xp_table", "timezone",
                   "dice_sides", "dice_explode", "dice_success", "dice_cancel", "language", "sheet_layout"}
        if "xp_table" in fields and fields["xp_table"] is not None:
            fields["xp_table"] = json.dumps(fields["xp_table"])
        if not fields or not set(fields) <= allowed:
            raise ValueError("invalid campaign fields")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._run(f"UPDATE campaigns SET {sets} WHERE id = ?", *fields.values(), campaign_id)

    # ------------------------------------------------------------------ characters
    async def create_character(self, campaign_id: int, owner_id: int, name: str, avatar_url: Optional[str],
                               parent_id: Optional[int] = None) -> Character:
        cid = await self._run(
            "INSERT INTO characters (campaign_id, owner_id, name, avatar_url, created_at, parent_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            campaign_id, owner_id, name, avatar_url, clock.now(), parent_id,
        )
        return await self.get_character(cid)

    async def get_character(self, character_id: int) -> Optional[Character]:
        return _character(await self._one("SELECT * FROM characters WHERE id = ?", character_id))

    async def get_character_by_name(self, campaign_id: int, owner_id: int, name: str) -> Optional[Character]:
        return _character(await self._one(
            "SELECT * FROM characters WHERE campaign_id = ? AND owner_id = ? AND name = ?", campaign_id, owner_id, name
        ))

    async def list_characters(self, campaign_id: int, owner_id: Optional[int] = None) -> list[Character]:
        if owner_id is None:
            rows = await self._all("SELECT * FROM characters WHERE campaign_id = ? ORDER BY name", campaign_id)
        else:
            rows = await self._all(
                "SELECT * FROM characters WHERE campaign_id = ? AND owner_id = ? ORDER BY name", campaign_id, owner_id
            )
        return [_character(r) for r in rows]

    async def update_character(self, character_id: int, **fields):
        allowed = {"name", "avatar_url", "color", "profile", "bio"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("invalid character fields")
        if "profile" in fields:
            fields["profile"] = json.dumps(fields["profile"], ensure_ascii=False) if fields["profile"] else None
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._run(f"UPDATE characters SET {sets} WHERE id = ?", *fields.values(), character_id)

    async def delete_character(self, character_id: int):
        await self._run("DELETE FROM characters WHERE id = ?", character_id)

    async def set_active_character(self, campaign_id: int, user_id: int, character_id: int):
        await self._run(
            "INSERT INTO active_characters (campaign_id, user_id, character_id) VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id, user_id) DO UPDATE SET character_id = excluded.character_id",
            campaign_id, user_id, character_id,
        )

    async def get_active_character(self, campaign_id: int, user_id: int) -> Optional[Character]:
        return _character(await self._one(
            "SELECT c.* FROM characters c JOIN active_characters a ON a.character_id = c.id "
            "WHERE a.campaign_id = ? AND a.user_id = ?",
            campaign_id, user_id,
        ))

    # ------------------------------------------------------------------ stats & skills
    async def set_stat(self, character_id: int, name: str, formula: str):
        await self._run(
            "INSERT INTO stats (character_id, name, formula) VALUES (?, ?, ?) "
            "ON CONFLICT(character_id, name) DO UPDATE SET formula = excluded.formula",
            character_id, name, formula,
        )

    async def delete_stat(self, character_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM stats WHERE character_id = ? AND name = ?", character_id, name)

    async def get_stats(self, character_id: int) -> dict[str, str]:
        rows = await self._all("SELECT name, formula FROM stats WHERE character_id = ? ORDER BY name", character_id)
        return {r["name"]: r["formula"] for r in rows}

    async def set_skill(self, character_id: int, skill: Skill):
        await self._run(
            "INSERT INTO skills (character_id, name, kind, formula, attributes, points) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(character_id, name) DO UPDATE SET kind = excluded.kind, formula = excluded.formula, "
            "attributes = excluded.attributes, points = excluded.points",
            character_id, skill.name, skill.kind, skill.formula,
            json.dumps(skill.attributes) if skill.attributes else None, skill.points,
        )

    async def delete_skill(self, character_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM skills WHERE character_id = ? AND name = ?", character_id, name)

    async def get_skills(self, character_id: int) -> dict[str, Skill]:
        rows = await self._all("SELECT * FROM skills WHERE character_id = ? ORDER BY name", character_id)
        return {
            r["name"]: Skill(
                r["name"], r["kind"], r["formula"],
                json.loads(r["attributes"]) if r["attributes"] else None, r["points"],
            )
            for r in rows
        }

    # ------------------------------------------------------------------ macros
    async def set_macro(self, guild_id: int, user_id: int, name: str, expression: str):
        await self._run(
            "INSERT INTO macros (guild_id, user_id, name, expression) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, name) DO UPDATE SET expression = excluded.expression",
            guild_id, user_id, name, expression,
        )

    async def delete_macro(self, guild_id: int, user_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM macros WHERE guild_id = ? AND user_id = ? AND name = ?", guild_id, user_id, name)

    async def get_macros(self, guild_id: int, user_id: int) -> dict[str, str]:
        rows = await self._all(
            "SELECT name, expression FROM macros WHERE guild_id = ? AND user_id = ? ORDER BY name", guild_id, user_id
        )
        return {r["name"]: r["expression"] for r in rows}

    async def set_campaign_macro(self, campaign_id: int, name: str, expression: str):
        await self._run(
            "INSERT INTO campaign_macros (campaign_id, name, expression) VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id, name) DO UPDATE SET expression = excluded.expression",
            campaign_id, name, expression,
        )

    async def delete_campaign_macro(self, campaign_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM campaign_macros WHERE campaign_id = ? AND name = ?", campaign_id, name)

    async def get_campaign_macros(self, campaign_id: int) -> dict[str, str]:
        rows = await self._all("SELECT name, expression FROM campaign_macros WHERE campaign_id = ? ORDER BY name",
                               campaign_id)
        return {r["name"]: r["expression"] for r in rows}

    async def get_roll_macros(self, campaign_id: Optional[int], guild_id: Optional[int], user_id: int) -> dict[str, str]:
        """Every macro a player can roll here: the campaign's, overridden by their own."""
        macros = await self.get_campaign_macros(campaign_id) if campaign_id else {}
        if guild_id:
            macros.update(await self.get_macros(guild_id, user_id))
        return macros

    # ------------------------------------------------------------------ roll log
    async def log_roll(self, *, guild_id, channel_id, campaign_id, user_id, character_id,
                       expression, label, total, natural, secret=False, kind=None, setting=None,
                       faces: Optional[dict] = None, expected: Optional[float] = None):
        await self._run(
            "INSERT INTO roll_log (guild_id, channel_id, campaign_id, user_id, character_id, expression, label, "
            "total, `natural`, secret, created_at, kind, setting, faces, expected) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            guild_id, channel_id, campaign_id, user_id, character_id, expression, label,
            total, natural, int(secret), clock.now(), kind, setting,
            json.dumps(faces, separators=(",", ":")) if faces else None, expected,
        )

    # ------------------------------------------------------------------ Phase 2: active characters
    async def list_active_characters(self, campaign_id: int) -> list[Character]:
        rows = await self._all(
            "SELECT c.* FROM characters c JOIN active_characters a ON a.character_id = c.id "
            "WHERE a.campaign_id = ? ORDER BY c.name", campaign_id,
        )
        return [_character(r) for r in rows]

    async def find_characters(self, campaign_id: int, name: str) -> list[Character]:
        rows = await self._all("SELECT * FROM characters WHERE campaign_id = ? AND name = ?", campaign_id, name)
        if not rows:
            rows = await self._all("SELECT * FROM characters WHERE campaign_id = ? AND name LIKE ? ESCAPE '\\'",
                                   campaign_id, _like_prefix(name))
        return [_character(r) for r in rows]

    # ------------------------------------------------------------------ character HP
    async def get_character_state(self, character_id: int) -> tuple[Optional[int], int]:
        row = await self._one("SELECT hp, temp_hp FROM character_state WHERE character_id = ?", character_id)
        return (row["hp"], row["temp_hp"]) if row else (None, 0)

    async def get_xp(self, character_id: int) -> int:
        row = await self._one("SELECT xp FROM character_state WHERE character_id = ?", character_id)
        return row["xp"] if row else 0

    async def set_xp(self, character_id: int, xp: int):
        await self._run(
            "INSERT INTO character_state (character_id, xp) VALUES (?, ?) "
            "ON CONFLICT(character_id) DO UPDATE SET xp = excluded.xp", character_id, xp)

    async def set_character_state(self, character_id: int, hp: Optional[int], temp_hp: int):
        await self._run(
            "INSERT INTO character_state (character_id, hp, temp_hp) VALUES (?, ?, ?) "
            "ON CONFLICT(character_id) DO UPDATE SET hp = excluded.hp, temp_hp = excluded.temp_hp",
            character_id, hp, temp_hp,
        )

    # ------------------------------------------------------------------ encounters
    async def create_encounter(self, campaign_id: int, channel_id: int) -> Encounter:
        eid = await self._run("INSERT INTO encounters (campaign_id, channel_id, created_at) VALUES (?, ?, ?)",
                              campaign_id, channel_id, clock.now())
        return await self.get_encounter(eid)

    async def get_encounter(self, encounter_id: int) -> Optional[Encounter]:
        return _row(Encounter, await self._one(
            "SELECT id, campaign_id, channel_id, tracker_message_id, round, current_id, active "
            "FROM encounters WHERE id = ?", encounter_id))

    async def get_active_encounter(self, campaign_id: int) -> Optional[Encounter]:
        return _row(Encounter, await self._one(
            "SELECT id, campaign_id, channel_id, tracker_message_id, round, current_id, active "
            "FROM encounters WHERE campaign_id = ? AND active = 1", campaign_id))

    async def update_encounter(self, encounter_id: int, **fields):
        allowed = {"tracker_message_id", "round", "current_id", "active", "channel_id"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("invalid encounter fields")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._run(f"UPDATE encounters SET {sets} WHERE id = ?", *fields.values(), encounter_id)

    async def add_combatant(self, encounter_id: int, name: str, initiative: int, tiebreak: float, *,
                            character_id=None, owner_id=None, hp=None, max_hp=None, ac=None) -> Combatant:
        cid = await self._run(
            "INSERT INTO combatants (encounter_id, name, initiative, tiebreak, character_id, owner_id, hp, max_hp, ac) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            encounter_id, name, initiative, tiebreak, character_id, owner_id, hp, max_hp, ac,
        )
        return await self.get_combatant(cid)

    async def get_combatant(self, combatant_id: int) -> Optional[Combatant]:
        return _row(Combatant, await self._one("SELECT * FROM combatants WHERE id = ?", combatant_id))

    async def list_combatants(self, encounter_id: int) -> list[Combatant]:
        rows = await self._all("SELECT * FROM combatants WHERE encounter_id = ? "
                               "ORDER BY initiative DESC, tiebreak DESC", encounter_id)
        return [_row(Combatant, r) for r in rows]

    async def find_combatants(self, encounter_id: int, name: str) -> list[Combatant]:
        rows = await self._all("SELECT * FROM combatants WHERE encounter_id = ? AND name = ?", encounter_id, name)
        if not rows:
            rows = await self._all("SELECT * FROM combatants WHERE encounter_id = ? AND name LIKE ? ESCAPE '\\'",
                                   encounter_id, _like_prefix(name))
        return [_row(Combatant, r) for r in rows]

    async def update_combatant(self, combatant_id: int, **fields):
        allowed = {"hp", "max_hp", "temp_hp", "initiative", "ac", "name"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("invalid combatant fields")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._run(f"UPDATE combatants SET {sets} WHERE id = ?", *fields.values(), combatant_id)

    async def remove_combatant(self, combatant_id: int):
        await self._run("DELETE FROM combatants WHERE id = ?", combatant_id)

    async def combatant_names(self, encounter_id: int) -> set[str]:
        rows = await self._all("SELECT name FROM combatants WHERE encounter_id = ?", encounter_id)
        return {r["name"].lower() for r in rows}

    # ------------------------------------------------------------------ conditions
    async def add_condition(self, *, character_id=None, combatant_id=None, name: str,
                            rounds: Optional[int] = None, note: Optional[str] = None, fresh: bool = False):
        col, target = ("character_id", character_id) if character_id else ("combatant_id", combatant_id)
        await self._run(f"DELETE FROM conditions WHERE {col} = ? AND name = ?", target, name)
        await self._run(f"INSERT INTO conditions ({col}, name, rounds_left, note, fresh) VALUES (?, ?, ?, ?, ?)",
                        target, name, rounds, note, int(fresh))

    async def remove_condition(self, *, character_id=None, combatant_id=None, name: str) -> bool:
        col, target = ("character_id", character_id) if character_id else ("combatant_id", combatant_id)
        return await self._changed(f"DELETE FROM conditions WHERE {col} = ? AND name = ?", target, name)

    async def get_conditions(self, *, character_id=None, combatant_id=None) -> list[Condition]:
        col, target = ("character_id", character_id) if character_id else ("combatant_id", combatant_id)
        rows = await self._all(f"SELECT * FROM conditions WHERE {col} = ? ORDER BY name", target)
        return [_row(Condition, r) for r in rows]

    async def tick_conditions(self, *, character_id=None, combatant_id=None) -> list[str]:
        """Count timed conditions down by one; returns the names that just expired."""
        col, target = ("character_id", character_id) if character_id else ("combatant_id", combatant_id)
        await self._run(
            f"UPDATE conditions SET rounds_left = rounds_left - 1 "
            f"WHERE {col} = ? AND rounds_left IS NOT NULL AND fresh = 0", target)
        await self._run(f"UPDATE conditions SET fresh = 0 WHERE {col} = ?", target)
        expired = await self._all(
            f"SELECT name FROM conditions WHERE {col} = ? AND rounds_left IS NOT NULL AND rounds_left <= 0", target)
        await self._run(
            f"DELETE FROM conditions WHERE {col} = ? AND rounds_left IS NOT NULL AND rounds_left <= 0", target)
        return [r["name"] for r in expired]

    # ------------------------------------------------------------------ monster templates
    async def save_monster(self, m: MonsterTemplate):
        await self._run(
            "INSERT INTO monster_templates (campaign_id, name, hp, initiative, ac, notes) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, name) DO UPDATE SET hp = excluded.hp, initiative = excluded.initiative, "
            "ac = excluded.ac, notes = excluded.notes",
            m.campaign_id, m.name, m.hp, m.initiative, m.ac, m.notes,
        )

    async def get_monster(self, campaign_id: int, name: str) -> Optional[MonsterTemplate]:
        return _row(MonsterTemplate, await self._one(
            "SELECT * FROM monster_templates WHERE campaign_id = ? AND name = ?", campaign_id, name))

    async def list_monsters(self, campaign_id: int) -> list[MonsterTemplate]:
        rows = await self._all("SELECT * FROM monster_templates WHERE campaign_id = ? ORDER BY name", campaign_id)
        return [_row(MonsterTemplate, r) for r in rows]

    async def delete_monster(self, campaign_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM monster_templates WHERE campaign_id = ? AND name = ?", campaign_id, name)


    # ------------------------------------------------------------------ Phase 3: companions
    async def list_companions(self, parent_id: int) -> list[Character]:
        rows = await self._all("SELECT * FROM characters WHERE parent_id = ? ORDER BY name", parent_id)
        return [_character(r) for r in rows]

    # ------------------------------------------------------------------ resources
    async def set_resource(self, r: Resource):
        await self._run(
            "INSERT INTO resources (character_id, name, current, max_formula, reset) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(character_id, name) DO UPDATE SET current = excluded.current, "
            "max_formula = excluded.max_formula, reset = excluded.reset",
            r.character_id, r.name, r.current, r.max_formula, r.reset,
        )

    async def get_resources(self, character_id: int) -> dict[str, Resource]:
        rows = await self._all("SELECT * FROM resources WHERE character_id = ? ORDER BY name", character_id)
        return {r["name"]: _row(Resource, r) for r in rows}

    async def update_resource_current(self, character_id: int, name: str, current: int):
        await self._run("UPDATE resources SET current = ? WHERE character_id = ? AND name = ?",
                        current, character_id, name)

    async def delete_resource(self, character_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM resources WHERE character_id = ? AND name = ?", character_id, name)

    # ------------------------------------------------------------------ random tables
    async def save_table(self, campaign_id: int, name: str, entries: list):
        await self._run(
            "INSERT INTO random_tables (campaign_id, name, entries) VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id, name) DO UPDATE SET entries = excluded.entries",
            campaign_id, name, json.dumps(entries),
        )

    async def get_table(self, campaign_id: int, name: str) -> Optional[tuple[str, list]]:
        row = await self._one("SELECT name, entries FROM random_tables WHERE campaign_id = ? AND name = ?",
                              campaign_id, name)
        return (row["name"], json.loads(row["entries"])) if row else None

    async def list_tables(self, campaign_id: int) -> list[tuple[str, int]]:
        rows = await self._all("SELECT name, entries FROM random_tables WHERE campaign_id = ? ORDER BY name",
                               campaign_id)
        return [(r["name"], len(json.loads(r["entries"]))) for r in rows]

    async def delete_table(self, campaign_id: int, name: str) -> bool:
        return await self._changed("DELETE FROM random_tables WHERE campaign_id = ? AND name = ?", campaign_id, name)

    # ------------------------------------------------------------------ notes
    async def save_note(self, campaign_id: int, title: str, category: str, content: str, gm_only: bool,
                        author_id: int) -> Note:
        now = clock.now()
        await self._run(
            "INSERT INTO notes (campaign_id, title, category, content, gm_only, author_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(campaign_id, title) DO UPDATE SET "
            "category = excluded.category, content = excluded.content, gm_only = excluded.gm_only, "
            "updated_at = excluded.updated_at",
            campaign_id, title, category, content, int(gm_only), author_id, now, now,
        )
        return await self.get_note(campaign_id, title)

    async def get_note(self, campaign_id: int, title: str) -> Optional[Note]:
        return _row(Note, await self._one("SELECT * FROM notes WHERE campaign_id = ? AND title = ?",
                                          campaign_id, title))

    async def list_notes(self, campaign_id: int, *, include_gm: bool, category: Optional[str] = None,
                         query: Optional[str] = None, limit: int = 25) -> list[Note]:
        sql = "SELECT * FROM notes WHERE campaign_id = ?"
        args: list = [campaign_id]
        if not include_gm:
            sql += " AND gm_only = 0"
        if category:
            sql += " AND category = ?"
            args.append(category)
        if query:
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += " AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"
            args += [like, like]
        sql += " ORDER BY category, title LIMIT ?"
        args.append(limit)
        return [_row(Note, r) for r in await self._all(sql, *args)]

    async def delete_note(self, note_id: int):
        await self._run("DELETE FROM notes WHERE id = ?", note_id)


    # ------------------------------------------------------------------ Phase 4: events
    async def add_event(self, *, campaign_id: Optional[int], guild_id: int, kind: str, text: str,
                        user_id: Optional[int] = None, value: Optional[int] = None):
        await self._run(
            "INSERT INTO events (campaign_id, guild_id, kind, text, user_id, value, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", campaign_id, guild_id, kind, text[:300], user_id, value, clock.now())

    async def list_events(self, campaign_id: int, start: int, end: int) -> list[Event]:
        rows = await self._all("SELECT * FROM events WHERE campaign_id = ? AND created_at BETWEEN ? AND ? "
                               "ORDER BY id", campaign_id, start, end)
        return [_row(Event, r) for r in rows]

    async def count_events(self, guild_id: int, user_id: int, kind: str, min_value: Optional[int] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM events WHERE guild_id = ? AND user_id = ? AND kind = ?"
        args = [guild_id, user_id, kind]
        if min_value is not None:
            sql += " AND value >= ?"
            args.append(min_value)
        return (await self._one(sql, *args))["n"]

    async def events_by_user(self, guild_id: int, kind: str, campaign_id: Optional[int] = None,
                             limit: int = 3) -> list[tuple[int, int]]:
        sql = "SELECT user_id, COUNT(*) AS n FROM events WHERE guild_id = ? AND kind = ? AND user_id IS NOT NULL"
        args: list = [guild_id, kind]
        if campaign_id is not None:
            sql += " AND campaign_id = ?"
            args.append(campaign_id)
        sql += " GROUP BY user_id ORDER BY n DESC LIMIT ?"
        args.append(limit)
        return [(r["user_id"], r["n"]) for r in await self._all(sql, *args)]

    # ------------------------------------------------------------------ sessions
    async def start_session(self, campaign_id: int, channel_id: int, title: Optional[str]) -> Session:
        row = await self._one("SELECT COALESCE(MAX(number), 0) AS n FROM sessions WHERE campaign_id = ?", campaign_id)
        sid = await self._run(
            "INSERT INTO sessions (campaign_id, number, title, channel_id, started_at) VALUES (?, ?, ?, ?, ?)",
            campaign_id, row["n"] + 1, title, channel_id, clock.now())
        return _row(Session, await self._one("SELECT * FROM sessions WHERE id = ?", sid))

    async def get_active_session(self, campaign_id: int) -> Optional[Session]:
        return _row(Session, await self._one(
            "SELECT * FROM sessions WHERE campaign_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", campaign_id))

    async def end_session(self, session_id: int) -> Session:
        await self._run("UPDATE sessions SET ended_at = ? WHERE id = ?", clock.now(), session_id)
        return _row(Session, await self._one("SELECT * FROM sessions WHERE id = ?", session_id))

    async def get_session(self, campaign_id: int, number: Optional[int] = None) -> Optional[Session]:
        if number is None:
            return _row(Session, await self._one(
                "SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number DESC LIMIT 1", campaign_id))
        return _row(Session, await self._one("SELECT * FROM sessions WHERE campaign_id = ? AND number = ?",
                                             campaign_id, number))

    async def list_sessions(self, campaign_id: int) -> list[Session]:
        rows = await self._all("SELECT * FROM sessions WHERE campaign_id = ? ORDER BY number DESC LIMIT 25",
                               campaign_id)
        return [_row(Session, r) for r in rows]

    async def sessions_attended(self, guild_id: int, user_id: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) AS n FROM sessions s JOIN campaigns c ON c.id = s.campaign_id WHERE c.guild_id = ? "
            "AND EXISTS (SELECT 1 FROM roll_log r WHERE r.campaign_id = s.campaign_id AND r.user_id = ? "
            "AND r.secret = 0 AND r.created_at BETWEEN s.started_at AND COALESCE(s.ended_at, ?))",
            guild_id, user_id, clock.now())
        return row["n"]

    # ------------------------------------------------------------------ roll queries (stats)
    async def roll_rows(self, *, guild_id: int, user_id: Optional[int] = None, campaign_id: Optional[int] = None,
                        start: Optional[int] = None, end: Optional[int] = None) -> list[RollRow]:
        """Public (non-secret) rolls, oldest first."""
        sql = ("SELECT user_id, character_id, expression, label, total, `natural`, created_at, kind, setting, "
               "faces, expected FROM roll_log WHERE guild_id = ? AND secret = 0")
        args: list = [guild_id]
        for col, op, val in (("user_id", "=", user_id), ("campaign_id", "=", campaign_id),
                             ("created_at", ">=", start), ("created_at", "<=", end)):
            if val is not None:
                sql += f" AND {col} {op} ?"
                args.append(val)
        sql += " ORDER BY id"
        return [_row(RollRow, r) for r in await self._all(sql, *args)]

    # ------------------------------------------------------------------ achievements
    async def unlocked_achievements(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = await self._all("SELECT `key`, unlocked_at FROM achievements WHERE guild_id = ? AND user_id = ?",
                               guild_id, user_id)
        return {r["key"]: r["unlocked_at"] for r in rows}

    async def unlock_achievement(self, guild_id: int, user_id: int, key: str) -> bool:
        return await self._changed("INSERT OR IGNORE INTO achievements (guild_id, user_id, `key`, unlocked_at) VALUES (?, ?, ?, ?)",
                        guild_id, user_id, key, clock.now())

    async def achievement_counts(self, guild_id: int) -> list[tuple[int, int]]:
        rows = await self._all("SELECT user_id, COUNT(*) AS n FROM achievements WHERE guild_id = ? "
                               "GROUP BY user_id ORDER BY n DESC LIMIT 10", guild_id)
        return [(r["user_id"], r["n"]) for r in rows]

    async def count_user_companions(self, guild_id: int, user_id: int) -> int:
        row = await self._one("SELECT COUNT(*) AS n FROM characters ch JOIN campaigns c ON c.id = ch.campaign_id "
                              "WHERE c.guild_id = ? AND ch.owner_id = ? AND ch.parent_id IS NOT NULL",
                              guild_id, user_id)
        return row["n"]

    async def count_user_notes(self, guild_id: int, user_id: int) -> int:
        row = await self._one("SELECT COUNT(*) AS n FROM notes n JOIN campaigns c ON c.id = n.campaign_id "
                              "WHERE c.guild_id = ? AND n.author_id = ?", guild_id, user_id)
        return row["n"]

    async def campaign_player_ids(self, campaign_id: int) -> list[int]:
        rows = await self._all("SELECT DISTINCT owner_id FROM characters WHERE campaign_id = ?", campaign_id)
        return [r["owner_id"] for r in rows]

    # ------------------------------------------------------------------ scheduling
    async def set_schedule(self, campaign_id: int, channel_id: int, starts_at: int, title: Optional[str]):
        await self._run(
            "INSERT INTO scheduled_sessions (campaign_id, channel_id, starts_at, title, reminded) "
            "VALUES (?, ?, ?, ?, 0) ON CONFLICT(campaign_id) DO UPDATE SET channel_id = excluded.channel_id, "
            "starts_at = excluded.starts_at, title = excluded.title, reminded = 0",
            campaign_id, channel_id, starts_at, title)

    async def get_schedule(self, campaign_id: int) -> Optional[Scheduled]:
        return _row(Scheduled, await self._one("SELECT * FROM scheduled_sessions WHERE campaign_id = ?", campaign_id))

    async def all_schedules(self) -> list[Scheduled]:
        return [_row(Scheduled, r) for r in await self._all("SELECT * FROM scheduled_sessions")]

    async def mark_reminded(self, campaign_id: int, bits: int):
        await self._run("UPDATE scheduled_sessions SET reminded = reminded | ? WHERE campaign_id = ?", bits, campaign_id)

    async def delete_schedule(self, campaign_id: int) -> bool:
        return await self._changed("DELETE FROM scheduled_sessions WHERE campaign_id = ?", campaign_id)

    # ------------------------------------------------------------------ inventory & money
    # character_id None = the party stash of the campaign

    @staticmethod
    def _owner(character_id: Optional[int]) -> tuple[str, tuple]:
        return ("character_id IS NULL", ()) if character_id is None else ("character_id = ?", (character_id,))

    async def list_items(self, campaign_id: int, character_id: Optional[int]) -> list[Item]:
        where, args = self._owner(character_id)
        rows = await self._all(f"SELECT * FROM items WHERE campaign_id = ? AND {where} ORDER BY name",
                               campaign_id, *args)
        return [_row(Item, r) for r in rows]

    async def get_item(self, campaign_id: int, character_id: Optional[int], name: str) -> Optional[Item]:
        where, args = self._owner(character_id)
        return _row(Item, await self._one(f"SELECT * FROM items WHERE campaign_id = ? AND {where} AND name = ?",
                                          campaign_id, *args, name))

    async def add_item(self, campaign_id: int, character_id: Optional[int], name: str, qty: int,
                       note: Optional[str] = None) -> Item:
        """Add to an existing item with that name (and update its note if given), or create it."""
        item = await self.get_item(campaign_id, character_id, name)
        if item:
            await self._run("UPDATE items SET qty = qty + ?, note = COALESCE(?, note) WHERE id = ?", qty, note, item.id)
        else:
            await self._run("INSERT INTO items (campaign_id, character_id, name, qty, note) VALUES (?, ?, ?, ?, ?)",
                            campaign_id, character_id, name, qty, note)
        return await self.get_item(campaign_id, character_id, name)

    async def take_item(self, item: Item, qty: int) -> int:
        """Remove qty of an item (all of it when qty >= item.qty). Returns how many are left."""
        left = item.qty - qty
        if left <= 0:
            await self._run("DELETE FROM items WHERE id = ?", item.id)
            return 0
        await self._run("UPDATE items SET qty = ? WHERE id = ?", left, item.id)
        return left

    async def get_money(self, campaign_id: int, character_id: Optional[int]) -> dict[str, int]:
        where, args = self._owner(character_id)
        rows = await self._all(f"SELECT currency, amount FROM money WHERE campaign_id = ? AND {where} ORDER BY id",
                               campaign_id, *args)
        return {r["currency"]: r["amount"] for r in rows}

    async def change_money(self, campaign_id: int, character_id: Optional[int], currency: str, delta: int) -> int:
        """Add (or with a negative delta, remove) money. Returns the new amount. Empty purses are removed."""
        where, args = self._owner(character_id)
        row = await self._one(f"SELECT id, amount FROM money WHERE campaign_id = ? AND {where} AND currency = ?",
                              campaign_id, *args, currency)
        amount = (row["amount"] if row else 0) + delta
        if row and amount == 0:
            await self._run("DELETE FROM money WHERE id = ?", row["id"])
        elif row:
            await self._run("UPDATE money SET amount = ? WHERE id = ?", amount, row["id"])
        elif amount:
            await self._run("INSERT INTO money (campaign_id, character_id, currency, amount) VALUES (?, ?, ?, ?)",
                            campaign_id, character_id, currency, amount)
        return amount

    async def campaign_currencies(self, campaign_id: int) -> list[str]:
        """Currencies used anywhere in the campaign, most common first."""
        rows = await self._all("SELECT currency, COUNT(*) AS n FROM money WHERE campaign_id = ? "
                               "GROUP BY currency ORDER BY n DESC, currency", campaign_id)
        return [r["currency"] for r in rows]


def _like_prefix(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"
