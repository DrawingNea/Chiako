"""The /help chapters in German (same keys as core/helptext.py). Commands stay English: Discord's slash commands are."""
from __future__ import annotations

from .helptext import Chapter

CHAPTERS_DE: list[Chapter] = [
    Chapter("start", "", "Erste Schritte", "Kampagne anlegen, Charakter erstellen und zum ersten Mal würfeln", """
Willkommen! 🌸 Ich würfle für eure Pen-&-Paper-Runden und behalte Charaktere, Kämpfe und Spielabende im Blick.
Über das Menü unten springst du zu jedem Kapitel, mit ‹ Zurück und Weiter › blätterst du weiter.

### 1. Die SL legt eine Kampagne an
Eine **Kampagne** ist das Spiel eurer Gruppe und gehört zu einem oder mehreren Kanälen.
• `/campaign create name:Fluch des Strahd` macht den aktuellen Kanal zum Zuhause der Kampagne.
• `/campaign link` fügt weitere Kanäle hinzu. Threads gehören automatisch zur Kampagne ihres Kanals.

### 2. Alle erstellen einen Charakter
• `/char create name:Lyra` erstellt einen Charakter und macht ihn zu deinem **aktiven** Charakter,
  also dem, für den du in dieser Kampagne würfelst.
• `/stat bulk entries: kk=12, ge=14, ko=13, level=1` trägt seine Werte ein.

### 3. Würfeln!
• `/r 1d20+5` würfelt alles Mögliche. Statt `d` geht auch `W`: `/r 2W6+3`.
• `/r 1d20+ge` addiert den Wert `ge` deines Charakters. Schreib einfach den Namen des Werts.
• `/skill add name:schleichen formula:1d20+ge` speichert eine Probe, `/check schleichen` würfelt sie.
• Ganz ohne Slash-Befehl: schreib {me} `würfel 2W6` in den Chat.

Deine Würfe erscheinen unter Namen und Bild deines Charakters, mit einem **Reroll**-Knopf.

### Wer ist die SL?
Wer die Kampagne angelegt hat, alle mit der SL-Rolle der Kampagne (`/campaign gm-role`) und
Server-Admins. Befehle nur für die SL sind mit **(SL)** gekennzeichnet.
"""),

    Chapter("dice", "", "Würfeln", "Würfelschreibweise, Namen für Würfe, Vorteil, geheime Würfe und Würfe im Text", """
### So schreibst du einen Wurf
`XdY` (oder `XWY`) heißt „würfle **X** Würfel mit **Y** Seiten und zähle sie zusammen“.
Rechnen mit `+ - * /` und Klammern geht auch.

• `2d6+3` zwei sechsseitige Würfel plus 3
• `d20` ein W20 · `d%` ein W100
• `4d6kh3` vier würfeln, die **h**öchsten drei behalten (**k**eep **h**ighest) · `2d20kl1` den niedrigsten
• `4d6dl1` vier würfeln, den niedrigsten streichen (**d**rop **l**owest) · `5d10dh2` die höchsten zwei streichen
• `3d6!` **explodierende Würfel**: jede 6 bringt einen weiteren Würfel · `5d10!9` 9er und 10er explodieren
• `2d6r1` jede 1 einmal **neu würfeln**
• `4dF` **Fate-Würfel** (+, 0, −), das Ergebnis steht auf der Fate-Leiter (Ordentlich, Gut, Großartig, …)
• `6d10>=8` **Erfolge zählen**, statt zusammenzurechnen (siehe *Würfelpools*)

### Würfe benennen
Häng `# Name` an: `/r 1d20+5 # Langschwert` zeigt **Langschwert** beim Ergebnis.

### Vorteil & Nachteil
`/r 1d20+5 advantage:Advantage` würfelt den W20 zweimal und nimmt das höhere Ergebnis,
mit Disadvantage das niedrigere.

### Weitere Arten zu würfeln
• `/check` würfelt eine deiner Fertigkeiten, optional mit `modifier`.
• `/secret` würfelt so, dass **nur die SL** das Ergebnis sieht. Geheime Würfe von Spielenden gehen
  privat an die SL; eigene geheime Würfe der SL bekommen einen **Reveal**-Knopf zum späteren Aufdecken.
• `[[1d20+3]]` irgendwo in einer Nachricht würfelt direkt (bis zu 5 pro Nachricht).
• `/pbta` würfelt 2W6 plus einen Wert für *Powered by the Apocalypse*: Voller Erfolg, Teilerfolg oder Fehlschlag.
• `/3d20` macht eine DSA-Probe mit 3W20 und einfachen Zahlen.

### Das Ergebnis lesen
Die kleine Zeile beschreibt den Wurf in Worten, die große zeigt jeden Würfel, die größte das Ergebnis.
Durchgestrichene Würfel wurden gestrichen und zählen nicht.
"""),

    Chapter("pools", "", "Würfelpools & Kampagnenregeln", "Erfolge zählen, explodierende Würfel und die Würfelregeln der Kampagne", """
In manchen Spielen zählt man Würfel nicht zusammen: Man würfelt eine Handvoll und **zählt die Erfolge**.
Jeder Würfel, der hoch genug ist, ist ein Erfolg.

### Einen Pool selbst würfeln
• `/r 5d10>=8` würfelt fünf W10. Jeder Würfel mit **8 oder mehr** ist ein Erfolg.
• `/r 5d10!>=8` genauso, aber jede 10 **explodiert**: Sie bringt einen weiteren Würfel, der ebenfalls
  Erfolg haben und explodieren kann.
• `/r 5d10!>=8f1` dazu **hebt** jede 1 einen Erfolg **auf**.
Erfolge sind unterstrichen, Würfel aus Explosionen stehen hinter einem `-`.

### Würfelregeln der Kampagne (SL)
Damit das niemand jedes Mal tippen muss, legt die SL die Regeln einmal für die ganze Kampagne fest:
`/campaign dice sides:10 success:8 explode:10 cancel:1`
• `sides` welcher Würfel, hier ein W10
• `success` ab diesem Ergebnis ist ein Würfel ein Erfolg. Weglassen, um zusammenzuzählen.
• `explode` ab diesem Ergebnis kommt ein weiterer Würfel dazu. Weglassen für keine Explosionen.
• `cancel` bis zu diesem Ergebnis hebt ein Würfel einen Erfolg auf (optional)
`/campaign dice` ohne Optionen zeigt die aktuellen Regeln, `sides:0` schaltet sie aus.

### Mit den Kampagnenregeln würfeln
Sind die Regeln gesetzt, **bedeutet eine Zahl eine Anzahl Würfel**:
• `/check 7` würfelt sieben Würfel nach den Kampagnenregeln.
• Eine Fertigkeit mit einer Zahl als Wert ist eine Würfelanzahl: `/skill add name:schiessen formula:5`,
  dann `/check schiessen`.
• Fertigkeiten und Werte kombinieren: `/check schiessen & ge` würfelt 5 Würfel plus deine Geschicklichkeit.
• `modifier` gibt Würfel dazu oder nimmt welche weg: `/check schiessen modifier:2`.
• Im Chat: {me} `w7` oder {me} `probe schiessen und ge`.
Fertigkeiten mit Würfeln darin, wie `1d20+ge`, werden weiterhin genau so gewürfelt, wie sie eingetragen sind.
"""),

    Chapter("chat", "", "Mit dem Bot reden", "Würfeln, indem du den Bot im Chat erwähnst, ganz ohne Slash-Befehle", """
Zum Würfeln brauchst du keine Slash-Befehle: Beginne deine Nachricht mit einer Erwähnung von mir
und schreib dahinter, was gewürfelt werden soll.

### Beispiele
• {me} `würfel 2W6+3` · {me} `r 1d20+ge` · {me} `probe schleichen`
• {me} `würfel auf schiessen und ge` · {me} `pool(7)`
• {me} `w5` würfelt fünf Würfel nach den Würfelregeln der Kampagne
• {me} `hilfe` zeigt eine kurze Erinnerung

Du bekommst dasselbe Ergebnis wie mit `/r`, inklusive **Reroll**-Knopf, und der Wurf zählt für
deine Statistik und Erfolge. Ich reagiere nur, wenn die Nachricht mit der Erwähnung **beginnt**,
ein „danke {me}!“ löst also keinen Wurf aus.

### Andere Sprachen
Das erste Wort und die Wörter für „für“ und „und“ können in mehreren Sprachen sein:
**Deutsch** `würfel`, `würfle`, `wirf`, `prüfe`, `probe` · `auf`, `für` · `und`
**Englisch** `roll`, `check`, `throw` · `for` · `and`
**Französisch** `lance`, `jet` · `pour` · `et`
**Spanisch** `tira`, `lanza` · `para` · `y`
**Italienisch** `tira`, `lancia` · `per` · `e`
**Niederländisch** `gooi`, `werp` · `voor` · `en`
**Portugiesisch** `rola`, `joga` · `para` · `e`

### Würfe im Text
Setz einen Wurf in doppelte eckige Klammern, irgendwo in deiner Nachricht:
`Ich schwinge meine Axt [[1d12+kk]] und brülle!` Ich antworte mit deinem Satz und dem Ergebnis darin.
"""),

    Chapter("chars", "", "Charaktere, Werte & Fertigkeiten", "Charaktere, Werte und Formeln, Fertigkeiten, 3W20-Proben, Export und Import", """
### Charaktere
• `/char create` erstellt einen Charakter, optional mit Link zu einem Bild.
• `/char use` wechselt deinen aktiven Charakter, `/char list` zeigt alle deine Charaktere.
• `/char show` zeigt deinen **Charakterbogen** als Karte: Bild, Lebenspunkte, Stufe, Zustände, Werte,
  Fertigkeiten, Ressourcen, Inventar und Geld. Mit `public:True` sieht ihn der ganze Tisch.
• `/char color` gibt deiner Karte eine eigene Farbe (`#8e44ad`, `purple`, …).
• `/char avatar`, `/char rename` und `/char delete` machen, was sie sagen.
Du kannst mehrere Charaktere pro Kampagne haben und jederzeit wechseln. Die SL kann den Bogen mit
`/campaign sheet` an euer Spiel anpassen (siehe *Kampagneneinstellungen*).

### Werte
Werte sind die Zahlen auf deinem Charakterbogen: `/stat set name:ge value:14`.
• Nutze sie in jedem Wurf über ihren Namen: `1d20+ge`.
• `/stat bulk entries: kk=12, ge=14, level=1` setzt mehrere auf einmal.
• Ein Wert kann eine **Formel** sein, die sich selbst aktualisiert:
  `/stat set name:max_hp value:10 + ko * level`. Ändert sich `ko` oder `level`, zieht `max_hp` nach.
Heißt eine Fertigkeit oder ein Makro genauso wie ein Wert, gewinnt die Fertigkeit bzw. das Makro.
Mit `@ge` ist immer der Wert gemeint.

### Fertigkeiten
Eine Fertigkeit ist ein Wurf, den du einmal speicherst und immer wieder nutzt:
`/skill add name:schleichen formula:1d20+ge+bonus`. Würfle sie mit `/check schleichen` oder
`/r schleichen`, oder nutze sie in größeren Würfen wie `/r schleichen+2`.
Mit Würfelregeln der Kampagne kann eine Fertigkeit einfach eine Würfelanzahl sein (siehe *Würfelpools*).

**3W20-Fertigkeiten** (DSA): `/skill add-3d20 name:klettern attr1:mu attr2:ge attr3:kk points:6`,
dann `/check klettern`. Das Ergebnis zeigt die Qualitätsstufe (QS), kritische Erfolge (zwei 1en) und
Patzer (zwei 20en).

### Export & Import
`/char export` schickt dir eine `.json`-Datei mit deinem Charakter und seinen Begleitern: Werte,
Fertigkeiten, Ressourcen, Lebenspunkte, EP, Inventar und Geld. `/char import` macht aus der Datei wieder
einen Charakter, in jeder Kampagne und auf jedem Server, optional mit neuem `name`. Ideal als Backup
oder für den Umzug in eine neue Kampagne.
"""),

    Chapter("inventory", "", "Inventar & Geld", "Gegenstände, Geld und das gemeinsame Gruppeninventar", """
Jeder Charakter hat ein Inventar und einen Geldbeutel, und die Kampagne hat ein gemeinsames
**Gruppeninventar** für Beute, die allen gehört.

### Gegenstände
• `/item add name:Seil amount:2 note:15 m` legt Gegenstände in das Inventar deines Charakters.
• `/item remove name:Seil` nimmt sie wieder heraus: verbraucht, verkauft oder verloren. Ohne `amount`
  werden alle entfernt.
• `/item give name:Heiltrank to:Grom` gibt einen Gegenstand an einen anderen Charakter.
• Mit `stash:True` landet bzw. verschwindet ein Gegenstand stattdessen im Gruppeninventar.

### Geld
Jede Währung eures Spiels funktioniert: Dukaten, Gold, Credits, Nuyen, € …
• `/money add amount:30 currency:Dukaten` · `/money spend amount:12`
• `/money give amount:10 to:Grom` bezahlt einen anderen Charakter.
Hast du eine Währung einmal benutzt, kannst du `currency` weglassen, und ich nehme deine.

### Das Gruppeninventar
• `/item give … to:Gruppeninventar` und `/money give … to:Gruppeninventar` legen etwas hinein.
• `/item take name:Heiltrank` und `/money take amount:20` nehmen etwas heraus.
• Alle in der Kampagne können das Gruppeninventar nutzen, also teilt fair!

### Hineinschauen
`/inventory` zeigt deine Gegenstände und dein Geld; mit `whose` wählst du einen anderen Charakter oder
das Gruppeninventar. Dein Inventar steht auch auf deinem Charakterbogen (`/char show`).

### Für die SL
Verteil Beute direkt mit `character:` bei `/item add` und `/money add`, oder leg sie mit `stash:True`
ins Gruppeninventar und lass die Gruppe sie aufteilen.
"""),

    Chapter("macros", "", "Makros", "Eigene Abkürzungen für Würfe, Makros mit Werten und Kampagnenmakros", """
Ein **Makro** ist eine Abkürzung für einen Wurf, den du oft brauchst. Makros gehören *dir* und nicht
einem Charakter, sie funktionieren also in jeder Kampagne auf dem Server.

### Makros speichern und benutzen
• `/macro save name:feuerball expression:8d6 # Feuerball`, dann würfeln mit `/r feuerball` oder `[[feuerball]]`.
• Makros können Werte, Fertigkeiten und andere Makros nutzen: `/macro save name:heimlich expression:schleichen + 5`.
• `/macro list` zeigt deine Makros, `/macro remove` löscht eines.

### Makros mit Werten
Schreib `$1` dorthin, wo du bei jedem Wurf eine Zahl einsetzen willst:
`/macro save name:pool expression:$1d10!>=8 # Pool`
Dann würfle `/r pool(5)`, `/r pool(8)` oder `/r pool(ge+2)`.
Mehr Werte nötig? Nutze `$2`, `$3` usw. und würfle `pool(7, 9)`.

### Kampagnenmakros (SL)
Mit `campaign:True` teilst du ein Makro mit allen in der Kampagne:
`/macro save name:pool expression:$1d10!>=8 # Pool campaign:True`
Jetzt kann jede:r `pool(5)` mit den eigenen Werten würfeln. Ein eigenes Makro mit demselben Namen hat
Vorrang. `/macro remove name:pool campaign:True` entfernt es wieder.
"""),

    Chapter("combat", "", "Kampf", "Initiative, Monster, Lebenspunkte, Zustände und Gruppenproben", """
### Initiative
1. **SL:** `/init start` postet die Initiativeliste mit den Knöpfen **Join** und **Start combat**.
2. **Spielende:** drückt **Join**. Eure Initiative nutzt eure Fertigkeit `initiative`, falls
   vorhanden, sonst die Formel der Kampagne (`/campaign init-formula 1d20+ge`).
3. **SL:** fügt Monster hinzu mit `/init spawn template:Goblin count:3` oder `/init add`.
4. **SL:** drückt **Start combat**. Wer dran ist, wird angepingt und drückt **Next turn**,
   wenn der Zug vorbei ist.
Außerdem: `/init show` postet die Liste erneut unten im Chat; `/init move`, `/init remove` und
`/init end` passen den Kampf an oder beenden ihn.

### Monstervorlagen (SL)
`/monster save name:Goblin hp:2d6 initiative:1d20+2 ac:15` speichert ein Monster, das du immer wieder
ins Spiel bringen kannst.

### Lebenspunkte
• `/hp damage amount:2d6+3 target:Goblin 2` · `/hp heal` · `/hp temp` für temporäre LP · `/hp show`
• Deine maximalen Lebenspunkte sind dein Wert `max_hp`. Die SL kann sie mit `/hp set` korrigieren.
• Bei Monstern sehen Spielende nur, wie es ihnen geht: Unhurt, Hurt, Bloodied oder Down.

### Zustände
`/condition add name:Betäubt target:Goblin 1 rounds:2` zählt am Ende jedes Zuges des Ziels herunter,
und ich sage Bescheid, wenn der Zustand vorbei ist. Ohne `rounds` bleibt er, bis er entfernt wird.

### Gruppenproben (SL)
`/group-check roll:wahrnehmung dc:15` lässt alle auf **Roll** drücken und sammelt die Ergebnisse
in einer Nachricht. Mit Schwierigkeit (DC) schafft es die Gruppe, wenn mindestens die Hälfte besteht.
`secret:True` versteckt die Ergebnisse vor den Spielenden.

### Übersicht
`/dashboard` postet Lebenspunkte und Zustände der Gruppe und hält sie aktuell. Anpinnen!
"""),

    Chapter("progress", "", "Fortschritt & Begleiter", "Ressourcen, Rasten, EP und Stufen, Begleiter", """
### Ressourcen
Alles, was sich verbraucht: Zauberplätze, Munition, Schicksalspunkte…
• `/res add name:astral max:level+1 reset:Long rest` legt eine an. Das Maximum darf eine Formel sein
  und wächst dann mit der Stufe.
• `/res use astral` verbraucht eins, `/res gain` gibt etwas zurück, `/res list` zeigt alle.

### Rasten
• `/rest kind:Short rest` füllt alles auf, was sich bei einer kurzen Rast erholt.
• `/rest kind:Long rest` füllt alles auf und heilt deine Lebenspunkte. Mit `restore_hp:False` ohne Heilung.
• Die SL kann die ganze Gruppe auf einmal rasten lassen: `party:True`.

### EP & Stufen
• **SL:** `/xp table dnd5e` wählt eine Stufentabelle: `dnd5e`, `pathfinder`, eigene Zahlen wie
  `0, 1000, 3000` oder `none`.
• **SL:** `/xp award amount:300 reason:die Goblinhöhle` gibt der ganzen Gruppe EP. `split:True` teilt
  sie stattdessen auf.
• Steigt jemand eine Stufe auf, verkünde ich das und erhöhe den Wert `level`, sodass Formeln wie
  `max_hp = 10 + level * 5` automatisch mitwachsen.
• `/xp show` zeigt, wie weit es bis zur nächsten Stufe ist.

### Begleiter
Haustiere, Vertraute und Gefolge sind vollwertige Charaktere, die zu deinem gehören:
• `/companion add Schnurrbart` legt einen an.
• `/companion roll name:Schnurrbart expression:1d20+2` würfelt als Begleiter.
• `/companion join` bringt ihn in einen Kampf.
Um seine Werte zu ändern, wechsle mit `/char use Schnurrbart` zu ihm und mit `/char use Lyra` zurück.
"""),

    Chapter("world", "", "Weltenbau", "Schnelle Generatoren, Zufallstabellen und Kampagnennotizen", """
### Schnelle Generatoren
`/generate npc` · `name` · `tavern` · `loot` · `weather` · `complication`. Perfekt zum Improvisieren!

### Zufallstabellen (SL)
`/table create name:Wald` öffnet einen Editor, in dem du pro Zeile einen Eintrag schreibst:
• `3* Ein Rudel Wölfe` macht einen Eintrag dreimal so wahrscheinlich.
• `[[2d6]] Goblins` würfelt im Eintrag.
• `{loot}` würfelt auf einer anderen Tabelle.
`/table roll Wald` zieht einen zufälligen Eintrag. Außerdem gibt es `/table add`, `edit`, `show`,
`list` und `delete`. `/table edit npc` kopiert eine eingebaute Tabelle in deine Kampagne, damit du sie
anpassen kannst.

### Notizen
Halte NSCs, Orte, Quests und mehr fest: `/note add title:Bürgermeister Ulric category:NPC`.
Finde sie mit `/note show`, `/note search` und `/note list` wieder; ändere sie mit `/note edit` oder
`/note delete`. Notizen nur für die SL (`gm_only:True`) bleiben für Spielende unsichtbar, auch in der
Suche. Nur wer eine Notiz geschrieben hat oder die SL kann sie ändern oder löschen.
"""),

    Chapter("sessions", "", "Spielabende, Statistik & Planung", "Rückblicke, Würfelstatistik, Errungenschaften und den nächsten Termin planen", """
### Spielabende (SL)
Beginne mit `/session start title:Die Goblinhöhle` und beende mit `/session end`.
Dann poste ich einen Rückblick: wie lange ihr gespielt habt, wer am meisten und am wenigsten Glück
hatte, der höchste Wurf, kritische Treffer, besiegte Monster, Stufenaufstiege und alle Höhepunkte,
die jemand mit `/session moment text:…` festgehalten hat. `/session recap` und `/session list` zeigen
frühere Abende.

### Würfelstatistik
• `/stats` zeigt, wie sich deine Würfel verhalten, aufgeteilt nach Art des Würfelns:
  – **Würfelpools**, ein Abschnitt pro Regel-Set: Erfolge pro Wurf im Vergleich zum Erwartungswert,
    Würfe ohne Erfolg, dein bester Wurf und Bonuswürfel durch Explosionen;
  – **jede Würfelart** (W20, W10, W6, …): dein Schnitt im Vergleich zum erwarteten, und wie oft die
    höchste und niedrigste Seite kam;
  – **3W20-Proben** und deine höchste Summe, plus ein Glücksurteil über alle deine Würfel.
  Wähle eine andere Person mit `player` oder einen anderen `scope` (dieser Abend, diese Kampagne, ganzer Server).
• `/halloffame` zeigt die Bestenlisten, inklusive der Glückspilze und Pechvögel.
• `/achievements` zeigt, welche der 17 Errungenschaften du (oder jemand anderes) freigeschaltet hast.
Geheime Würfe zählen nie, damit sie nichts verraten.

### Den nächsten Termin planen
• **SL:** stell einmal die Zeitzone der Kampagne ein: `/campaign timezone Europe/Berlin`.
• **SL:** `/schedule set when:fr 19:30` setzt den nächsten Spielabend. `morgen 19:30`, `9.10. 19:30 Uhr`
  und `2026-10-09 19:30` gehen auch.
• Am Tag vorher pinge ich alle an: **„Morgen ist Spieltag!“**. Weitere Erinnerungen kommen eine
  Stunde vorher und zum Start.
Alle sehen die Uhrzeit in ihrer eigenen Zeitzone. `/schedule show` zeigt den nächsten Termin,
`/schedule cancel` sagt ihn ab. Für die Terminsuche nutzt am besten die eingebauten Umfragen von Discord.
"""),

    Chapter("gm", "", "Kampagneneinstellungen (SL)", "Alles, was die SL für die Kampagne einstellen kann, an einem Ort", """
`/campaign info` zeigt alle Einstellungen der Kampagne in diesem Kanal.

### Die Kampagne
• `/campaign create` startet eine Kampagne in diesem Kanal.
• `/campaign language` stellt ein, ob ich in dieser Kampagne Deutsch oder Englisch spreche.
• `/campaign link` fügt diesen Kanal einer bestehenden Kampagne hinzu; `/campaign unlink` entfernt ihn.
• `/campaign gm-role` gibt einer Rolle SL-Rechte, `/campaign transfer` übergibt die Kampagne an eine neue SL.

### Würfeln
• `/campaign dice sides:10 success:8 explode:10 cancel:1` legt die Würfelregeln der Kampagne fest
  (siehe *Würfelpools*).
• `/campaign init-formula 1d20+ge` legt fest, wie Initiative für Charaktere ohne Fertigkeit
  `initiative` gewürfelt wird.
• `/campaign webhooks` postet Würfe unter Namen und Bild des jeweiligen Charakters. Das ist
  standardmäßig an und braucht die Berechtigung **Webhooks verwalten**.

### Der Charakterbogen
`/campaign sheet` öffnet einen Editor, in dem du den Bogen für euer Spiel gestaltest, ein Abschnitt pro Zeile:
```
Eigenschaften: MU=mu, KL=kl, IN=in, CH=ch, FF=ff, GE=ge, KO=ko, KK=kk
Kampf: LeP=max_hp, Ini=initiative
Talente: Klettern=klettern, Schleichen=schleichen
```
Einträge können Werte oder Fertigkeiten sein, `Beschriftung=name` zeigt deine eigene Beschriftung.
Alles, was du nicht aufführst, erscheint trotzdem unter *Weitere*. `/campaign sheet reset:True` kehrt
zum automatischen Layout zurück.

### Gemeinsame Inhalte
• `/macro save … campaign:True` Makros für alle
• `/monster save` Monstervorlagen · `/table create` Zufallstabellen
• `/note add gm_only:True` geheime Notizen · `/xp table` die Stufentabelle

### Zeit
`/campaign timezone Europe/Berlin` legt die Zeitzone für die Termine fest, die du bei `/schedule` eingibst.
"""),
]
