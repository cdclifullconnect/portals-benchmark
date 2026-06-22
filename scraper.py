"""
Benchmark scraper — Portales Inmobiliarios MX
Corre mensualmente via GitHub Actions.
Extrae datos de pricing con Claude API y actualiza data.json + index.html.
"""

import json
import os
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import anthropic

# ── Configuración ──────────────────────────────────────────────────────────────

PORTALS = [
    {
        "id": "proppit",
        "name": "Proppit",
        "url": "https://proppit.com/?country=mx",
        "color": "#6ee7b7",
    },
    {
        "id": "inmuebles24",
        "name": "Inmuebles24",
        "url": "https://www.inmuebles24.com/noticias/noticias/venta/abc-anuncios/",
        "color": "#60a5fa",
    },
    {
        "id": "propiedades",
        "name": "Propiedades.com",
        "url": "https://propiedades.com/publicar",
        "color": "#f9a8d4",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9",
}

# ── Scraping ────────────────────────────────────────────────────────────────────

def fetch_text(url: str) -> str:
    """Descarga una página y devuelve su texto limpio."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Eliminar scripts, estilos y nav para reducir ruido
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:8000]
    except Exception as e:
        print(f"  ⚠ Error fetching {url}: {e}")
        return ""


# ── Extracción con Claude ───────────────────────────────────────────────────────

EXTRACT_PROMPT = """Eres un analista de precios. Analiza el texto de la página de pricing de este portal inmobiliario mexicano y extrae TODOS los planes disponibles para profesionales (agentes/inmobiliarias).

Portal: {portal_name}
URL: {url}

Texto de la página:
{text}

Responde ÚNICAMENTE con un JSON válido con esta estructura (sin texto adicional, sin markdown):
{{
  "portal_id": "{portal_id}",
  "portal_name": "{portal_name}",
  "scraped_at": "{date}",
  "model": "descripción de 1 línea del modelo de negocio",
  "plans": [
    {{
      "name": "nombre del plan",
      "properties": número o null,
      "featured_included": número o null,
      "price_monthly": número o null,
      "price_quarterly": número o null,
      "price_includes_vat": true/false,
      "duration_days": número o null,
      "auto_renewal": true/false,
      "notes": "notas adicionales o null"
    }}
  ],
  "base_free": true/false,
  "notes": "notas generales del portal"
}}

Si no encuentras información de precios, devuelve plans: [] y explica en notes."""


def extract_plans(portal: dict, text: str, client: anthropic.Anthropic) -> dict:
    """Usa Claude para extraer planes estructurados del texto."""
    if not text:
        return {"portal_id": portal["id"], "portal_name": portal["name"], "plans": [], "error": "No se pudo obtener el contenido"}

    prompt = EXTRACT_PROMPT.format(
        portal_name=portal["name"],
        portal_id=portal["id"],
        url=portal["url"],
        text=text,
        date=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Limpiar posibles ```json fences
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parse error for {portal['name']}: {e}")
        return {"portal_id": portal["id"], "portal_name": portal["name"], "plans": [], "error": str(e)}


# ── Generación de HTML ──────────────────────────────────────────────────────────

def format_price(price, includes_vat: bool) -> str:
    if price is None:
        return '<span class="na-cell">No disponible</span>'
    label = "c/IVA" if includes_vat else "+ IVA"
    return f'<div class="price">${price:,.0f}</div><div class="price-note">{label}</div>'


def build_html(all_data: list) -> str:
    """Genera el HTML completo a partir de los datos extraídos."""
    updated = datetime.utcnow().strftime("%B %Y")

    # Cards de portales
    portal_cards = ""
    for d in all_data:
        pid = d.get("portal_id", "")
        color_map = {"proppit": "#6ee7b7", "inmuebles24": "#60a5fa", "propiedades": "#f9a8d4"}
        color = color_map.get(pid, "#aaa")
        plan_count = len(d.get("plans", []))
        model_text = d.get("model", "—")
        portal_cards += f"""
      <div class="portal-card {pid}">
        <div class="portal-name">{d.get('portal_name','')}</div>
        <div class="portal-stat"><div class="stat-label">Modelo</div><div class="stat-value">{model_text}</div></div>
        <div class="portal-stat" style="margin-top:10px;"><div class="stat-label">Planes encontrados</div>
        <div class="stat-value" style="color:{color};">{plan_count} planes</div></div>
        <div style="margin-top:10px;"><span class="badge badge-verified">✓ Actualizado {updated}</span></div>
      </div>"""

    # Tablas por portal
    tables_html = ""
    for d in all_data:
        pid = d.get("portal_id", "")
        name = d.get("portal_name", "")
        plans = d.get("plans", [])
        notes = d.get("notes", "")

        if not plans:
            tables_html += f'<div class="section-label">{name}</div><p style="color:var(--muted);font-size:12px;margin-bottom:32px;">{notes or "Sin datos disponibles."}</p>'
            continue

        has_quarterly = any(p.get("price_quarterly") for p in plans)
        rows = ""
        for p in plans:
            props = p.get("properties")
            props_str = str(props) if props is not None else "—"
            feat = p.get("featured_included")
            feat_str = str(feat) if feat is not None else "—"
            monthly = format_price(p.get("price_monthly"), p.get("price_includes_vat", False))
            quarterly = format_price(p.get("price_quarterly"), p.get("price_includes_vat", False)) if has_quarterly else ""
            plan_notes = p.get("notes") or ""
            duration = f'{p.get("duration_days", 30)} días' if p.get("duration_days") else "30 días"
            renewal = "Auto." if p.get("auto_renewal") else "Manual"

            rows += f"""<tr>
              <td><div class="plan-name">{p.get('name','')}</div><div class="plan-desc">{plan_notes}</div></td>
              <td><span class="n-props">{props_str}</span></td>
              <td>{feat_str}</td>
              <td>{duration} · {renewal}</td>
              <td>{monthly}</td>
              {"<td>" + quarterly + "</td>" if has_quarterly else ""}
            </tr>"""

        quarterly_th = '<th>Trimestral</th>' if has_quarterly else ''
        tables_html += f"""
      <div class="section-label">{name} — Planes para profesionales</div>
      <div class="table-wrapper" style="margin-bottom:32px;">
        <table>
          <thead><tr>
            <th>Plan</th><th>Propiedades</th><th>Destacados</th><th>Duración</th><th class="portal-col {pid}">Precio mensual</th>{quarterly_th}
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>"""

    # Notas
    notes_html = ""
    for d in all_data:
        if d.get("notes"):
            notes_html += f'<div class="note-item"><strong>{d["portal_name"]}</strong> — {d["notes"]}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Benchmark Precios — Portales Inmobiliarios MX</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
    :root {{
      --bg:#0f0f11;--surface:#18181c;--surface2:#1f1f25;--border:#2a2a32;
      --text:#e8e8f0;--muted:#6b6b80;--accent:#7c6af7;--accent-soft:rgba(124,106,247,.12);
      --green:#4ade80;--yellow:#fbbf24;
      --proppit:#6ee7b7;--inmuebles:#60a5fa;--propiedades:#f9a8d4;
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:14px;padding:48px 24px}}
    .container{{max-width:1140px;margin:0 auto}}
    header{{margin-bottom:48px}}
    .eyebrow{{font-family:'DM Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}}
    h1{{font-size:32px;font-weight:700;letter-spacing:-.02em;line-height:1.2;margin-bottom:8px}}
    h1 span{{color:var(--muted);font-weight:300}}
    .meta{{font-size:12px;color:var(--muted);font-family:'DM Mono',monospace;display:flex;gap:24px;margin-top:16px;flex-wrap:wrap}}
    .meta-item{{display:flex;align-items:center;gap:6px}}
    .dot{{width:6px;height:6px;border-radius:50%;background:var(--accent)}}
    .section-label{{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)}}
    .portals-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:48px}}
    .portal-card{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;position:relative;overflow:hidden}}
    .portal-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px}}
    .portal-card.proppit::before{{background:var(--proppit)}}
    .portal-card.inmuebles24::before{{background:var(--inmuebles)}}
    .portal-card.propiedades::before{{background:var(--propiedades)}}
    .portal-name{{font-size:13px;font-weight:600;margin-bottom:4px}}
    .portal-stat{{margin-top:8px}}
    .stat-label{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:2px}}
    .stat-value{{font-size:13px;font-weight:500}}
    .badge{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:20px;font-weight:500}}
    .badge-verified{{background:rgba(74,222,128,.12);color:var(--green)}}
    .table-wrapper{{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:48px}}
    table{{width:100%;border-collapse:collapse}}
    thead tr{{background:var(--surface2)}}
    th{{padding:14px 20px;text-align:left;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)}}
    th.portal-col{{font-size:12px;font-weight:600;text-transform:none;letter-spacing:0}}
    th.portal-col.proppit{{color:var(--proppit)}}
    th.portal-col.inmuebles24{{color:var(--inmuebles)}}
    th.portal-col.propiedades{{color:var(--propiedades)}}
    td{{padding:14px 20px;border-bottom:1px solid var(--border);vertical-align:top;line-height:1.5}}
    tr:last-child td{{border-bottom:none}}
    tr:hover td{{background:rgba(124,106,247,.03)}}
    .plan-name{{font-weight:600;font-size:13px;margin-bottom:2px}}
    .plan-desc{{font-size:11px;color:var(--muted)}}
    .price{{font-family:'DM Mono',monospace;font-size:16px;font-weight:500}}
    .price-note{{font-size:10px;color:var(--muted);margin-top:2px}}
    .n-props{{font-family:'DM Mono',monospace;font-weight:500}}
    .na-cell{{color:var(--muted);font-size:11px;font-style:italic}}
    .notes{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:32px}}
    .notes-title{{font-size:12px;font-weight:600;margin-bottom:12px}}
    .note-item{{display:flex;gap:10px;margin-bottom:8px;font-size:12px;color:var(--muted);line-height:1.5}}
    .note-item::before{{content:'—';color:var(--border);flex-shrink:0}}
    .note-item strong{{color:var(--text)}}
    footer{{display:flex;justify-content:space-between;align-items:center;padding-top:24px;border-top:1px solid var(--border);font-size:11px;color:var(--muted);font-family:'DM Mono',monospace;flex-wrap:wrap;gap:8px}}
    @media(max-width:768px){{.portals-grid{{grid-template-columns:1fr}}h1{{font-size:22px}}td,th{{padding:10px 12px}}}}
  </style>
</head>
<body>
<div class="container">
  <header>
    <div class="eyebrow">Benchmark competitivo · México</div>
    <h1>Precios de portales inmobiliarios <span>para profesionales</span></h1>
    <div class="meta">
      <div class="meta-item"><div class="dot"></div> Última actualización: {updated}</div>
      <div class="meta-item"><div class="dot" style="background:var(--green)"></div> Actualización automática mensual</div>
      <div class="meta-item"><div class="dot" style="background:var(--muted)"></div> Mercado: México</div>
    </div>
  </header>

  <div class="section-label">Portales analizados</div>
  <div class="portals-grid">{portal_cards}</div>

  {tables_html}

  <div class="notes">
    <div class="notes-title">Fuentes y notas metodológicas</div>
    {notes_html}
    <div class="note-item"><strong>Metodología</strong> — Datos extraídos automáticamente cada mes via GitHub Actions + Claude API. Los precios pueden variar; verificar directamente en cada portal antes de tomar decisiones comerciales.</div>
  </div>

  <footer>
    <div>benchmark-mx · proppit · inmuebles24 · propiedades.com</div>
    <div>generado automáticamente · {updated}</div>
  </footer>
</div>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY no está configurada")

    client = anthropic.Anthropic(api_key=api_key)
    all_data = []

    for portal in PORTALS:
        print(f"\n→ Procesando {portal['name']}...")
        text = fetch_text(portal["url"])
        print(f"  {len(text)} caracteres obtenidos")
        data = extract_plans(portal, text, client)
        print(f"  {len(data.get('plans', []))} planes extraídos")
        all_data.append(data)

    # Guardar datos crudos
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print("\n✓ data.json guardado")

    # Regenerar HTML
    html = build_html(all_data)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✓ index.html regenerado")


if __name__ == "__main__":
    main()
