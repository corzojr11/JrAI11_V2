import sys

file_path = "app.py"
with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_lab_block = False

for i, line in enumerate(lines):
    if "# ====================== JUEZ PONDERADO ======================" in line:
        in_lab_block = True
        # Insert the 'with tab_lab:' block at 4 spaces indentation
        new_lines.append("    with tab_lab:\n")
    
    if in_lab_block and "# ====================== USUARIOS ======================" in line:
        in_lab_block = False

    if in_lab_block:
        # Indent by 4 spaces unless it's an empty line
        if line.strip():
            new_lines.append("    " + line)
        else:
            new_lines.append(line)
    else:
        new_lines.append(line)

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("app.py actualizado con éxito.")
