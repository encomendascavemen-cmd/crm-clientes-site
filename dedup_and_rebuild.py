#!/usr/bin/env python3
"""
Fix the double-processed relatorio_magento.html by rebuilding it correctly from scratch.
Strategy: extract the original products content (unmodified core), then apply the tab
integration exactly once.
"""

import re

CURRENT = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_magento.html"
GENERO  = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_genero.html"
OUT1    = "/Users/pedrovieira/Desktop/Claude Code/cavemen-dashboard/relatorio_magento.html"
OUT2    = "/Users/pedrovieira/Desktop/relatorio_produtos_cavemen.html"

with open(CURRENT, "r", encoding="utf-8") as f:
    current = f.read()

with open(GENERO, "r", encoding="utf-8") as f:
    genero = f.read()

print(f"Current file: {len(current):,} chars")
print(f"Gender file: {len(genero):,} chars")

# ── Step 1: Strip the tab wrapper modifications from current file ──────────────
# The current file has the tab structure twice. We need to:
# 1. Remove duplicate <nav class="tab-nav">
# 2. Remove duplicate <div id="tab-produtos" class="tab-panel active">
# 3. Remove second <div id="tab-demograficos"> and its content
# 4. Remove the extra </div> closing the first tab-produtos wrapper
# 5. Remove duplicate JS sections (switchTab, initDemo, demoRender)
# 6. Remove duplicate CSS sections

# The cleanest approach: reconstruct from the raw HTML + CSS structure
# The current file has this structure (after the double-processing):
# <html>
#   <head>
#     <style>[original CSS][TAB_NAV_CSS][gender_scoped_CSS][TAB_NAV_CSS again][gender_scoped_CSS again]</style>
#   </head>
#   <body>
#     ...
#     </header>
#     <nav class="tab-nav">...</nav>   ← first (from run 1)
#     <nav class="tab-nav">...</nav>   ← second (from run 2)
#     <div id="tab-produtos" class="tab-panel active">   ← first wrapper
#     <div id="tab-produtos" class="tab-panel active">   ← second wrapper
#     <!-- ── FILTROS ── --> ... <footer>...</footer>
#     </div>              ← closes second tab-produtos
#     <div id="tab-demograficos">...</div>   ← first demographics (correct content)
#     </div>              ← closes first tab-produtos
#     <div id="tab-demograficos">...</div>   ← second demographics (duplicate)
#     ...
#     <script>
#       [original JS]
#       [switchTab from run 1][initDemo from run 1]
#       [switchTab from run 2][initDemo from run 2]
#     </script>

# Strategy: Since both runs used the same gender file content, and the structure
# is predictable, let's surgically remove the duplicates.

# ── Remove duplicate CSS ──────────────────────────────────────────────────────
# Find the </style> tag - before it there should be two copies of TAB_NAV_CSS + gender_scoped_CSS
# The TAB_NAV_CSS starts with "/* Tab navigation */"
TAB_NAV_CSS_MARKER = "\n/* Tab navigation */"

style_end = current.find('</style>')
style_content_before_close = current[:style_end]

# Find first and second occurrence of TAB_NAV_CSS_MARKER
first_tab_css = style_content_before_close.find(TAB_NAV_CSS_MARKER)
second_tab_css = style_content_before_close.find(TAB_NAV_CSS_MARKER, first_tab_css + 1)

if first_tab_css == -1:
    raise ValueError("Could not find Tab nav CSS in style block")
if second_tab_css == -1:
    raise ValueError("Could not find second Tab nav CSS - file may not be double-processed")

print(f"First tab CSS at char: {first_tab_css:,}")
print(f"Second tab CSS at char: {second_tab_css:,}")

# Remove from second_tab_css to </style> (excluding the actual </style>)
# Everything from second_tab_css to style_end should be removed
result = current[:second_tab_css] + current[style_end:]
print(f"After CSS dedup: {len(result):,} chars")

# ── Remove duplicate tab-nav HTML ─────────────────────────────────────────────
# Find both <nav class="tab-nav"> and remove the second one
NAV_PATTERN = '<nav class="tab-nav">'
first_nav = result.find(NAV_PATTERN)
second_nav = result.find(NAV_PATTERN, first_nav + 1)

if second_nav == -1:
    raise ValueError("Could not find second nav.tab-nav")

# Find end of second nav (closing </nav>)
second_nav_end = result.find('</nav>', second_nav) + len('</nav>')
# Remove second nav including its newline
if result[second_nav_end] == '\n':
    second_nav_end += 1

result = result[:second_nav] + result[second_nav_end:]
print(f"After nav dedup: {len(result):,} chars")

# ── Remove duplicate tab-produtos wrapper ─────────────────────────────────────
# Now we have:
# <nav class="tab-nav">...</nav>
# <div id="tab-produtos" class="tab-panel active">   ← outer (keep this)
# <div id="tab-produtos" class="tab-panel active">   ← inner (remove this)
# <!-- ── FILTROS ── --> ... <footer>...</footer>
# </div>    ← closes inner (remove this)
# <div id="tab-demograficos">...</div>   ← first demo (correct)
# </div>    ← closes outer
# <div id="tab-demograficos">...</div>   ← second demo (remove)

TAB_PROD_OPEN = '<div id="tab-produtos" class="tab-panel active">'
first_prod = result.find(TAB_PROD_OPEN)
second_prod = result.find(TAB_PROD_OPEN, first_prod + 1)

if second_prod == -1:
    raise ValueError("Could not find second tab-produtos div")

# Remove the second opening tag (and its trailing newline)
second_prod_tag_end = second_prod + len(TAB_PROD_OPEN)
if result[second_prod_tag_end] == '\n':
    second_prod_tag_end += 1

result = result[:second_prod] + result[second_prod_tag_end:]
print(f"After tab-produtos open dedup: {len(result):,} chars")

# Now find the structure:
# <footer>...</footer>
# </div>    ← this closes what was the second (inner) div, now remove it
# <div id="tab-demograficos">...</div>   ← first (correct)
# </div>    ← this closes the outer tab-produtos
# <div id="tab-demograficos">...</div>   ← second (remove along with everything to </body>)

FOOTER_PROD = '<footer>Cavemen Store · Relatório de Produtos · 2026</footer>'
footer_pos = result.find(FOOTER_PROD)
if footer_pos == -1:
    raise ValueError("Could not find products footer")

footer_end = footer_pos + len(FOOTER_PROD)

# After footer, find the pattern: \n</div>\n\n<div id="tab-demograficos"
# That first </div> is the one we want to remove (closes inner duplicate)
after_footer = result[footer_end:]
print(f"Content after footer (first 200 chars): {repr(after_footer[:200])}")

# Find the first </div> after footer - this is the extra one from inner duplicate
first_div_close_after_footer = after_footer.find('</div>')
if first_div_close_after_footer == -1:
    raise ValueError("Could not find </div> after footer")

# Check that the next thing after this </div> is the first tab-demograficos
div_close_end = first_div_close_after_footer + len('</div>')

# Now find the second tab-demograficos
DEMO_PANEL = '<div id="tab-demograficos" class="tab-panel">'
first_demo_in_after = after_footer.find(DEMO_PANEL)
second_demo_in_after = after_footer.find(DEMO_PANEL, first_demo_in_after + 1)

print(f"First demo panel at after_footer pos: {first_demo_in_after}")
print(f"Second demo panel at after_footer pos: {second_demo_in_after}")

if second_demo_in_after == -1:
    print("WARNING: No second demo panel found - may already be clean")
    # Structure might be: </div>\n\n<div id="tab-demograficos">...</div>\n</div>
    # Just remove the first extra </div>
    result = result[:footer_end] + after_footer[:first_div_close_after_footer] + after_footer[div_close_end:]
else:
    # Find the end of second demo panel (find its closing </div>)
    # Count brace depth from second_demo_in_after
    depth = 0
    idx = second_demo_in_after
    second_demo_end = -1
    while idx < len(after_footer):
        if after_footer[idx:idx+4] == '<div':
            depth += 1
        elif after_footer[idx:idx+6] == '</div>':
            depth -= 1
            if depth == 0:
                second_demo_end = idx + 6
                break
        idx += 1

    if second_demo_end == -1:
        raise ValueError("Could not find end of second demo panel")

    print(f"Second demo panel ends at after_footer pos: {second_demo_end}")

    # Also find the closing </div> of the outer tab-produtos (between first and second demo)
    # It's at: after first demo end, before second demo start
    # Structure: [first_demo]</div>\n\n[second_demo]
    first_demo_end_idx = after_footer.find('</div>', first_demo_in_after)
    # Count depth to get proper end
    depth = 0
    idx = first_demo_in_after
    first_demo_end = -1
    while idx < len(after_footer):
        if after_footer[idx:idx+4] == '<div':
            depth += 1
        elif after_footer[idx:idx+6] == '</div>':
            depth -= 1
            if depth == 0:
                first_demo_end = idx + 6
                break
        idx += 1

    print(f"First demo panel ends at after_footer pos: {first_demo_end}")

    # Find the </div> that closes tab-produtos (between first_demo_end and second_demo_in_after)
    outer_close_start = after_footer.find('</div>', first_demo_end)
    outer_close_end = outer_close_start + 6

    print(f"Outer </div> (tab-produtos close) at: {outer_close_start}")

    # Now remove:
    # 1. The first </div> after footer (extra inner close)
    # 2. The second demo panel and everything after it up to (but not including) the outer </div>
    # New structure after footer:
    # \n<div id="tab-demograficos">...</div>\n</div>

    # Build the corrected after_footer:
    # - Remove: chars 0..div_close_end (the extra first </div>)
    # - Keep: div_close_end..second_demo_in_after (includes first demo panel + outer </div>)
    # - Remove: second_demo_in_after..second_demo_end (remove second demo)
    # - Keep: second_demo_end.. (rest of file after second demo)

    corrected_after = (
        after_footer[div_close_end:second_demo_in_after] +
        after_footer[second_demo_end:]
    )
    result = result[:footer_end] + corrected_after
    print(f"After full panel dedup: {len(result):,} chars")

# ── Remove duplicate JS sections ──────────────────────────────────────────────
# Find both switchTab functions and remove the second one (plus everything between
# second switchTab and second initDemo end)

SWITCH_TAB_MARKER = '\nfunction switchTab(tab) {'
first_switch = result.find(SWITCH_TAB_MARKER)
second_switch = result.find(SWITCH_TAB_MARKER, first_switch + 1)

if second_switch == -1:
    print("No duplicate switchTab found - JS may already be clean")
else:
    print(f"First switchTab at: {first_switch:,}")
    print(f"Second switchTab at: {second_switch:,}")

    # Find the end of the second initDemo function
    # It ends with "}\n" after the last closing brace
    # Find second initDemo
    INIT_DEMO_MARKER = 'function initDemo() {'
    first_init = result.find(INIT_DEMO_MARKER)
    second_init = result.find(INIT_DEMO_MARKER, first_init + 1)

    if second_init == -1:
        raise ValueError("Could not find second initDemo")

    print(f"Second initDemo at: {second_init:,}")

    # Find the closing } of second initDemo by counting braces
    depth = 0
    idx = second_init
    second_init_end = -1
    in_func = False
    while idx < len(result):
        c = result[idx]
        if c == '{':
            depth += 1
            in_func = True
        elif c == '}':
            depth -= 1
            if in_func and depth == 0:
                second_init_end = idx + 1
                break
        idx += 1

    if second_init_end == -1:
        raise ValueError("Could not find end of second initDemo")

    # Skip trailing newlines
    while second_init_end < len(result) and result[second_init_end] == '\n':
        second_init_end += 1

    print(f"Second initDemo ends at: {second_init_end:,}")

    # Remove from second_switch to second_init_end
    result = result[:second_switch] + result[second_init_end:]
    print(f"After JS dedup: {len(result):,} chars")

# ── Write output files ────────────────────────────────────────────────────────
with open(OUT1, "w", encoding="utf-8") as f:
    f.write(result)
print(f"\nWritten to: {OUT1}")
print(f"File size: {len(result):,} chars (~{len(result)//1024} KB)")

with open(OUT2, "w", encoding="utf-8") as f:
    f.write(result)
print(f"Written to: {OUT2}")

# ── Validation ────────────────────────────────────────────────────────────────
print("\n── Validation ──────────────────────────────────────────────────────────")
checks = [
    ('Single tab-nav', result.count('class="tab-nav"') == 1),
    ('Single tab-produtos', result.count('id="tab-produtos"') == 1),
    ('Single tab-demograficos', result.count('id="tab-demograficos"') == 1),
    ('Single switchTab function', result.count('function switchTab') == 1),
    ('Single initDemo function', result.count('function initDemo') == 1),
    ('Single demoRender function', result.count('function demoRender') == 1),
    ('Single Tab nav CSS block', result.count('/* Tab navigation */') == 1),
    ('DEMO_DATA present', 'const DEMO_DATA' in result),
    ('demo- prefixed IDs in HTML (aFrom)', 'id="demo-aFrom"' in result),
    ('demo- prefixed IDs in HTML (btnApply)', 'id="demo-btnApply"' in result),
    ('demo- prefixed IDs in JS (aFrom)', "getElementById('demo-aFrom')" in result),
    ('demoCharts variable', 'let demoCharts' in result),
    ('No Chart.js CDN', 'cdnjs.cloudflare.com/ajax/libs/Chart.js' not in result),
    ('Original initCharts preserved', 'initCharts()' in result),
    ('Original applyFilters preserved', 'applyFilters()' in result),
    ('tab-btn active button', 'class="tab-btn active"' in result),
    ('Single demo-aFrom ID', result.count('id="demo-aFrom"') == 1),
    ('Single demo-btnApply ID', result.count('id="demo-btnApply"') == 1),
]

all_ok = True
for name, ok in checks:
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}]  {name}")
    if not ok:
        all_ok = False

print(f"\nAll checks passed: {all_ok}")
print(f"Final file size: {len(result):,} characters (~{len(result)//1024} KB)")
