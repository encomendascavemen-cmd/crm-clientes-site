#!/usr/bin/env python3
"""
Integrates relatorio_genero.html as a "Dados Demográficos" tab into relatorio_magento.html.
"""

import re

MAGENTO = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_magento.html"
GENERO  = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_genero.html"
OUT1    = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_magento.html"
OUT2    = "/Users/pedrovieira/Desktop/relatorio_produtos_cavemen.html"

# ── Read source files ──────────────────────────────────────────────────────────
with open(MAGENTO, "r", encoding="utf-8") as f:
    magento = f.read()

with open(GENERO, "r", encoding="utf-8") as f:
    genero = f.read()

print(f"Magento: {len(magento):,} chars")
print(f"Genero:  {len(genero):,} chars")

# ── Extract gender report sections ────────────────────────────────────────────
# CSS: everything between <style> and </style>
css_match = re.search(r'<style>(.*?)</style>', genero, re.DOTALL)
if not css_match:
    raise ValueError("Could not find <style> block in gender report")
gender_css_raw = css_match.group(1)
print(f"Gender CSS extracted: {len(gender_css_raw):,} chars")

# Body content: between </header> and <footer>
body_match = re.search(r'</header>(.*?)<footer', genero, re.DOTALL)
if not body_match:
    raise ValueError("Could not find body content in gender report")
gender_body_raw = body_match.group(1).strip()
print(f"Gender body extracted: {len(gender_body_raw):,} chars")

# JavaScript: between <script> (after footer) and </script>
script_match = re.search(r'<footer>.*?</footer>\s*<script>(.*?)</script>', genero, re.DOTALL)
if not script_match:
    raise ValueError("Could not find <script> block in gender report")
gender_js_raw = script_match.group(1)
print(f"Gender JS extracted: {len(gender_js_raw):,} chars")

# ── Scope gender CSS with #tab-demograficos prefix ───────────────────────────
def scope_css(css_text, prefix):
    """Prefix all CSS selectors with the given prefix, preserving @media blocks."""
    result = []
    i = 0
    n = len(css_text)

    while i < n:
        if css_text[i].isspace():
            result.append(css_text[i])
            i += 1
            continue

        if css_text[i:i+2] == '/*':
            end = css_text.find('*/', i+2)
            if end == -1:
                end = n - 2
            result.append(css_text[i:end+2])
            i = end + 2
            continue

        if css_text[i] == '@':
            brace_open = css_text.find('{', i)
            if brace_open == -1:
                result.append(css_text[i:])
                break
            at_header = css_text[i:brace_open+1]
            result.append(at_header)
            i = brace_open + 1
            depth = 1
            inner_start = i
            while i < n and depth > 0:
                if css_text[i] == '{':
                    depth += 1
                elif css_text[i] == '}':
                    depth -= 1
                i += 1
            inner_content = css_text[inner_start:i-1]
            scoped_inner = scope_css(inner_content, prefix)
            result.append(scoped_inner)
            result.append('}')
            continue

        brace_open = css_text.find('{', i)
        if brace_open == -1:
            result.append(css_text[i:])
            break

        selector = css_text[i:brace_open]

        brace_close = css_text.find('}', brace_open)
        if brace_close == -1:
            result.append(css_text[i:])
            break

        declaration = css_text[brace_open:brace_close+1]

        sel_stripped = selector.strip()
        if sel_stripped not in ('*', 'body', 'html') and not sel_stripped.startswith('body') and not sel_stripped.startswith('html'):
            parts = sel_stripped.split(',')
            prefixed_parts = []
            for part in parts:
                p = part.strip()
                if p:
                    prefixed_parts.append(f'{prefix} {p}')
            if prefixed_parts:
                result.append(', '.join(prefixed_parts))
                result.append(declaration)
                result.append('\n')

        i = brace_close + 1

    return ''.join(result)

gender_css_scoped = scope_css(gender_css_raw, '#tab-demograficos')
print(f"Scoped CSS length: {len(gender_css_scoped):,} chars")

# ── Prefix IDs in gender body HTML ───────────────────────────────────────────
DEMO_IDS = [
    'aFrom', 'aTo', 'bFrom', 'bTo', 'chkB', 'vsSep', 'periodBWrap', 'btnApply',
    'kpis', 'kpiTitle', 'headerSub', 'chartMonthly', 'chartMonthlyTitle',
    'chartPie', 'chartTicket', 'chartCities', 'chartSearch',
    'tbMale', 'tbFemale', 'tbSplit', 'tbCities', 'tbSearch'
]

def prefix_ids_in_html(html, ids, prefix='demo-'):
    for id_name in ids:
        html = re.sub(
            rf'\bid="({re.escape(id_name)})"',
            lambda m, p=prefix, n=id_name: f'id="{p}{n}"',
            html
        )
    return html

gender_body = prefix_ids_in_html(gender_body_raw, DEMO_IDS)
print(f"Body after ID prefixing: {len(gender_body):,} chars")

# ── Process gender JavaScript ─────────────────────────────────────────────────
gender_js = gender_js_raw

# 1. Replace getElementById references for known IDs
for id_name in DEMO_IDS:
    gender_js = re.sub(
        rf"getElementById\(['\"]({re.escape(id_name)})['\"]",
        lambda m, n=id_name: f"getElementById('demo-{n}'",
        gender_js
    )

# 2. Rename function 'render' to 'demoRender'
gender_js = re.sub(r'\brender\b', 'demoRender', gender_js)

# 3. Rename DATA variable to DEMO_DATA
gender_js = re.sub(r'\bDATA\b', 'DEMO_DATA', gender_js)

# 4. Rename 'charts' variable to 'demoCharts'
gender_js = re.sub(r'\bcharts\b', 'demoCharts', gender_js)

# ── Extract and wrap in initDemo() ───────────────────────────────────────────
# The gender JS structure:
# 1. const DATA = {...};          <- large JSON data block
# 2. function monthsInRange ...   <- utility functions
# 3. function demoRender ...      <- main render function
# 4. function delta ...           <- helper functions
# 5. function render* ...         <- render functions
# 6. (function initDates(){...})(); <- IIFE setting default dates
# 7. document.getElementById('chkB').addEventListener(...)  <- event listeners
# 8. document.getElementById('btnApply').addEventListener(...)
# 9. // Initial render
# 10. demoRender();

# Find the DEMO_DATA block (it's the first const)
data_match = re.search(r'^(const DEMO_DATA\s*=\s*\{)', gender_js, re.MULTILINE)
if not data_match:
    raise ValueError("Could not find DEMO_DATA in JS")

# Find the end of the JSON object (matching brace)
data_start = data_match.start()
# The DATA object ends with "};" - find it by counting braces
brace_depth = 0
data_end = data_start
in_data = False
for idx in range(data_start, len(gender_js)):
    c = gender_js[idx]
    if c == '{':
        brace_depth += 1
        in_data = True
    elif c == '}':
        brace_depth -= 1
        if in_data and brace_depth == 0:
            data_end = idx + 1
            # Skip the semicolon
            if data_end < len(gender_js) and gender_js[data_end] == ';':
                data_end += 1
            break

data_section = gender_js[data_start:data_end]
print(f"Data section length: {len(data_section):,} chars")

# Everything after the data section
rest_js = gender_js[data_end:].strip()

# Now find the initialization code: starts with the IIFE (function initDates...
# and ends with demoRender();
# The IIFE pattern: (function initDates(){
iife_pos = rest_js.find('(function initDates()')
if iife_pos == -1:
    raise ValueError("Could not find initDates IIFE in JS")

# Functions-only section (all function definitions before initDates)
functions_only = rest_js[:iife_pos].strip()
print(f"Functions-only JS: {len(functions_only):,} chars")

# Init code: from (function initDates(){ to end
init_code_raw = rest_js[iife_pos:].strip()
# Remove trailing whitespace/newlines
init_code_raw = init_code_raw.rstrip()
print(f"Init code raw length: {len(init_code_raw):,} chars")

# ── Build the complete initDemo() wrapper ─────────────────────────────────────
init_demo_js = f"""
// ── Demographics Tab ──────────────────────────────────────────────────────────
{data_section}

// ── Demographics helper functions ─────────────────────────────────────────────
{functions_only}

// ── Initialize demographics tab (called on first tab click) ──────────────────
function initDemo() {{
  if (window._demoReady) return;
  window._demoReady = true;

  // Set default dates
  {init_code_raw}
}}
"""

print(f"initDemo JS length: {len(init_demo_js):,} chars")

# ── Tab navigation CSS ────────────────────────────────────────────────────────
TAB_NAV_CSS = """
/* Tab navigation */
.tab-nav{display:flex;background:#1a1a1a;border-bottom:2px solid #2a2a2a;padding:0 36px}
.tab-btn{padding:14px 24px;background:none;border:none;color:#777;font-size:.9rem;font-weight:600;cursor:pointer;letter-spacing:.5px;border-bottom:2px solid transparent;margin-bottom:-2px;transition:color .2s,border-color .2s}
.tab-btn:hover{color:#c8a96e}
.tab-btn.active{color:#c8a96e;border-bottom-color:#c8a96e}
.tab-panel{display:none}
.tab-panel.active{display:block}
"""

# ── Tab switching JS ──────────────────────────────────────────────────────────
TAB_SWITCH_JS = """
function switchTab(tab) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  event.target.classList.add('active');
  if (tab === 'demograficos' && !window._demoReady) {
    initDemo();
  }
}
"""

# ── Tab nav HTML ──────────────────────────────────────────────────────────────
TAB_NAV_HTML = """<nav class="tab-nav">
  <button class="tab-btn active" onclick="switchTab('produtos')">📦 Relatório de Produtos</button>
  <button class="tab-btn" onclick="switchTab('demograficos')">👥 Dados Demográficos</button>
</nav>"""

# ── Modify magento HTML ───────────────────────────────────────────────────────
result = magento

# A) Add tab nav CSS and scoped demographic CSS before </style>
style_insert = TAB_NAV_CSS + "\n" + gender_css_scoped + "\n"
result = result.replace('</style>', style_insert + '</style>', 1)
print(f"After CSS insert: {len(result):,} chars")

# B) Insert tab nav HTML after </header>
result = result.replace('</header>', '</header>\n' + TAB_NAV_HTML, 1)
print(f"After tab nav HTML: {len(result):,} chars")

# C) Find the content to wrap: from <!-- ── FILTROS ── --> to </footer>
filters_comment = '<!-- ── FILTROS ── -->'
footer_tag_start = '<footer>Cavemen Store'

filters_pos = result.find(filters_comment)
footer_pos = result.find(footer_tag_start)

if filters_pos == -1:
    raise ValueError("Could not find '<!-- ── FILTROS ── -->' in magento HTML")
if footer_pos == -1:
    raise ValueError("Could not find footer in magento HTML")

footer_end_pos = result.find('</footer>', footer_pos) + len('</footer>')

existing_content = result[filters_pos:footer_end_pos]
print(f"Existing products content to wrap: {len(existing_content):,} chars")

# Build wrapped products tab + demographics tab
demographics_panel = f'<div id="tab-demograficos" class="tab-panel">\n{gender_body}\n</div>'
wrapped_content = (
    f'<div id="tab-produtos" class="tab-panel active">\n'
    f'{existing_content}\n'
    f'</div>\n\n'
    f'{demographics_panel}'
)

result = result[:filters_pos] + wrapped_content + result[footer_end_pos:]
print(f"After content wrapping: {len(result):,} chars")

# D) Add demographics JS and tab switch JS before the final </script>
last_script_pos = result.rfind('</script>')
if last_script_pos == -1:
    raise ValueError("Could not find closing </script> in magento HTML")

js_insert = TAB_SWITCH_JS + "\n" + init_demo_js + "\n"
result = result[:last_script_pos] + js_insert + result[last_script_pos:]
print(f"After JS insert: {len(result):,} chars")

# ── Write output files ────────────────────────────────────────────────────────
with open(OUT1, "w", encoding="utf-8") as f:
    f.write(result)
print(f"\nWritten to: {OUT1}")
print(f"File size: {len(result):,} chars")

with open(OUT2, "w", encoding="utf-8") as f:
    f.write(result)
print(f"Written to: {OUT2}")

# ── Validation ────────────────────────────────────────────────────────────────
print("\n── Validation ──────────────────────────────────────────────────────────")
checks = [
    ('tab-nav present', 'class="tab-nav"' in result),
    ('tab-produtos panel', 'id="tab-produtos"' in result),
    ('tab-demograficos panel', 'id="tab-demograficos"' in result),
    ('tab-btn active class', 'tab-btn active' in result),
    ('switchTab function', 'function switchTab' in result),
    ('initDemo function', 'function initDemo' in result),
    ('DEMO_DATA present', 'const DEMO_DATA' in result),
    ('demo- prefixed IDs in HTML (aFrom)', 'id="demo-aFrom"' in result),
    ('demo- prefixed IDs in HTML (btnApply)', 'id="demo-btnApply"' in result),
    ('demo- prefixed IDs in JS (aFrom)', "getElementById('demo-aFrom')" in result),
    ('demo- prefixed IDs in JS (chkB)', "getElementById('demo-chkB')" in result),
    ('demoRender function defined', 'function demoRender()' in result),
    ('demoCharts variable', 'let demoCharts' in result),
    ('No Chart.js CDN in output', 'cdnjs.cloudflare.com/ajax/libs/Chart.js' not in result),
    ('Original initCharts call preserved', 'initCharts()' in result),
    ('Original applyFilters preserved', 'applyFilters()' in result),
    ('Products footer inside tab-produtos', '</footer>\n</div>' in result or '</footer>\r\n</div>' in result),
    ('No bare render() call at top level', result.count('\nrender();') == 0 or result.count('\ndemoRender();') > 0),
]

all_ok = True
for name, ok in checks:
    status = "OK" if ok else "FAIL"
    print(f"  [{status}]  {name}")
    if not ok:
        all_ok = False

print(f"\nAll checks passed: {all_ok}")
print(f"Final file size: {len(result):,} characters (~{len(result)//1024} KB)")
