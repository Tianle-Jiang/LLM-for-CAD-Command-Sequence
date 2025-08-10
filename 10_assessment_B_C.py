import os
import re
import shutil
import difflib
import json
import pandas as pd
import traceback
from typing import List, Dict, Any, Tuple, Optional

# --- Stage 1: Import and Configure All Necessary External Modules ---

# Attempt to import the reconstruction module
try:
    import reconstruction
    RECONSTRUCTION_MODULE_AVAILABLE = True
    # Key: Disable interactive display in the reconstruction module for automated execution
    reconstruction.display_available = False
    print("Successfully imported and configured the reconstruction module.")
except ImportError:
    print("Warning: reconstruction.py not found. Model reconstruction will be unavailable.")
    RECONSTRUCTION_MODULE_AVAILABLE = False

# Set environment variable for offscreen rendering before importing any OCC/Display modules
os.environ['PYTHONOCC_OFFSCREEN_RENDERING'] = "1"

# Attempt to import the decoder
try:
    from decode_json import decompress_to_json_with_validation
    DECODER_AVAILABLE = True
    print("Successfully imported validation decoder.")
except ImportError:
    print("Error: 'decode_json.py' not found. Please place it in the same directory.")
    DECODER_AVAILABLE = False

# Attempt to import OCC (python-occ-core)
try:
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Display.SimpleGui import init_display
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB, Quantity_NOC_BLACK
    from OCC.Core.Aspect import Aspect_TOL_SOLID
    from OCC.Core.Prs3d import Prs3d_LineAspect
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib_Add
    OCC_AVAILABLE = True
    print("Successfully imported python-occ-core.")
except ImportError:
    OCC_AVAILABLE = False
    print("Warning: python-occ-core library not found. Image saving and BBox calculation will be unavailable.")

# Attempt to import Pillow for image stitching
try:
    from PIL import Image
    PIL_AVAILABLE = True
    print("Successfully imported Pillow (PIL) for image stitching.")
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: Pillow (PIL) library not found. Image stitching will be unavailable.")


# --- Stage 2: Core Utility Functions ---

def clear_previous_results(output_dir: str, csv_path: str):
    """Clears result files and directories from the previous run."""
    print(f"Clearing previous results for '{output_dir}'...")
    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
            print(f"  -> Successfully deleted directory: {output_dir}")
        except OSError as e:
            print(f"  -> Error deleting directory {output_dir}: {e.strerror}")
    if os.path.exists(csv_path):
        try:
            os.remove(csv_path)
            print(f"  -> Successfully deleted file: {csv_path}")
        except OSError as e:
            print(f"  -> Error deleting file {csv_path}: {e.strerror}")
    os.makedirs(output_dir, exist_ok=True)
    print("Cleanup complete.")


def clean_response_text(raw_text: str) -> str:
    """
    Filters the raw response string to keep only valid-looking command lines.
    This function removes extra natural language descriptions and redundant empty lines.
    """
    cleaned_lines = []
    command_pattern = re.compile(r'^\s*[\-]*\s*[A-Z]\s*\(')
    for line in raw_text.splitlines():
        if command_pattern.match(line):
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def load_ground_truth_bbox(file_path: str) -> Dict[str, Dict[str, float]]:
    """Loads ground truth bounding box dimensions from the description file."""
    bbox_data = {}
    if not os.path.exists(file_path):
        print(f"Warning: Bounding box description file not found at '{file_path}'. Cannot calculate BBox similarity.")
        return bbox_data
    bbox_regex = re.compile(r"X=([\d.]+),Y=([\d.]+),Z=([\d.]+)")
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(';', 3)
            if len(parts) == 4:
                part_id, _, _, bbox_str = parts
                match = bbox_regex.match(bbox_str)
                if match:
                    x, y, z = map(float, match.groups())
                    bbox_data[part_id] = {"X": x, "Y": y, "Z": z}
    print(f"Successfully loaded ground truth bounding boxes for {len(bbox_data)} parts.")
    return bbox_data


def get_shape_bbox_dimensions(shape: "TopoDS_Shape") -> Optional[Dict[str, float]]:
    """Calculates the bounding box dimensions of a given OCC shape."""
    if not OCC_AVAILABLE or not shape or shape.IsNull(): return None
    bbox = Bnd_Box()
    try:
        brepbndlib_Add(shape, bbox, True)
        if bbox.IsVoid(): return None
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        return {"X": xmax - xmin, "Y": ymax - ymin, "Z": zmax - zmin}
    except Exception as e:
        print(f"      -> An exception occurred during BBox calculation: {e}")
        return None


def calculate_bbox_similarity(recon_dims: Dict[str, float], truth_dims: Dict[str, float]) -> float:
    """Calculates the average similarity between two bounding boxes by comparing their sorted dimensions."""
    recon_sorted = sorted(recon_dims.values())
    truth_sorted = sorted(truth_dims.values())
    total_sim = 0
    for i in range(3):
        d_recon, d_truth = recon_sorted[i], truth_sorted[i]
        denominator = max(d_recon, d_truth)
        sim = 1 - (abs(d_recon - d_truth) / denominator) if denominator > 1e-6 else 1.0
        total_sim += sim
    return total_sim / 3


def save_shape_as_image(display, shape: "TopoDS_Shape", image_path: str, part_id: str, reference_image_dir: str):
    """
    Saves the successfully reconstructed 3D model as a PNG image.
    If a reference image is found, it stitches it with the newly generated image.
    """
    if not OCC_AVAILABLE or not shape or shape.IsNull() or display is None: return

    temp_image_path = image_path.replace(".png", "_temp_generated.png")
    try:
        display.EraseAll()
        shape_color = Quantity_Color(0.545, 0.271, 0.075, Quantity_TOC_RGB)
        ais_objects = display.DisplayShape(shape, color=shape_color, update=False, transparency=0.6)

        if not isinstance(ais_objects, list): ais_objects = [ais_objects]
        if ais_objects:
            for ais_solid in ais_objects:
                if ais_solid:
                    ais_solid.SetDisplayMode(1)
                    drawer = ais_solid.Attributes()
                    drawer.SetFaceBoundaryDraw(True)
                    line_aspect = Prs3d_LineAspect(Quantity_Color(Quantity_NOC_BLACK), Aspect_TOL_SOLID, 2.5)
                    drawer.SetLineAspect(line_aspect)
        display.FitAll()
        display.View.Redraw()

        if not display.View.Dump(str(temp_image_path)):
            print(f"      -> FAILED to save temporary image: {temp_image_path}")
            return
    except Exception as e:
        print(f"      -> An exception occurred while generating the shape image: {e}")
        traceback.print_exc()
        return

    if not PIL_AVAILABLE:
        os.rename(temp_image_path, image_path)
        print(f"      -> Pillow not available. Saved single image to: {image_path}")
        return

    reference_path = os.path.join(reference_image_dir, f"{part_id}.png")

    try:
        if not os.path.exists(reference_path):
            os.rename(temp_image_path, image_path)
            print(f"      -> Reference image not found at '{reference_path}'. Saving generated image only.")
            return

        generated_img = Image.open(temp_image_path)
        reference_img = Image.open(reference_path)

        h_gen, h_ref = generated_img.height, reference_img.height
        if h_gen != h_ref:
            target_height = max(h_gen, h_ref)
            if generated_img.height != target_height:
                ratio = target_height / generated_img.height
                generated_img = generated_img.resize((int(generated_img.width * ratio), target_height), Image.LANCZOS)
            if reference_img.height != target_height:
                ratio = target_height / reference_img.height
                reference_img = reference_img.resize((int(reference_img.width * ratio), target_height), Image.LANCZOS)

        total_width = reference_img.width + generated_img.width
        max_height = reference_img.height
        combined_img = Image.new('RGBA', (total_width, max_height))
        combined_img.paste(reference_img, (0, 0))
        combined_img.paste(generated_img, (reference_img.width, 0))
        combined_img.save(image_path)
        print(f"      -> Successfully saved combined image to: {image_path}")

    except Exception as e:
        print(f"      -> An exception occurred during image stitching: {e}")
        if os.path.exists(temp_image_path):
            os.rename(temp_image_path, image_path)
    finally:
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)


def validate_response_format(response_text: str) -> Tuple[bool, str]:
    """Checks if each line of the response conforms to the precise format of a compressed command."""
    if not response_text.strip():
        return False, "Response is empty."
    lines = [line for line in response_text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        line = line.strip()
        match = re.match(r'^[ \-]*([A-Z]) *\( *(.*?) *\)$', line)
        if not match:
            return False, f"Line {i + 1}: Incorrect base structure: '{line}'."
        command, params_str = match.groups()
        params = []
        if params_str:
            params_list_str = [p.strip() for p in params_str.split(',')]
            for p_str in params_list_str:
                try:
                    params.append(float(p_str))
                except ValueError:
                    params.append(p_str)
        is_valid, error_msg = validate_command_parameters(command, params)
        if not is_valid:
            return False, f"Line {i + 1}, {error_msg}"
    return True, "Format is valid."


def validate_command_parameters(command: str, params: List[Any]) -> Tuple[bool, str]:
    """Validates the parameters of a single command according to predefined rules."""
    rules = {
        'S': (1, [lambda p: isinstance(p, (int, float)) and p > 0]),
        'P': (1, [lambda p: isinstance(p, (int, float)) and p > 0]),
        'O': (1, [lambda p: str(p).lower() in ['true', 'false']]),
        'L': (4, [lambda p: isinstance(p, (int, float))] * 4),
        'C': (3, [lambda p: isinstance(p, (int, float))] * 3),
        'A': (11, [lambda p: isinstance(p, (int, float))] * 11),
        'T': (12, [lambda p: isinstance(p, (int, float))] * 12),
        'E': (6, [
            lambda p: isinstance(p, (int, float)) and p > 0,
            lambda p: isinstance(p, (int, float)) and p > 0,
            lambda p: p in ['New', 'Join', 'Cut'],
            lambda p: p in ['One', 'Two', 'Symmetric'],
            lambda p: isinstance(p, (int, float)),
            lambda p: isinstance(p, (int, float)),
        ])
    }
    if command not in rules: return False, f"Unknown command '{command}'."
    expected_count, check_functions = rules[command]
    if len(params) != expected_count: return False, f"Command '{command}': Expected {expected_count} parameters, but got {len(params)}."
    for i, (param, check_func) in enumerate(zip(params, check_functions)):
        if not check_func(param): return False, f"Command '{command}', parameter {i + 1}: Invalid type or value '{param}'."
    return True, ""


def evaluate_response(response_text: str) -> Dict[str, Any]:
    """
    Executes the full evaluation pipeline: Format -> Decode -> Reconstruct.
    This version runs in a single process to avoid multiprocessing resource conflicts.
    """
    is_valid, error_message = validate_response_format(response_text)
    if not is_valid:
        return {"score": 0.0, "data": error_message, "reconstructed_shape": None, "details": error_message}

    lines = response_text.strip().splitlines()
    decode_result = decompress_to_json_with_validation(lines)
    if not decode_result['success']:
        return {"score": 0.0, "data": decode_result['data'], "reconstructed_shape": None,
                "details": decode_result['data']}

    decoded_json = decode_result['data']

    if not RECONSTRUCTION_MODULE_AVAILABLE:
        return {"score": 0.5, "data": decoded_json, "details": "Reconstruction module not available.",
                "reconstructed_shape": None}

    reconstructed_shape = None
    details = ""
    score = 0.5

    try:
        shape = reconstruction.build_model_from_data(decoded_json)
        if shape and not shape.IsNull():
            score = 1.0
            reconstructed_shape = shape
            details = "Reconstruction successful."
        else:
            details = "Reconstruction resulted in a null shape."
    except Exception as e:
        details = f"Reconstruction failed with exception: {e}"
        print(f"      -> Reconstruction Error: {e}")

    return {"score": score, "data": decoded_json, "details": details, "reconstructed_shape": reconstructed_shape}


def get_string_similarity(str1: str, str2: str) -> float:
    """Calculates the similarity ratio between two strings."""
    str1_cleaned = "\n".join([line.strip() for line in str1.splitlines() if line.strip()])
    str2_cleaned = "\n".join([line.strip() for line in str2.splitlines() if line.strip()])
    return difflib.SequenceMatcher(None, str1_cleaned, str2_cleaned).ratio()


def generate_console_report(df: pd.DataFrame, total_parts: int, source_file: str):
    """Prints a formatted evaluation report to the console, including the new scores."""
    if df.empty:
        print("\nNo valid records for analysis. Report not generated.")
        return

    evaluated_parts = len(df)
    avg_score = df['score'].mean()
    avg_bbox_sim = df.loc[df['score'] == 1.0, 'bbox_sim'].mean() if 'bbox_sim' in df.columns and not df[df['score'] == 1.0].empty else 0.0

    dist = df['score'].value_counts().sort_index(ascending=False)

    print("\n" + "=" * 80)
    print(f" Full Pipeline (Decode + Reconstruct) Evaluation Report for: {source_file}")
    print("=" * 80)
    print(f"| {'Overview':<76} |")
    print(f"| {'-' * 76} |")
    print(f"| Total Parts in Source: {total_parts:<10} | Evaluated Parts: {evaluated_parts:<27} |")
    print("=" * 80)
    print(f"| {'Core Metrics':<76} |")
    print(f"| {'-' * 76} |")
    print(f"| Average Score: {avg_score:<.4f}                                                    |")
    if avg_bbox_sim > 0:
        print(f"| Average BBox Similarity (for score=1.0): {avg_bbox_sim:<.4f}                        |")
    print("=" * 80)
    print(f"| {'Score Distribution':<76} |")
    print(f"| {'-' * 76} |")
    print(f"| {'Score':<10} | {'Count':<10} | {'Description':<25} | {'Percentage':<25} |")
    print(f"| {'-' * 10} | {'-' * 10} | {'-' * 25} | {'-' * 25} |")
    score_map = {0.0: "Format/Decode Error", 0.5: "Reconstruct Fail", 1.0: "Reconstruct Success"}
    for score, count in dist.items():
        percent = (count / evaluated_parts) * 100 if evaluated_parts > 0 else 0
        desc = score_map.get(score, "Unknown")
        print(f"| {score:<10.2f} | {count:<10} | {desc:<25} | {f'{percent:.2f}%':<25} |")
    print("=" * 80)


# --- Stage 3: Main Logic ---

def process_evaluation_file(results_file: str, output_dir: str, bbox_ground_truth: Dict,
                            display_context: Optional[Any]):
    """
    Processes a single evaluation file and generates the corresponding results and reports.
    """
    # --- Configuration ---
    ground_truth_dir = "compressed_json"
    output_csv_path = os.path.join(output_dir, "evaluation_summary.csv")

    clear_previous_results(output_dir, output_csv_path)

    if not os.path.exists(results_file):
        print(f"Error: Results file not found at '{results_file}'. Aborting this task.")
        return

    with open(results_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    final_records = []
    total_lines = len(lines)
    print(f"\nFound {total_lines} parts in source file '{results_file}'. Starting full evaluation...")

    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line: continue

        print(f"Processing part {line_num + 1}/{total_lines}...", end='\r')

        try:
            parts = line.split(';', 2)
            if len(parts) != 3:
                print(
                    f"\n  -> Warning: Skipping malformed source line {line_num + 1} (expected 3 parts, got {len(parts)}): {line[:70]}...")
                continue
            part_id, _reference_text, responses_str = parts
            responses = responses_str.split('<|>')
        except ValueError:
            print(f"\n  -> Warning: Skipping malformed source line {line_num + 1}: {line[:50]}...")
            continue

        gt_path = os.path.join(ground_truth_dir, f"{part_id}.txt")
        if not os.path.exists(gt_path):
            continue
        with open(gt_path, 'r', encoding='utf-8') as f_gt:
            ground_truth_text = f_gt.read()

        part_evaluations = []
        for i, res_text in enumerate(responses):
            res_text = res_text.replace('\\n', '\n')
            res_text = clean_response_text(res_text)

            eval_result = evaluate_response(res_text)
            similarity = get_string_similarity(res_text, ground_truth_text)

            record = {
                "part_id": part_id,
                "response_index": i + 1,
                "score": eval_result["score"],
                "similarity": similarity,
                "response_text": res_text,
                "details": eval_result.get("details", ""),
                "decoded_json": eval_result["data"] if eval_result["score"] >= 0.5 else None,
                "reconstructed_shape": eval_result["reconstructed_shape"]
            }

            if record["score"] == 1.0:
                truth_dims = bbox_ground_truth.get(part_id)
                if truth_dims:
                    recon_dims = get_shape_bbox_dimensions(record["reconstructed_shape"])
                    if recon_dims:
                        record["bbox_sim"] = calculate_bbox_similarity(recon_dims, truth_dims)

            part_evaluations.append(record)

        if not part_evaluations: continue

        best_response = max(part_evaluations, key=lambda x: (x["score"], x.get("bbox_sim", 0), x["similarity"]))
        final_records.append(best_response)

        # --- Save Results ---
        score_dir_name = f"{best_response['score']:.1f}"
        target_dir = os.path.join(output_dir, score_dir_name)
        os.makedirs(target_dir, exist_ok=True)
        output_path = os.path.join(target_dir, f"{part_id}.txt")
        with open(output_path, 'w', encoding='utf-8') as f_out:
            f_out.write(best_response['response_text'])

        if best_response['score'] == 1.0:
            success_dir = os.path.join(output_dir, "reconstruction_success")
            os.makedirs(success_dir, exist_ok=True)

            json_output_path = os.path.join(success_dir, f"{part_id}.json")
            with open(json_output_path, 'w', encoding='utf-8') as f_json:
                json.dump(best_response['decoded_json'], f_json, indent=2, ensure_ascii=False)

            if display_context and best_response["reconstructed_shape"]:
                image_path = os.path.join(success_dir, f"{part_id}.png")
                reference_dir = "compressed_json"
                save_shape_as_image(display_context, best_response["reconstructed_shape"], image_path, part_id,
                                    reference_dir)

    print(f"\nEvaluation for '{results_file}' finished.")
    # --- Generate Final Report ---
    df = pd.DataFrame(final_records)

    generate_console_report(df, total_lines, results_file)

    if not df.empty:
        csv_columns = ['part_id', 'score', 'similarity', 'bbox_sim', 'response_index', 'details']
        if 'bbox_sim' not in df.columns:
            df['bbox_sim'] = None
        df_to_save = df[csv_columns]
        df_to_save.to_csv(output_csv_path, index=False)
        print(f"\n✅ Evaluation summary saved to: '{os.path.abspath(output_csv_path)}'")
    else:
        print(f"\nEvaluation for '{results_file}' did not produce any records.")


def main():
    """
    Main execution function, responsible for initializing global resources
    and processing all evaluation tasks in sequence.
    """
    if not DECODER_AVAILABLE:
        print("Decoder module is not available. Aborting all tasks.")
        return

    # --- Global Configuration and Initialization ---
    bbox_file = "descriptions_for_compressed_json.txt"
    bbox_ground_truth = load_ground_truth_bbox(bbox_file)

    display_context = None
    if OCC_AVAILABLE:
        try:
            display_context, _, _, _ = init_display()
            bg_color = Quantity_Color(245 / 255, 245 / 255, 245 / 255, Quantity_TOC_RGB)
            display_context.View.SetBackgroundColor(bg_color)
            print("OCC Display initialized for offscreen rendering.")
        except Exception as e:
            print(f"Could not initialize OCC Display, image saving will be disabled. Error: {e}")
            display_context = None

    # --- Define the list of tasks to process ---
    evaluation_tasks = [
        {"input": "batch_test_results_B.txt", "output": "evaluation_responses_B"},
        {"input": "batch_test_results_C.txt", "output": "evaluation_responses_C"},
    ]

    # --- Loop through and execute each task ---
    for task in evaluation_tasks:
        print("\n" + "#" * 80)
        print(f"# Starting evaluation for: {task['input']} -> {task['output']}")
        print("#" * 80)
        process_evaluation_file(
            results_file=task["input"],
            output_dir=task["output"],
            bbox_ground_truth=bbox_ground_truth,
            display_context=display_context
        )

    print("\n" + "=" * 40 + "\nAll evaluation tasks completed.\n" + "=" * 40)


if __name__ == "__main__":
    if RECONSTRUCTION_MODULE_AVAILABLE and hasattr(reconstruction, 'script_dir'):
        reconstruction.script_dir = os.path.dirname(os.path.abspath(__file__))
    main()
