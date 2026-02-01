# Analyysi
```text
Tässä dokumentissa arvioidaan tekoälyn (ChatGPT) roolia kokoushuoneiden varausrajapinnan
toteutuksessa sekä niitä parannuksia, joita tekoälyn tuottamaan koodiin tehtiin projektin aikana.
```
---

## 1. Mitä tekoäly teki hyvin? 
```text
Tekoäly onnistui erityisesti projektin alkuvaiheessa luomaan toimivan ja käyttökelpoisen
pohjaratkaisun. Kun tehtävänanto ja vaatimukset määriteltiin riittävän selkeästi,
tekoäly tuotti nopeasti FastAPI-sovelluksen, joka sisälsi:

- oikeat endpointit (POST, GET, DELETE)
- in-memory-tallennuksen ilman tietokantaa
- perusliiketoimintalogiikan (päällekkäisyyksien estäminen, aikavälien tarkistus)
- aikavyöhykkeen huomioimisen
- selkeän ja testattavan rakenteen jatkokehitykselle

Tekoäly oli erityisen hyödyllinen “raakaversion” tuottamisessa: se antoi nopeasti
toimivan kokonaisuuden, jota pystyi ajamaan, testaamaan ja kehittämään eteenpäin.
Kun promptit olivat tarkkoja ja rajattuja, tekoälyn tuottama koodi oli teknisesti
oikein ja loogisesti järkevää.

Lisäksi tekoäly auttoi hyvin yksittäisissä täsmällisissä tehtävissä, kuten:
- pytest-testien kirjoittamisessa
- yksittäisten validointien lisäämisessä
```

## 2. Mitä tekoäly teki huonosti? 
```text
Vaikka tekoäly tuotti toimivaa koodia, sen tuottamassa ratkaisussa ilmeni useita
heikkouksia, jotka vaativat kriittistä tarkastelua ja korjaamista.

Keskeisimmät ongelmat olivat:

1. Luettavuus ja johdonmukaisuus  
  Koodi oli aluksi vaikeasti hahmotettavaa: funktiot olivat pitkiä, vastuut
  sekoittuivat ja nimeäminen ei ollut kaikkialla yhtä selkeää.

2. Epäjohdonmukaiset tyypitykset  
  Osa funktioista ja endpointeista käytti tyyppivihjeitä, mutta osa ei.
  Tämä heikensi koodin laatua ja vaikeutti ymmärtämistä, vaikka muuten
  tyyppivihjeitä oli käytössä.

3. Liian karkeat oletukset liiketoimintalogiikassa
  Esimerkiksi:
  - menneisyyden tarkistus tehtiin aluksi sekuntitasolla, mikä esti käytännössä
    tasatunnin varaukset
  - 30 minuutin aikablokit tarkistettiin ensin UTC-ajassa, mikä johti virheisiin
    kesä- ja talviajan vaihtuessa

4. Yhden vastuun periaatteen rikkominen
  Tekoälyn alkuperäinen `validate_business_rules`-funktio sisälsi liian monta
  erillistä tarkistusta, mikä teki siitä vaikeasti testattavan ja ylläpidettävän.
```

## 3. Mitkä olivat tärkeimmät parannukset, jotka teit tekoälyn tuottamaan koodiin ja miksi? 
```text
Projektin aikana tekoälyn tuottamaa koodia muokattiin ja refaktoroitiin merkittävästi.
Tärkeimmät parannukset olivat:

1. Liiketoimintalogiikan tarkentaminen
- Menneisyyden tarkistus muutettiin sallimaan varauksen aloitus kuluvan minuutin alusta
- 30 minuutin aikablokkivalidaatio siirrettiin tarkistettavaksi
  Europe/Helsinki-paikallisajassa
- Näillä muutoksilla logiikka vastaa paremmin todellista käyttötarvetta

2. Funktioiden pilkkominen
- Pitkä `validate_business_rules` pilkottiin pienempiin, selkeästi nimettyihin
  apufunktioihin
- Tämä paransi luettavuutta, testattavuutta ja yhden vastuun periaatteen noudattamista

3. Tyypitysten lisääminen
- Kaikki FastAPI-endpointit ja keskeiset funktiot saivat eksplisiittiset paluuarvon tyypitykset
- Tämä teki koodista johdonmukaisempaa ja helpommin ymmärrettävää

4. Dokumentaation ja testien lisääminen
- Funktioihin lisättiin kattavat docstringit yhtenäisellä tyylillä
- Pytest-testit lisättiin varauksen luontiin, listaukseen ja poistoon
- Testit varmistavat, että logiikka toimii myös refaktorointien jälkeen

5. Koodin yleinen siistiminen
- Importtien järjestys korjattiin
- Käyttämättömät importit poistettiin
- Rivinvaihdot ja rakenne yhtenäistettiin
```
## Yhteenveto
```text
Tekoäly toimi projektissa tehokkaana apuvälineenä, mutta ei itsenäisenä
ratkaisijana. Parhaan lopputuloksen saavuttaminen vaati
kriittistä arviointia, täsmällisiä promptteja ja käsin tehtyä refaktorointia.

Lopullinen, refaktoroitu koodi on selkeämpi, turvallisempi ja
ylläpidettävämpi kuin tekoälyn alkuperäinen tuotos. Tämä osoittaa,
että tekoäly on parhaimmillaan tukityökalu, ei korvaaja ohjelmoijan
ammatilliselle harkinnalle.
```