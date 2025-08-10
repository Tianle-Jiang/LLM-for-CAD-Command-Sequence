import os
import shutil
import json  # Import json module for parsing files

# --- Path Configuration ---
BASE_DIR = os.getcwd()
CATEGORIZED_DIR = os.path.join(BASE_DIR, "categorized_parts")
JSON_SOURCE_DIR = os.path.join(BASE_DIR, "compressed_json")
PNG_SOURCE_DIR = os.path.join(BASE_DIR, "compressed_json")

# --- Check Directory Existence ---
for path, name in [(CATEGORIZED_DIR, "categorized_parts"),
                   (JSON_SOURCE_DIR, "compressed_json"),
                   (PNG_SOURCE_DIR, "compressed_json")]:
    if not os.path.exists(path):
        print(f"[ERROR] Required directory '{name}' not found at: {path}")
        exit()

# --- Clean Up Existing Data ---
print(f"\nCleaning up existing subfolders in '{CATEGORIZED_DIR}'...")
cleaned_folders_count = 0
for item in os.listdir(CATEGORIZED_DIR):
    item_path = os.path.join(CATEGORIZED_DIR, item)
    if os.path.isdir(item_path):
        try:
            shutil.rmtree(item_path)
            print(f"  Removed: {item}")
            cleaned_folders_count += 1
        except OSError as e:
            print(f"  [ERROR] Could not remove {item_path}: {e}")
print(f"Finished cleanup. Removed {cleaned_folders_count} folders.")

# --- Update Category Files: Add Sketch/Extrude Counts ---
print("\nUpdating category files with sketch/extrude counts...")
for filename in os.listdir(CATEGORIZED_DIR):
    if not (filename.endswith(".txt") and filename.startswith("category_")):
        continue

    category_txt_path = os.path.join(CATEGORIZED_DIR, filename)
    updated_lines = []

    with open(category_txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                updated_lines.append(line)
                continue

            # The line format from the previous script is expected to be:
            # part_id:tag:description:bbox:category_number
            parts = line.split(":", 5)
            if len(parts) < 5:
                updated_lines.append(line)
                continue

            part_id = parts[0].strip()
            base_info = ":".join(parts[:5])  # Reconstruct the original line content

            json_file = part_id + ".json"
            json_path = os.path.join(JSON_SOURCE_DIR, json_file)

            sketch_count = 0
            extrude_count = 0

            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as json_f:
                        data = json.load(json_f)

                    sketch_count = sum(1 for item in data.get("sequence", [])
                                       if item.get("type") == "Sketch")
                    extrude_count = sum(1 for item in data.get("sequence", [])
                                        if item.get("type") == "ExtrudeFeature")
                except Exception as e:
                    print(f"  [WARNING] Failed to parse {json_file}: {str(e)}")
            else:
                print(f"  [WARNING] JSON not found for {part_id}")

            # Append the new counts to the line
            updated_line = f"{base_info}:{sketch_count}:{extrude_count}"
            updated_lines.append(updated_line)

    # Overwrite the file with the updated lines
    with open(category_txt_path, 'w', encoding='utf-8') as f:
        for line in updated_lines:
            f.write(line + "\n")

    print(f"Updated {filename} with sketch/extrude counts")

# --- Process Category Files and Copy Related Files ---
print("\nProcessing categories and copying files...")
for filename in os.listdir(CATEGORIZED_DIR):
    if not (filename.endswith(".txt") and filename.startswith("category_")):
        continue

    category_txt_path = os.path.join(CATEGORIZED_DIR, filename)
    category_base = filename.replace(".txt", "")
    json_target_dir = os.path.join(CATEGORIZED_DIR, f"{category_base}_json")
    png_target_dir = os.path.join(CATEGORIZED_DIR, f"{category_base}_png")

    os.makedirs(json_target_dir, exist_ok=True)
    os.makedirs(png_target_dir, exist_ok=True)

    print(f"\nProcessing category: {filename}")
    json_copied = png_copied = json_missing = png_missing = 0

    # The updated format is now:
    # part_id:tag:description:bbox:category_number:sketch_count:extrude_count
    with open(category_txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue

            # Split the line to extract the part_id
            parts = line.split(':', 5)
            if len(parts) < 4:  # Ensure at least the basic part info exists
                continue

            part_id = parts[0].strip()

            # Note: The following lines might not extract the intended sketch/extrude counts
            # due to the split limit. This behavior is preserved from the original script.
            sketch_count = parts[4].strip() if len(parts) > 4 else "?"
            extrude_count = parts[5].strip() if len(parts) > 5 else "?"

            # Process JSON file
            json_file = part_id + ".json"
            json_src = os.path.join(JSON_SOURCE_DIR, json_file)
            if os.path.exists(json_src):
                shutil.copy(json_src, json_target_dir)
                json_copied += 1
            else:
                print(f"  [!] JSON not found: {json_file}")
                json_missing += 1

            # Process PNG file
            png_file = part_id + ".png"
            png_src = os.path.join(PNG_SOURCE_DIR, png_file)
            if os.path.exists(png_src):
                shutil.copy(png_src, png_target_dir)
                png_copied += 1
            else:
                print(f"  [!] PNG not found: {png_file}")
                png_missing += 1

    print(f"Copied {json_copied} JSON files to {json_target_dir}")
    print(f"Copied {png_copied} PNG files to {png_target_dir}")
    if json_missing > 0 or png_missing > 0:
        print(f"Missing: {json_missing} JSON, {png_missing} PNG")

print("\nAll operations completed!")
