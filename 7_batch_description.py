# -*- coding: utf-8 -*-
import os
import json
import time
import copy  # Used for deep copying data structures
from google import genai
from google.genai import types
# Assume this configuration is the same as used by a previous script, defining categories to process.
from chosen_categories import CATEGORIES_CONFIG as CATEGORIES

# === Configuration ===
# Please paste your Gemini API key here.
# Note: For security, using environment variables or a secure key management service is recommended.
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"
BASE_DIR = "categorized_parts"
# The name for the new output file.
OUTPUT_FILE = "descriptions_for_compressed_json.txt"
# The source file containing simple descriptions.
DESCRIPTIONS_SOURCE_FILE = "descriptions_with_mappings_combined.txt"
# The directory name for the new compressed JSON files.
COMPRESSED_JSON_DIR = "compressed_json"

# --- Processing Settings ---
# Delay in seconds between API requests to avoid rate limiting.
REQUEST_DELAY_SECONDS = 0
# Maximum size for JSON files to avoid processing overly large files.
MAX_JSON_SIZE = 30 * 1024  # 30KB

# === Prompt for Geometric Analysis ===
GEOMETRIC_ANALYSIS_PROMPT = (
    """
As a CAD expert, analyze the geometric construction from the provided JSON data. Create a hierarchical summary based on the operational flow.

### Analysis Rules ###
1.  **Overall Order**: Process features (`Sketch`, `Extrude`, etc.) in the exact order they appear in the JSON file.
2.  **Top-Level Features**: For each feature like `Sketch` or `Extrude`, start a new line with its name in bold (e.g., `**Sketch1**`).
3.  **Profile Description**: For a `Sketch`, create an indented bullet point for each `Profile` it contains (e.g., `- **Profile1**`). On the same line, describe its geometry, focusing on loop relationships, shapes, and relative dimensions (e.g., "side length X", "radius Y"). Do not use absolute coordinates. If a dimension like side length is not directly provided, calculate it from the coordinates.
4.  **Extrude Description**: For an `Extrude` feature, add a colon and the description on the same line as its name. The description must specify the referenced profile (e.g., `Profile1`), the operation (new body, join, cut), direction (one-sided, symmetric), and the distance.
5.  **Format**:
    - Strictly adhere to the list, indentation, and formatting shown in the example.
    - **Use natural language**: Describe the geometric meaning. Do not use raw JSON field names in your response.
    - Be direct and concise, with no introductory or concluding text.

### Example Output ###
**Sketch1**:
- **Profile1**: Defines an outer square profile with a side length of 10 and an inner circular profile with a radius of 2.
**Extrude1**: Creates a new body by extruding Profile1 from Sketch1 one-sided for a distance of 5.0.
    """
)


# --- JSON Cropping Function ---
def crop_json_data(original_data: dict) -> dict:
    """
    In-memory cropping of the JSON data to keep only essential parts for the API call.
    - Removes the 'sequence' key.
    - For 'Sketch' entities, keeps only 'type', 'profiles', and 'transform'.
    """
    # Use deepcopy to avoid modifying the original data object.
    data = copy.deepcopy(original_data)

    # 1. Remove the 'sequence' section.
    if 'sequence' in data:
        del data['sequence']

    # 2. Crop 'Sketch' entities.
    if 'entities' in data and isinstance(data.get('entities'), dict):
        # Iterate through the entities dictionary.
        for entity_key, entity_value in data['entities'].items():
            if isinstance(entity_value, dict) and entity_value.get('type') == 'Sketch':
                # Create a new dictionary containing only the essential keys.
                cropped_sketch = {
                    'type': 'Sketch',
                    'profiles': entity_value.get('profiles', {}),  # Use .get for safety.
                    'transform': entity_value.get('transform', {})  # Retain the transform section.
                }
                # Replace the original entity with the cropped one.
                data['entities'][entity_key] = cropped_sketch

    return data


def get_geometric_analysis_from_json(client: genai.Client, json_data: dict) -> str:
    """
    Generates a geometric analysis based solely on the provided JSON data.
    """
    if client is None:
        return "API client not initialized"

    try:
        contents = [
            types.Part(text=f"- **JSON Data**: {json.dumps(json_data)}"),
            types.Part(text=GEOMETRIC_ANALYSIS_PROMPT)
        ]

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents
        )

        if response and response.text:
            # Sanitize the output text for storage in a single line.
            analysis_text = response.text.strip().replace('\n', '\\n').replace(';', ',')
            return analysis_text
        else:
            raise ValueError("API response for geometric analysis was empty.")
    except Exception as e:
        print(f"❌ Geometric Analysis API Error: {e}")
        return "Geometric analysis generation failed"


def load_simple_descriptions(filepath: str) -> dict:
    """
    Loads simple descriptions from the combined file into a dictionary for quick lookup.
    """
    descriptions = {}
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: Description file '{filepath}' not found. Simple descriptions in the final output will be empty.")
        return descriptions

    print(f"Loading simple descriptions from '{filepath}'...")
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            # Split by all semicolons. The first part is the ID, the last part is the simple description.
            # This handles cases where the detailed description itself contains semicolons.
            parts = line.strip().split(';')
            if len(parts) >= 2:
                part_id = parts[0].strip()
                simple_desc = parts[-1].strip()
                if part_id:
                    descriptions[part_id] = simple_desc
    print(f"Loading complete. Found {len(descriptions)} descriptions.")
    return descriptions


# --- Function to load bounding box data ---
def load_bounding_boxes(base_dir: str, categories: list) -> dict:
    """
    Loads bounding box sizes from category-specific .txt files into a dictionary.
    """
    bounding_boxes = {}
    print("Loading bounding box data...")
    for category in categories:
        category_name = category.get('name')
        if not category_name:
            continue

        # Construct the path to the category's .txt file.
        filepath = os.path.join(base_dir, f"{category_name}.txt")

        if not os.path.exists(filepath):
            print(f"  -> ⚠️ Warning: Bounding box file '{filepath}' not found.")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                # Split by colon and take the fourth part.
                parts = line.strip().split(':')
                if len(parts) >= 4:
                    part_id = parts[0].strip()
                    bbox_size = parts[3].strip()
                    if part_id:
                        bounding_boxes[part_id] = bbox_size

    print(f"Loading complete. Found {len(bounding_boxes)} bounding box entries.")
    return bounding_boxes


def main():
    """
    Main function to scan directories, read and crop JSON, generate analysis, and combine results.
    """
    client = None
    try:
        if not GEMINI_API_KEY or "YOUR_GEMINI_API_KEY" in GEMINI_API_KEY:
            print("❌ Error: Gemini API key is not set. Please set the GEMINI_API_KEY in the script.")
            return
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Error initializing Gemini client: {e}. Please check your API key or environment setup.")
        return

    # --- Load all necessary data ---
    descriptions_map = load_simple_descriptions(DESCRIPTIONS_SOURCE_FILE)
    bounding_boxes_map = load_bounding_boxes(BASE_DIR, CATEGORIES)

    # --- Resume from previous run if output file exists ---
    processed_ids = set()
    if os.path.exists(OUTPUT_FILE):
        print(f"Output file detected: {OUTPUT_FILE}. Loading already processed part IDs...")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f_in:
            for line in f_in:
                if ';' in line:
                    part_id = line.split(';', 1)[0].strip()
                    if part_id:
                        processed_ids.add(part_id)
        print(f"Loading complete. Found {len(processed_ids)} processed parts.")
    else:
        print(f"No output file found. A new file will be created: {OUTPUT_FILE}")

    # --- Process parts by category ---
    json_source_dir = COMPRESSED_JSON_DIR
    if not os.path.isdir(json_source_dir):
        print(f"❌ Error: JSON source directory '{json_source_dir}' not found. Script cannot continue.")
        return

    parts_processed_this_session = 0
    for category in CATEGORIES:
        # The list of part IDs is now sourced from the Category_Name_png directory.
        id_source_dir = os.path.join(BASE_DIR, f"{category['name']}_png")

        print(f"\n🔍 Processing category: {category['name']}")

        if not os.path.isdir(id_source_dir):
            print(f"  -> ⚠️ Warning: ID source directory '{id_source_dir}' not found, skipping this category.")
            continue

        for filename in sorted(os.listdir(id_source_dir)):
            if not filename.lower().endswith(".png"):
                continue

            part_id = os.path.splitext(filename)[0]

            if part_id in processed_ids:
                print(f"  -> ⏭️ Skipping (already processed): {part_id}")
                continue

            # --- Data Integrity Checks ---
            # 1. Check if the JSON file exists in the common directory.
            json_path = os.path.join(json_source_dir, f"{part_id}.json")
            if not os.path.exists(json_path):
                print(f"  -> ⚠️ Skipping (missing data): Corresponding JSON file not found in '{json_source_dir}': {part_id}.json")
                continue

            # 2. Check if the simple description exists.
            if part_id not in descriptions_map:
                print(f"  -> ⚠️ Skipping (missing data): Simple description for part {part_id} not found in the source file.")
                continue

            # 3. Check if the bounding box data exists.
            if part_id not in bounding_boxes_map:
                print(f"  -> ⚠️ Skipping (missing data): Bounding box data for part {part_id} not found in category files.")
                continue

            # --- All checks passed, proceed with processing ---
            parts_processed_this_session += 1
            print(f"\n[{parts_processed_this_session}] 📦 Processing new part: {part_id}")

            json_size = os.path.getsize(json_path)
            if json_size >= MAX_JSON_SIZE:
                print(
                    f"  -> ⚠️ Skipping: JSON file is too large ({json_size / 1024:.1f}KB >= {MAX_JSON_SIZE / 1024}KB)")
                continue

            try:
                with open(json_path, "r", encoding="utf-8") as f_json:
                    json_data = json.load(f_json)

                # --- Crop the JSON data before sending it to the API ---
                print("  -> Cropping JSON data...")
                cropped_data = crop_json_data(json_data)

                print("  -> Generating geometric analysis...")
                analysis_result = get_geometric_analysis_from_json(client, cropped_data)

                if "failed" in analysis_result:
                    print(f"  -> ❌ Geometric analysis generation failed, skipping this part.")
                    continue
                print("  -> Geometric analysis generated.")

                # --- Combine all data pieces ---
                simple_description = descriptions_map[part_id]
                bounding_box = bounding_boxes_map[part_id]

                # Construct the final output line.
                output_line = f"{part_id};{analysis_result};{simple_description};{bounding_box}\n"

                with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out:
                    f_out.write(output_line)

                print(f"  -> ✅ Success! Saved analysis and description for {part_id}.")

            except json.JSONDecodeError:
                print(f"  -> ❌ Error: Invalid JSON format, could not parse: {json_path}")
            except Exception as e:
                print(f"  -> ❌ An unexpected error occurred while processing {part_id}: {e}")

            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\n\n=== All Categories Processed ===")
    print(f"Number of parts processed in this session: {parts_processed_this_session}")
    final_count = len(processed_ids) + parts_processed_this_session
    print(f"Total cumulative parts in the output file: {final_count}")
    print(f"Final results have been saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
