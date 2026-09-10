# Spotprognos för Home Assistant

Custom integration för [Home Assistant](https://www.home-assistant.io/) som skapar
sensorer med elpris och sjudygnsprognos för Nord Pools day-ahead-marknad i SE1–SE4,
från [Spotprognos](https://hakannormark.github.io/power-price-oracle/) öppna API.

**Status:** under uppbyggnad. Se [`CLAUDE.md`](CLAUDE.md) för specifikationen och
[`docs/START.md`](docs/START.md) för hur bygget startas.

Planerat:

- val av elområde, modell och enhet i gränssnittet
- aktuellt pris, nästa timme, dygnets lägsta, snitt och högsta, billigaste tre timmar
- prognoslistor i samma format som Nord Pool-integrationen, för grafer och laddstyrning
- nästa månads snittpris bredvid terminsmarknadens pris
- installation via HACS

Spotpriset är exklusive påslag, elcertifikat, energiskatt, nätavgift och moms. En
prognos är en modell, inte ett löfte.

## Licens

MIT, se [LICENSE](LICENSE).
