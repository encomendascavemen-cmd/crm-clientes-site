#!/usr/bin/env python3
"""Generates products_report.html from products_data.json"""

import json

with open("products_data.json", encoding="utf-8") as f:
    data = json.load(f)

products   = data["products"]
categories = data["categories"]
months     = data["months"]
stores     = ["Guimarães", "Braga", "Porto", "Online"]
colors     = {"Guimarães": "#3B82F6", "Braga": "#10B981", "Porto": "#F59E0B", "Online": "#8B5CF6"}
generated  = data.get("generated_at", "")[:16].replace("T", " ")
days       = data.get("days", 90)

NAMES = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
def fmt_m(m):
    y, mo = m.split("-")
    return f"{NAMES[int(mo)-1]} {y}"

month_labels = [fmt_m(m) for m in months]

def js(v):
    return json.dumps(v, ensure_ascii=False)

total_rev = data["total_revenue"]
top10     = products[:10]

# Monthly data for top 10 products
top10_monthly = []
for p in top10:
    vals = [p["by_month"].get(m, {}).get("revenue", 0) for m in months]
    top10_monthly.append({"label": p["reference"] or p["name"][:20], "data": vals})

# Category chart data
cat_labels  = [c["name"] for c in categories[:12]]
cat_revs    = [c["revenue"] for c in categories[:12]]
cat_palette = [
    "#3B82F6","#10B981","#F59E0B","#8B5CF6","#EF4444","#06B6D4",
    "#F97316","#84CC16","#EC4899","#6366F1","#14B8A6","#A78BFA"
]

# Store breakdown for top 10
store_datasets = []
for store in stores:
    vals = [p["by_store"].get(store, {}).get("revenue", 0) for p in top10]
    store_datasets.append({"label": store, "data": vals,
                            "backgroundColor": colors[store], "borderRadius": 4})

top10_labels = [p["reference"] or p["name"][:25] for p in top10]

# All products table rows
def table_rows(prods, limit=50):
    rows = []
    max_rev = prods[0]["revenue"] if prods else 1
    for i, p in enumerate(prods[:limit]):
        bar_pct = p["revenue"] / max_rev * 100
        store_pills = ""
        for store in stores:
            sv = p["by_store"].get(store, {}).get("revenue", 0)
            if sv > 0:
                pct = sv / p["revenue"] * 100
                store_pills += f'<span class="pill" style="background:{colors[store]}22;color:{colors[store]};">{store} {pct:.0f}%</span>'
        rows.append(f"""
        <tr>
          <td class="rank">{i+1}</td>
          <td class="ref">{p.get('reference','')[:20]}</td>
          <td class="name">{p.get('name','')[:70]}</td>
          <td><span class="cat-badge">{p.get('category_name','')[:22]}</span></td>
          <td style="text-align:right;">{p['qty']:.0f}</td>
          <td style="text-align:right;">{p['orders']}</td>
          <td>
            <div class="rev-bar">
              <div class="rev-mini-bar"><div class="rev-mini-fill" style="width:{bar_pct:.1f}%"></div></div>
              <span style="font-weight:600;white-space:nowrap;">{p['revenue']:,.2f}€</span>
            </div>
          </td>
          <td style="text-align:right;">{p['avg_price']:,.2f}€</td>
          <td>{store_pills}</td>
        </tr>""")
    return "\n".join(rows)

def build_js_products(prods, clrs):
    result = []
    for p in prods:
        store_keys = [s for s in p["by_store"].keys() if p["by_store"][s]["revenue"] > 0]
        pills = "".join(
            '<span class="pill" style="background:' + clrs[s] + '22;color:' + clrs[s] + ';">' + s + '</span>'
            for s in store_keys
        )
        row = (
            '<td class="rank">__RANK__</td>'
            + '<td class="ref">' + p.get("reference","")[:20] + '</td>'
            + '<td class="name">' + p.get("name","")[:70] + '</td>'
            + '<td><span class="cat-badge">' + p.get("category_name","")[:22] + '</span></td>'
            + '<td style="text-align:right;">' + str(int(p["qty"])) + '</td>'
            + '<td style="text-align:right;">' + str(p["orders"]) + '</td>'
            + '<td><div class="rev-bar"><div class="rev-mini-bar"><div class="rev-mini-fill" style="width:__BAR__%"></div></div>'
            + '<span style="font-weight:600;">' + "{:,.2f}€".format(p["revenue"]) + '</span></div></td>'
            + '<td style="text-align:right;">' + "{:,.2f}€".format(p["avg_price"]) + '</td>'
            + '<td>' + pills + '</td>'
        )
        result.append({
            "reference":     p["reference"],
            "name":          p["name"],
            "category_name": p["category_name"],
            "qty":           p["qty"],
            "orders":        p["orders"],
            "revenue":       p["revenue"],
            "avg_price":     p["avg_price"],
            "stores":        store_keys,
            "_row_html":     row,
        })
    return result


# Pre-compute strings that would need backslashes inside f-strings (Python 3.9 restriction)
cat_options = "".join(
    '<option value="' + c["name"] + '">' + c["name"] + ' (' + str(c["unique_products"]) + ')</option>'
    for c in categories
)

html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cavemen Store · Relatório de Produtos</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0f1117; --card:#1a1d27; --border:#2a2d3e; --text:#e2e8f0; --muted:#8892a4;
    --blue:#3B82F6; --green:#10B981; --amber:#F59E0B; --purple:#8B5CF6;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:14px; }}

  header {{ display:flex; align-items:center; justify-content:space-between; padding:18px 32px; border-bottom:1px solid var(--border); background:var(--card); }}
  .logo {{ display:flex; align-items:center; gap:12px; }}
  .logo-icon {{ width:38px; height:38px; background:linear-gradient(135deg,#3B82F6,#8B5CF6); border-radius:9px; display:flex; align-items:center; justify-content:center; font-size:18px; }}
  .logo h1 {{ font-size:17px; font-weight:700; }}
  .logo p {{ font-size:11px; color:var(--muted); }}
  .nav a {{ text-decoration:none; color:var(--muted); font-size:13px; padding:6px 14px; border-radius:8px; border:1px solid var(--border); margin-left:8px; }}
  .nav a:hover {{ color:var(--text); border-color:var(--blue); }}
  .meta {{ text-align:right; }}
  .meta .updated {{ font-size:11px; color:var(--muted); }}
  .meta .period {{ font-size:13px; font-weight:600; margin-top:2px; }}

  main {{ padding:26px 32px; max-width:1600px; margin:0 auto; }}

  /* KPIs */
  .kpi-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:22px; }}
  .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:13px; padding:18px 20px; position:relative; overflow:hidden; }}
  .kpi::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; border-radius:13px 13px 0 0; }}
  .kpi.k1::before {{ background:linear-gradient(90deg,#3B82F6,#8B5CF6); }}
  .kpi.k2::before {{ background:#10B981; }}
  .kpi.k3::before {{ background:#F59E0B; }}
  .kpi.k4::before {{ background:#8B5CF6; }}
  .kpi.k5::before {{ background:#EF4444; }}
  .kpi-label {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin-bottom:7px; }}
  .kpi-value {{ font-size:24px; font-weight:700; letter-spacing:-.5px; }}
  .kpi-sub {{ font-size:11px; color:var(--muted); margin-top:5px; }}

  /* Cards */
  .charts-row {{ display:grid; gap:16px; margin-bottom:22px; }}
  .row-2 {{ grid-template-columns:1.4fr 1fr; }}
  .row-3 {{ grid-template-columns:1fr 1fr 1fr; }}
  .row-1 {{ grid-template-columns:1fr; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:13px; padding:20px; }}
  .card-title {{ font-size:14px; font-weight:600; margin-bottom:3px; }}
  .card-sub {{ font-size:12px; color:var(--muted); margin-bottom:16px; }}

  /* Search + filter */
  .table-controls {{ display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap; }}
  .search-box {{
    flex:1; min-width:200px; max-width:340px;
    background:rgba(255,255,255,0.05); border:1px solid var(--border);
    color:var(--text); border-radius:9px; padding:8px 14px; font-size:13px;
    outline:none;
  }}
  .search-box:focus {{ border-color:var(--blue); }}
  .filter-select {{
    background:rgba(255,255,255,0.05); border:1px solid var(--border);
    color:var(--text); border-radius:9px; padding:8px 12px; font-size:13px;
    outline:none; cursor:pointer;
  }}
  .filter-select option {{ background:#1a1d27; }}
  .count-label {{ font-size:12px; color:var(--muted); margin-left:auto; }}

  /* Table */
  .table-wrap {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; min-width:900px; }}
  thead th {{
    text-align:left; font-size:11px; color:var(--muted); text-transform:uppercase;
    letter-spacing:.5px; padding:8px 10px; border-bottom:1px solid var(--border);
    cursor:pointer; user-select:none; white-space:nowrap;
  }}
  thead th:hover {{ color:var(--text); }}
  thead th.sort-asc::after {{ content:" ↑"; color:var(--blue); }}
  thead th.sort-desc::after {{ content:" ↓"; color:var(--blue); }}
  tbody tr {{ transition:background .15s; }}
  tbody tr:hover {{ background:rgba(255,255,255,0.025); }}
  tbody td {{ padding:10px 10px; font-size:13px; border-bottom:1px solid rgba(255,255,255,0.04); vertical-align:middle; }}
  .rank {{ color:var(--muted); width:28px; font-size:12px; }}
  .ref {{ font-family:monospace; font-size:11px; color:var(--muted); white-space:nowrap; }}
  .name {{ font-weight:500; max-width:240px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .cat-badge {{
    display:inline-block; padding:2px 8px; border-radius:20px;
    font-size:11px; background:rgba(99,102,241,0.15); color:#818CF8;
    white-space:nowrap;
  }}
  .pill {{
    display:inline-block; padding:2px 7px; border-radius:20px;
    font-size:11px; margin-right:3px; white-space:nowrap;
  }}
  .rev-bar {{ display:flex; align-items:center; gap:8px; }}
  .rev-mini-bar {{ flex:1; height:5px; background:rgba(255,255,255,0.07); border-radius:999px; overflow:hidden; max-width:80px; }}
  .rev-mini-fill {{ height:100%; background:linear-gradient(90deg,#3B82F6,#8B5CF6); border-radius:999px; }}

  footer {{ text-align:center; padding:18px; color:var(--muted); font-size:12px; border-top:1px solid var(--border); }}

  @media(max-width:1100px) {{
    .kpi-grid {{ grid-template-columns:repeat(3,1fr); }}
    .row-2,.row-3 {{ grid-template-columns:1fr; }}
  }}
  @media(max-width:640px) {{
    main {{ padding:14px; }}
    .kpi-grid {{ grid-template-columns:repeat(2,1fr); }}
    header {{ padding:14px; flex-wrap:wrap; gap:10px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🪨</div>
    <div>
      <h1>Cavemen Store · Relatório de Produtos</h1>
      <p>Últimos {days} dias · Dados Moloni</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px;">
    <nav class="nav">
      <a href="dashboard.html">← Dashboard Geral</a>
    </nav>
    <div class="meta">
      <div class="updated">Atualizado {generated}</div>
      <div class="period">{len(months)} meses de dados</div>
    </div>
  </div>
</header>

<main>

<!-- KPIs -->
<div class="kpi-grid">
  <div class="kpi k1">
    <div class="kpi-label">Faturação Total</div>
    <div class="kpi-value">{total_rev:,.0f} €</div>
    <div class="kpi-sub">Últimos {days} dias</div>
  </div>
  <div class="kpi k2">
    <div class="kpi-label">Produtos Únicos</div>
    <div class="kpi-value">{data['unique_products']}</div>
    <div class="kpi-sub">{len(categories)} categorias</div>
  </div>
  <div class="kpi k3">
    <div class="kpi-label">Unidades Vendidas</div>
    <div class="kpi-value">{data['total_qty']:,.0f}</div>
    <div class="kpi-sub">Qty total</div>
  </div>
  <div class="kpi k4">
    <div class="kpi-label">Top Categoria</div>
    <div class="kpi-value" style="font-size:16px;margin-top:4px;">{categories[0]['name'] if categories else '—'}</div>
    <div class="kpi-sub">{categories[0]['revenue']:,.0f}€ · {categories[0]['unique_products']} produtos</div>
  </div>
  <div class="kpi k5">
    <div class="kpi-label">Top Produto</div>
    <div class="kpi-value" style="font-size:15px;margin-top:4px;">{products[0]['reference'] if products else '—'}</div>
    <div class="kpi-sub">{products[0]['revenue']:,.0f}€ · {products[0]['qty']:.0f} unid.</div>
  </div>
</div>

<!-- Tendência mensal top 10 + Categorias donut -->
<div class="charts-row row-2">
  <div class="card">
    <div class="card-title">Tendência Mensal · Top 10 Produtos</div>
    <div class="card-sub">Faturação mensal por produto (linha)</div>
    <canvas id="trendChart" height="110"></canvas>
  </div>
  <div class="card">
    <div class="card-title">Faturação por Categoria</div>
    <div class="card-sub">Top 12 categorias</div>
    <div style="display:flex;align-items:center;justify-content:center;max-height:300px;">
      <canvas id="catChart" style="max-height:290px;max-width:290px;"></canvas>
    </div>
  </div>
</div>

<!-- Top 10 por loja + Categorias tabela -->
<div class="charts-row row-2">
  <div class="card">
    <div class="card-title">Top 10 Produtos · Revenue por Loja</div>
    <div class="card-sub">Barras empilhadas por loja</div>
    <canvas id="storeChart" height="100"></canvas>
  </div>
  <div class="card">
    <div class="card-title">Top Categorias</div>
    <div class="card-sub">Por faturação gerada</div>
    <div style="overflow-y:auto;max-height:300px;">
      <table style="min-width:unset;">
        <thead>
          <tr>
            <th>#</th>
            <th>Categoria</th>
            <th style="text-align:right;">Qtd.</th>
            <th style="text-align:right;">Produtos</th>
            <th>Faturação</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f'''<tr>
            <td class="rank">{i+1}</td>
            <td style="font-weight:500;">{c['name']}</td>
            <td style="text-align:right;">{c['qty']:.0f}</td>
            <td style="text-align:right;">{c['unique_products']}</td>
            <td><div class="rev-bar">
              <div class="rev-mini-bar"><div class="rev-mini-fill" style="width:{c['revenue']/categories[0]['revenue']*100:.1f}%"></div></div>
              <span style="font-weight:600;">{c['revenue']:,.0f}€</span>
            </div></td>
          </tr>''' for i,c in enumerate(categories[:15]))}
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- Full Products Table -->
<div class="card">
  <div class="card-title">Todos os Produtos</div>
  <div class="card-sub">Ordenável · Filtrável por categoria e loja</div>
  <div class="table-controls">
    <input class="search-box" id="searchInput" type="text" placeholder="Pesquisar por referência ou nome...">
    <select class="filter-select" id="catFilter" onchange="filterTable()">
      <option value="">Todas as categorias</option>
      {cat_options}
    </select>
    <select class="filter-select" id="storeFilter" onchange="filterTable()">
      <option value="">Todas as lojas</option>
      {"".join(f'<option value="{s}">{s}</option>' for s in stores)}
    </select>
    <span class="count-label" id="countLabel">{len(products)} produtos</span>
  </div>
  <div class="table-wrap">
    <table id="productsTable">
      <thead>
        <tr>
          <th class="rank-col">#</th>
          <th onclick="sortTable('reference')" data-col="reference">Referência</th>
          <th onclick="sortTable('name')" data-col="name">Produto</th>
          <th onclick="sortTable('category_name')" data-col="category_name">Categoria</th>
          <th onclick="sortTable('qty')" data-col="qty" style="text-align:right;">Qtd.</th>
          <th onclick="sortTable('orders')" data-col="orders" style="text-align:right;">Vendas</th>
          <th onclick="sortTable('revenue')" data-col="revenue" class="sort-desc">Faturação</th>
          <th onclick="sortTable('avg_price')" data-col="avg_price" style="text-align:right;">Preço Médio</th>
          <th>Lojas</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {table_rows(products, 200)}
      </tbody>
    </table>
  </div>
</div>

</main>

<footer>Cavemen Store · Relatório de Produtos · Dados Moloni · {generated}</footer>

<script>
Chart.defaults.color = '#8892a4';
Chart.defaults.borderColor = '#2a2d3e';
Chart.defaults.font.family = "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif";

const COLORS = {js(colors)};
const STORES = {js(stores)};
const MONTHS = {js(month_labels)};

function fmtEur(v) {{
  return new Intl.NumberFormat('pt-PT',{{style:'currency',currency:'EUR',maximumFractionDigits:0}}).format(v);
}}

// Trend palette (distinct colours)
const TREND_PALETTE = [
  '#3B82F6','#10B981','#F59E0B','#8B5CF6','#EF4444',
  '#06B6D4','#F97316','#84CC16','#EC4899','#6366F1'
];

// ─── TREND CHART ────────────────────────────────────────────────
const trendData = {js(top10_monthly)};
new Chart(document.getElementById('trendChart'), {{
  type: 'line',
  data: {{
    labels: MONTHS,
    datasets: trendData.map((d,i) => ({{
      ...d,
      borderColor: TREND_PALETTE[i % 10],
      backgroundColor: 'transparent',
      tension: 0.4, pointRadius: 3, borderWidth: 2,
    }}))
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position:'top', align:'end', labels:{{ boxWidth:10, padding:12, font:{{size:11}} }} }},
      tooltip: {{ callbacks: {{ label: c => ` ${{c.dataset.label}}: ${{fmtEur(c.parsed.y)}}` }} }}
    }},
    scales: {{
      x: {{ grid:{{color:'rgba(255,255,255,0.04)'}}, ticks:{{font:{{size:11}}}} }},
      y: {{ grid:{{color:'rgba(255,255,255,0.04)'}}, ticks:{{callback:v=>fmtEur(v)}} }}
    }}
  }}
}});

// ─── CATEGORY DONUT ─────────────────────────────────────────────
const catLabels = {js(cat_labels)};
const catRevs   = {js(cat_revs)};
const catColors = {js(cat_palette)};

new Chart(document.getElementById('catChart'), {{
  type: 'doughnut',
  data: {{
    labels: catLabels,
    datasets: [{{
      data: catRevs,
      backgroundColor: catColors,
      borderColor: '#1a1d27',
      borderWidth: 2,
      hoverOffset: 6,
    }}]
  }},
  options: {{
    responsive: true, cutout:'62%',
    plugins: {{
      legend: {{ position:'bottom', labels:{{ padding:10, boxWidth:10, font:{{size:11}} }} }},
      tooltip: {{
        callbacks: {{
          label: c => ` ${{c.label}}: ${{fmtEur(c.parsed)}} (${{(c.parsed/catRevs.reduce((a,b)=>a+b,0)*100).toFixed(1)}}%)`
        }}
      }}
    }}
  }}
}});

// ─── STORE BREAKDOWN BAR ────────────────────────────────────────
const storeDs = {js(store_datasets)};
const top10Labels = {js(top10_labels)};

new Chart(document.getElementById('storeChart'), {{
  type: 'bar',
  data: {{ labels: top10Labels, datasets: storeDs }},
  options: {{
    responsive: true,
    interaction: {{ mode:'index', intersect:false }},
    plugins: {{
      legend: {{ position:'top', align:'end', labels:{{ boxWidth:10, padding:12, font:{{size:11}} }} }},
      tooltip: {{
        callbacks: {{
          label: c => ` ${{c.dataset.label}}: ${{fmtEur(c.parsed.y)}}`,
          footer: items => ` Total: ${{fmtEur(items.reduce((a,b)=>a+b.parsed.y,0))}}`
        }}
      }}
    }},
    scales: {{
      x: {{ stacked:true, grid:{{display:false}}, ticks:{{font:{{size:10}},maxRotation:35}} }},
      y: {{ stacked:true, grid:{{color:'rgba(255,255,255,0.04)'}}, ticks:{{callback:v=>fmtEur(v)}} }}
    }}
  }}
}});

// ─── TABLE SEARCH / FILTER / SORT ───────────────────────────────
const ALL_PRODUCTS = {js(build_js_products(products[:100], colors))};

let sortCol = 'revenue', sortDir = -1;
let filtered = [...ALL_PRODUCTS];

function renderTable() {{
  const body = document.getElementById('tableBody');
  const maxRev = filtered.length ? Math.max(...filtered.map(p=>p.revenue)) : 1;
  body.innerHTML = filtered.map((p,i) => {{
    const bar = (p.revenue/maxRev*100).toFixed(1);
    const row = p._row_html.replace('__RANK__', i+1).replace('__BAR__', bar);
    return `<tr>${{row}}</tr>`;
  }}).join('');
  document.getElementById('countLabel').textContent = `${{filtered.length}} produtos`;
}}

function filterTable() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  const cat = document.getElementById('catFilter').value;
  const store = document.getElementById('storeFilter').value;
  filtered = ALL_PRODUCTS.filter(p => {{
    const matchQ = !q || p.reference.toLowerCase().includes(q) || p.name.toLowerCase().includes(q);
    const matchCat = !cat || p.category_name === cat;
    const matchStore = !store || p.stores.includes(store);
    return matchQ && matchCat && matchStore;
  }});
  filtered.sort((a,b) => sortDir * (b[sortCol] > a[sortCol] ? 1 : -1));
  renderTable();
}}

document.getElementById('searchInput').addEventListener('input', filterTable);

function sortTable(col) {{
  if (sortCol === col) sortDir *= -1;
  else {{ sortCol = col; sortDir = -1; }}
  document.querySelectorAll('thead th').forEach(th => {{
    th.classList.remove('sort-asc','sort-desc');
    if (th.dataset.col === col) th.classList.add(sortDir === -1 ? 'sort-desc' : 'sort-asc');
  }});
  filterTable();
}}
</script>
</body>
</html>
"""

with open("products_report.html", "w", encoding="utf-8") as f:
    f.write(html)

print("✅ products_report.html gerado!")
