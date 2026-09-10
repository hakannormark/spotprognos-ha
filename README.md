# Spotprognos för Home Assistant

[![CI](https://github.com/hakannormark/spotprognos-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/hakannormark/spotprognos-ha/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)

Custom integration för [Home Assistant](https://www.home-assistant.io/) med elpris och
sjudygnsprognos för Nord Pools day-ahead-marknad i SE1–SE4. Data kommer från
[Spotprognos](https://hakannormark.github.io/power-price-oracle/) öppna API, som
uppdateras fyra gånger per dygn. Integrationen läser bara det publika API:t, och
det behövs ingen nyckel.

*English below.*

- Aktuellt pris och nästa timme: officiellt pris när det finns, annars prognos
- Dagens och morgondagens lägsta, snitt och högsta pris
- Starttid för dygnets billigaste tre sammanhängande timmar
- En prognossensor med listor i samma format som Nord Pool-integrationen, för
  ApexCharts och EV Smart Charging, plus hela veckoprognosen med osäkerhetsintervall
- Nästa månads snittpris bredvid terminsmarknadens pris
- Val av elområde, modell, enhet (öre/kWh eller EUR/MWh), påslag och moms i gränssnittet

> **Spotpriset är exklusive** påslag, elcertifikat, energiskatt, nätavgift och moms,
> om du inte själv lägger till påslag och moms i inställningarna. **En prognos är
> inte ett löfte.** Se [Ansvarsfriskrivning](#ansvarsfriskrivning).

## Installation

Kräver Home Assistant 2026.9.1 eller senare och [HACS](https://hacs.xyz/).

1. HACS → ⋮ (uppe till höger) → **Anpassade arkiv** (*Custom repositories*).
2. Lägg till `https://github.com/hakannormark/spotprognos-ha` med kategorin
   **Integration**.
3. Sök fram **Spotprognos** i HACS, installera och starta om Home Assistant.
4. **Inställningar → Enheter och tjänster → Lägg till integration → Spotprognos**.

Utan HACS: kopiera mappen `custom_components/spotprognos` till `custom_components/`
i din Home Assistant-konfiguration och starta om.

## Konfiguration

Allt ställs in i gränssnittet. Varje elområde läggs till för sig, och samma elområde
kan bara läggas till en gång.

| Inställning | Standard | Förklaring |
| --- | --- | --- |
| Elområde | – | SE1 Luleå, SE2 Sundsvall, SE3 Stockholm eller SE4 Malmö. |
| Modell | Följ Spotprognos standardmodell | Används för timmar som saknar officiellt pris. Standardmodellen byts när en annan modell mätt sig bättre, och integrationen följer med. Välj en bestämd modell bara om du vet varför. Försvinner den ur API:t används standardmodellen, och det loggas en gång. |
| Enhet | öre/kWh | öre/kWh räknas om med växelkursen som Spotprognos publicerar (EUR/MWh × SEK per EUR ÷ 10). EUR/MWh är priset som det handlas. |
| Påslag | 0 | Elhandlarens påslag i öre/kWh exklusive moms. Läggs på varje timme och på alla sensorer. |
| Moms | Av | Lägger 25 % moms på spotpris plus påslag. |

Allt utom elområdet kan ändras i efterhand under **Konfigurera** på integrationen,
utan att den tas bort och läggs till igen.

## Sensorer

En enhet per elområde, t.ex. *Spotprognos SE3*. Entitets-id:n nedan är de som skapas
när Home Assistant körs på svenska. På engelska blir de t.ex.
`sensor.spotprognos_se3_current_price`.

| Entitet | Exempel på entitets-id | Visar |
| --- | --- | --- |
| Pris just nu | `sensor.spotprognos_se3_pris_just_nu` | Officiellt pris om det finns, annars vald modells prognos (p50). Attribut: `source` (`official` eller `forecast`), `p10`, `p90`, `model`, `fx_rate`, `fx_stale`, `start`. |
| Pris nästa timme | `sensor.spotprognos_se3_pris_nasta_timme` | Samma sak för nästa timme. |
| Dagens lägsta / snittpris / högsta | `sensor.spotprognos_se3_dagens_lagsta_pris` m.fl. | Över dygnets timmar, svensk tid. |
| Morgondagens lägsta / snittpris / högsta | `sensor.spotprognos_se3_morgondagens_lagsta_pris` m.fl. | `unavailable` tills alla morgondagens timmar har officiellt pris, normalt efter körningen runt 13:30. |
| Billigaste tre timmar | `sensor.spotprognos_se3_billigaste_tre_timmar` | Starttid (tidsstämpel) för dygnets billigaste tre sammanhängande timmar. Attribut: `end` och `average`. |
| Prognos | `sensor.spotprognos_se3_prognos` | Priset just nu, med listor för grafer och laddstyrning (se nedan). |
| Nästa månads snittpris | `sensor.spotprognos_se3_nasta_manads_snittpris` | Månadsprognos från Spotprognos långtidsmodell. Attribut: `p10`, `p90`, `lt_market` (terminsmarknadens pris), `lt_market_tenor`, `last_year` (samma månad förra året), `month`. |
| Försämrad körning | `binary_sensor.spotprognos_se3_forsamrad_korning` | På när en datakälla föll bort i senaste körningen och delar av datan kan vara från en tidigare körning. Priserna visas ändå. |

Alla priser har den enhet, det påslag och den moms du valt. Långtidssensorn räknas om
med samma växelkurs som timpriserna.

Om API:t inte svarar eller skickar trasig data blir sensorerna `unavailable`, och
integrationen försöker igen var 30:e minut. Skickar Spotprognos demodata (syntetiska
priser) blir prissensorerna `unavailable` och en varning skrivs i loggen.

### Prognossensorns attribut

Formatet är detsamma som i Nord Pool- och ENTSO-E-integrationerna, så att kort och
laddstyrning som redan läser dem fungerar utan omvägar.

| Attribut | Innehåll |
| --- | --- |
| `raw_today` | Dagens timmar: `[{"start": …, "end": …, "value": …}, …]` |
| `raw_tomorrow` | Morgondagens timmar i samma format, tom lista tills de officiella priserna finns |
| `today`, `tomorrow` | Bara värdena, i timordning |
| `tomorrow_valid` | `true` när alla morgondagens timmar har officiellt pris |
| `forecast` | Alla kommande timmar, från den pågående och cirka en vecka fram: `start`, `end`, `value`, `p10`, `p90`, `source` |

`p10` och `p90` är prognosens osäkerhetsintervall: åtta utfall av tio ska hamna
mellan dem. För timmar med officiellt pris är de `null`. `raw_today` och `today`
innehåller prognos för timmar som ännu inte har officiellt pris, vilket normalt aldrig
händer för i dag.

Listorna sparas inte i Home Assistants databas (recorder), så de fyller den inte.

**Morgondagen** räknas som tillgänglig först när börsens priser är publicerade, precis
som i Nord Pool-integrationen. Då planerar t.ex. EV Smart Charging inte laddning på
prognoser. Prognoserna för morgondagen och veckan finns alltid i `forecast`.

## Exempel

### ApexCharts: veckoprognos med osäkerhetsintervall

Kräver [apexcharts-card](https://github.com/RomRider/apexcharts-card) från HACS.

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Elpris SE3, officiellt och prognos
  show_states: true
graph_span: 7d
span:
  start: hour
now:
  show: true
  label: Nu
yaxis:
  - decimals: 0
series:
  - entity: sensor.spotprognos_se3_prognos
    name: Pris
    type: line
    curve: stepline
    stroke_width: 2
    show:
      in_header: before_now
    data_generator: |
      return entity.attributes.forecast.map(h => [new Date(h.start).getTime(), h.value]);
  - entity: sensor.spotprognos_se3_prognos
    name: p10
    type: line
    curve: stepline
    stroke_width: 1
    stroke_dash: 4
    show:
      in_header: false
    data_generator: |
      return entity.attributes.forecast.map(h => [new Date(h.start).getTime(), h.p10]);
  - entity: sensor.spotprognos_se3_prognos
    name: p90
    type: line
    curve: stepline
    stroke_width: 1
    stroke_dash: 4
    show:
      in_header: false
    data_generator: |
      return entity.attributes.forecast.map(h => [new Date(h.start).getTime(), h.p90]);
```

### ApexCharts: i dag och i morgon

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Elpris SE3 i dag och i morgon
graph_span: 2d
span:
  start: day
now:
  show: true
series:
  - entity: sensor.spotprognos_se3_prognos
    type: column
    data_generator: |
      return [...entity.attributes.raw_today, ...entity.attributes.raw_tomorrow]
        .map(h => [new Date(h.start).getTime(), h.value]);
```

### Automation: ladda när det är billigast

Slår på laddboxen i början av dygnets billigaste tre timmar och av tre timmar senare.
Byt `switch.laddbox` mot din egen entitet.

```yaml
alias: Ladda bilen när elen är billigast
triggers:
  - trigger: time
    at: sensor.spotprognos_se3_billigaste_tre_timmar
conditions:
  - condition: state
    entity_id: binary_sensor.spotprognos_se3_forsamrad_korning
    state: "off"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.laddbox
  - delay: "03:00:00"
  - action: switch.turn_off
    target:
      entity_id: switch.laddbox
mode: single
```

Sensorn gäller kalenderdygnet, 00–24 svensk tid. Vill du ladda över natten, eller
planera efter bilens batterinivå och avresetid, är
[EV Smart Charging](https://github.com/jonasbkarlsson/ev_smart_charging) bättre: välj
`sensor.spotprognos_se3_prognos` som priskälla.

## Så fungerar det

- Integrationen hämtar `zones/SE?/forecast.json` och `longterm.json` var 30:e minut.
  Spotprognos skriver om filerna runt 06:30, 10:15, 13:30 och 18:00, och GitHub Pages
  cachar dem i upp till tio minuter.
- Timmen väljs med Home Assistants klocka, och sensorerna byter värde precis vid varje
  hel timme.
- Dygn räknas i svensk tid (`Europe/Stockholm`), eftersom elmarknadens dygn gör det.
- Diagnostik (under integrationens ⋮-meny) visar körningens `generated_at`, `run_id`,
  `degraded`, vald och faktisk modell samt växelkurs.

## Ansvarsfriskrivning

Spotpriset är Nord Pools day-ahead-pris för elområdet, **utan** elhandlarens påslag,
elcertifikat, energiskatt, nätavgift och moms, om du inte själv lagt till påslag och
moms. Det du betalar är högre.

Priser för timmar utan officiellt pris är **prognoser från en statistisk modell, inte
ett löfte**. De kan slå fel, ibland mycket. Använd `source` och intervallet p10–p90 när
du styr något som kostar pengar. Integrationen och Spotprognos lämnas som de är, utan
garantier. Den här integrationen är inte kopplad till Nord Pool, Home Assistant eller
någon elhandlare.

## Utveckling

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

Testerna går aldrig mot nätet. De använder riktiga filer från API:t, sparade i
`tests/fixtures/`. CI kör även `hassfest` och HACS-valideringen.

---

## English

Custom integration for Home Assistant with the electricity spot price and a seven-day
forecast for the Swedish price zones SE1–SE4, from the open
[Spotprognos](https://hakannormark.github.io/power-price-oracle/) API. No API key.

**Install:** HACS → ⋮ → Custom repositories → add
`https://github.com/hakannormark/spotprognos-ha` as an *Integration*, install
**Spotprognos**, restart, then **Settings → Devices & services → Add integration →
Spotprognos**. Requires Home Assistant 2026.9.1 or later.

**Configure** one entry per price zone: the model (following the Spotprognos default
model is recommended), the unit (öre/kWh or EUR/MWh), and optionally your supplier's
markup in öre/kWh and 25 % VAT. Everything except the zone can be changed later under
*Configure*.

**Entities** per zone: current price, next hour's price, lowest/average/highest price
today and tomorrow, the start of today's cheapest three consecutive hours, a forecast
sensor, next month's average price with the futures price, and a *degraded run* binary
sensor. The current price is the official price when published and the selected
model's forecast (p50) otherwise, with `source`, `p10` and `p90` as attributes.
Tomorrow's sensors stay unavailable until all of tomorrow's official prices are out.

The **forecast sensor** has `raw_today`, `raw_tomorrow`, `today`, `tomorrow` and
`tomorrow_valid` in the same format as the Nord Pool integration, so ApexCharts and EV
Smart Charging work with it directly, plus `forecast`: every coming hour for about a
week, with `value`, `p10`, `p90` and `source`. The lists are excluded from the recorder.

**Disclaimer:** the spot price excludes supplier markup, electricity certificates,
energy tax, grid fees and VAT unless you add markup and VAT yourself. Prices for hours
without an official price are forecasts from a statistical model, not a promise.
Provided as is, without warranty. Not affiliated with Nord Pool or Home Assistant.

## Licens / License

MIT, se [LICENSE](LICENSE).
