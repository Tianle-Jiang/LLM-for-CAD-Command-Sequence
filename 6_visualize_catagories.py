import os
import random
import tkinter as tk
from tkinter import ttk
from collections import defaultdict
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib

# Use the TkAgg backend for matplotlib to integrate with tkinter
matplotlib.use('TkAgg')

# --- Path Configuration ---
BASE_DIR = os.getcwd()
CATEGORIZED_DIR = os.path.join(BASE_DIR, "categorized_parts")
PNG_SOURCE_DIR = os.path.join(BASE_DIR, "reconstruction_results")
INPUT_FILE = os.path.join(BASE_DIR, "labels.txt")

# --- Read Original Label Data ---
# This dictionary will store the original tag and description for each part ID.
part_id_to_data = {}
try:
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(';', 2)
            if len(parts) >= 3:
                part_id = parts[0].strip()
                tag = parts[1].strip()
                description = parts[2].strip()
                part_id_to_data[part_id] = {
                    'tag': tag,
                    'description': description
                }
except FileNotFoundError:
    print(f"Error: Input file '{INPUT_FILE}' not found. Exiting.")
    exit()

# --- Category Statistics ---
# These dictionaries will store the count of parts per category and their image paths.
category_counts = {}
category_to_images = defaultdict(list)

if not os.path.exists(CATEGORIZED_DIR):
    print(f"Error: Directory '{CATEGORIZED_DIR}' does not exist.")
    exit()

# Iterate through the categorized .txt files to gather data.
for file in sorted(os.listdir(CATEGORIZED_DIR)):
    if file.endswith(".txt") and file.startswith("category_"):
        category_name = file.replace(".txt", "")
        txt_path = os.path.join(CATEGORIZED_DIR, file)
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                current_category_part_ids = []
                for line in f:
                    line = line.strip()
                    if not line or ":" not in line:
                        continue

                    # Parse the new format: part_id:tag:description:bbox:category_number
                    parts = line.split(':', 3)
                    if len(parts) >= 4:
                        pid = parts[0].strip()
                        current_category_part_ids.append(pid)

                        # Construct the path to the corresponding PNG file.
                        png_dir = os.path.join(CATEGORIZED_DIR, f"{category_name}_png")
                        if os.path.exists(png_dir):
                            img_path = os.path.join(png_dir, pid + ".png")
                            if os.path.exists(img_path):
                                category_to_images[category_name].append((img_path, pid))
                        else:
                            # Fallback to the source directory if the categorized one doesn't exist.
                            img_path = os.path.join(PNG_SOURCE_DIR, pid + ".png")
                            if os.path.exists(img_path):
                                category_to_images[category_name].append((img_path, pid))

                category_counts[category_name] = len(current_category_part_ids)
        except Exception as e:
            print(f"Error processing file '{txt_path}': {e}")


# Sort categories by the number of parts in descending order.
def category_sort_key_by_count(name):
    return -category_counts.get(name, 0)

category_names = sorted(category_counts.keys(), key=category_sort_key_by_count)

if not category_names:
    print("No categorized data found.")
    exit()

# Format category names for display (e.g., 'category_3_screws' -> 'screws').
def format_category_label(category_name):
    parts = category_name.split("_", 2)
    if len(parts) > 2:
        return parts[2].replace("_", " ")
    return category_name.replace("_", " ")

formatted_category_names = [format_category_label(cat) for cat in category_names]

# --- GUI Setup ---
root = tk.Tk()
root.title("Mechanical Parts Visual Analysis")
root.geometry("2000x1300")

# Create styles for widgets.
style = ttk.Style()
style.configure("Big.TButton", font=("Arial", 20))
style.configure("Large.TButton", font=("Arial", 16))

# --- Top: Chart Area ---
# Bar Chart
bar_fig, bar_ax = plt.subplots(figsize=(10, 8))
bar_values = [category_counts[k] for k in category_names]
bars = bar_ax.bar(range(len(category_names)), bar_values, color='skyblue')
bar_ax.set_title("Parts per Category", fontsize=18)
bar_ax.set_xticks(range(len(category_names)))
bar_ax.set_xticklabels(formatted_category_names, rotation=45, ha='right', fontsize=12)
bar_ax.tick_params(axis='y', labelsize=10)
bar_ax.set_ylabel("Count", fontsize=12)

# Add value labels on top of each bar.
for bar in bars:
    yval = bar.get_height()
    bar_ax.text(bar.get_x() + bar.get_width() / 2, yval + 0.5, round(yval), ha='center', va='bottom', fontsize=10)

bar_fig.tight_layout(rect=[0, 0, 1, 0.9])
bar_canvas = FigureCanvasTkAgg(bar_fig, master=root)
bar_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

# Pie Chart
pie_fig, pie_ax = plt.subplots(figsize=(10, 6))
pie_ax.pie(
    bar_values,
    labels=formatted_category_names,
    autopct='%1.1f%%',
    startangle=140,
    textprops={'fontsize': 12},
    pctdistance=0.6,
    labeldistance=1.05
)
pie_ax.set_title("Category Distribution", fontsize=18)
pie_fig.tight_layout(rect=[0.1, 0, 0.9, 1])
pie_canvas = FigureCanvasTkAgg(pie_fig, master=root)
pie_canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

# --- Middle: Image Display Area ---
board_frame = tk.Frame(root, bg="white", relief=tk.SUNKEN, bd=1)
board_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)


def show_category_board(category):
    """Displays part images, tags, and descriptions for the selected category."""
    for widget in board_frame.winfo_children():
        widget.destroy()

    image_id_pairs = category_to_images[category]
    if not image_id_pairs:
        no_image_label = tk.Label(board_frame, text=f"No images found for '{format_category_label(category)}'.",
                                  bg="white", font=("Arial", 12))
        no_image_label.grid(row=0, column=0, columnspan=10, padx=5, pady=5, sticky="nsew")
        board_frame.grid_columnconfigure(0, weight=1)
        return

    # Randomly select up to 10 sample parts to display.
    sampled_items = random.sample(image_id_pairs, min(10, len(image_id_pairs)))

    for idx, (img_path, part_id) in enumerate(sampled_items):
        item_frame = tk.Frame(board_frame, bg="white")
        item_frame.grid(row=0, column=idx, padx=5, pady=5, sticky="nsew")

        # Get the part's data.
        part_data = part_id_to_data.get(part_id, {})
        tag = part_data.get('tag', f"[unknown]")
        description = part_data.get('description', "Description not available")

        try:
            img = Image.open(img_path)
            img.thumbnail((180, 180))
            tk_img = ImageTk.PhotoImage(img, master=root)

            img_label = tk.Label(item_frame, image=tk_img, bg="white")
            img_label.image = tk_img  # Keep a reference to avoid garbage collection.
            img_label.pack(side=tk.TOP, pady=(0, 2))

            # Display the tag.
            tag_label = tk.Label(item_frame, text=tag, bg="white", font=("Arial", 9), wraplength=180, justify=tk.CENTER)
            tag_label.pack(side=tk.TOP)

            # Display the description.
            desc_label = tk.Label(item_frame, text=description, bg="white", font=("Arial", 9),
                                  wraplength=180, justify=tk.CENTER, fg="#555555")
            desc_label.pack(side=tk.TOP, pady=(0, 5))

        except Exception as e:
            print(f"Error loading image '{img_path}': {e}")
            error_label = tk.Label(item_frame, text="Image load failed", bg="white", font=("Arial", 10))
            error_label.pack(side=tk.TOP, pady=(0, 2))

            # Display part info even if image fails.
            info_label = tk.Label(item_frame, text=f"ID: {part_id}\n{description}", bg="white",
                                  font=("Arial", 9), wraplength=180, justify=tk.CENTER)
            info_label.pack(side=tk.BOTTOM)

    # Configure layout weights for the display board.
    for i in range(10):
        board_frame.grid_columnconfigure(i, weight=1)
    board_frame.grid_rowconfigure(0, weight=1)


# --- Bottom: Button Area ---
button_frame = tk.Frame(root)
button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

# Configure button columns to expand equally.
for i in range(8):
    button_frame.grid_columnconfigure(i, weight=1)

# Add a button for each category.
buttons_per_row = 8
for i, cat in enumerate(category_names):
    row = i // buttons_per_row
    col = i % buttons_per_row
    label = formatted_category_names[i]
    btn = ttk.Button(button_frame, text=label, command=lambda c=cat: show_category_board(c))
    btn.configure(style="Big.TButton")
    btn.grid(row=row, column=col, padx=5, pady=5, ipadx=5, ipady=5, sticky="ew")

# Add Save and Exit buttons.
final_row = (len(category_names) + buttons_per_row - 1) // buttons_per_row
save_button = ttk.Button(button_frame, text="Save Poster as Image", command=lambda: save_gui_as_image())
save_button.configure(style="Large.TButton")
save_button.grid(row=final_row, column=0, columnspan=buttons_per_row // 2, padx=10, pady=15, ipadx=10, ipady=10,
                 sticky="ew")


def exit_program():
    root.destroy()

exit_button = ttk.Button(button_frame, text="Exit Program", command=exit_program)
exit_button.configure(style="Large.TButton")
exit_button.grid(row=final_row, column=buttons_per_row // 2, columnspan=(buttons_per_row + 1) // 2,
                 padx=10, pady=15, ipadx=10, ipady=10, sticky="ew")


# --- Save Functionality (Placeholder) ---
def save_gui_as_image():
    # The actual implementation would depend on the environment (e.g., using a library like pyscreenshot).
    print("Save functionality would be implemented here.")


# --- Layout Configuration ---
root.grid_rowconfigure(0, weight=2)  # Give more space to charts.
root.grid_rowconfigure(1, weight=1)  # Give space to the image board.
root.grid_rowconfigure(2, weight=0)  # Buttons have fixed space.
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)

# Start the Tkinter main loop.
root.mainloop()
