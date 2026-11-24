# Kundedatabase

Kunderegister for landbruksrådgiving. Kundene lagres i en lokal SQLite-database, og Excel (.xlsx) brukes
til import og eksport. Programmet er bygd i samme stil som Gjødselplan.

## Kom i gang

Du trenger Python 3.11 eller nyere **med tkinter**. Installasjonen fra python.org har det.
(Homebrew-Python mangler tkinter.)

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # openpyxl og pytest
.venv/bin/python app.py                       # start programmet
```

Andre kommandoer:

```sh
.venv/bin/python -m pytest                    # kjør testene
.venv/bin/python app.py --selftest            # sjekk installasjonen uten å klikke (skriver selftest.log)
.venv/bin/python app.py --geotest             # får vi kontakt med Kartverket? (krever internett)
.venv/bin/python tools/make_sample_xlsx.py    # lag sample/kunder_test.xlsx med OPPDIKTEDE kunder
```

**Windows-versjon:** kjør `build_windows.bat` på en Windows-PC, eller arbeidsflyten **Windows-bygg** på GitHub.
Resultatet er `dist/Kundedatabase-<versjon>-windows.zip` med `Kundedatabase.exe`. PC-en trenger ikke Python.

## Importere Excel-filen din

1. Trykk **Importer…** og velg .xlsx-filen.
2. Programmet leter etter overskriftene i de 10 første radene. Disse kolonnene brukes:

   `Firma | Sted | Kategori | Fullt navn | E-post | Adresse 1 | Postnummer | Org.nr | Gnr og bnr | Kommunenr | Telefon - Mobilnr.`

   - Store og små bokstaver, mellomrom og tegnsetting spiller ingen rolle («ORG.NR.» = «Org.nr»).
   - Kolonner som mangler, blir tomme. Andre kolonner blir ikke brukt; forhåndsvisningen viser hvilke.
   - Har filen flere ark, velger du ark øverst til høyre.
3. Sjekk forhåndsvisningen, og velg hvordan kundene skal importeres:
   - **Slå sammen** (anbefalt):
     - En kunde med samme Org.nr, eller samme Firma + Fullt navn når Org.nr mangler, blir oppdatert.
     - Tomme celler i filen sletter ingenting.
     - Notater og koordinater beholdes.
     - Alle andre rader blir nye kunder.
   - **Erstatt alle**: alle kunder slettes først, også notater og koordinater.
   - Det tas en sikkerhetskopi før hver import.
4. Etter importen får du en oppsummering: nye, oppdatert, hoppet over (uendret eller uten navn), feil og
   advarsler. Programmet tilbyr så å hente koordinater for de nye kundene.

Detaljer om innholdet:

- **Ledende nuller:** Postnummer, Kommunenr, Org.nr og Telefon lagres som tekst. Har Excel lagret
  postnummer 0150 som tallet 150, blir det rettet til 0150 (det samme gjelder kommunenr).
- **Gnr og bnr** kan skrives som `12/3`, `12/3/0`, `12-3`, `gnr 12 bnr 3`, `4642-12/3`, eller flere adskilt med
  komma, semikolon eller «og».
- **Advarsler** stopper aldri en import eller lagring. Det gjelder ugyldig e-post, Org.nr som ikke er
  9 siffer eller har feil kontrollsiffer, og Postnummer eller Kommunenr som ikke er 4 siffer.

## Bruke programmet

- **Liste og detaljer:**
  - Klikk på en kolonneoverskrift for å sortere.
  - **Søk** leter i alle feltene, også notatene, og alle ordene må finnes.
  - Dobbeltklikk for å redigere. Detaljene til høyre viser alle feltene og eventuelle advarsler.
- **Ny kunde / Rediger / Slett:**
  - Kategori kan velges fra listen eller skrives fritt.
  - Koordinater kan skrives inn eller limes inn fra Google Maps: høyreklikk stedet og klikk på tallene.
  - Du blir alltid spurt før noe slettes.
- **Utvalg (☑):**
  - Klikk i første kolonne, eller trykk mellomrom, for å velge en kunde.
  - Knapper: *Velg alle synlige*, *Fjern alle* og *Inverter*. *Vis bare valgte* skjuler resten.
  - Utvalget beholdes når du søker eller filtrerer. Statuslinjen viser «X valgt av Y».
- **Utvalgskriterier:**
  - Lag rader med felt, operator og verdi. Operatorene er inneholder, er lik, starter med, er ikke,
    er tom, er ikke tom og en av (verdier adskilt med komma).
  - Kombiner radene med OG eller ELLER.
  - *Velg alle treff* gjør treffene til utvalget. *Legg treff til utvalg* legger dem til det du har valgt fra før.
  - Kriteriene kan lagres med navn.
- **Vis i Google Maps:** åpner kundens punkt, eller søker på adressen hvis kunden mangler koordinater.
- **Eksporter…:**
  - Velg valgte (☑) kunder, kundene som vises i listen nå, eller alle.
  - De 11 kolonnene kommer i samme rekkefølge som ved import, så filen kan importeres igjen.
  - Koordinater og notater er valgfrie ekstrakolonner, og importen leser dem også.

## Koordinater

Koordinatene hentes fra Kartverkets åpne tjenester. Det trengs ingen nøkkel. Programmet prøver i denne
rekkefølgen:

1. **Kommunenr + gnr/bnr** (Eiendom-API): punktet for eiendommens hovedteig. Det er mest nøyaktig for gårder.
2. **Adresse 1 + Postnummer** (Adresse-API). Uten eksakt treff prøves et omtrentlig søk.
3. **Postnummer**: midten av adressene i postnummeret. Uten postnummer brukes **Sted** (Stedsnavn-API).
   Begge gir bare en omtrentlig plassering.

Slik fungerer oppslagene:

- Velg **Koordinater → Hent manglende koordinater**. Oppslagene går i bakgrunnen, så programmet kan brukes
  mens de pågår. Det sendes høyst 4 forespørsler i sekundet.
- *Stopp* beholder det som er funnet så langt.
- Koordinatene lagres i databasen. Endrer du adressen, blir de hentet på nytt neste gang. Koordinater du har
  satt selv («Manuell»), beholdes.
- Kunder uten koordinater har oransje rad og «⚠ Mangler» eller «⚠ Ikke funnet» i kolonnen Koordinater.
- Bare adressefeltene sendes til Kartverket.

## Kart over utvalget

- **Kart → Vis utvalget på kart** (eller knappen *Vis på kart*) lager et kart over de valgte (☑) kundene og
  åpner det i nettleseren. Er ingen valgt, kan du bruke kundene som vises i listen.
  - Kartet lages med Leaflet, med Kartverket topo eller OpenStreetMap som bakgrunn. Du kan bytte øverst til
    høyre i kartet.
  - Pinnene har farge etter kategori, og det er en tegnforklaring nederst til høyre.
  - Klikk på en pinne for å se firma, navn, telefon, e-post og lenken «Åpne i Google Maps».
  - Kunder uten koordinater får du en advarsel om, og de står også listet på kartet.
- **Kart → Eksporter KML…** lager en fil du kan importere i Google My Maps (mymaps.google.com: lag et nytt
  kart og velg *Importer*).
- Valgfritt: legg inn en **Google Maps API-nøkkel** under **Fil → Innstillinger…**. Da lages kartet med Google
  Maps i stedet. Nøkkelen skrives inn i kartfilen, så ikke del den filen.

## Personvern og datamappe

Kundedataene er personopplysninger. Slik er det ordnet:

- Alt programmet lagrer, ligger i datamappen:
  - `data/` når programmet kjøres fra kildekoden;
  - `%APPDATA%\Kundedatabase` i Windows-versjonen;
  - en annen mappe hvis miljøvariabelen `KUNDEDB_DATA` peker dit.
- Datamappen, `*.db`, `*.xlsx`, `*.kml` og kartfilene er utelatt fra git. Legg aldri ekte kundedata i repoet.
  Bruk `tools/make_sample_xlsx.py` for testdata.

| Fil / mappe | Innhold |
|---|---|
| `kundedatabase.db` | Alle kunder og innstillinger (SQLite) |
| `backups/` | Kopi ved hver oppstart og før hver import (de 20 nyeste beholdes) |
| `export/` | Standardmappe for eksport; kartfilene `kart_*.html` (de 10 nyeste beholdes) |
| `utvalg.json` | Lagrede utvalgskriterier |
| `kundedatabase.log` | Feillogg |

Ikke legg datamappen i en delt mappe (OneDrive, Dropbox, fellesdisk) uten å tenke over hvem som kan lese den.
