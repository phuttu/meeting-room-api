# Meeting Room Booking API

Yksinkertainen FastAPI-pohjainen REST API kokoushuoneiden varaamiseen.  

## Ominaisuudet

- Huoneiden varaus (POST)
- Varausten listaus huonekohtaisesti (GET)
- Varausten poisto (DELETE)
- In-memory-tallennus (ei tietokantaa)
- Aikavyöhyketietoinen käsittely (Europe/Helsinki)
- Automaattiset pytest-testit

Tuetut huoneet:
- A
- B

---

## Varauslogiikka

Seuraavat liiketoimintasäännöt on toteutettu:

- Varaukset eivät saa mennä päällekkäin saman huoneen sisällä
- Varaus ei voi alkaa menneisyydessä  
  (sallitaan aloitus kuluvan minuutin alusta)
- Aloitusajan täytyy olla ennen lopetusaikaa
- Varaus on sallittu vain virka-aikaan (08:00–16:00 Europe/Helsinki)
- Varaus on tehtävä 30 minuutin aikablokeissa (xx:00 tai xx:30)
- Varauksen kesto on vähintään 30 minuuttia ja enintään 8 tuntia
- Varaus ei saa ylittää yhtä paikallista kalenteripäivää


---

## Asennus ja käyttöönotto

### 1. Kloonaa projekti

```bash
git clone <repository-url>
cd meeting-room-api
```

### 2. Luo virtuaaliympäristö

```bash
python -m venv venv
```

### 3. Aktivoi virtuaaliympäristö

```bash
.\venv\Scripts\Activate
```

### 4. Asenna riippuvuudet

```bash
python -m pip install -r requirements.txt
```

### 5. Käynnistä sovellus

```bash
uvicorn main:app --reload
```

Sovelluksen käynnistyttyä API-dokumentaatio on saatavilla osoitteessa: http://127.0.0.1:8000/docs

### 6. Testaus
Projektissa on automaattiset pytest-testit.
Testit voidaan ajaa komennolla:

```bash
python -m pytest
```

## API-esimerkit

Alla esimerkit, joilla voit testata endpointit komentoriviltä.  

### Luo varaus (POST)

```powershell
Invoke-RestMethod `
  -Method POST `
  -Uri "http://127.0.0.1:8000/rooms/A/reservations" `
  -ContentType "application/json" `
  -Body '{"start":"2026-02-02T09:00:00","end":"2026-02-02T10:00:00"}'
```

### Listaa varaukset (GET)

```powershell
Invoke-RestMethod `
  -Method GET `
  -Uri "http://127.0.0.1:8000/rooms/A/reservations"
```

### Poista varaus (DELETE)

```powershell
Invoke-RestMethod `
  -Method DELETE `
  -Uri "http://127.0.0.1:8000/rooms/A/reservations/<PUT_RESERVATION_ID_HERE>"
```