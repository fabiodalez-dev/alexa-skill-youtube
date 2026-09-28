# Jukebox: YouTube Music su Alexa, dal tuo server

Jukebox è una skill Alexa privata che fa suonare su un Echo la musica e i podcast di YouTube Music, senza pubblicità e senza abbonamento Premium. Gira tutta su un server di casa: la skill riceve i comandi vocali, il server cerca su YouTube Music, estrae l'audio e lo passa all'Echo.

L'ho scritta per usare un Echo Dot di terza generazione con il catalogo di YouTube Music, che Amazon non offre fra i servizi musicali in Italia. Funziona in italiano.

> **Uso personale.** Estrarre l'audio da YouTube viola i termini di servizio di YouTube. La skill va usata in modalità sviluppo, sul proprio account Amazon, e **non va pubblicata** nello store di Alexa.

## Cosa si può chiedere

Tutti i comandi si dicono dopo "Alexa, chiedi a Jukebox di…" (all'infinito: "di mettere", "di farmi sentire") oppure dopo "Alexa, apri Jukebox" (all'imperativo: "metti…").

**Musica**

- un brano: "mettere Albachiara di Vasco Rossi", poi continua con la radio di YouTube Music
- un brano da un album: "mettere Luna dall'album Il suicidio dei samurai"
- una traccia: "mettere la terza traccia dell'album Wow", "l'ultima canzone di Requiem"
- un album: "mettere l'album Wow dei Verdena", "l'ultimo album di Vasco", "il primo disco di De André"
- un artista: "mettere musica di Lucio Dalla", "le più ascoltate di Vasco", "canzoni a caso di Mina"
- la discografia: "farmi sentire la discografia dei Verdena", tutti gli album dal primo all'ultimo, senza ristampe doppie
- radio e atmosfere: "la radio di Albachiara", "musica simile ai Verdena", "musica rilassante", "musica per studiare"
- la classifica italiana: "mettere la classifica", nella versione audio dei brani e non nei videoclip
- dal testo: "mettere la canzone che fa e la chiamano estate"
- la coda: "aggiungere Vita spericolata alla coda", "mettere l'album di questa canzone", "altro di questo artista"
- il loop: "mettere in loop Albachiara", "in loop l'album Wow", "mettere in loop questa canzone", "togliere il loop"

**Podcast**

- "mettere l'ultimo episodio di Tintoria"
- "mettere il podcast Tintoria": riprende l'episodio lasciato a metà, altrimenti l'ultimo
- "riprendere il podcast", "dove ero rimasto": riparte dal minuto giusto anche giorni dopo
- "mettere la puntata con Alessandro Barbero", "la puntata su Napoleone"
- "andare avanti di cinque minuti", "tornare indietro di trenta secondi", "andare al minuto novanta"
- "mettere l'episodio precedente", "dirmi cosa sto ascoltando"

**Le tue playlist** (facoltativo, dal tuo canale YouTube pubblico)

- "dirmi quali playlist ho", poi rispondi con il nome
- "mettere la mia playlist Relax", "mettere i miei preferiti"

Durante l'ascolto funzionano anche senza nominare Jukebox i comandi base di Alexa: "Alexa, pausa", "riprendi", "avanti", "indietro".

Quando la ricerca è incerta, Jukebox chiede conferma ("Intendi Sole di …?"): con "no" propone il risultato successivo.

## Come funziona

```
"Alexa, chiedi a Jukebox di mettere…"
      │
 Alexa cloud ──HTTPS──▶ nginx ──▶ Jukebox (Flask + gunicorn)
                                   ├─ verifica firma Amazon e Skill ID
                                   ├─ parse.py: dalla frase al comando
                                   ├─ music.py: ricerca con ytmusicapi
                                   ├─ streams.py: audio con yt-dlp, cache locale
                                   └─ state.py: coda per dispositivo, posizione dei podcast (SQLite)
      Echo ◀── audio HTTPS (URL firmati) ──┘
```

Alcune scelte che vale la pena conoscere:

- **Formato audio.** Alexa non riproduce Opus: Jukebox usa l'itag 140 di YouTube (AAC 128 kbps in MP4), disponibile anche senza account, che l'Echo suona senza conversioni.
- **Brani.** Vengono scaricati e rimuxati (senza ricodifica) in un MP4 con l'indice in testa, poi serviti da nginx con supporto Range. Il brano successivo viene preparato in anticipo, così parte senza attesa.
- **Podcast.** Un episodio di due ore pesa più di 100 MB: invece di aspettare il download completo, il server lo manda all'Echo mentre lo scarica. In una prova il primo byte è arrivato in 3,7 secondi e il salto al minuto 62 in 6,6. La posizione viene salvata ogni minuto e alla pausa.
- **Una frase, un campo.** Alexa ammette un solo campo di testo libero per frase: "la terza traccia dell'album Wow" arriva come testo, e la struttura (traccia, album, artista, podcast) la ricava `jukebox/parse.py`.
- **Titoli originali.** Con l'interfaccia in inglese YouTube traduce i titoli dei video ("Muschio Selvaggio" diventa "Wild Musk"): i podcast si leggono in italiano, mentre le ricerche si fanno in inglese perché in italiano ytmusicapi non restituisce risultati.
- **Sicurezza.** `/alexa` accetta solo richieste firmate da Amazon e destinate alla tua Skill ID. Gli URL audio sono firmati con HMAC e scadono dopo 24 ore, quindi il server non diventa un proxy aperto.

## Requisiti

- Un server Linux sempre acceso (io uso Debian 12), con Python 3.11 o successivo, `ffmpeg`, `git` e `unzip`
- Un dominio o sottodominio che punti al server, raggiungibile da internet sulla porta 443
- Un certificato HTTPS valido (Let's Encrypt va bene) e nginx che accetti **TLS 1.2**: Alexa non si collega agli endpoint solo TLS 1.3
- Un account sviluppatore Amazon gratuito, creato con lo **stesso account** dell'Echo

## Installazione sul server

I comandi presuppongono Debian o Ubuntu e i percorsi usati dal file di servizio (`/opt/jukebox`, `/var/cache/jukebox`, `/var/lib/jukebox`).

**1. Pacchetti, utente e cartelle**

```bash
sudo apt install python3-venv ffmpeg git unzip nginx
sudo useradd --system --home /var/lib/jukebox --shell /usr/sbin/nologin jukebox
sudo mkdir -p /opt/jukebox/bin /var/cache/jukebox /var/lib/jukebox
sudo chown jukebox:jukebox /var/cache/jukebox /var/lib/jukebox
```

**2. Codice e dipendenze Python**

```bash
sudo git clone https://github.com/fabiodalez-dev/alexa-skill-youtube.git /opt/jukebox/app
sudo python3 -m venv /opt/jukebox/venv
sudo /opt/jukebox/venv/bin/pip install -r /opt/jukebox/app/requirements.txt
```

**3. Deno**, il runtime JavaScript che yt-dlp usa per estrarre gli stream di YouTube (per un server ARM scegli lo zip `aarch64`)

```bash
curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip
sudo unzip -o /tmp/deno.zip -d /opt/jukebox/bin && rm /tmp/deno.zip
```

**4. Configurazione**

```bash
sudo cp /opt/jukebox/app/deploy/jukebox.env.example /etc/jukebox.env
sudo chown root:jukebox /etc/jukebox.env && sudo chmod 640 /etc/jukebox.env
openssl rand -hex 32
```

Apri `/etc/jukebox.env`, incolla la chiave generata in `JUKEBOX_SECRET` e imposta `JUKEBOX_PUBLIC_URL` con il tuo dominio. `JUKEBOX_SKILL_ID` lo riempi dopo aver creato la skill.

**5. Servizio**

```bash
sudo cp /opt/jukebox/app/deploy/jukebox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jukebox
curl http://127.0.0.1:8099/health
```

**6. nginx.** Parti da `deploy/nginx-jukebox.conf`, sostituisci `jukebox.example.com` e i percorsi dei certificati, attiva il sito e ricarica nginx. Se usi **YunoHost**, aggiungi il dominio con `yunohost domain add`, installa il certificato con `yunohost domain cert install`, e copia invece `deploy/nginx-yunohost.conf` nella cartella `.d` del dominio: contiene solo le location, con l'istruzione che le esclude dal login di YunoHost.

Controllo finale, da un'altra macchina:

```bash
curl https://jukebox.example.com/health
```

## Creare la skill su Amazon

Il server non deve collegarsi ad Amazon: sei tu a dire ad Amazon dove si trova il server.

1. Vai su [developer.amazon.com/alexa/console/ask](https://developer.amazon.com/alexa/console/ask) ed entra con l'account del tuo Echo.
2. **Create Skill**: nome `Jukebox`, lingua **Italian (IT)**, tipo **Custom**, hosting **Provision your own**, template **Start from scratch**.
3. **Interaction Model → JSON Editor**: incolla il contenuto di `skill-package/interactionModels/custom/it-IT.json`, poi **Save** e **Build skill**. Con oltre settemila frasi la compilazione richiede qualche minuto.
4. **Interfaces**: attiva **Audio Player**, poi di nuovo **Build skill**.
5. **Endpoint**: scegli **HTTPS**, scrivi `https://jukebox.example.com/alexa` in Default Region e seleziona *"My development endpoint has a certificate from a trusted certificate authority"*. Copia lo **Skill ID** (lo mostra la console sopra i campi Lambda: è lo stesso anche con HTTPS), poi **Save**.
6. Scrivi lo Skill ID in `JUKEBOX_SKILL_ID` dentro `/etc/jukebox.env` e riavvia: `sudo systemctl restart jukebox`.
7. Scheda **Test**: imposta **Development**.

Prova nel simulatore scrivendo `chiedi a jukebox di mettere albachiara di vasco rossi`, poi a voce sull'Echo. Il simulatore non riproduce l'audio: la prova vera la fa solo il dispositivo.

## Modificare le frasi

Il modello di interazione è generato, non va modificato a mano. Le frasi nascono dalla combinazione di verbi ("metti", "mettere", "fammi sentire", "mettiamo", "puoi mettere"…) e forme di richiesta in `tools/build_model.py`:

```bash
python3 tools/build_model.py
```

Lo script controlla che nessuna frase compaia in due intent e che non ci siano cifre, poi riscrive `skill-package/interactionModels/custom/it-IT.json`, da reincollare nella console.

## Test

```bash
python3 tests/test_parse.py
```

verifica l'interprete delle frasi (55 casi). `tests/simulate.py` simula invece le richieste di Alexa contro la logica completa della skill e fa ricerche vere su YouTube Music, quindi va lanciato sul server con la configurazione caricata:

```bash
sudo runuser -u jukebox -- bash -c 'set -a; . /etc/jukebox.env; cd /opt/jukebox/app && /opt/jukebox/venv/bin/python tests/simulate.py'
```

## Problemi noti e soluzioni

| Sintomo | Causa | Soluzione |
|---|---|---|
| Alexa dice "non posso raggiungere la skill" e nel log di nginx non compare nulla | nginx accetta solo TLS 1.3 | `ssl_protocols TLSv1.2 TLSv1.3;` |
| Qualsiasi frase finisce in `AMAZON.FallbackIntent` | modello non compilato, oppure frase non prevista | **Build skill** nella console; aggiungi la forma in `build_model.py` |
| Il servizio non parte: `Error detecting the version of libcrypto` | `oscrypto` di PyPI e OpenSSL 3.0.x | già risolto in `requirements.txt` con la versione da git |
| Brani lenti a partire, download che si blocca | IPv6 difettoso sulla rete | `streams.py` forza già IPv4 verso YouTube |
| Titoli in inglese | interfaccia inglese di YouTube | podcast ed episodi si leggono già in italiano |
| Alexa rinuncia su playlist molto grandi | risposta oltre circa 8 secondi | le playlist personali sono in cache e precaricate ogni mezz'ora |

Limiti che non dipendono da Jukebox: il lettore di Alexa non permette di cambiare la velocità dei podcast, i comandi di salto e ricerca richiedono sempre "chiedi a Jukebox di…", e delle playlist personali si vedono solo quelle pubbliche.

## Struttura del progetto

```
jukebox/
  app.py        endpoint HTTP: /alexa, /s/ (brani), /p/ (episodi), /health
  skill.py      intent, eventi AudioPlayer, coda, loop, podcast
  parse.py      dalla frase libera al comando
  music.py      YouTube Music: brani, album, artisti, playlist, classifica, podcast
  streams.py    estrazione audio, cache, download progressivo, URL firmati
  state.py      stato per dispositivo e posizione degli episodi (SQLite)
tools/build_model.py     generatore del modello di interazione
skill-package/…/it-IT.json   modello generato, da incollare nella console Alexa
deploy/          servizio systemd, nginx (standalone e YunoHost), configurazione di esempio
tests/           test dell'interprete e simulazione delle richieste di Alexa
```
