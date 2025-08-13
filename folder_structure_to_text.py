import os
import tkinter as tk
from tkinter import filedialog

def select_folder():
    root = tk.Tk()
    root.withdraw()  # Hide main window
    folder_selected = filedialog.askdirectory(title="Select Folder to Scan")
    return folder_selected

def get_folder_structure(folder_path):
    structure_lines = []
    for root, dirs, files in os.walk(folder_path):
        level = root.replace(folder_path, '').count(os.sep)
        indent = '    ' * level
        structure_lines.append(f"{indent}{os.path.basename(root)}/")
        subindent = '    ' * (level + 1)
        for f in files:
            structure_lines.append(f"{subindent}{f}")
    return '\n'.join(structure_lines)

def write_to_text_file(content, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    folder = select_folder()
    if not folder:
        print("No folder selected. Exiting.")
        return

    print(f"Selected folder: {folder}")
    structure = get_folder_structure(folder)

    output_file = os.path.join(folder, "folder_structure.txt")
    write_to_text_file(structure, output_file)
    print(f"Folder structure saved to {output_file}")

if __name__ == '__main__':
    main()
