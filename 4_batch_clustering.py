import os
import time
from collections import defaultdict
from google import genai
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib

# --- Configuration Parameters ---
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"  # Please replace with your actual Gemini API Key
client = genai.Client(api_key=GEMINI_API_KEY)

INPUT_FILE = "labels.txt"
OUTPUT_DIR = "categorized_parts"
BATCH_SIZE = 100
MAX_RETRIES = 5
TOP_N_CATEGORIES_FOR_RECHECK = 5
STEP_FILES_DIR = "compressed_json"  # Directory where STEP files are stored

failed_items = []
recheck_failed_items = []

# --- Category List (Simplified - No Descriptions) ---
CATEGORIES_WITH_DESCRIPTIONS = [
    "non-mechanical parts", "multiple separate parts",
    "screws", "nuts", "clips",
    "bearings", "shafts/cylinders", "gaskets/washers",
    "brackets", "plates/disks", "beams", "housings/bushings",
    "frames", "shells", "panels",
    "gears", "pulleys",
    "blocks", "pipes", "handles",
    "levers", "linkages", "flanges", "couplings"
]

CATEGORIES = CATEGORIES_WITH_DESCRIPTIONS
CATEGORY_NUMBER_MAP = {i + 1: name for i, name in enumerate(CATEGORIES_WITH_DESCRIPTIONS)}
CATEGORY_NAME_TO_NUMBER_MAP = {name: i + 1 for i, name in enumerate(CATEGORIES_WITH_DESCRIPTIONS)}

# Build a string of numbered categories without descriptions for the prompt.
NUMBERED_CATEGORIES_STR = '\n'.join(
    [f"{i + 1}. {name}" for i, name in enumerate(CATEGORIES_WITH_DESCRIPTIONS)]
)


# --- Function: Calculate Bounding Box of a STEP file ---
def calculate_bbox(step_file_path):
    """Calculates the bounding box dimensions of a STEP file."""
    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(step_file_path)
        if status != IFSelect_RetDone:
            raise ValueError(f"STEP file reading failed (status code: {status})")

        reader.TransferRoots()
        shape = reader.Shape()

        bbox = Bnd_Box()
        brepbndlib.Add(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        x_size = round(xmax - xmin, 4)
        y_size = round(ymax - ymin, 4)
        z_size = round(zmax - zmin, 4)
        return f"X={x_size},Y={y_size},Z={z_size}"
    except Exception as e:
        print(f"Failed to calculate bounding box for: {step_file_path}, Error: {str(e)}")
        return "X=0,Y=0,Z=0"  # Return a default value on failure.


# --- Function: Get or Calculate Bounding Box Size ---
def get_bbox_size(part_id):
    """Gets or calculates the bounding box size for a part."""
    step_file = os.path.join(STEP_FILES_DIR, f"{part_id}.step")
    if os.path.exists(step_file):
        return calculate_bbox(step_file)
    else:
        print(f"Warning: STEP file not found: {step_file}")
        return "X=0,Y=0,Z=0"


# --- UPDATED PROMPT TEMPLATES ---
PROMPT_TEMPLATE = f"""
You are an expert in mechanical component classification. You will receive a list of CAD part numbers, their semantic tags, and descriptions.

Your task is to precisely categorize each part into one of the types based on the predefined list below. 
**Maintain the original semantic tag and description for each part exactly as they appear in the input; do not alter or rephrase them.**

Valid component categories (choose only from this numbered list):
{NUMBERED_CATEGORIES_STR}

Classification rules:
1. Each part must belong to exactly one category from the list above.
2. Consider both the structured tags and descriptive text for classification.
3. Do not invent new categories. Use only the provided category numbers.
4. Do not use vague terms like "Other", "Miscellaneous", or "General".
5. Do not include any explanation or commentary. Output only the classified part information.
6. All part numbers and their corresponding tags and descriptions from the input must appear exactly once in the output. Do not skip, hallucinate, or alter parts or their information.

Output format (strictly adhere to this format: PartNumber: Tag: Description: CategoryNumber):
PartNumber: Tag: Description: CategoryNumber
PartNumber: Tag: Description: CategoryNumber
...

Input:
{{batch_text}}
"""

RECHECK_PROMPT_TEMPLATE = f"""
You are an expert in mechanical component classification. You will receive a list of CAD part numbers, their semantic tags, descriptions, and a suggested category.

Your task is to re-evaluate if each part truly belongs to its suggested category. If it does not, you must re-categorize it into one of the valid component categories from the list below. 
**Maintain the original semantic tag and description for each part exactly as they appear in the input; do not alter or rephrase them.**

Valid component categories (choose only from this numbered list):
{NUMBERED_CATEGORIES_STR}

Classification rules:
1. For each part, if it belongs to the suggested category, output that category number.
2. If a part does NOT belong to its suggested category, choose exactly one category from the provided numbered list that it *does* belong to.
3. Consider both the structured tags and descriptive text for re-evaluation.
4. Do not invent new categories. Use only the provided category numbers.
5. Do not use vague terms like "Other", "Miscellaneous", or "General".
6. Do not include any explanation or commentary. Output only the classified part information.
7. All part numbers and their corresponding tags and descriptions from the input must appear exactly once in the output. Do not skip, hallucinate, or alter parts or their information.

Output format (strictly adhere to this format: PartNumber: Tag: Description: CategoryNumber):
PartNumber: Tag: Description: CategoryNumber
PartNumber: Tag: Description: CategoryNumber
...

Input:
{{batch_text}}
"""

# --- Read Data ---
try:
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print(f"Error: Input file '{INPUT_FILE}' not found. Please ensure the file exists.")
    exit()

# --- Prepare Output Directory and Files ---
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Clear all .txt files in the output directory before starting.
print(f"\nClearing all .txt files in '{OUTPUT_DIR}'...")
for filename in os.listdir(OUTPUT_DIR):
    if filename.endswith(".txt"):
        file_path = os.path.join(OUTPUT_DIR, filename)
        try:
            os.remove(file_path)
            print(f"  Removed: {filename}")
        except OSError as e:
            print(f"  Could not remove {filename}: {e}")


# --- Processing Function ---
def process_batch(batch_input_lines, batch_context_id, prompt_template, validation_strictness='initial'):
    """
    Processes a single batch of part labels, categorizes them using the Gemini API,
    and validates the output. Can be used for initial classification or recheck.

    Args:
        batch_input_lines (list): A list of raw part label lines for the current batch.
                                  For initial: 'PartNumber;Tag;Description'
                                  For recheck: 'PartId: Tag: Description: SuggestedCategoryNumber'
        batch_context_id (str): A string identifier for the batch (e.g., 'Initial Batch 1', 'Recheck Category X Batch 2').
        prompt_template (str): The prompt template to use (PROMPT_TEMPLATE or RECHECK_PROMPT_TEMPLATE).
        validation_strictness (str): 'initial' for initial classification validation,
                                     'recheck' for recheck validation.

    Returns:
        list: A list of (part_id, tag, description, category_num, original_full_line) tuples if successful,
              or None if the batch failed after all retries.
    """
    original_part_data_map = {}  # {part_id: {'full_line': original_line, 'tag': tag, 'description': description}}
    batch_text_for_prompt = []  # 'PartNumber: Tag: Description' or 'PartNumber: Tag: Description: SuggestedCategoryNumber'

    if validation_strictness == 'initial':
        for line in batch_input_lines:
            # Format: part_id;tag;description
            parts = line.split(';', 2)
            if len(parts) < 3:
                print(f"Warning: Malformed input line: '{line}'. Skipping.")
                continue

            part_id = parts[0].strip()
            tag = parts[1].strip()
            description = parts[2].strip()

            original_part_data_map[part_id] = {
                'full_line': line,
                'tag': tag,
                'description': description
            }
            batch_text_for_prompt.append(f"{part_id}: {tag}: {description}")

    elif validation_strictness == 'recheck':
        # batch_input_lines are tuples: (part_id, tag, description, suggested_category_num, original_full_line)
        for part_data_tuple in batch_input_lines:
            part_id, tag, description, suggested_category_num, original_full_line = part_data_tuple
            original_part_data_map[part_id] = {
                'full_line': original_full_line,
                'tag': tag,
                'description': description,
                'suggested_category_num': suggested_category_num
            }
            batch_text_for_prompt.append(f"{part_id}: {tag}: {description}: {suggested_category_num}")
    else:
        raise ValueError("Invalid validation_strictness. Must be 'initial' or 'recheck'.")

    original_ids = set(original_part_data_map.keys())
    batch_text = '\n'.join(batch_text_for_prompt)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\nProcessing {batch_context_id} (Attempt {attempt} / {MAX_RETRIES})...")
        prompt = prompt_template.format(batch_text=batch_text)

        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[prompt]
            )
            result = response.text.strip()

            parsed_items_for_batch = []
            output_ids = set()

            lines_in_output = result.splitlines()
            if not lines_in_output:
                print(f"{batch_context_id} returned an empty response. Retrying...")
                continue

            for line in lines_in_output:
                line = line.strip()
                if not line:
                    continue

                # Split into 4 parts: PartNumber, Tag, Description, CategoryNumber
                parts = line.split(':', 3)
                if len(parts) == 4:
                    part_id = parts[0].strip()
                    tag = parts[1].strip()
                    description = parts[2].strip()
                    try:
                        category_num = int(parts[3].strip())

                        if category_num in CATEGORY_NUMBER_MAP:
                            if part_id in original_part_data_map:
                                orig_data = original_part_data_map[part_id]
                                # Validate that both tag and description match the original input.
                                if orig_data['tag'] == tag and orig_data['description'] == description:
                                    if validation_strictness == 'recheck':
                                        print(
                                            f"  Recheck: Part {part_id} - Original: {orig_data.get('suggested_category_num', 'N/A')}, New: {category_num}")

                                    parsed_items_for_batch.append(
                                        (part_id, tag, description, category_num, orig_data['full_line']))
                                    output_ids.add(part_id)
                                else:
                                    print(f"{batch_context_id}: Tag or description mismatch for part '{part_id}'.")
                                    print(f"  Original tag: '{orig_data['tag']}', Output tag: '{tag}'")
                                    print(
                                        f"  Original description: '{orig_data['description']}', Output description: '{description}'")
                                    parsed_items_for_batch = []
                                    break
                            else:
                                print(
                                    f"{batch_context_id}: Unexpected part ID '{part_id}' found in output. Retrying batch...")
                                parsed_items_for_batch = []
                                break
                        else:
                            print(
                                f"{batch_context_id}: Invalid category number '{category_num}' found in output. Retrying batch...")
                            parsed_items_for_batch = []
                            break
                    except ValueError:
                        print(f"{batch_context_id}: Malformed category number in line: '{line}'. Retrying batch...")
                        parsed_items_for_batch = []
                        break
                else:
                    print(
                        f"{batch_context_id}: Incorrect output line format: '{line}'. Expected 4 parts, got {len(parts)}. Retrying batch...")
                    parsed_items_for_batch = []
                    break

            # If parsing failed for any line in the output, retry the whole batch.
            if not parsed_items_for_batch and len(result.strip()) > 0:
                continue

            # --- Final Validation: Check for Missing and Extra Part IDs ---
            missing_ids = original_ids - output_ids
            extra_ids = output_ids - original_ids

            if missing_ids or extra_ids:
                print(f"{batch_context_id} validation failed: Part ID mismatch.")
                if missing_ids:
                    print("  Missing part IDs:", missing_ids)
                if extra_ids:
                    print("  Unexpected part IDs:", extra_ids)

                if attempt == MAX_RETRIES:
                    print(
                        f"{batch_context_id} reached max retries due to part mismatch. Adding failed parts to respective lists.")
                    # Add only the actually missing parts to the global failed_items list.
                    target_failed_list = recheck_failed_items if validation_strictness == 'recheck' else failed_items
                    for p_id in missing_ids:
                        target_failed_list.append(original_part_data_map[p_id]['full_line'])
                    return None
                print("Retrying due to mismatch...")
                continue

            print(f"{batch_context_id} passed validation.")
            return parsed_items_for_batch

        except Exception as e:
            print(f"{batch_context_id} API or other error: {e}")
            time.sleep(min(2 ** attempt, 60))  # Exponential backoff
            if attempt == MAX_RETRIES:
                print(f"API error reached max retries for {batch_context_id}. Skipping.")
                target_failed_list = recheck_failed_items if validation_strictness == 'recheck' else failed_items
                target_failed_list.extend([original_part_data_map[p_id]['full_line'] for p_id in original_ids])
                return None
            print("Retrying due to API or other error...")
            continue
    return None


# --- Main Processing Logic ---
all_classified_parts_data = defaultdict(
    list)  # Stores (part_id, tag, description, category_num, original_line) grouped by category_num

print("\nStarting initial batch processing of part labels...")
for i in range(0, len(lines), BATCH_SIZE):
    batch = lines[i:i + BATCH_SIZE]
    batch_context_id = f"Initial Batch {i // BATCH_SIZE + 1}"
    classified_items = process_batch(
        batch_input_lines=batch,
        batch_context_id=batch_context_id,
        prompt_template=PROMPT_TEMPLATE,
        validation_strictness='initial'
    )
    if classified_items:
        for part_id, tag, description, category_num, original_line in classified_items:
            all_classified_parts_data[category_num].append((part_id, tag, description, category_num, original_line))

# --- Secondary Check Logic ---
print("\n--- Starting Secondary Check ---")

if not all_classified_parts_data:
    print("No parts were initially classified successfully. Skipping secondary check.")
else:
    # Count parts per category.
    category_counts = {cat_num: len(parts) for cat_num, parts in all_classified_parts_data.items()}

    # Get top N categories for recheck.
    sorted_categories = sorted(category_counts.items(), key=lambda item: item[1], reverse=True)
    top_n_category_nums = [cat_num for cat_num, count in sorted_categories[:TOP_N_CATEGORIES_FOR_RECHECK]]

    print(f"Identified top {TOP_N_CATEGORIES_FOR_RECHECK} categories for recheck: "
          f"{[CATEGORY_NUMBER_MAP[cn] for cn in top_n_category_nums if cn in CATEGORY_NUMBER_MAP]}")

    # Create a temporary structure to hold parts during rechecking.
    reclassified_parts_temp = defaultdict(list)
    for cat_num, parts_list in all_classified_parts_data.items():
        reclassified_parts_temp[cat_num].extend(parts_list)

    # Prepare parts from top categories for rechecking in batches.
    parts_for_recheck_batches = []
    for current_category_num in top_n_category_nums:
        if current_category_num in reclassified_parts_temp:
            parts_in_category = list(reclassified_parts_temp[current_category_num])
            for part_data in parts_in_category:
                part_id, tag, description, category_num, original_line = part_data
                parts_for_recheck_batches.append((part_id, tag, description, category_num, original_line))

    # List to store reclassification decisions.
    reclassification_decisions = []

    if not parts_for_recheck_batches:
        print("No parts found in top categories for recheck.")
    else:
        print(f"Total {len(parts_for_recheck_batches)} parts identified for batch recheck.")
        for i in range(0, len(parts_for_recheck_batches), BATCH_SIZE):
            recheck_batch = parts_for_recheck_batches[i:i + BATCH_SIZE]
            batch_context_id = f"Recheck Batch {i // BATCH_SIZE + 1}"

            rechecked_items = process_batch(
                batch_input_lines=recheck_batch,
                batch_context_id=batch_context_id,
                prompt_template=RECHECK_PROMPT_TEMPLATE,
                validation_strictness='recheck'
            )

            if rechecked_items:
                for part_id, tag, description, new_category_num, original_line in rechecked_items:
                    # Find the original part data to get its current category.
                    current_category_num = None
                    for p_data_in_batch in recheck_batch:
                        if p_data_in_batch[0] == part_id and p_data_in_batch[1] == tag and p_data_in_batch[
                            2] == description:
                            current_category_num = p_data_in_batch[3]
                            break

                    if current_category_num is not None and current_category_num != new_category_num:
                        # This part needs to be moved.
                        reclassification_decisions.append(
                            ((part_id, tag, description, original_line), current_category_num, new_category_num)
                        )
                        print(
                            f"  Decision: Part '{part_id}' to move from {CATEGORY_NUMBER_MAP.get(current_category_num, 'Unknown')} "
                            f"to {CATEGORY_NUMBER_MAP.get(new_category_num, 'Unknown')}.")
                    elif current_category_num is not None and current_category_num == new_category_num:
                        print(
                            f"  Part '{part_id}' confirmed to be in category {CATEGORY_NUMBER_MAP.get(current_category_num, 'Unknown')}.")
                    else:
                        print(
                            f"  Warning: Could not determine current category for rechecked part '{part_id}' or recheck failed.")

    # Apply all collected reclassification decisions after all recheck batches are processed.
    if reclassification_decisions:
        print("\nApplying all reclassification decisions...")
        for part_data, old_cat_num, new_cat_num in reclassification_decisions:
            part_id, tag, description, original_line = part_data
            # Ensure the part is still in the old category before attempting to move.
            if any(item[0] == part_id for item in reclassified_parts_temp[old_cat_num]):
                # Remove from old category.
                reclassified_parts_temp[old_cat_num] = [item for item in reclassified_parts_temp[old_cat_num] if
                                                        item[0] != part_id]
                # Add to new category.
                reclassified_parts_temp[new_cat_num].append((part_id, tag, description, new_cat_num, original_line))
                print(f"  Applied move for '{part_id}' from {CATEGORY_NUMBER_MAP.get(old_cat_num, 'Unknown')} "
                      f"to {CATEGORY_NUMBER_MAP.get(new_cat_num, 'Unknown')}.")
            else:
                print(
                    f"  Warning: Part '{part_id}' not found in its expected old category {CATEGORY_NUMBER_MAP.get(old_cat_num, 'Unknown')} during final move. Skipping.")

    # After all recheck batches and moves, update the main classified data.
    all_classified_parts_data = reclassified_parts_temp

# --- Final File Writing with Bounding Box ---
print("\nWriting all categorized parts to files with bounding box sizes...")
# Clear files again before final write to ensure clean output.
for i in range(1, len(CATEGORIES) + 1):
    category_name = CATEGORY_NUMBER_MAP[i]
    output_file_name = f"category_{i}_{category_name.replace(' ', '_').replace('/', '_')}.txt"
    output_path = os.path.join(OUTPUT_DIR, output_file_name)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            print(f"Could not clear file {output_path}: {e}")

for category_num, parts_list in all_classified_parts_data.items():
    if not parts_list:
        continue  # Skip empty categories.

    category_name = CATEGORY_NUMBER_MAP[category_num]
    output_file_name = f"category_{category_num}_{category_name.replace(' ', '_').replace('/', '_')}.txt"
    output_path = os.path.join(OUTPUT_DIR, output_file_name)
    with open(output_path, 'a', encoding='utf-8') as out:
        for part_data in parts_list:  # (part_id, tag, description, category_num, original_line)
            # Get the bounding box size.
            bbox_size = get_bbox_size(part_data[0])
            # Append the bounding box size to the description.
            out.write(f"{part_data[0]}: {part_data[1]}: {part_data[2]}: {bbox_size}: {part_data[3]}\n")
    print(f"Wrote {len(parts_list)} items to {output_file_name} (with bounding box)")

# --- Handle Failed Items ---
if failed_items:
    print(f"\n{len(failed_items)} parts could not be successfully categorized during initial processing.")
    unprocessed_file_path = os.path.join(OUTPUT_DIR, "unprocessed_items_initial_failure.txt")
    with open(unprocessed_file_path, 'w', encoding='utf-8') as f:
        for item in failed_items:
            f.write(item + '\n')
    print(f"These parts have been saved to '{unprocessed_file_path}' for your manual review.")

if recheck_failed_items:
    print(f"\n{len(recheck_failed_items)} parts failed secondary recheck.")
    recheck_unprocessed_file_path = os.path.join(OUTPUT_DIR, "unprocessed_items_recheck_failure.txt")
    with open(recheck_unprocessed_file_path, 'w', encoding='utf-8') as f:
        for item in recheck_failed_items:
            f.write(item + '\n')
    print(f"These parts have been saved to '{recheck_unprocessed_file_path}' for your manual review.")

if not failed_items and not recheck_failed_items:
    print("\nAll parts processed and rechecked successfully.")
