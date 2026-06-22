# Benchmark Portales Inmobiliarios — México

Benchmark automático de precios para agentes/inmobiliarias en portales mexicanos.

**Portales monitoreados:** Proppit · Inmuebles24 · Propiedades.com

## Cómo funciona

1. GitHub Actions corre `scraper.py` el primer día de cada mes
2. El script descarga las páginas de pricing de cada portal
3. Claude API extrae los planes y precios de forma estructurada
4. Los resultados se guardan en `data.json` y se regenera `index.html`
5. GitHub Pages publica el `index.html` automáticamente

## Setup inicial

### 1. Añadir la API key de Anthropic

En el repo → **Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: tu API key de Anthropic

### 2. Activar GitHub Pages

En el repo → **Settings → Pages**

- Source: `Deploy from a branch`
- Branch: `main` / `(root)`

### 3. Ejecutar manualmente la primera vez

En el repo → **Actions → Update Benchmark → Run workflow**

## Estructura

```
├── index.html          # Web del benchmark (generada automáticamente)
├── data.json           # Datos crudos en JSON (generado automáticamente)
├── scraper.py          # Script de scraping + extracción con Claude
└── .github/
    └── workflows/
        └── update-benchmark.yml  # Schedule mensual
```

## Añadir un portal nuevo

En `scraper.py`, añadir al array `PORTALS`:

```python
{
    "id": "nuevo_portal",
    "name": "Nombre Portal",
    "url": "https://url-de-pricing.com",
    "color": "#hexcolor",
},
```

## Ejecutar localmente

```bash
pip install requests beautifulsoup4 anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python scraper.py
```
