# THE EMPIRE

Gioco di strategia globale a turni per il terminale. Prende la **guerra
totale** di *Theatre Europe* (1985: armate, attacchi aerei, armi chimiche,
escalation nucleare, l'apocalisse come sconfitta di tutti) e il
**sistema di conquista** di *Empire* (Walter Bright, 1977: città che
producono unità, trasporti, portaerei, carburante degli aerei, nebbia di
guerra) e li porta **sulla scala del mondo intero**.

La mappa è il mondo reale: viene dai dati Natural Earth ed è disegnata in
caratteri Braille come in [Terrascope](https://github.com/a-shygun/Terrascope),
il punto di partenza del progetto. Ogni carattere è una casella di gioco
(1° di longitudine × 2° di latitudine) e i suoi 2×4 punti Braille
disegnano la costa vera. La mappa si avvolge da est a ovest: il Pacifico si
attraversa.

![Europa al turno 4 della Terza Guerra Mondiale](docs/screenshot.png)

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

## Musica ed effetti sonori

Suoni e musiche sono **sintetizzati dal gioco stesso** in stile 8-bit, con
onde quadre, triangolari e rumore come i computer di Theatre Europe. Nel
progetto non c'è nessun file audio: al primo avvio vengono generati in un paio
di secondi in `~/.theempire/sounds`.

- **Musica**: nel menu e nella lobby la Toccata in re minore di Bach
  (omaggio a Theatre Europe; la composizione è di pubblico dominio), in
  guerra una marcia in minore con rullante, e quando l'Orologio scende sotto
  i 5 minuti un tema di tensione con battito cardiaco e ticchettio. A fine
  partita c'è una fanfara di vittoria, un lamento per la sconfitta o il vento
  sul mondo morto a mezzanotte.
- **Effetti**:
  - battaglie, città conquistate o perdute, crolli di una fazione;
  - attacco nucleare (sirena, fischio, esplosione), missile intercettato,
    gas, aereo abbattuto;
  - tregua, inizio del tuo turno online, allarmi.
- Senti solo gli eventi che conosci. Le battaglie lontane tra altri e le
  esplosioni nella nebbia di guerra restano mute. Le atomiche si sentono in
  tutto il mondo.
- Il tasto `M` passa da **musica ed effetti** a **solo effetti** a **muto**,
  e la scelta resta per le partite successive. Da riga di comando:
  `--audio all|sfx|off` oppure `--muto`.
- Per suonare usa il lettore già presente: `afplay` su macOS, `paplay`,
  `pw-play` o `aplay` su Linux, altrimenti `ffplay`. Se non ne trova nessuno
  il gioco funziona lo stesso e usa il beep del terminale per gli eventi
  importanti. Il server online non suona: l'audio è sul computer di ogni
  giocatore.

## Multiplayer online

Una partita online ha un **server** che tiene la partita e guida le fazioni
dell'IA, e fino a un **giocatore per fazione** che si collega da un altro
terminale o da un altro computer. Le fazioni indicate con `--faction` sono i
posti per i giocatori umani; le altre le gioca l'IA. Senza `--faction`, tutte
le fazioni sono posti umani.

```bash
# chi ospita: server su porta 7777, posti per NATO e Patto, 3 minuti a turno
python3 -m theempire --serve --scenario coldwar --faction nato --faction pact \
        --password segreta --turn-time 180

# chi ospita e gioca dallo stesso terminale (server in background)
python3 -m theempire --serve --scenario ww3 --faction west --faction east --play west

# gli altri giocatori
python3 -m theempire --join 192.168.1.20 --name Bruno --password segreta
python3 -m theempire --join mioserver.example.org:7777 --faction east
```

- La partita comincia quando tutti i posti sono occupati. Fino ad allora
  compare la lobby con i nomi dei giocatori.
- I turni restano a fazioni alterne: mentre tocca agli altri puoi guardare
  la mappa, la panoramica e il registro, e scrivere in **chat** (`T`). Quando
  tocca a te il terminale emette un beep.
- **Nebbia di guerra vera.** Il server manda a ogni giocatore solo le unità
  nemiche che le sue forze vedono, e solo i suoi messaggi. Il generatore
  casuale dei combattimenti resta sul server. Il server controlla ogni
  comando, quindi non si può muovere un'unità altrui né agire fuori turno.
- Con `--turn-time` il server chiude da solo il turno di chi supera il
  tempo. Il conto alla rovescia compare in alto.
- **Rientro.** Se cadi, rilancia lo stesso `--join`: il client ha salvato in
  `~/.theempire/online.json` un gettone che ti restituisce il tuo posto.
- Il server salva da sé a ogni turno in `~/.theempire/server-<porta>.json`.
  Si riprende con `--serve --load <file>`: i posti restano agli stessi
  giocatori. `S` da un client chiede un salvataggio immediato.
- **Su internet** chi ospita deve aprire la porta TCP (7777 o quella scelta)
  sul router/firewall, o usare una VPN come Tailscale o ZeroTier. Il traffico
  non è cifrato: per partite tra sconosciuti usate una VPN o un tunnel SSH
  (`ssh -L 7777:localhost:7777 host`) e mettete sempre una password.

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
- Le IA sono attori razionali: non fanno mai il lancio che porterebbe
  l'orologio a mezzanotte, a meno di essere ormai spacciate (3 città o
  meno). Tu invece puoi farlo.
- Dopo 6 turni senza armi di distruzione di massa la tensione cala e
  l'orologio recupera un minuto.
- **A mezzanotte la partita finisce e perdono tutti.**

### Diplomazia: le tregue
Con `O` proponi una **tregua di 15 turni** a un'altra fazione. Durante la
tregua le due fazioni non possono attaccarsi, entrare nelle caselle
dell'altra né colpirla con armi chimiche o nucleari (nel pannello compare
`≈`). Allo scadere si torna in guerra.

- L'IA accetta volentieri quando sta perdendo o quando l'orologio è sotto i
  5 minuti. Un'IA aggressiva che sta vincendo rifiuta quasi sempre, e
  nessuno firma con chi lo ha appena colpito con l'atomica.
- Le IA in difficoltà propongono a loro volta tregue alla fazione più forte.
- Dopo un rifiuto puoi riproporre la stessa tregua solo dopo 5 turni.
- Strategia: una tregua sul fronte secondario ti libera le truppe per quello
  principale, ma dura poco. Usala per una spallata, non per sempre.

### Vittoria
- **Dominio**: controlla il 50% delle città del mondo (55% nella Guerra Fredda).
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
| `M` | audio: musica ed effetti → solo effetti → muto |
| `N`, `C` | attacco nucleare / chimico sulla casella del cursore |
| `O` | diplomazia: proponi una tregua o rispondi a una proposta |
| `T` | chat (partite online) |
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
- Attento a vincere troppo in fretta: quando una fazione si avvicina al
  dominio (92% della soglia), le IA si sentono perse e diventano molto più
  propense al primo colpo nucleare. A volte conviene fermarsi, consolidare
  e abbattere prima i loro arsenali conquistando le grandi città.
- La fanteria tiene, i corazzati prendono, i bombardieri ammorbidiscono.
  Prima di un assalto, bombarda la città per abbassarne la milizia.
- Guarda la percentuale di vittoria nel pannello prima di ogni attacco.
- Le unità danneggiate tornano in città: lì recuperano 1 PV a turno.
- Un trasporto carico che viaggia senza scorta è un bersaglio.
- Tieni d'occhio il limite logistico: costruisci unità di qualità (incrociatori,
  bombardieri, corazzati) quando sei vicino al tetto.

## Scelte di progetto (e alternative possibili)

Dove c'erano dubbi è stata fatta una scelta, segnata qui insieme
all'alternativa, così si può cambiare strada.

1. **Turni contro tempo reale.** Theatre Europe era semi-real-time; qui i
   turni sono simultanei per fazione, come in Empire, perché a scala
   mondiale servono tempo e riflessione. Alternativa: turni a tempo limitato
   (es. 60 secondi).
2. **Griglia contro province.** Una griglia regolare (360×72) mantiene la
   geografia vera e la regola "un'unità per casella" di Empire. Alternativa:
   province/regioni stile Risiko, più leggibili ma meno tattiche.
3. **Neutrali passivi, diplomazia minima.** I paesi neutrali difendono le
   città con la milizia ma non hanno eserciti. Tra le fazioni ci sono solo
   tregue a tempo. Alternative: neutrali armati che si alleano con chi viene
   attaccato, alleanze vere, embarghi.
4. **Niente rifornimenti di linea.** C'è solo un tetto logistico globale.
   Alternativa: rifornimento per catena di città (unità isolate più deboli),
   come nei wargame.
5. **Bilanciamento dei blocchi.** L'Occidente ha più città; Eurasia e Cina
   compensano con l'industria di guerra (×1.5 e ×1.35) e con più truppe
   iniziali. I numeri sono in `theempire/scenarios.py`.
6. **Un turno = una settimana.** Il calendario serve solo all'atmosfera.

7. **Online con turni alterni.** Il server è l'unico arbitro e ogni
   giocatore muove nel suo turno. Alternativa: turni simultanei (tutti danno
   ordini insieme, il server li risolve), più veloci ma con regole di
   conflitto molto più complicate.

Possibili sviluppi: alleanze, eventi casuali (colpi di stato, crisi
petrolifere), tecnologie (scudo antimissile, stealth), turni simultanei
online, client web, editor di scenari.

## Struttura del codice

```
theempire/
  world.py      griglia, vicinanze con avvolgimento, distanze, BFS
  units.py      tipi di unità e costi
  scenarios.py  fazioni, paesi, testate, dottrine
  game.py       regole: movimento, combattimento, produzione, armi DM, vittoria, salvataggi
  ai.py         avversari (campi di distanza condivisi, sbarchi, raid aerei, escalation, tregue)
  commands.py   i comandi del giocatore, validati: unica via per cambiare la partita
  net.py        multiplayer: server autoritativo, client, protocollo JSON su TCP
  ui.py         interfaccia curses: mappa Braille, pannello, registro, lobby, menu
  audio.py      sintetizzatore chiptune, effetti e musiche, riproduzione in background
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
