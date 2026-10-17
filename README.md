**English** · [Italiano](README.it.md)

# THE EMPIRE

A turn-based global strategy game for the terminal. It takes the **total
war** of *Theatre Europe* (1985: armies, air strikes, chemical weapons,
nuclear escalation, the apocalypse as everyone's defeat) and a classic
grid-based **conquest system** (cities that produce units, transports,
aircraft carriers, aircraft fuel, fog of war) and brings them **to the scale of the whole world**.
From board games it takes the **cards** (Futurisiko-style), the **secret
objectives** and the **continental bonuses** (Risk-style) and the **world events**
that shuffle everyone's plans.

The map is the real world: it comes from Natural Earth data and is drawn in
Braille characters as in [Terrascope](https://github.com/a-shygun/Terrascope),
the project's starting point. Each character is a game square
(1° of longitude × 2° of latitude) and its 2×4 Braille dots
draw the real coastline. The map wraps from east to west: you can cross the
Pacific. The Mediterranean is navigable end to end, from the Atlantic to the
Levant: the channel between Tunis and Sicily was opened by hand (in
`assets/world.json`), since the 1°×2° grid did not derive it from the
Natural Earth coastlines.

![Europe on turn 4 of World War III](docs/screenshot.png)

### In short: how to win

Each faction has a **secret objective** (for example "conquer North
Africa and the Middle East" or "eliminate the Eastern Bloc"): whoever completes it
wins at once. Otherwise the winner is whoever **dominates** the world (55% of the cities),
whoever eliminates all rivals, or whoever has the most points when the turns run out. If
the **Doomsday Clock** reaches midnight, everyone loses.

To get there:
- you **conquer cities** with infantry and armour: each city produces one unit
  at a time, and **directives** (`P`) retool every factory;
- you hold **whole regions** (13 in the world) for a production bonus from
  +10% to +30% across the whole empire;
- you play **cards** (`K`): espionage, defections, revolts, coups;
- you exploit **world events**, which every 5-8 turns change the rules
  for everyone (oil crisis, famine, boom, UN summit...);
- you use **diplomacy** (`O`) to sign truces on the secondary front.

The `o` key shows everything on one page: your objective and how far along
you are, the regions and who holds them, the events in progress.

## Getting started

If it's your first time, start with the **tutorial**: it's the first scenario in the menu
(or `python3 -m theempire --scenario tutorial`). An instructor, in a
box on the map, explains one thing at a time and waits for you to actually
do it: look at the map, select and move a unit, give a
march order, choose production and a directive, end the turn
and read the bulletin, conquer a city, play a card. Then they
introduce the secret objective and the regions (opening the `o` page) and show you
a real world event, an economic boom to exploit. At the end
they leave you the objective: take Tirana, with a Reinforcements card as a gift.
`h` hides or shows the box.


You need Python 3.10+ and a UTF-8 terminal, ideally with 256 colours. The game
uses only the standard library: nothing to install.

```bash
python3 -m theempire                 # menu: scenario, faction, difficulty
python3 -m theempire --list          # scenarios and factions
python3 -m theempire --scenario ww3 --faction east --difficulty difficile
python3 -m theempire --scenario coldwar --faction nato --faction pact   # hot-seat, 2 players
python3 -m theempire --load          # resumes ~/.theempire/save.json
python3 -m theempire --autoplay 100 --seed 1   # AI against AI, no interface
python3 -m theempire --lang en       # game in English (it, en, fr, es, de, pt)
```

To install it as a command: `pip install .` and then `theempire`.

## Languages

The game is available in **Italian, English, French, Spanish, German and
Portuguese**. You choose the language:
- from the command line with `--lang it|en|fr|es|de|pt`;
- from the first menu ("Lingua / Language");
- in game with the `L` key;
- in the server setup screen ("Language" row);
- in the web TUI login form.

Without an explicit choice the game uses the language saved last time, then
the system's (`LANG`), otherwise Italian. In online games every player
sees the game in their own language: the war log messages are translated
by each client.

Translations live in `theempire/locales/<lang>.json`, with the Italian
text as the key. `python3 tools/i18n.py check` lists missing or broken
translations, `python3 tools/i18n.py update` adds new texts to the
catalogues.

## Music and sound effects

Sounds and music are **synthesised by the game itself** in 8-bit style, with
square and triangle waves and noise like the computers of Theatre Europe. There
are no audio files in the project: on first launch they are generated in a couple
of seconds in `~/.theempire/sounds`.

- **Music**: in the menu and the lobby, Bach's Toccata in D minor
  (a tribute to Theatre Europe; the composition is in the public domain), in
  war a minor-key march with snare drum, and when the Clock drops below
  5 minutes a tension theme with heartbeat and ticking. At the end of the
  game there is a victory fanfare, a lament for defeat, or the wind
  over the dead world at midnight. With the `M` key you can choose the music:
  automatic, none, **Kalinka** (the fast chorus and the slow verse
  «Ах, под сосною», taken from the reference MIDI arrangement), the **Soviet anthem** (Aleksandrov's «Союз нерушимый»,
  transcribed from the official score: complete verse and chorus), the
  Toccata, the march, tension, victory, defeat or midnight.
- **Your own music**: put MIDI files (`.mid`) in the folder
  `~/.theempire/music` (or the one given by `THEEMPIRE_MUSIC`) and
  they appear in the `M` menu with the file name and keys 1-9: for example
  `~/.theempire/music/Give Peace a Chance.mid` becomes "Give Peace a
  Chance". The game plays them with its own synthesiser (bass, guitars,
  melody and drums, at most 4 minutes) and prepares them only once
  in the cache. The files remain yours: they are not part of the game or the
  repository. In the web TUI the folder of whoever starts the server is used.
- **Effects**:
  - battles, cities conquered or lost, a faction's collapse;
  - nuclear strike (siren, whistle, explosion), missile intercepted,
    gas, aircraft shot down;
  - truce, start of your online turn, alarms.
- **Every unit has its own voice**: a sound when it moves and
  one when it opens fire.

  | Unit | Movement | Fire |
  |---|---|---|
  | Infantry | marching footsteps | rifle volley |
  | Armour | diesel engine and tracks | cannon shot |
  | Fighter | passing jet | cannon bursts |
  | Bomber | heavy droning engines | whistling bombs and explosions |
  | Destroyer | whistle and fast propellers | rapid-fire guns |
  | Submarine | sonar ping | running torpedo and impact |
  | Transport | slow engine and low horn | — |
  | Cruiser | deep horn | broadside of heavy guns |
  | Aircraft carrier | horn and aircraft taking off | squadron taking off |

  Battles that concern you sound with the attacker's weapons: you hear
  the enemy submarine's torpedo coming.
- **War bulletin.** At the start of each of your turns the camera
  replays what the others have done since your previous turn,
  as in Theatre Europe. This applies to the AI factions and to other
  players, in hot-seat and online:
  - armies on the march, with each unit's voice;
  - **every attack in close-up**: the map centres on the clash, a
    ring flashes around the target, the attacker lights up, then
    fire and explosion with the sound of its weapon and finally the outcome
    (target destroyed, attacker repelled, city fallen). Attacks
    against you last longer and are flagged as "ATTACK AGAINST US";
  - cities conquered and lost, atomic bombs and chemical weapons.

  While the animation runs, the box at the bottom writes the **chronicle**
  of each scene. At the end the **written bulletin** appears, divided into
  sections:
  - weapons of mass destruction;
  - our front: every attack suffered, where, with which unit and how it ended;
  - the cities that changed flag (the ones lost are highlighted);
  - the other clashes sighted;
  - the movements observed: how many units and of what type, of which factions, and
    the most active areas.

  ```
  OUR FRONT · 6 attacks suffered, 2 repelled
  ⚔ AGAINST US · Bomber (Eurasian Union) on the city of Kharkiv → REPELLED
  ⚔ AGAINST US · Armour (Eurasian Union) on the city of Kharkiv → THE CITY FALLS
  CITIES THAT CHANGED FLAG · we lose 1
  ⚑ Kharkiv conquered by Eurasian Union (before: Atlantic Alliance) — LOST
  ```

  Any key skips the animation. `B` opens the **bulletin archive** at any time
  (the last 30 turns): ↑↓ scrolls, ←→ moves
  to previous and next turns, `R` replays that turn's animation.
  The bulletin respects the fog of war (online the server applies it),
  thins out marches that are too long and does not use up turn time.
- You only hear the events you know about. Distant battles between others and
  explosions in the fog of war stay silent. Atomic bombs are heard all over
  the world.
- The `M` key opens the audio menu: choose the music (automatic, none,
  Kalinka, Soviet anthem, Bach's Toccata, war march,
  tension, victory, defeat, midnight) and turn the effects on or off.
  The choice is kept for later games. From the command line:
  `--audio all|sfx|off` or `--muto`.
- To play sound it uses the player already present: `afplay` on macOS, `paplay`,
  `pw-play` or `aplay` on Linux, otherwise `ffplay`. If it finds none,
  the game works anyway and uses the terminal beep for important
  events. The online server plays no sound: the audio is on each
  player's computer.

## Playing from the browser (web TUI)

The game can also be played from a browser: same Braille map, same
colours, keys and mouse as the terminal, and the audio plays in the browser.

```bash
# game server on 7777 + web page on 8080
python3 -m theempire --serve --web --scenario ww3 --faction west --faction east --password segreta
# then the players open http://<server-address>:8080/
```

- The page asks for name, faction and password. For each browser the server starts
  a real client in a virtual terminal and shows it with
  [xterm.js](https://xtermjs.org/) (MIT, included in the project: no
  internet needed).
- **Tablets and phones**: the ⌨ button shows a keypad with the directions,
  the cursor arrows and the main commands (Enter, next, go to,
  production, end turn...). A− / A+ change the text size.
- **Audio in the browser**: effects and music travel as invisible signals
  in the terminal stream, and the page plays them with the Web Audio API. The
  🔊 button turns them off.
- **Rejoining**: the browser remembers your seat. If you reload the page you return
  to your faction.
- You can put the web page in front of someone else's game server:
  `python3 -m theempire --join host:7777 --web 8080`.
- The password never goes into the address: it travels inside the connection.
  On the internet, put the page behind HTTPS anyway (a reverse proxy such as
  Caddy or nginx) or a VPN. It works on Linux and macOS, because it uses the system's
  virtual terminals.

## Online multiplayer

An online game has a **server** that holds the game and runs the AI
factions, and up to **one player per faction** who connects from another
terminal or another computer. The factions given with `--faction` are the
seats for human players; the AI plays the others. Without `--faction`, all
factions are human seats.

### The setup screen
The easiest way to host: `python3 -m theempire --serve` (without a
scenario), or the **"Host an online game..."** entry in the start
menu. A page opens with all the options:

| Option | What it decides |
|---|---|
| Game | new, or one saved by a previous server |
| Scenario | which war |
| One row per faction | human player (a seat) or AI |
| AI difficulty | easy, normal, hard |
| Secret objectives, World events | yes or no |
| Time per turn | no limit, 60, 90, 120, 180 or 300 seconds |
| You play as | none (server only) or the faction you play from this terminal, and your name |
| Game port, Web TUI, Web port | where clients and the browser connect |
| Password | empty = game open to everyone |

Select with ↑↓, change with ←→ or space, type in the text fields.
A warning explains what is wrong (no human seat, identical ports...). At
the bottom of the page there is always the **equivalent command**, to copy for
next time. On startup the server prints how to join: the `--join` command
with the machine's address on the local network and the address for the browser.

### From the command line

```bash
# the host: server on port 7777, seats for NATO and the Pact, 3 minutes per turn
python3 -m theempire --serve --scenario coldwar --faction nato --faction pact \
        --password segreta --turn-time 180

# the host plays from the same terminal (server in the background)
python3 -m theempire --serve --scenario ww3 --faction west --faction east --play west

# the other players
python3 -m theempire --join 192.168.1.20 --name Bruno --password segreta
python3 -m theempire --join mioserver.example.org:7777 --faction east
```

- The game starts when all the seats are taken. Until then
  the lobby appears with the players' names.
- Turns still alternate between factions: while it's the others' turn you can look at
  the map, the overview and the log, and write in the **chat** (`T`). When
  it's your turn the terminal beeps.
- **Real fog of war.** The server sends each player only the enemy units
  that their forces can see, and only their own messages. The random
  generator for combat stays on the server. The server checks every
  command, so you cannot move someone else's unit or act out of turn.
- With `--turn-time` the server ends the turn of anyone who runs over the
  time by itself. The countdown appears at the top.
- `--senza-obiettivi` and `--senza-eventi` remove secret objectives and
  world events (they also apply to local games).
- **Rejoining.** If you drop, run the same `--join` again: the client has saved in
  `~/.theempire/online.json` a token that gives you back your seat.
- The server saves by itself every turn in `~/.theempire/server-<port>.json`.
  You resume with `--serve --load <file>`: the seats stay with the same
  players. `S` from a client asks for an immediate save.
- **On the internet** the host must open the TCP port (7777 or the chosen one)
  on the router/firewall, or use a VPN such as Tailscale or ZeroTier. The traffic
  is not encrypted: for games between strangers use a VPN or an SSH tunnel
  (`ssh -L 7777:localhost:7777 host`) and always set a password.

## Scenarios

| Scenario | Factions | Idea |
|---|---|---|
| **Tutorial: the Balkan campaign** (`tutorial`) | Italian Command against Rebel Republic | An instructor teaches you the game step by step, up to the conquest of Tirana |
| **World War III** (`ww3`) | Atlantic Alliance, Eurasian Union, Eastern Bloc | Three armed blocs; the rest of the world is neutral and can be conquered |
| **Cold War 1985** (`coldwar`) | NATO, Warsaw Pact | The original Theatre Europe brought to a world scale; China stays neutral |
| **Six empires** (`empire`) | six empires | A single capital each, the whole world to take, atomic bombs must be built |

## Rules

### Cities and production
There are 320 real cities: all the capitals plus the largest metropolises, in
proportion to the population and size of the countries. Each one has a
**size** from 1 to 3 (population over 1 or 5 million). It produces
`size + 1 if capital` points per turn, multiplied by the faction's
industry. Each city builds **one thing at a time**.
Ships can only be built in ports. Cities have a **militia** that
defends them even without troops.

- **Unrest**: a city in unrest **produces half** as long as the
  count lasts (you see it in the city panel, "unrest 3t"). A city
  ends up there when it has just been conquered (5 turns: the population has not yet accepted
  its new master), when hit by a Sabotage card, or when it
  has just revolted or changed hands in a coup
  (3 turns). Each turn the count goes down by one. It does not affect units or
  militia: it is a brake on the economy, so a conquest only really pays off
  after a few turns.
- The **logistic limit** (you see it as `Units n/limit`) grows with the cities
  you own. Above the limit, cities finish their production and wait.

### Units

| | Unit | Domain | Moves | HP | Att | Def | Cost | Notes |
|---|---|---|---|---|---|---|---|---|
| I | Infantry | land | 1 | 2 | 2 | 3 | 6 | conquers cities |
| A | Armour | land | 2 | 3 | 4 | 2 | 10 | conquers cities |
| F | Fighter | air | 8 | 1 | 3 | 3 | 12 | 16 fuel, ×1.5 against aircraft |
| B | Bomber | air | 6 | 2 | 6 | 1 | 18 | 24 fuel |
| D | Destroyer | sea | 3 | 3 | 2 | 2 | 12 | detects submarines, ×2 against them |
| S | Submarine | sea | 2 | 2 | 4 | 1 | 14 | invisible unless adjacent |
| T | Transport | sea | 3 | 1 | 0 | 1 | 10 | carries 6 land units |
| R | Cruiser | sea | 2 | 6 | 3 | 3 | 22 | bombards the coast without penalty |
| C | Aircraft carrier | sea | 2 | 6 | 1 | 2 | 28 | carries 6 aircraft, mobile base |
| U | Drone | air | 6 | 1 | 1 | 1 | 4 | sees 3 squares, 8 fuel; cheap |
| H | Hypersonic missile | air | 12 | 1 | 9 | 0 | 14 | range 12, spent in its attack |

Cities also produce **nuclear warheads** (45 points, cities of size
2 or more) and **chemical weapons** (20).

### Today's weapons: drones, hypersonic missiles and space
They exist in World War III and Six Empires; **not in Cold War 1985** (nor
in the tutorial), where the arsenal is that of the 1980s.

- **Drones** (`U`): a third of the cost of a fighter, and they see far (3
  squares). Reconnaissance, harassment, hunting unescorted transports: in
  battle they count for little.
- **Hypersonic missiles** (`H`): fly up to 12 squares and strike with
  attack 9; they are spent in the attack, won or lost, and need not fly
  back. Ideal against carriers, cruisers and distant garrisons.
- **Spy satellites** (40 points, only cities of size 3 or capitals): go
  into orbit above the city that built them. Each one sees **every enemy
  unit** (except submarines, which stay submerged) in a band 25° of
  longitude wide, from pole to pole, and so their **moves in the war
  bulletin**. Every turn the orbit shifts by 30°: more satellites cover more
  of the world.
- **Anti-satellite weapons** (16 points, cities of size 2 or more): kept in
  stock like warheads. With the **`Z`** key (or by clicking the `⊙` line of
  the panel) you fire them at a faction: 75% of the time they shoot down one
  of its satellites and leave it blind right where you are moving.
- How many satellites each faction has is known to all; where they fly is not.
- The AI builds satellites when it has big cities, answers whoever spies on
  it with anti-satellite weapons and uses missiles on valuable targets.

### Movement
- Outside cities there is **only one unit per square**, plus one aircraft:
  aircraft **fly over your units** (land units or ships) and can stop
  there, one per square; the map shows the aircraft. Over enemy units,
  however, you cannot pass: moving there is an attack. In cities you can
  stack as many as you like.
- Land units **board** a transport by moving onto its square and
  **disembark** by moving onto a land square (disembarking uses up the turn).
  With `l`/`u` you load and unload a ship stopped in port.
- Ships only enter friendly ports. A city on an isthmus (Panamá,
  Istanbul, Suez...) acts as a canal.
- Aircraft use 1 fuel per square and refuel in cities
  or on an aircraft carrier. At zero they crash: the panel shows the fuel.
- **Zoom**: `+` and `-` (or the "Zoom +" and "Zoom -" buttons at the bottom of the
  panel; on a phone, pinch with two fingers) enlarge the map
  ×2 or ×4. As in Terrascope the map is not distorted and does not repeat the
  same dots: each square becomes a block of 2×2 or 4×4 characters and
  the coastline is redrawn from a land map 4 times finer
  (`assets/land_hd.bin`, from Natural Earth). The cursor becomes the whole
  block, and units and cities sit at the centre of their block. To see more of the
  world there is the overview (`m`).
- **With the mouse**:
  - click on one of your units: you select it (click again to move to the
    next one in the same city);
  - click on a square next to the active unit: it moves there, or attacks;
  - click on a distant square: the path appears, a second click on the
    same square sends it marching (Esc cancels);
  - drag to move the map, wheel to scroll it, right button to
    select. It also works in the web TUI, and on touch screens your finger
    acts as the mouse: a tap is a click, dragging moves the map;
  - **the panel is clickable**: "Cards (K)" opens the cards, "Directive (P)"
    the directives, a faction the diplomacy, "Awaiting orders (n)" goes
    to the next unit, "Produces (p)" the city's production, a listed
    unit takes command of it. At the bottom of the panel there are the buttons
    End turn, Bulletin, Diplomacy, World, Audio, Save, Help, and the
    hints in the bottom row ("n next", "E end turn"...) can
    be clicked too. In menus a click chooses the entry, a click outside closes, the
    wheel scrolls.

### Production directives
With `P` you give a single order to the whole war economy and all cities
retool immediately. Work already done is kept, and cities conquered
later follow the same directive.

| Directive | What the cities build |
|---|---|
| manual | you decide, city by city |
| balanced | the AI decides based on the situation |
| land offensive | armour in the large cities, infantry in the small ones |
| air power | fighters, and bombers in one large city out of three |
| sea control | destroyers, submarines, cruisers and a few aircraft carriers in ports; troops inland |
| landings | transports in half the ports, troops elsewhere |
| defence | infantry everywhere |
| deterrence | nuclear warheads in capitals and metropolises, troops elsewhere |

If you set a city by hand with `p`, that city leaves the directive and the
panel marks it "(manual)". From the production menu, `X` puts it back under
the directive. In the directives menu, `T` applies the new order also
to the cities set by hand.

### Turn timer
To give the game pace you can limit the time of each turn. You choose it
in the start menu (no limit, 1, 2, 3 or 5 minutes) or with
`--turn-time SECONDS`, also locally and in hot-seat. The countdown
is at the top right. 10 seconds before the end the alarm sounds, and when time runs out
the turn ends by itself: units with a march order carry on, the
others stay where they are. The animated summary of the opponents' moves does not
use up your time.

### Combat
To attack, move a unit against an enemy. The clash is a duel in rounds:
in each round one of the two loses a hit point, with probability
`attack / (attack + defence)`, until one of the two dies. The panel
shows the **probability of victory** before you attack.

- Defence in a city ×1.5, fortified ×1.25.
- **Support**: +15% to the land attack for each other land unit of yours
  adjacent to the target (up to +60%). Concentrating forces matters.
- Amphibious assault directly from a transport: attack halved.
- Only infantry and armour conquer cities. Aircraft and ships bombard them
  and lower their militia.

### Fog of war
You know the geography and the colour of the cities, but you see enemy units only
within range of your forces. Submarines can only be seen up close.

### Escalation and the Doomsday Clock
The **Doomsday Clock** starts at 10 minutes to midnight (7 in the
Cold War) and sits at the top right, together with the DEFCON level.

| Weapon | Effect | Clock |
|---|---|---|
| ☣ Chemical (`C`) | 2 damage to all land units in a 3×3 area, militia halved; range 4 squares from your forces | −1 min |
| ☢ Nuclear (`N`) | everything destroyed in a 3×3 area, radioactive fallout for 12 turns, cities irradiated for 10 turns, the city hit loses one size; global range | −2 min, −3 if you hit a city |

- Each warhead can be **intercepted** by the target's missile defence
  (from 15% to 25%). Even an intercepted launch costs a minute.
- To launch you must type the **authorisation code** that appears on
  screen, as in the Theatre Europe manual.
- Whoever is hit usually **retaliates** (mutually assured destruction):
  the AIs almost always react, and hit your largest city.
- The AIs are rational actors: they never make the launch that would bring
  the clock to midnight, unless they are already doomed (3 cities or
  fewer). You, on the other hand, can.
- After 6 turns without weapons of mass destruction tension eases and
  the clock gains back a minute.
- **At midnight the game ends and everyone loses.**

### Cards (Futurisiko-style)
Besides moving units you can play **secret cards** that change the
war. You earn them in two ways:
- **by conquering**: as in Risk, at the end of the turn you draw a card if in the
  turn you took at least one city, by arms, a revolt or a
  coup;
- **from the secret services**: everyone receives a card every 6 turns.

You can hold at most 5 cards. The `K` key shows your hand and plays a
card; in the panel you see how many you have (♠) and how many each rival has.

| Card | Effect | Succeeds |
|---|---|---|
| Five-year plan (×3) | +50% production in all cities for 3 turns | always |
| General mobilisation (×2) | every city immediately gains one turn of production | always |
| Reinforcements (×3) | 2 infantry and 1 armour in one of your cities, beyond the logistic limit | always |
| Defection (×3) | an enemy unit you can see, outside cities, comes over to you | 65% |
| Commando (×2) | eliminates an enemy unit next to your forces | 70% |
| Revolt (×2) | an enemy city of size 1-2 rises up (minor capitals too, such as Warsaw or Minsk; not the faction's main capital, such as Moscow or Washington): neutral, or yours if you have land troops next to it (and the garrison comes over to you) | 60% |
| Coup (×1) | a neutral country with at most 4 cities, where you have a unit within 3 squares, comes over to you entirely | 50% |
| Espionage (×3) | you see all the units of a faction until your next turn, plus a report on cities, armies, warheads, cards and production | always |
| Sabotage (×2) | in an enemy city production restarts from zero, with 3 turns of unrest | 75% |
| Missile shield (×1) | +50% missile interception for 6 turns | always |
| Détente (×2) | peace summit: the Doomsday Clock goes back 3 minutes | always |

- A card that fails is spent anyway, and the victim learns of the
  attempt.
- Cards played against you appear in the war bulletin (section
  "Cards and covert actions"). Revolts and coups are public news.
- **The AI plays cards too**: it uses the economic ones at once, keeps shield and
  détente for when the clock gets close to midnight, and uses
  defections, commandos and sabotage where they hurt most.
- **Online, cards are secret**: the server sends nobody the hand
  of the others or the order of the deck, only how many cards each one has.
- Strategy: keep a Détente for moments of nuclear crisis and an
  Espionage before an offensive. A Defection on an aircraft carrier or a
  loaded transport is worth a battle won.

### Diplomacy: truces
With `O` you propose a **15-turn truce** to another faction. During the
truce the two factions cannot attack each other, enter each other's
squares or hit each other with chemical or nuclear weapons (the panel shows
`≈`). When it expires, it's back to war.

- The AI gladly accepts when it is losing or when the clock is under
  5 minutes. An aggressive AI that is winning almost always refuses, and
  nobody signs with someone who has just hit them with an atomic bomb.
- AIs in difficulty in turn propose truces to the strongest faction.
- After a refusal you can propose the same truce again only after 5 turns.
- Strategy: a truce on the secondary front frees your troops for the
  main one, but it doesn't last long. Use it for a decisive push, not forever.

### Secret objectives (Risk-style)
At the start of the game each faction receives a **secret objective**: whoever
completes it **wins at once**, before world domination. Yours appears in a
box on the first turn and in the panel (`◎ Objective`, with how far along
you are); `o` shows it again. The possible objectives:

- **two regions**: conquer all the cities of two regions (see below);
- **eliminate a faction**: you must take its last city yourself. If
  someone else eliminates it, the objective becomes "control N cities";
- **N cities**: the same number for everybody, 47% of the world's cities
  (domination needs 55%);
- **N enemy capitals**: conquer and hold almost half of the capitals that
  at the start belonged to your rivals (at most 12); neutral ones don't
  count.

The others' objectives are secret, online too: only an
**Espionage** card reveals them, and they are all revealed at the end of the game. The AI pursues
its own and does not sign truces with the faction it has to eliminate. There are no
objectives in the tutorial.

### Regions (continental bonuses)
The world is divided into 13 regions: North America, Central America and the Caribbean,
South America, Western Europe, Eastern Europe and the Balkans, Russia-Caucasus-Central
Asia, Middle East, North Africa, Sub-Saharan Africa, South
Asia, East Asia, Southeast Asia, Oceania. Whoever holds **all**
the cities of a region gets a **production bonus in all their cities**,
from +10% (North Africa, 8 cities) to +30% (Sub-Saharan Africa, 51 cities). The
bonuses add up; losing even a single city of the region removes them, and
gaining and losing them is announced to everyone.

The panel shows the regions you hold (`⚑`) or the one you are closest to;
`o` opens the full table: your cities per region, bonus and who holds it.
Strategy: an isolated enemy city inside your region is worth more than its
size, and taking one from your opponent removes their bonus.

### World events
Every 5-8 turns something happens that affects everyone, announced with a box
at the start of your turn and in the log (in light blue):

| Event | Effect |
|---|---|
| Oil crisis | for 3 turns aircraft and ships have half their moves |
| Famine | for 3 turns cities of size 3 produce 30% less |
| Economic boom | for 3 turns +25% production for everyone |
| Harsh winter | for 3 turns land units beyond the 45th parallel north move 1 less |
| UN summit | 6-turn truce imposed between the two strongest powers at war |
| Insurrection | an ungarrisoned city of the largest faction goes back to neutral |
| Hurricane | aircraft and ships outside ports in a stretch of sea lose 1 hit point |
| Arms race | one warhead to each nuclear power, the Clock advances by 1 minute |
| Diplomatic thaw | the Clock goes back 1 minute |
| Volunteers | one extra infantry in the capital of each faction |

The effects in progress appear in the panel (`✦`). There are no events in the
tutorial.

### Victory
- **Secret objective** completed (see above).
- **Domination**: control 55% of the world's cities (50% in Six empires, 90% in the
  tutorial, where you win by taking Tirana).
- **Conquest**: all rivals without cities.
- **On points** when the turns run out (300; 400 in Six empires).
- **Midnight**: no winner.

## Controls

In all menus (production, directives, cards, diplomacy, audio, confirmations)
you move with the **arrows ↑↓** and confirm with **Enter**. The letter or
number next to each entry chooses it at once, and Esc cancels.

| Key | Action |
|---|---|
| `q w e` `a d` `z x c` (or keypad) | moves the active unit in the 8 directions |
| arrows, PgUp/PgDn | move the cursor |
| mouse | click: select, move or attack; distant click + second click: march; drag or wheel: scroll the map |
| `Enter` | selects the unit under the cursor (in a city it cycles through the units); on an empty city it opens production |
| `n` / `Tab`, `space` | next unit / skip the unit |
| `s`, `f` | sentry (wakes up if the enemy arrives), fortify |
| `g` | go to: move the cursor and press Enter (the path is shown) |
| `A` | **automatic**: the unit passes under AI control |
| `v` | wakes the units under the cursor, including the ships' cargo |
| `l` / `u` | load / unload a ship in port |
| `p`, `P` | city production, production directive for all cities |
| `m` | world overview (one Braille dot = one square; click to jump) |
| `M` | audio: choose music and effects |
| `L` | game language |
| `N`, `C` | nuclear / chemical strike on the square under the cursor |
| `O` | diplomacy: propose a truce or answer a proposal |
| `K` | your cards: read them and play one |
| `o` | secret objective, regions with their bonuses, world events |
| `Z` | space: spy satellites and anti-satellite weapons |
| `+` / `-` | map zoom |
| `B` | war bulletin archive: read, browse the turns, `R` to replay the animation |
| `T` | chat (online games) |
| `E` | end turn (followed by the animated summary of the opponents' moves) |
| `S`, `Q`, `?` | save, quit (saving), help |

The active unit (the one taking orders) **blinks** on the map, so you
spot it at a glance even when you move the cursor away.

At the start of the game infantry is fortified and the rest is on sentry. Units
wake up by themselves when the enemy approaches, so each turn
only the front asks you for orders. A new unit asks for orders immediately.

## Recommended strategies

**Atlantic Alliance.** You have more cities than anyone, but they are spread over four
continents. Your limit is logistics, not industry.
1. Hold Eastern Europe. Poland, the Baltic states and Ukraine are the
   "Fulda Gap" of 2027: fortify the infantry in the cities and keep the
   armour behind for counter-attacks, which with the support bonus make the difference.
2. The Americas are almost all neutral and reachable by land. Put the
   American armour on automatic (`A`) heading south: Mexico and Brazil
   double your industry.
3. Aircraft carriers are your best card: mobile bases hold the
   Pacific and the Atlantic. Escort them with destroyers, because Eurasian
   submarines hunt them.
4. Don't fire first. Your doctrine is cautious and the AIs answer
   blow for blow: a single atomic bomb can cost you New York.

**Eurasian Union.** Few cities but the strongest industry (×1.5) and plenty of
armoured troops.
1. Attack at once: the neutrals of Central Asia and the Middle East
   (Iran, Iraq, Turkey, Central Asia) are reachable by land.
2. Break through in Europe with masses of armour: three units adjacent to the same
   target give +30% attack.
3. Use submarines against enemy transports: every transport sunk
   costs the opponent up to 6 units.
4. Chemical weapons (6) serve to break a fortified defence, but every use
   brings midnight closer.

**Eastern Bloc.** A huge mass of infantry and China's industrial
heartland.
1. Southeast Asia and India are your natural expansion.
2. Japan, South Korea and Taiwan are enemy outposts a step away:
   isolate them with submarines before landing.
3. You have only 10 warheads: build more in the large cities if the
   conflict escalates, because the deterrent counts even if you don't use it.

**Objectives, regions and events**
- Your secret objective decides where to attack: don't scatter your forces on
  fronts you don't need. A coup or a revolt (cards) are the
  quickest way to complete a region.
- Watch who is about to complete a region (`o`): taking a single
  city from them removes their bonus, and may block their objective.
- Play an Espionage card on the most threatening rival: besides their army
  it reveals their secret objective.
- An economic boom is the time to put all cities on a production
  directive; an oil crisis halts fleets and air forces, so it is
  the time for land offensives.

**In general**
- Beware of winning too fast: when a faction gets close to
  domination (92% of the threshold), the AIs feel lost and become much more
  inclined to a nuclear first strike. Sometimes it pays to stop, consolidate
  and first bring down their arsenals by conquering the large cities.
- Infantry holds, armour takes, bombers soften up.
  Before an assault, bombard the city to lower its militia.
- Check the victory percentage in the panel before every attack.
- Damaged units go back to a city: there they recover 1 HP per turn.
- A loaded transport travelling without escort is a target.
- Keep an eye on the logistic limit: build quality units (cruisers,
  bombers, armour) when you are close to the cap.

## Design choices (and possible alternatives)

Where there were doubts a choice was made, noted here together
with the alternative, so the course can be changed.

1. **Turns versus real time.** Theatre Europe was semi-real-time; here
   turns alternate between factions, because at a world
   scale you need time and reflection. Alternative: time-limited turns
   (e.g. 60 seconds).
2. **Grid versus provinces.** A regular grid (360×72) keeps the
   real geography and the "one unit per square" rule. Alternative:
   Risk-style provinces/regions, more readable but less tactical.
3. **Passive neutrals, minimal diplomacy.** Neutral countries defend their
   cities with militia but have no armies. Between factions there are only
   timed truces. Alternatives: armed neutrals that ally with whoever is
   attacked, real alliances, embargoes.
4. **No supply lines.** There is only a global logistic cap.
   Alternative: supply through a chain of cities (isolated units weaker),
   as in wargames.
5. **Balancing the blocs.** The West has more cities; Eurasia and China
   compensate with war industry (×1.5 and ×1.35) and more starting
   troops. The numbers are in `theempire/scenarios.py`.
6. **One turn = one week.** The calendar is only there for atmosphere.

7. **Online with alternating turns.** The server is the only referee and each
   player moves in their own turn. Alternative: simultaneous turns (everyone gives
   orders together, the server resolves them), faster but with much more
   complicated conflict rules.
8. **The AI's turn can be watched.** Every move of the opposing factions is
   recorded and replayed at the end of the turn like a TV newscast, as in
   Theatre Europe. Alternative: the invisible turn, with only reports
   in the event log.

Possible developments: alliances, random events (coups, oil
crises), technologies (missile shield, stealth), simultaneous online turns,
web client, scenario editor.

## Code structure

```
theempire/
  world.py      grid, wrap-around neighbours, distances, BFS, fine land map for zoom
  units.py      unit types and costs
  scenarios.py  factions, countries, warheads, doctrines
  game.py       rules: movement, combat, production, WMD, victory, saves
  ai.py         opponents (shared distance fields, landings, air raids, escalation, truces, cards)
  cards.py      Futurisiko-style cards: deck, draw, effects
  regions.py    the world's 13 regions and their production bonuses
  missions.py   the secret objectives
  events.py     the world events
  midi.py       reading and synthesis of the player's MIDI files
  commands.py   the player's commands, validated: the only way to change the game
  net.py        multiplayer: authoritative server, client, JSON protocol over TCP
  ui.py         curses interface: Braille map, panel, log, lobby, menus
  audio.py      chiptune synthesiser, effects, unit voices and music, background playback
  web.py        web TUI: HTTP/WebSocket gateway that brings the client to the browser
  assets/web/   web TUI page and xterm.js (MIT)
  cli.py        command line
  serversetup.py  the server setup screen
  i18n.py       languages: tr, Msg, catalogues
  locales/      translations (one JSON file per language)
  assets/world.json   map generated from Natural Earth
  assets/land_hd.bin  land map 4 times finer, for zoom
tools/build_world.py  regenerates the map (requires numpy and Pillow)
tools/i18n.py         checks and updates the translation catalogues
tests/                pytest tests
```

```bash
pip install pytest && python3 -m pytest           # tests
pip install numpy Pillow && python3 tools/build_world.py --source /tmp/ne   # regenerate the map
python3 tools/build_world.py --source /tmp/ne --hd-only   # only the fine land map for zoom
```

## Credits

- *Theatre Europe* (PSS, 1985) and the classic grid-based conquest games for the inspiration.
- [Terrascope](https://github.com/a-shygun/Terrascope) (MIT) for the technique of
  rendering the map in Braille.
- Geographic data [Natural Earth](https://www.naturalearthdata.com/) (public domain).
- [xterm.js](https://github.com/xtermjs/xterm.js) (MIT) for the terminal in the browser.
- Public domain music: Toccata and Fugue in D minor BWV 565 (J. S. Bach),
  anthem of the USSR (A. V. Aleksandrov, 1883–1946).
