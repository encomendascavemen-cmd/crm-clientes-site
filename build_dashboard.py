#!/usr/bin/env python3
"""Generates dashboard.html from dashboard_data.json"""

import json

with open("dashboard_data.json", encoding="utf-8") as f:
    data = json.load(f)

months      = data["months"]
stores      = ["Guimarães", "Braga", "Porto", "Online"]
colors      = {"Guimarães": "#3B82F6", "Braga": "#10B981", "Porto": "#F59E0B", "Online": "#8B5CF6"}
colors_soft = {"Guimarães": "rgba(59,130,246,0.15)", "Braga": "rgba(16,185,129,0.15)",
               "Porto": "rgba(245,158,11,0.15)", "Online": "rgba(139,92,246,0.15)"}

total_rev   = sum(data["store_totals"].values())
total_orders= sum(data["store_orders"].values())

# Month labels (Apr 2025 → Apr 2026)
def fmt_month(m):
    y, mo = m.split("-")
    names = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
    return f"{names[int(mo)-1]} {y}"

month_labels = [fmt_month(m) for m in months]

# Daily data
all_days = sorted(set(
    day for store in stores
    for day in data["daily_sales_30d"].get(store, {}).keys()
))
day_labels = [d[5:] for d in all_days]  # MM-DD

def js_array(lst):
    return json.dumps(lst)

def js_obj(d):
    return json.dumps(d, ensure_ascii=False)

monthly_datasets = []
for store in stores:
    vals = [round(data["monthly_revenue"][store].get(m, 0), 2) for m in months]
    monthly_datasets.append({
        "label": store,
        "data": vals,
        "borderColor": colors[store],
        "backgroundColor": colors_soft[store],
        "tension": 0.4,
        "fill": False,
        "pointRadius": 4,
        "pointHoverRadius": 6,
        "borderWidth": 2.5,
    })

daily_datasets = []
for store in stores:
    vals = [round(data["daily_sales_30d"].get(store, {}).get(d, 0), 2) for d in all_days]
    daily_datasets.append({
        "label": store,
        "data": vals,
        "backgroundColor": colors[store],
        "borderRadius": 3,
    })

top_products = data["top_products"][:15]

generated = data.get("generated_at", "")[:16].replace("T", " ")

html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cavemen Store · Dashboard de Vendas</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3e;
    --text: #e2e8f0;
    --muted: #8892a4;
    --accent-gm: #3B82F6;
    --accent-br: #10B981;
    --accent-pt: #F59E0B;
    --accent-on: #8B5CF6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }}
  header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 32px;
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }}
  .logo {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .logo-icon {{
    width: 40px; height: 40px;
    background: linear-gradient(135deg, #3B82F6, #8B5CF6);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
  }}
  .logo h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  .logo p {{ font-size: 12px; color: var(--muted); }}
  .meta {{ text-align: right; }}
  .meta .updated {{ font-size: 12px; color: var(--muted); }}
  .meta .period {{ font-size: 13px; font-weight: 600; margin-top: 2px; }}
  main {{ padding: 28px 32px; max-width: 1600px; margin: 0 auto; }}

  /* KPI CARDS */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
    position: relative;
    overflow: hidden;
  }}
  .kpi-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    border-radius: 14px 14px 0 0;
  }}
  .kpi-card.gm::before {{ background: var(--accent-gm); }}
  .kpi-card.br::before {{ background: var(--accent-br); }}
  .kpi-card.pt::before {{ background: var(--accent-pt); }}
  .kpi-card.on::before {{ background: var(--accent-on); }}
  .kpi-card.total::before {{ background: linear-gradient(90deg,#3B82F6,#8B5CF6); }}
  .kpi-label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .kpi-value {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; }}
  .kpi-sub {{ font-size: 12px; color: var(--muted); margin-top: 6px; }}
  .kpi-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    margin-top: 4px;
  }}

  /* CHARTS GRID */
  .charts-row {{
    display: grid;
    gap: 16px;
    margin-bottom: 24px;
  }}
  .charts-row-2 {{ grid-template-columns: 2fr 1fr; }}
  .charts-row-1 {{ grid-template-columns: 1fr; }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px;
  }}
  .chart-title {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 4px;
  }}
  .chart-subtitle {{
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 18px;
  }}
  .chart-wrap {{ position: relative; }}

  /* STORE BARS */
  .store-bars {{ margin-top: 16px; }}
  .store-bar-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
  }}
  .store-bar-label {{ width: 90px; font-size: 13px; flex-shrink: 0; }}
  .store-bar-track {{
    flex: 1;
    height: 10px;
    background: rgba(255,255,255,0.06);
    border-radius: 999px;
    overflow: hidden;
  }}
  .store-bar-fill {{
    height: 100%;
    border-radius: 999px;
    transition: width 0.6s ease;
  }}
  .store-bar-val {{ width: 80px; text-align: right; font-size: 13px; font-weight: 600; flex-shrink: 0; }}

  /* TABLE */
  .table-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 24px;
  }}
  .table-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    text-align: left;
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }}
  tbody tr:hover {{ background: rgba(255,255,255,0.02); }}
  tbody td {{
    padding: 11px 12px;
    font-size: 13px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }}
  .rank {{ color: var(--muted); width: 30px; }}
  .ref {{ font-family: monospace; font-size: 12px; color: var(--muted); }}
  .name {{ font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .rev-bar {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .rev-mini-bar {{
    flex: 1;
    height: 6px;
    background: rgba(255,255,255,0.06);
    border-radius: 999px;
    overflow: hidden;
    max-width: 120px;
  }}
  .rev-mini-fill {{
    height: 100%;
    background: linear-gradient(90deg, #3B82F6, #8B5CF6);
    border-radius: 999px;
  }}

  /* FOOTER */
  footer {{
    text-align: center;
    padding: 20px;
    color: var(--muted);
    font-size: 12px;
    border-top: 1px solid var(--border);
  }}

  @media (max-width: 1100px) {{
    .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-row-2 {{ grid-template-columns: 1fr; }}
  }}
  @media (max-width: 640px) {{
    main {{ padding: 16px; }}
    .kpi-grid {{ grid-template-columns: 1fr; }}
    header {{ padding: 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🪨</div>
    <div>
      <h1>Cavemen Store</h1>
      <p>Dashboard de Vendas · Moloni</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px;">
    <a href="products_report.html" style="text-decoration:none;color:#8892a4;font-size:13px;padding:6px 14px;border-radius:8px;border:1px solid #2a2d3e;">Relatório de Produtos →</a>
    <div class="meta">
      <div class="updated">Atualizado em {generated}</div>
      <div class="period">Últ. 12 meses · Todas as lojas</div>
    </div>
  </div>
</header>

<main>

  <!-- KPI CARDS -->
  <div class="kpi-grid">
    <div class="kpi-card total">
      <div class="kpi-label">Faturação Total</div>
      <div class="kpi-value">{total_rev:,.0f} €</div>
      <div class="kpi-sub">{total_orders:,} vendas · Média {total_rev/total_orders:.0f}€/venda</div>
    </div>
    <div class="kpi-card gm">
      <div class="kpi-label">Loja Guimarães</div>
      <div class="kpi-value">{data["store_totals"].get("Guimarães",0):,.0f} €</div>
      <div class="kpi-sub">{data["store_orders"].get("Guimarães",0):,} vendas · Ticket médio {data["store_avg_ticket"].get("Guimarães",0):.0f}€</div>
    </div>
    <div class="kpi-card br">
      <div class="kpi-label">Loja Braga</div>
      <div class="kpi-value">{data["store_totals"].get("Braga",0):,.0f} €</div>
      <div class="kpi-sub">{data["store_orders"].get("Braga",0):,} vendas · Ticket médio {data["store_avg_ticket"].get("Braga",0):.0f}€</div>
    </div>
    <div class="kpi-card pt">
      <div class="kpi-label">Loja Porto</div>
      <div class="kpi-value">{data["store_totals"].get("Porto",0):,.0f} €</div>
      <div class="kpi-sub">{data["store_orders"].get("Porto",0):,} vendas · Ticket médio {data["store_avg_ticket"].get("Porto",0):.0f}€</div>
    </div>
  </div>

  <!-- SECOND ROW KPI (Online + breakdown) -->
  <div class="kpi-grid" style="margin-bottom:24px;">
    <div class="kpi-card on">
      <div class="kpi-label">Loja Online</div>
      <div class="kpi-value">{data["store_totals"].get("Online",0):,.0f} €</div>
      <div class="kpi-sub">{data["store_orders"].get("Online",0):,} vendas · Ticket médio {data["store_avg_ticket"].get("Online",0):.0f}€</div>
    </div>
    <div class="kpi-card total" style="grid-column: span 3;">
      <div class="kpi-label">Quota de Faturação por Loja (últimos 12 meses)</div>
      <div class="store-bars">
        {"".join(f'''
        <div class="store-bar-row">
          <div class="store-bar-label">{store}</div>
          <div class="store-bar-track">
            <div class="store-bar-fill" style="width:{data["store_totals"].get(store,0)/total_rev*100:.1f}%;background:{colors[store]};"></div>
          </div>
          <div class="store-bar-val" style="color:{colors[store]};">{data["store_totals"].get(store,0)/total_rev*100:.1f}%</div>
        </div>
        ''' for store in stores)}
      </div>
    </div>
  </div>

  <!-- MONTHLY REVENUE CHART -->
  <div class="charts-row charts-row-1">
    <div class="chart-card">
      <div class="chart-title">Faturação Mensal por Loja</div>
      <div class="chart-subtitle">Últimos 12 meses (IVA incluído)</div>
      <div class="chart-wrap"><canvas id="monthlyChart" height="80"></canvas></div>
    </div>
  </div>

  <!-- DAILY + DONUT -->
  <div class="charts-row charts-row-2">
    <div class="chart-card">
      <div class="chart-title">Vendas Diárias · Últimos 30 Dias</div>
      <div class="chart-subtitle">Faturação por loja (barras empilhadas)</div>
      <div class="chart-wrap"><canvas id="dailyChart" height="110"></canvas></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Quota por Loja</div>
      <div class="chart-subtitle">% do total faturado</div>
      <div class="chart-wrap" style="max-height:280px;display:flex;align-items:center;justify-content:center;">
        <canvas id="donutChart" style="max-height:260px;max-width:260px;"></canvas>
      </div>
    </div>
  </div>

  <!-- MONTHLY ORDERS CHART -->
  <div class="charts-row charts-row-1">
    <div class="chart-card">
      <div class="chart-title">Número de Vendas por Loja</div>
      <div class="chart-subtitle">Quantidade de documentos emitidos por mês</div>
      <div class="chart-wrap"><canvas id="ordersChart" height="70"></canvas></div>
    </div>
  </div>

  <!-- TOP PRODUCTS TABLE -->
  <div class="table-card">
    <div class="table-header">
      <div>
        <div class="chart-title">Top Produtos · Últimos 30 Dias</div>
        <div class="chart-subtitle" style="margin-bottom:0;">Por faturação gerada (com detalhes de produto)</div>
      </div>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Referência</th>
          <th>Nome do Produto</th>
          <th style="text-align:right;">Qtd.</th>
          <th>Faturação</th>
          <th style="text-align:right;">Preço Médio</th>
        </tr>
      </thead>
      <tbody>
        {"".join(f'''
        <tr>
          <td class="rank">{i+1}</td>
          <td class="ref">{p.get("reference","")[:20]}</td>
          <td class="name">{p.get("name","")[:80]}</td>
          <td style="text-align:right;">{p.get("qty",0):.0f}</td>
          <td>
            <div class="rev-bar">
              <div class="rev-mini-bar">
                <div class="rev-mini-fill" style="width:{p.get("revenue",0)/top_products[0].get("revenue",1)*100:.1f}%;"></div>
              </div>
              <span style="font-weight:600;">{p.get("revenue",0):,.2f}€</span>
            </div>
          </td>
          <td style="text-align:right;">{p.get("revenue",0)/p.get("qty",1):,.2f}€</td>
        </tr>
        ''' for i, p in enumerate(top_products))}
      </tbody>
    </table>
  </div>

</main>

<footer>
  Cavemen Store · Dados extraídos via API Moloni · {generated}
</footer>

<script>
const COLORS = {js_obj(colors)};
const MONTHS = {js_array(month_labels)};
const DAYS   = {js_array(day_labels)};
const STORES = {js_array(stores)};

Chart.defaults.color = '#8892a4';
Chart.defaults.borderColor = '#2a2d3e';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

function fmtEur(v) {{
  return new Intl.NumberFormat('pt-PT', {{style:'currency',currency:'EUR',maximumFractionDigits:0}}).format(v);
}}

// ─── MONTHLY REVENUE ───────────────────────────────────────────
const monthlyDatasets = {js_obj(monthly_datasets)};
// Apply fill correctly (Chart.js 4)
monthlyDatasets.forEach(ds => {{ ds.fill = false; }});

new Chart(document.getElementById('monthlyChart'), {{
  type: 'line',
  data: {{ labels: MONTHS, datasets: monthlyDatasets }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'top', align: 'end', labels: {{ boxWidth: 12, padding: 16, font: {{ size: 12 }} }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: ${{fmtEur(ctx.parsed.y)}}`
        }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, ticks: {{ maxRotation: 0 }} }},
      y: {{
        grid: {{ color: 'rgba(255,255,255,0.04)' }},
        ticks: {{ callback: v => fmtEur(v) }}
      }}
    }}
  }}
}});

// ─── DAILY STACKED ─────────────────────────────────────────────
const dailyDatasets = {js_obj(daily_datasets)};

new Chart(document.getElementById('dailyChart'), {{
  type: 'bar',
  data: {{ labels: DAYS, datasets: dailyDatasets }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'top', align: 'end', labels: {{ boxWidth: 12, padding: 16, font: {{ size: 12 }} }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: ${{fmtEur(ctx.parsed.y)}}`,
          footer: items => ` Total: ${{fmtEur(items.reduce((a,b)=>a+b.parsed.y,0))}}`
        }}
      }}
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
      y: {{
        stacked: true,
        grid: {{ color: 'rgba(255,255,255,0.04)' }},
        ticks: {{ callback: v => fmtEur(v) }}
      }}
    }}
  }}
}});

// ─── DONUT ──────────────────────────────────────────────────────
const storeTotals = {js_obj({s: round(data["store_totals"].get(s,0),2) for s in stores})};

new Chart(document.getElementById('donutChart'), {{
  type: 'doughnut',
  data: {{
    labels: STORES,
    datasets: [{{
      data: STORES.map(s => storeTotals[s] || 0),
      backgroundColor: STORES.map(s => COLORS[s]),
      borderColor: '#1a1d27',
      borderWidth: 3,
      hoverOffset: 6,
    }}]
  }},
  options: {{
    responsive: true,
    cutout: '65%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ padding: 16, boxWidth: 12, font: {{ size: 12 }} }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.label}}: ${{fmtEur(ctx.parsed)}} (${{(ctx.parsed/Object.values(storeTotals).reduce((a,b)=>a+b,0)*100).toFixed(1)}}%)`
        }}
      }}
    }}
  }}
}});

// ─── MONTHLY ORDERS ─────────────────────────────────────────────
const ordersData = {js_obj({s: [data["monthly_orders"][s].get(m,0) for m in months] for s in stores})};

new Chart(document.getElementById('ordersChart'), {{
  type: 'bar',
  data: {{
    labels: MONTHS,
    datasets: STORES.map(s => ({{
      label: s,
      data: ordersData[s],
      backgroundColor: COLORS[s],
      borderRadius: 4,
    }}))
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'top', align: 'end', labels: {{ boxWidth: 12, padding: 16, font: {{ size: 12 }} }} }},
      tooltip: {{
        callbacks: {{
          footer: items => ` Total: ${{items.reduce((a,b)=>a+b.parsed.y,0)}} vendas`
        }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0 }} }},
      y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, beginAtZero: true }}
    }}
  }}
}});
</script>
</body>
</html>
"""

with open("dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)

print("✅ dashboard.html gerado com sucesso!")
