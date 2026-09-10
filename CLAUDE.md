# Spotprognos för Home Assistant — instruktioner för Claude Code

Det här repot ska bli en **custom integration för Home Assistant**, distribuerad via
**HACS**. Den skapar sensorer med elpris och elprisprognos för de svenska elområdena
SE1–SE4 från Spotprognos öppna JSON-API. Användaren väljer elområde, modell och
enhet i gränssnittet.

Läs hela den här filen innan du börjar, och följ arbetsordningen längst ned.

---

## Källan: Spotprognos API

Spotprognos är ett separat projekt (<https://github.com/hakannormark/power-price-oracle>)
som fyra gånger per dygn räknar ut en sjudygnsprognos för Nord Pools day-ahead-priser
och publicerar den som statiska JSON-filer på GitHub Pages.

- **Bas-URL:** `https://hakannormark.github.io/power-price-oracle/api/v1/`
- **Fullständig fältreferens:** <https://hakannormark.github.io/power-price-oracle/api.html>
  Läs den innan du skriver API-klienten. Den är facit. Stämmer något nedan inte med
  den, eller med filerna själva, är det filerna som gäller.
- Ingen nyckel, ingen rate limit, ingen autentisering. Integrationen använder **bara**
  det publika API:t. Den skrapar ingenting och anropar inga andra tjänster.

### Filer

| Sökväg | Används till |
| --- | --- |
| `zones/{SE1..SE4}/forecast.json` | Huvudkällan: timserie från i går 00:00 till sju dygn fram, alla modeller, växelkurs och drivkrafter |
| `models.json` | Modellerna som finns: `id`, `name_sv`, `description_sv`, `is_default` |
| `longterm.json` | Månadens snittpris 1–3 månader fram per elområde |
| `status.json` | Körstatus och `next_expected_update_utc` |
| `zones.json`, `accuracy.json`, `zones/*/history.json`, `zones/*/accuracy.json` | Används inte i första versionen |

### Konventioner du måste följa

- **Priser är i EUR/MWh.** Öre/kWh = EUR/MWh × `fx.rate` ÷ 10. `fx.rate` följer med
  i varje fil. Att bara dela med 10 ger eurocent, inte öre. Det felet har redan
  gjorts en gång i huvudprojektet.
- **`default_model`** anger modellen sajten visar. Den kan bytas när en annan modell
  mätt sig bättre. Standardvalet i integrationen ska vara *följ `default_model`*, inte
  ett inskrivet modell-id.
- **`series[]`**: en post per timme, `ts` är leveranstimmens början (ISO-8601 med offset,
  `Europe/Stockholm`), `actual` är officiellt pris eller `null`, `source` är
  `official`, `forecast` eller `demo`, och `models.<id>` har `p10`, `p50`, `p90`.
  p50 är prognosen. Åtta utfall av tio ska hamna mellan p10 och p90.
- **Aktuellt pris** = `actual` om det finns, annars vald modells `p50`. Timmen väljs med
  Home Assistants klocka, inte med `generated_at`.
- **En modell kan sakna värde för vissa timmar.** Kontrollera att nyckeln finns. Saknas
  den vald modellen helt i en fil: fall tillbaka på `default_model` och logga det en
  gång, spamma inte loggen.
- **`degraded: true`**: någon källa föll bort och delar kan vara från en tidigare körning.
  **`demo: true`**: syntetiska priser, visa inte som riktiga (sensor `unavailable` och
  en varning i loggen). **`fx.stale: true`**: äldre växelkurs används.
- **Uppdatering:** filerna skrivs om runt 06:30, 10:15, 13:30 och 18:00 svensk tid.
  Morgondagens officiella priser finns från körningen efter auktionen, normalt 13:30.
  GitHub Pages cachar i upp till tio minuter. **Polla var 30:e minut**, aldrig oftare
  än var 15:e.
- Inom `v1` tas inga fält bort. Nya kan tillkomma, så ignorera okända fält och krascha
  inte på dem.

---

## Vad integrationen ska göra

### Konfiguration i gränssnittet (config flow)

Ingen YAML. En config entry per elområde. Frågor:

1. **Elområde:** SE1, SE2, SE3 eller SE4 (med namn: Luleå, Sundsvall, Stockholm, Malmö).
   Samma elområde får inte läggas till två gånger.
2. **Modell:** *Följ Spotprognos standardmodell (rekommenderas)*, eller en av modellerna
   i `models.json` med svenskt namn. Hämta listan när flödet visas.
3. **Enhet:** öre/kWh (standard) eller EUR/MWh.
4. **Valfritt:** påslag i öre/kWh och om moms (25 %) ska läggas på. Standard: av. Gör
   det tydligt att spotpriset annars är exklusive allt.

Samma val ska gå att ändra i efterhand via ett **options flow**, utan att integrationen
tas bort och läggs till igen.

### Entiteter per elområde

En **enhet (device)** per elområde, t.ex. *Spotprognos SE3*. Entiteter:

| Entitet | Innehåll |
| --- | --- |
| Pris just nu | Officiellt pris om det finns, annars prognos. Attribut: `source`, `p10`, `p90`, `model`, `fx_rate`. |
| Pris nästa timme | Samma för nästa timme. |
| Dagens lägsta / snitt / högsta | Över dygnets timmar. |
| Morgondagens lägsta / snitt / högsta | `unavailable` tills det finns data för morgondagen. |
| Billigaste tre timmar | Starttid (timestamp) för dygnets billigaste sammanhängande tre timmar, snittpris som attribut. |
| Prognos | Huvudsensor med **attributlistor** för grafer och laddstyrning (se nedan). |
| Nästa månads snittpris | Från `longterm.json`, standardmodellen där. Attribut: terminsmarknadens pris (`lt_market`) och intervallet p10–p90. |
| Försämrad körning (binary sensor) | På när `degraded` är sant. |

**Attributformat för prognoslistor.** Använd samma format som Nord Pool- och
ENTSO-E-integrationerna, så att ApexCharts-kort och EV Smart Charging fungerar utan
omvägar: `raw_today` och `raw_tomorrow` som listor av
`{"start": iso, "end": iso, "value": pris}`, `today` och `tomorrow` som listor av
värden, samt `tomorrow_valid`. Lägg därtill `forecast` med alla kommande timmar,
med `value`, `p10`, `p90` och `source`. Kontrollera formatet mot de integrationerna
innan du låser det.

Tänk på recorder-storleken. Stora attributlistor bör uteslutas ur recorder
(`_unrecorded_attributes`).

### Övrigt

- **Diagnostik** (`diagnostics.py`): config entry, senaste `generated_at`, `run_id`,
  `degraded`, vald och faktisk modell, växelkurs.
- **Översättningar:** svenska och engelska (`translations/sv.json`, `en.json`, `strings.json`).
- **Felhantering:** nätverksfel eller trasig JSON ska ge `UpdateFailed`, så att
  entiteterna blir `unavailable` och Home Assistant försöker igen. Det får aldrig krascha.

---

## Arkitektur

- **Domän:** `spotprognos`. Kod i `custom_components/spotprognos/`.
- **Filer:** `__init__.py`, `manifest.json`, `const.py`, `api.py` (ren klient utan
  Home Assistant-beroenden, lätt att testa), `coordinator.py` (`DataUpdateCoordinator`),
  `config_flow.py`, `sensor.py`, `binary_sensor.py`, `diagnostics.py`, `strings.json`,
  `translations/`.
- HTTP via `async_get_clientsession(hass)`, med timeout. Lägg koordinatorn i
  `entry.runtime_data`.
- `unique_id` för entiteter: `f"{entry.entry_id}_{key}"`. Använd `EntityDescription`
  och `has_entity_name = True`.
- Ingen extern Python-dependency om det inte krävs. `aiohttp` finns redan i Home Assistant.
- Följ Home Assistants aktuella utvecklardokumentation
  (<https://developers.home-assistant.io/>). Kontrollera vilken Home Assistant-version
  som är aktuell när du börjar, och använd de API:er som gäller i den i stället för att
  anta.

### manifest.json och hacs.json

- `manifest.json`: `domain`, `name` ("Spotprognos"), `codeowners` (`["@hakannormark"]`),
  `config_flow: true`, `documentation` och `issue_tracker` (repots URL:er),
  `iot_class: "cloud_polling"`, `integration_type: "service"`, `requirements: []`,
  `version`.
- `hacs.json` i repots rot: `name`, `homeassistant` (lägsta version du testat mot),
  `render_readme: true`.
- Repots URL: `https://github.com/hakannormark/spotprognos-ha`.

---

## Kvalitet

- **Tester** med `pytest-homeassistant-custom-component`. Hämta en riktig
  `forecast.json`, `models.json` och `longterm.json` en gång och spara dem i
  `tests/fixtures/`. Testerna får aldrig anropa nätet.
- **Testfall som måste finnas:**
  - config flow, även dubblett-skyddet
  - options flow
  - aktuellt pris med `actual` respektive `null`
  - omräkningen till öre med `fx.rate`
  - fallback när vald modell saknas
  - `demo` och `degraded`
  - byte av timme
  - morgondagen saknas
  - billigaste tre timmar
  - påslag och moms
- **Lint:** `ruff`.
- **GitHub Actions:** en workflow som kör testerna, `hassfest` (Home Assistants
  validering) och HACS-validering (`hacs/action`). Alla tre ska vara gröna innan en release.
- Kör testerna och båda valideringarna lokalt eller i CI innan du säger att något är klart.
  Rapportera ärligt vad som är verifierat och vad som inte är det.

---

## Arbetsordning

Arbeta i den här ordningen och avsluta varje steg med gröna tester och en commit:

1. **Skelett:** `manifest.json`, `hacs.json`, `const.py`, tom integration som laddas,
   CI-workflow med hassfest och HACS-validering.
2. **API-klient** och fixtures, med tester.
3. **Koordinator:** hämtning var 30:e minut, felhantering, val av modell, omräkning.
4. **Config flow och options flow**, med tester.
5. **Sensorer:** pris nu, nästa timme, dygnens lägsta/snitt/högsta, billigaste tre
   timmar, prognossensorn med attributlistor.
6. **Binary sensor för försämrad körning** och **långtidssensorn**.
7. **Diagnostik och översättningar**, svenska och engelska.
8. **README:**
   - installation via HACS som custom repository
   - konfiguration
   - vad varje sensor visar
   - ett ApexCharts-exempel
   - en exempelautomation som laddar när det är billigast
   - ansvarsfriskrivning: spotpris utan påslag, skatt och nät; en prognos är inte ett löfte
9. **Release `v0.1.0`** med GitHub-release och releasenoteringar.

Committa och pusha till `main` efter varje avslutat steg. Ändra aldrig historiken.

## Klart betyder

- Integrationen går att installera via HACS som custom repository och läggas till i
  gränssnittet.
- Alla entiteter ovan finns och visar rimliga värden mot det riktiga API:t.
- Tester, hassfest och HACS-validering är gröna i CI.
- README förklarar installation och användning på svenska, med en kortare engelsk del.
