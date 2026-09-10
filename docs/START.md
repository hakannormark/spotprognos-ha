# Starta bygget med Claude Code

Öppna en terminal och starta Claude Code i repots mapp:

```bash
cd ~/Claude/spotprognos-ha
claude
```

Claude Code läser `CLAUDE.md` automatiskt. Klistra sedan in den här första prompten:

---

> Läs CLAUDE.md och fältreferensen på
> https://hakannormark.github.io/power-price-oracle/api.html, och hämta de riktiga
> JSON-filerna en gång för att se hur de ser ut. Bygg sedan integrationen enligt
> arbetsordningen i CLAUDE.md, ett steg i taget. Kör testerna efter varje steg,
> committa och pusha till main. Stanna och fråga mig bara om något kräver ett
> beslut som inte står i CLAUDE.md. Rapportera efter varje steg vad som är klart
> och vad som är verifierat.

---

## Efteråt: installera i Home Assistant

När `v0.1.0` är släppt:

1. HACS → ⋮ → **Custom repositories** → lägg till
   `https://github.com/hakannormark/spotprognos-ha`, kategori **Integration**.
2. Installera **Spotprognos** och starta om Home Assistant.
3. Inställningar → Enheter och tjänster → **Lägg till integration** → *Spotprognos*.
