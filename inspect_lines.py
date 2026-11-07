with open("web_ui.py", encoding="utf-8") as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    for target in ["def inventory_screen", "def render_edit_unit_modal_html", "def inventory_model_detail_screen", "def product_units_screen"]:
        if target in l:
            print(f"{target} at line {i+1}")
