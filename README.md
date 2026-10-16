# THE EMPIRE

Gioco di strategia globale a turni per il terminale. Prende la **guerra
totale** di *Theatre Europe* (1985: armate, attacchi aerei, armi chimiche,
escalation nucleare, l'apocalisse come sconfitta di tutti) e il
**sistema di conquista** di *Empire* (Walter Bright, 1977: città che
producono unità, trasporti, portaerei, carburante degli aerei, nebbia di
guerra) e li porta **sulla scala del mondo intero**.

La mappa è il mondo reale. Viene dai dati Natural Earth e la disegno in
caratteri Braille come fa [Terrascope](https://github.com/a-shygun/Terrascope),
il punto di partenza del progetto. Ogni carattere è una casella di gioco
(1° di longitudine × 2° di latitudine) e i suoi 2×4 punti Braille
disegnano la costa vera. La mappa si avvolge da est a ovest: il Pacifico si
attraversa.

```
 THE EMPIRE · Terza Guerra Mondiale · 1 mar 2027 · turno 1      ☢ 23:50  10 MIN A MEZZANOTTE  DEFCON 4
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢹⣿⣿⣿⣤⣄⡀ ⢠⣶⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣦⣽⡛⠟⠉     │ALLEANZA ATLANTICA
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠋⠁           ⠈⠉⠬⣿⣿⣿⣿⣿⣿⣷⣶⡶⢠⡄⠉⢘⣇        │Città  86  industria 206.0/turno
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⣤⡀           ⠈⠁⢴⣿⣿⣿⣿⣿⣿⣿⣿⣷⣤⣀⣤⣾⣿⣷⣄    │Unità 317/341  ☢ 20  ☣ 0
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣶⣤⣤⣀      ⢀⣧⡀ ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡀    │Unione Eurasiatica     24 città
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿★A⣿⠟                                │Blocco Orientale       31 città
```

## Avvio

Serve Python 3.10+ e un terminale UTF-8, meglio se a 256 colori. Il gioco
usa solo la libreria standard: niente da installare.

```bash
python3 -m theempire                 # menu: scenario, fazione, difficoltà
python3 -m theempire --list          # scenari e fazioni
python3 -m theempire --scenario ww3 --faction east --difficulty difficile
python3 -m theempire --scenario coldwar --faction nato --faction pact   # hot-seat, 2 giocatori
python3 -m theempire --load          # riprende ~/.theempire/save.json
python3 -m theempire --autoplay 100 --seed 1   # IA contro IA, senza interfaccia
```

Per installarlo come comando: `pip install .` e poi `theempire`.

## Scenari

| Scenario | Fazioni | Idea |
|---|---|---|
| **Terza Guerra Mondiale** (`ww3`) | Alleanza Atlantica, Unione Eurasiatica, Blocco Orientale | Tre blocchi armati; il resto del mondo è neutrale e conquistabile |
| **Guerra Fredda 1985** (`coldwar`) | NATO, Patto di Varsavia | Il Theatre Europe originale portato su scala mondiale; la Cina resta neutrale |
| **Empire!** (`empire`) | sei imperi | Come l'Empire classico: una sola capitale a testa, tutto il mondo da prendere, le atomiche vanno costruite |

## Regole

### Città e produzione
Ci sono 320 città vere: tutte le capitali più le maggiori metropoli, in
proporzione alla popolazione e all'estensione dei paesi. Ognuna ha una
**dimensione** da 1 a 3 (popolazione oltre 1 o 5 milioni). Produce
`dimensione + 1 se capitale` punti a turno, moltiplicati per l'industria
della fazione. Ogni città costruisce **una cosa alla volta**, come in Empire.
Le navi si costruiscono solo nei porti. Le città hanno una **milizia** che le
difende anche senza truppe.

- Una città appena conquistata passa 5 turni in **disordini** (metà produzione).
- Il **limite logistico** (lo vedi come `Unità n/limite`) cresce con le città
  possedute. Oltre il limite le città finiscono la produzione e restano in attesa.

### Unità

| | Unità | Dominio | Mosse | PV | Att | Dif | Costo | Note |
|---|---|---|---|---|---|---|---|---|
| I | Fanteria | terra | 1 | 2 | 2 | 3 | 6 | conquista città |
| A | Corazzati | terra | 2 | 3 | 4 | 2 | 10 | conquista città |
| F | Caccia | aria | 8 | 1 | 3 | 3 | 12 | 16 di carburante, ×1.5 contro aerei |
| B | Bombardiere | aria | 6 | 2 | 6 | 1 | 18 | 24 di carburante |
| D | Cacciatorpediniere | mare | 3 | 3 | 2 | 2 | 12 | scopre i sommergibili, ×2 contro di loro |
| S | Sottomarino | mare | 2 | 2 | 4 | 1 | 14 | invisibile se non è adiacente |
| T | Trasporto | mare | 3 | 1 | 0 | 1 | 10 | porta 6 unità di terra |
| R | Incrociatore | mare | 2 | 6 | 3 | 3 | 22 | bombarda la costa senza penalità |
| C | Portaerei | mare | 2 | 6 | 1 | 2 | 28 | porta 6 aerei, base mobile |

Le città producono anche **testate nucleari** (45 punti, città di dimensione
2 o più) e **armi chimiche** (20).

### Movimento
- Fuori dalle città sta **una sola unità per casella**. Nelle città se ne
  ammassano quante vuoi.
- Le unità di terra **salgono** su un trasporto muovendosi sulla sua casella e
  **sbarcano** muovendosi su una casella di terra (lo sbarco consuma il turno).
  Con `l`/`u` carichi e scarichi una nave ferma in porto.
- Le navi entrano solo nei porti amici. Una città su un istmo (Panamá,
  Istanbul, Suez...) fa da canale.
- Gli aerei consumano 1 di carburante per casella e si riforniscono in città
  o su una portaerei. A zero precipitano: il pannello mostra il carburante.

### Combattimento
Per attaccare muovi un'unità contro un nemico. Lo scontro è quello di Empire:
a ogni round uno dei due perde un punto vita, con probabilità
`attacco / (attacco + difesa)`, finché uno dei due non muore. Il pannello
mostra la **probabilità di vittoria** prima che tu attacchi.

- Difesa in città ×1.5, fortificati ×1.25.
- **Supporto**: +15% all'attacco di terra per ogni altra tua unità di terra
  adiacente al bersaglio (fino a +60%). Concentrare le forze conta.
- Assalto anfibio direttamente da un trasporto: attacco dimezzato.
- Solo fanteria e corazzati conquistano le città. Aerei e navi le bombardano
  e ne abbassano la milizia.

### Nebbia di guerra
Conosci la geografia e il colore delle città, ma vedi le unità nemiche solo
nel raggio delle tue forze. I sottomarini si vedono solo da vicino.

### Escalation e Orologio dell'Apocalisse
L'**Orologio dell'Apocalisse** parte da 10 minuti alla mezzanotte (7 nella
Guerra Fredda) e sta in alto a destra, insieme al livello DEFCON.

| Arma | Effetto | Orologio |
|---|---|---|
| ☣ Chimica (`C`) | 2 danni a tutte le unità di terra in un'area 3×3, milizia dimezzata; portata 4 caselle dalle tue forze | −1 min |
| ☢ Nucleare (`N`) | tutto distrutto in un'area 3×3, ricaduta radioattiva per 12 turni, città irradiate per 10 turni, la città colpita perde una dimensione; portata globale | −2 min, −3 se colpisci una città |

- Ogni testata può essere **intercettata** dalla difesa antimissile del
  bersaglio (dal 15% al 25%). Anche un lancio intercettato costa un minuto.
- Per lanciare devi digitare il **codice di autorizzazione** che compare a
  schermo, come nel manuale di Theatre Europe.
- Chi viene colpito di solito **risponde** (distruzione mutua assicurata):
  le IA reagiscono quasi sempre, e colpiscono la tua città più grande.
- Dopo 6 turni senza armi di distruzione di massa la tensione cala e
  l'orologio recupera un minuto.
- **A mezzanotte la partita finisce e perdono tutti.**

### Vittoria
- **Dominio**: controlla il 50% delle città del mondo (45% nella Guerra Fredda).
- **Conquista**: tutti i rivali senza città.
- **Ai punti** allo scadere dei turni (300; 400 in Empire!).
- **Mezzanotte**: nessun vincitore.

## Comandi

| Tasto | Azione |
|---|---|
| `q w e` `a d` `z x c` (o tastierino) | muove l'unità attiva nelle 8 direzioni |
| frecce, PagSu/PagGiù, mouse | muovono il cursore |
| `Invio` | seleziona l'unità sotto il cursore (in città scorre le unità); su una città vuota apre la produzione |
| `n` / `Tab`, `spazio` | unità successiva / salta l'unità |
| `s`, `f` | sentinella (si sveglia se arriva il nemico), fortifica |
| `g` | vai a: sposta il cursore e premi Invio (il percorso viene mostrato) |
| `A` | **automatica**: l'unità passa sotto il controllo dell'IA |
| `v` | sveglia le unità sotto il cursore, compreso il carico delle navi |
| `l` / `u` | carica / scarica una nave in porto |
| `p`, `P` | produzione della città, produzione automatica in tutte le città |
| `m` | panoramica del mondo (un punto Braille = una casella; clic per saltare) |
| `N`, `C` | attacco nucleare / chimico sulla casella del cursore |
| `E` | fine turno |
| `S`, `Q`, `?` | salva, esci (salvando), aiuto |

A inizio partita la fanteria è fortificata e il resto è di sentinella. Le
unità si svegliano da sole quando il nemico si avvicina, così a ogni turno
ti chiede ordini solo il fronte. Un'unità nuova chiede subito ordini.

## Strategie consigliate

**Alleanza Atlantica.** Hai più città di tutti, ma sono sparse su quattro
continenti. Il tuo limite è la logistica, non l'industria.
1. Tieni l'Europa orientale. Polonia, Paesi Baltici e Ucraina sono il
   "Fulda Gap" del 2027: fortifica la fanteria nelle città e tieni dietro i
   corazzati per i contrattacchi, che col bonus di supporto fanno la differenza.
2. Le Americhe sono quasi tutte neutrali e raggiungibili via terra. Metti i
   corazzati americani in automatico (`A`) verso sud: Messico e Brasile
   raddoppiano la tua industria.
3. Le portaerei sono la tua carta migliore: le basi mobili tengono il
   Pacifico e l'Atlantico. Scortale con i cacciatorpediniere, perché i
   sottomarini eurasiatici le cercano.
4. Non sparare per primo. La tua dottrina è prudente e le IA rispondono
   colpo su colpo: una sola atomica può costare New York.

**Unione Eurasiatica.** Poche città ma l'industria più forte (×1.5) e tante
truppe corazzate.
1. Attacca subito: i neutrali dell'Asia centrale e del Medio Oriente
   (Iran, Iraq, Turchia, Asia centrale) sono raggiungibili via terra.
2. Sfonda in Europa con masse di corazzati: tre unità adiacenti allo stesso
   bersaglio danno +30% d'attacco.
3. Usa i sottomarini contro i trasporti nemici: ogni trasporto affondato
   costa all'avversario fino a 6 unità.
4. Le chimiche (6) servono a spezzare una difesa fortificata, ma ogni uso
   avvicina la mezzanotte.

**Blocco Orientale.** Una massa enorme di fanteria e il cuore industriale
cinese.
1. Il Sud-est asiatico e l'India sono la tua espansione naturale.
2. Il Giappone, la Corea del Sud e Taiwan sono avamposti nemici a un passo:
   isolali con i sottomarini prima di sbarcare.
3. Hai solo 10 testate: costruiscine altre nelle grandi città se il
   conflitto si inasprisce, perché il deterrente conta anche se non lo usi.

**In generale**
- La fanteria tiene, i corazzati prendono, i bombardieri ammorbidiscono.
  Prima di un assalto, bombarda la città per abbassarne la milizia.
- Guarda la percentuale di vittoria nel pannello prima di ogni attacco.
- Le unità danneggiate tornano in città: lì recuperano 1 PV a turno.
- Un trasporto carico che viaggia senza scorta è un bersaglio.
- Tieni d'occhio il limite logistico: costruisci unità di qualità (incrociatori,
  bombardieri, corazzati) quando sei vicino al tetto.

## Scelte di progetto (e alternative possibili)

Dove avevo dubbi ho fatto una scelta e l'ho segnata qui, così si può
cambiare strada.

1. **Turni contro tempo reale.** Theatre Europe era semi-real-time; qui i
   turni sono simultanei per fazione, come in Empire, perché a scala
   mondiale servono tempo e riflessione. Alternativa: turni a tempo limitato
   (es. 60 secondi).
2. **Griglia contro province.** Una griglia regolare (360×72) mantiene la
   geografia vera e la regola "un'unità per casella" di Empire. Alternativa:
   province/regioni stile Risiko, più leggibili ma meno tattiche.
3. **Neutrali passivi.** I paesi neutrali difendono le città con la milizia
   ma non hanno eserciti. Alternativa: neutrali armati che si alleano con
   chi viene attaccato, o diplomazia (alleanze, armistizi, embarghi).
4. **Niente rifornimenti di linea.** C'è solo un tetto logistico globale.
   Alternativa: rifornimento per catena di città (unità isolate più deboli),
   come nei wargame.
5. **Bilanciamento dei blocchi.** L'Occidente ha più città; Eurasia e Cina
   compensano con l'industria di guerra (×1.5 e ×1.35) e con più truppe
   iniziali. I numeri sono in `theempire/scenarios.py`.
6. **Un turno = una settimana.** Il calendario serve solo all'atmosfera.

Possibili sviluppi: diplomazia e armistizio, eventi casuali (colpi di stato,
crisi petrolifere), tecnologie (scudo antimissile, stealth), partite in
rete, salvataggi multipli, editor di scenari.

## Struttura del codice

```
theempire/
  world.py      griglia, vicinanze con avvolgimento, distanze, BFS
  units.py      tipi di unità e costi
  scenarios.py  fazioni, paesi, testate, dottrine
  game.py       regole: movimento, combattimento, produzione, armi DM, vittoria, salvataggi
  ai.py         avversari (campi di distanza condivisi, sbarchi, raid aerei, escalation)
  ui.py         interfaccia curses: mappa Braille, pannello, registro, menu
  cli.py        riga di comando
  assets/world.json   mappa generata da Natural Earth
tools/build_world.py  rigenera la mappa (richiede numpy e Pillow)
tests/                test pytest
```

```bash
pip install pytest && python3 -m pytest           # test
pip install numpy Pillow && python3 tools/build_world.py --source /tmp/ne   # rigenera la mappa
```

## Crediti

- *Theatre Europe* (PSS, 1985) ed *Empire* (Walter Bright, 1977) per l'ispirazione.
- [Terrascope](https://github.com/a-shygun/Terrascope) (MIT) per la tecnica di
  resa della mappa in Braille.
- Dati geografici [Natural Earth](https://www.naturalearthdata.com/) (pubblico dominio).
