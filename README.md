# Crawler ojetých aut (odděleně od aplikace)

Tato složka obsahuje samostatný crawler pro sběr reálných inzerátů z TipCars.

## Spuštění

V terminálu ve složce `crawler` spusť:

```bat
python -m pip install -r ..pp
equirements.txt
python crawler_tipcars.py --seeds seeds.txt --output-csv datautos_raw.csv --output-json datautos_raw.json --max-pages-per-seed 15
```

## Výstup

Crawler uloží data do:
- `crawler/data/autos_raw.csv`
- `crawler/data/autos_raw.json`

Potom zkopíruj `autos_raw.csv` do `app/data/autos_raw.csv` a pokračuj trénováním modelu v aplikaci.
