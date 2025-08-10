import os
import json
import re
import random
# Import the category configuration you have selected from an external file.
from chosen_categories import CATEGORIES_CONFIG as CATEGORIES


# ==============================================================================
#  1. Parsing Functions
# ==============================================================================

def load_compressed_descriptions(desc_file):
    """
    Parses the file with the format 'id;build plan;brief description;bbox'.
    This function is the single source of truth for all descriptions, build plans,
    and bounding box data.
    """
    all_descriptions = {}
    if not os.path.exists(desc_file):
        print(f"Error: Core description file not found: {desc_file}")
        return all_descriptions

    with open(desc_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split(';', 3)
            if len(parts) == 4:
                part_id, mapping, brief, bbox = parts
                all_descriptions[part_id.strip()] = {
                    "mapping": mapping.strip().replace('\\n', '\n'),
                    "brief": brief.strip().replace('\\n', '\n'),
                    "bbox": bbox.strip()
                }
            else:
                print(f"Warning: Malformed line found in {desc_file}, skipping: {line}")
    return all_descriptions


# ==============================================================================
#  2. Main Execution Function
# ==============================================================================
def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_dataset_path = os.path.join(base_dir, "test_dataset.txt")
    categorized_parts_dir = os.path.join(base_dir, "categorized_parts")

    train_part_ids = set()
    test_part_ids = set()

    # --- 1. Split train/test part IDs based on whether test_dataset.txt exists ---
    test_set_exists = os.path.exists(test_dataset_path)

    if test_set_exists:
        print(f"Found existing test set file: {test_dataset_path}")
        print("Loading test set IDs from this file. All other parts will be used for training.")
        with open(test_dataset_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                part_id = line.split(';', 1)[0]
                if part_id:
                    test_part_ids.add(part_id.strip())

        # Collect all available part IDs from the category files.
        all_part_ids = set()
        if not CATEGORIES:
            print("Warning: CATEGORIES_CONFIG imported from chosen_categories.py is empty.")
        for cat in CATEGORIES:
            cat_file = cat.get("txt_file")
            if not cat_file: continue
            path = os.path.join(categorized_parts_dir, cat_file)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        part_id = line.split(':', 1)[0].strip()
                        if part_id:
                            all_part_ids.add(part_id)
            else:
                print(f"  -> Warning: Category file not found: {path}")

        # Training set IDs = All IDs - Test set IDs
        train_part_ids = all_part_ids - test_part_ids

    else:
        print("No existing test set file found. Will randomly split to generate a new train/test set.")
        if not CATEGORIES:
            print("Warning: CATEGORIES_CONFIG imported from chosen_categories.py is empty.")

        for cat in CATEGORIES:
            cat_name = cat.get("name", "N/A")
            cat_file = cat.get("txt_file")
            if not cat_file:
                print(f"  -> Warning: Category '{cat_name}' is missing 'txt_file' config, skipping.")
                continue

            path = os.path.join(categorized_parts_dir, cat_file)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    current_cat_ids = [line.split(':', 1)[0].strip() for line in f if line.strip()]
                    random.shuffle(current_cat_ids)
                    test_size = int(len(current_cat_ids) * 0.05)

                    new_test_ids = set(current_cat_ids[:test_size])
                    new_train_ids = set(current_cat_ids[test_size:])

                    test_part_ids.update(new_test_ids)
                    train_part_ids.update(new_train_ids)
                    print(f"  -> Processed: {cat_file} (Train: {len(new_train_ids)}, Test: {len(new_test_ids)})")
            else:
                print(f"  -> Warning: Category file not found: {path}")

        # Ensure there is no overlap between train and test sets.
        train_part_ids -= test_part_ids

    if not train_part_ids and not test_part_ids:
        print("Could not collect any valid part IDs. Terminating script.")
        return
    print(f"Collection complete: {len(train_part_ids)} training IDs, {len(test_part_ids)} test IDs.")
    print("-" * 30)

    # --- 2. Load all description data ---
    desc_file_path = os.path.join(base_dir, "descriptions_for_compressed_json.txt")
    print(f"Loading description data for all parts from '{desc_file_path}'...")
    all_desc_map = load_compressed_descriptions(desc_file_path)
    if not all_desc_map:
        print("Description file is empty or does not exist. Terminating script.")
        return
    print(f"Loaded {len(all_desc_map)} description entries.")
    print("-" * 30)

    # --- 3. If the test set file didn't exist, build and save it now ---
    if not test_set_exists:
        print("Building and saving a new test set file...")
        test_set_lines = []
        data_dir = os.path.join(base_dir, "compressed_json")

        for part_id in test_part_ids:
            details = all_desc_map.get(part_id)
            if not details: continue

            cmd_set = "N/A"
            txt_path = os.path.join(data_dir, f"{part_id}.txt")
            if os.path.exists(txt_path):
                with open(txt_path, 'r', encoding='utf-8') as tf:
                    cmd_set = tf.read().replace('\n', '\\n')

            json_str = "N/A"
            json_path = os.path.join(data_dir, f"{part_id}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as jf:
                        json_data = json.load(jf)
                    json_str = json.dumps(json_data, ensure_ascii=False)
                except Exception:
                    json_str = "JSON_READ_ERROR"

            line_parts = [
                part_id,
                details.get("brief", "N/A").replace('\n', ' '),
                details.get("bbox", "N/A"),
                details.get("mapping", "N/A").replace('\n', '\\n'),
                cmd_set,
                json_str
            ]
            test_set_lines.append(";".join(line_parts))

        with open(test_dataset_path, 'w', encoding='utf-8') as f:
            for line in test_set_lines:
                f.write(line + '\n')
        print(f"New test set saved to: {test_dataset_path} ({len(test_set_lines)} items)")
    else:
        print("Skipping test set file creation as it already exists.")
    print("-" * 30)

    # --- 4. Initialize training dataset lists and AI instructions ---
    dataset_step1, dataset_step2 = [], []
    dataset_step3, dataset_step4 = [], []
    dataset_step5 = []

    instr1_3 = (
        """
As a CAD expert, create a procedural build plan from the provided part description and bounding box.

### Requirements ###
1.  **Logical Flow**: The plan must be geometrically sound, and the steps (`Sketch`, `Extrude`) must be in a logical sequence to build the part.
2.  **Bounding Box Adherence**: The final geometry's external dimensions must strictly match the provided bounding box. Use the bounding box to define the primary feature dimensions.
3.  **Natural Language**: Describe the geometric meaning of operations.
4.  **Conciseness**: Be direct. Do not include any introductory or concluding text. Your response must start directly with the build plan.

### Formatting Rules ###
- **Top-Level Features**: For each feature like `Sketch` or `Extrude`, start a new line with its name in bold (e.g., `**Sketch1**`).
- **Profile Description**: For a `Sketch`, create an indented bullet point for each `Profile` it contains (e.g., `- **Profile1**`). On the same line, describe its geometry, focusing on loop relationships (inner/outer), shapes, and key dimensions (e.g., "side length X", "radius Y").
- **Extrude Description**: For an `Extrude` feature, add a colon and the description on the same line as its name. The description must specify the referenced profile, the operation (new body, join, cut), direction, and distance.
        """
    )
    instr2 = (
        "Task: Generate a complete, precise, and parametric JSON modeling sequence based on the provided Build Plan. Your output must strictly adhere to the following rules:\n"
        "1. **Adherence to Plan**: Strictly and faithfully follow every step, operation, and sequence defined in the 'Build Plan'. Not only the profile itself, but also all the points and curves used within it must be defined. Do not add, omit, or alter the modeling process.\n"
        "2. **JSON Structure Integrity**: The root of each JSON file should be 'entities' ONLY. The 'entities' section is a library of all individual modeling features, such as 'Sketch' and 'Extrude'."
        "3. **Parameter Integrity**: Provide correct values for all fields in the JSON structure (including numerical values, attributes, and references). No placeholders or missing parameters are permitted. Ensure all entity references are correct.\n"
        "4. **Geometric & Numerical Accuracy**: The geometric logic must be flawless: profiles must be closed, constituent curves must connect sequentially (head-to-tail), and the number and type of points/curves defined must match the Build Plan.\n"
        "5. **Structural & Syntactic Correctness**: Strictly adhere to the predefined JSON structure, naming conventions, and official terminology. Do not add or remove fields or invent terms. The final output must be a single, valid JSON object.\n"
    )
    instr4 = (
        """
Task: Convert the CAD Build Plan into a structured, machine-readable command set.

### Rules ###
1.  **Direct Translation**: Faithfully translate every step from the Build Plan into its corresponding command format.
2.  **Geometric Continuity**: The multiple curve segments that form a profile must be connected head-to-tail by their coordinates.
3.  **Strict Syntax**: Adhere strictly to the command syntax, parameters, and ordering defined in the reference below.
4.  **Completeness**: Ensure every detail from the Build Plan (dimensions, references, operations) is represented in the final instruction set.
5.  **Conciseness**: Your response must contain only the command set. Do not include any other text, comments, or explanations.

### Command Reference ###
- **`S (sketch_id)`**: Marks the beginning of a new sketch. `sketch_id` is a natural number (1, 2, ...).
- **`P (profile_id)`**: Marks the beginning of a new profile within a sketch. `profile_id` is a natural number.
- **`O (is_outer)`**: Defines the loop type for the current profile. `is_outer` is `true` (outer loop) or `false` (inner loop).
- **`L (x1, y1, x2, y2)`**: Defines a straight line using absolute start (x1, y1) and end (x2, y2) coordinates.
- **`A (x1, y1, x2, y2, cx, cy, rvx, rvy, r, sa, ea)`**: Defines an arc with start/end points, center, reference vector, radius, and start/end angles.
- **`C (cx, cy, r)`**: Defines a full circle with center (cx, cy) and radius (r).
- **`T (ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)`**: Defines the 3D spatial pose (origin and axis vectors) of the current sketch.
- **`E (profile_id, sketch_id, operation, type, d1, d2)`**: Defines an extrusion feature.
        """
    )
    instr5 = (
        """
Task: Generate a structured, machine-readable command set directly from a CAD part description and its bounding box.

### Requirements ###
1.  **Direct Generation**: Infer the geometric steps and translate them directly into the specified command format.
2.  **Bounding Box Adherence**: The commands must produce a model whose final dimensions strictly match the provided bounding box.
3.  **Geometric Continuity**: The multiple curve segments that form a profile must be connected head-to-tail by their coordinates.
4.  **Strict Syntax**: Adhere strictly to the command syntax, parameters, and ordering defined in the reference below.
5.  **Conciseness**: Your response must contain only the command set. Do not include any other text, comments, or explanations.

### Command Reference ###
- **`S (sketch_id)`**: Marks the beginning of a new sketch. `sketch_id` is a natural number (1, 2, ...).
- **`P (profile_id)`**: Marks the beginning of a new profile within a sketch. `profile_id` is a natural number.
- **`O (is_outer)`**: Defines the loop type for the current profile. `is_outer` is `true` (outer loop) or `false` (inner loop).
- **`L (x1, y1, x2, y2)`**: Defines a straight line using absolute start (x1, y1) and end (x2, y2) coordinates.
- **`A (x1, y1, x2, y2, cx, cy, rvx, rvy, r, sa, ea)`**: Defines an arc with start/end points, center, reference vector, radius, and start/end angles.
- **`C (cx, cy, r)`**: Defines a full circle with center (cx, cy) and radius (r).
- **`T (ox, oy, oz, xx, xy, xz, yx, yy, yz, zx, zy, zz)`**: Defines the 3D spatial pose (origin and axis vectors) of the current sketch.
- **`E (profile_id, sketch_id, operation, type, d1, d2)`**: Defines an extrusion feature.
        """
    )

    # --- 5. Iterate through training IDs to generate five-step training samples ---
    print("Generating all five-step training samples for the training set...")
    data_dir = os.path.join(base_dir, "compressed_json")

    for part_id in train_part_ids:
        details = all_desc_map.get(part_id)
        if not details: continue

        brief_desc = details.get("brief", "")
        bbox_info = details.get("bbox", "")
        mapping_steps = details.get("mapping", "")

        # Create input for steps 1 & 3
        input_for_step1_3 = (
            f"Task: Infer a detailed, precise, and procedural build plan from a brief part description and its bounding box. Provide only the plan itself, strictly following all rules.\n\n"
            f"Description: {brief_desc}\n"
            f"Bounding box: {bbox_info}\n"
        )

        # Create separate input for step 5
        input_for_step5 = (
            f"Task: Infer the geometric modeling steps and generate a structured, machine-readable command set from the following part description and bounding box. Provide only the command set, strictly following all rules.\n\n"
            f"Description: {brief_desc}\n"
            f"Bounding box: {bbox_info}\n"
        )

        json_path = os.path.join(data_dir, f"{part_id}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    json_data = json.load(jf)
                output_for_step2 = json.dumps({"entities": json_data.get("entities", {})}, ensure_ascii=False, indent=2)
                dataset_step1.append({"instruction": instr1_3, "input": input_for_step1_3, "output": mapping_steps})
                input_for_step2 = (
                    f"Task: Generate a complete, precise, and parametric JSON modeling sequence based on the provided Build Plan. Do not include any comments, explanations, or any other extraneous text.\n\n"
                    f"--- Build Plan ---\n"
                    f"{mapping_steps}"
                )
                dataset_step2.append({"instruction": instr2, "input": input_for_step2, "output": output_for_step2})
            except Exception as e:
                print(f"[Error] Failed to process JSON file for part {part_id} ({json_path}): {e}")

        txt_path = os.path.join(data_dir, f"{part_id}.txt")
        if os.path.exists(txt_path):
            try:
                with open(txt_path, 'r', encoding='utf-8') as tf:
                    output_for_step4_5 = tf.read()
                dataset_step3.append({"instruction": instr1_3, "input": input_for_step1_3, "output": mapping_steps})
                input_for_step4 = (
                    f"Task: Convert the CAD Build Plan into a structured, machine-readable command set.\n\n"
                    f"--- Build Plan ---\n"
                    f"{mapping_steps}"
                )
                dataset_step4.append({"instruction": instr4, "input": input_for_step4, "output": output_for_step4_5})
                dataset_step5.append({"instruction": instr5, "input": input_for_step5, "output": output_for_step4_5})
            except Exception as e:
                print(f"[Error] Failed to process TXT file for part {part_id} ({txt_path}): {e}")

    print(f"Processed {len(train_part_ids)} training IDs, generating {len(dataset_step1)} valid samples.")

    # --- 6. Save all training datasets ---
    outputs = {
        "combined_dataset_step1.jsonl": dataset_step1,
        "combined_dataset_step2.jsonl": dataset_step2,
        "combined_dataset_step3.jsonl": dataset_step3,
        "combined_dataset_step4.jsonl": dataset_step4,
        "combined_dataset_step5.jsonl": dataset_step5,
    }

    print("-" * 30)
    print("\nSaving all training datasets...")
    for filename, data in outputs.items():
        out_path = os.path.join(base_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"  -> {filename} (Sample count: {len(data)})")

    print("\nDataset generation complete.")


if __name__ == "__main__":
    main()
