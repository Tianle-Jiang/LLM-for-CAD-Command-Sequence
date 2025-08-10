# -*- coding: utf-8 -*-
import os
import json
import shutil
import multiprocessing

# --- Step 1: Import all required modules ---
# Try to import custom modules and provide clear error messages on failure.
try:
    from compress_json import compress_cad_json
    from decode_json import decompress_to_json
    # Note: We assume reconstruction.reconstruct_model returns a shape object.
    from reconstruction import reconstruct_model
    import reconstruction  # Import to set module-level variables.
except ImportError as e:
    print(f"Error: Failed to import required modules: {e}")
    print("Please ensure compress_json.py, decode_json.py, and reconstruction.py are in the same directory.")
    exit()

# --- Added: Import modules for image saving ---
# Set environment variable for offscreen rendering. This must be done before importing any OCC/Display modules.
os.environ['PYTHONOCC_OFFSCREEN_RENDERING'] = "1"

# Try to import OCC (python-occ-core).
try:
    from OCC.Core.TopoDS import TopoDS_Shape
    from OCC.Display.SimpleGui import init_display
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB, Quantity_NOC_BLACK
    from OCC.Core.Aspect import Aspect_TOL_SOLID
    from OCC.Core.Prs3d import Prs3d_LineAspect

    OCC_AVAILABLE = True
    print("Successfully imported python-occ-core. Image saving is enabled.")
except ImportError:
    OCC_AVAILABLE = False
    print("Warning: python-occ-core library not found. Image saving feature will be disabled.")

# --- Path Configuration ---
# Source directory containing the original JSON files.
SOURCE_DIR = 'pruned_json'
# Unified processing and output directory for all intermediate and final files.
OUTPUT_DIR = 'compressed_json'


# --- Added: Simplified image saving function migrated from 9_assessment_A.py ---
def save_shape_as_image(display, shape: TopoDS_Shape, image_path: str):
    """
    Renders the given TopoDS_Shape object and saves it as a PNG image.
    """
    if not OCC_AVAILABLE or not shape or shape.IsNull() or display is None:
        print("      -> OCC not available or model is empty, skipping image saving.")
        return

    try:
        display.EraseAll()

        # Set the model color to an opaque brown.
        shape_color = Quantity_Color(0.545, 0.271, 0.075, Quantity_TOC_RGB)
        # The transparency parameter has been removed to make it opaque.
        ais_objects = display.DisplayShape(shape, color=shape_color, update=False)

        if not isinstance(ais_objects, list):
            ais_objects = [ais_objects]

        # Set the display mode to include bold black outlines.
        if ais_objects:
            for ais_solid in ais_objects:
                if ais_solid:
                    ais_solid.SetDisplayMode(1)  # 1 for Shaded mode.
                    drawer = ais_solid.Attributes()
                    drawer.SetFaceBoundaryDraw(True)
                    # Increase the stroke width from 2.5 to 4.0.
                    line_aspect = Prs3d_LineAspect(Quantity_Color(Quantity_NOC_BLACK), Aspect_TOL_SOLID, 4.0)
                    drawer.SetLineAspect(line_aspect)

        display.FitAll()
        display.View.Redraw()

        # Save the image.
        if display.View.Dump(str(image_path)):
            print(f"      -> Image successfully saved to: {image_path}")
        else:
            print(f"      -> [Failed] Could not save image to: {image_path}")

    except Exception as e:
        print(f"      -> [Exception] An error occurred during image generation: {e}")


def run_compression_stage(source_dir, output_dir):
    """
    Stage 1: Compresses all source JSON files.
    Reads .json files from source_dir, compresses them, and saves them to output_dir.
    """
    print("\n" + "=" * 20 + " Stage 1: Compression " + "=" * 20)

    if not os.path.isdir(source_dir):
        print(f"Error: Source directory '{source_dir}' does not exist.")
        return [], []

    source_files = [f for f in os.listdir(source_dir) if f.lower().endswith('.json')]
    if not source_files:
        print(f"Warning: No .json files found in '{source_dir}'.")
        return [], []

    os.makedirs(output_dir, exist_ok=True)
    success_files = []
    failure_cases = []

    print(f"Found {len(source_files)} files, starting compression...")
    for i, filename in enumerate(source_files, 1):
        file_id = os.path.splitext(filename)[0]
        source_path = os.path.join(source_dir, filename)
        output_path = os.path.join(output_dir, f"{file_id}.txt")

        try:
            compressed_text = compress_cad_json(source_path)
            if compressed_text.startswith("Error:"):
                raise ValueError(f"Compression function returned an error: {compressed_text}")

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(compressed_text)
            success_files.append(os.path.basename(output_path))
            print(f"({i}/{len(source_files)}) {filename}: Compression successful")
        except Exception as e:
            print(f"({i}/{len(source_files)}) {filename}: Compression failed")
            failure_cases.append({"file": filename, "stage": "Compression", "error": str(e)})

    print(f"--- Compression stage complete: {len(success_files)} succeeded, {len(failure_cases)} failed ---")
    return success_files, failure_cases


def run_decoding_stage(processing_dir, files_to_process):
    """
    Stage 2: Decodes all compressed text files.
    Decodes .txt files in processing_dir and generates .json files.
    """
    print("\n" + "=" * 20 + " Stage 2: Decoding " + "=" * 20)

    if not files_to_process:
        print("No files to decode, skipping this stage.")
        return [], []

    success_files = []
    failure_cases = []

    print(f"Found {len(files_to_process)} files, starting decoding...")
    for i, filename in enumerate(files_to_process, 1):
        file_id = os.path.splitext(filename)[0]
        source_path = os.path.join(processing_dir, filename)
        output_path = os.path.join(processing_dir, f"{file_id}.json")

        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                compressed_lines = f.read().splitlines()

            reconstructed_json_str = decompress_to_json(compressed_lines)
            json.loads(reconstructed_json_str)  # Validate the JSON output.

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(reconstructed_json_str)
            success_files.append(os.path.basename(output_path))
            print(f"({i}/{len(files_to_process)}) {filename}: Decoding successful")
        except Exception as e:
            print(f"({i}/{len(files_to_process)}) {filename}: Decoding failed")
            failure_cases.append({"file": filename, "stage": "Decoding", "error": str(e)})

    print(f"--- Decoding stage complete: {len(success_files)} succeeded, {len(failure_cases)} failed ---")
    return success_files, failure_cases


def run_reconstruction_stage(processing_dir, display_context):
    """
    Stage 3: Batch reconstructs models from JSON files and saves images for successful ones.
    All outputs (logs, images) are saved in the processing_dir.
    """
    print("\n" + "=" * 20 + " Stage 3: Reconstruction & Image Saving " + "=" * 20)

    if not os.path.exists(processing_dir):
        print(f"Error: Processing directory '{processing_dir}' does not exist.")
        return [], []

    json_files = [f for f in os.listdir(processing_dir) if f.endswith(".json")]
    if not json_files:
        print(f"Warning: No .json files found for reconstruction in '{processing_dir}'.")
        return [], []

    success_files = []
    failure_cases = []

    log_path = os.path.join(processing_dir, "reconstruction_summary_log.txt")
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Batch Reconstruction Log\n")
        log_file.write(f"Total files: {len(json_files)}\n\n")

        print(f"Found {len(json_files)} JSON files, starting batch reconstruction...")

        for i, json_file in enumerate(json_files):
            json_path = os.path.join(processing_dir, json_file)
            file_id = os.path.splitext(json_file)[0]
            print(f"\n==> [{i + 1}/{len(json_files)}] Processing: {json_file}")
            log_file.write(f"[{i + 1}/{len(json_files)}] Processing {json_file} ... ")

            reconstructed_shape = None  # Initialize shape variable.
            try:
                # Capture the reconstructed model.
                reconstructed_shape = reconstruct_model(json_path)
                if reconstructed_shape is None or reconstructed_shape.IsNull():
                    raise ValueError("Reconstruction function did not return a valid model.")

                log_file.write("Success\n")
                success_files.append(json_file)

                # Save an image if reconstruction was successful.
                if OCC_AVAILABLE and display_context:
                    image_path = os.path.join(processing_dir, f"{file_id}.png")
                    save_shape_as_image(display_context, reconstructed_shape, image_path)

            except Exception as e:
                error_message = f"Failed: {e}"
                log_file.write(error_message + "\n")
                print(f"Error processing file {json_file}: {e}")
                failure_cases.append({"file": json_file, "stage": "Reconstruction", "error": str(e)})

    print(f"\n--- Reconstruction stage complete: {len(success_files)} succeeded, {len(failure_cases)} failed ---")
    print(f"Reconstruction log saved to: {log_path}")
    return success_files, failure_cases


def main():
    """
    Main execution function that runs the compression, decoding, and reconstruction stages in sequence.
    """
    print("--- Starting Integrated Batch Process (Compress -> Decode -> Reconstruct) ---")

    # --- Global Settings ---
    # Disable interactive graphics display from the reconstruction module.
    reconstruction.display_available = False
    # Set the script directory to ensure the reconstruction module finds the correct output path.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    reconstruction.script_dir = script_dir

    # --- Initialize OCC display context for offscreen rendering ---
    display_context = None
    if OCC_AVAILABLE:
        try:
            print("Initializing OCC display context for image saving...")
            display_context, _, _, _ = init_display()
            # Set a light gray background color.
            bg_color = Quantity_Color(245 / 255, 245 / 255, 245 / 255, Quantity_TOC_RGB)
            display_context.View.SetBackgroundColor(bg_color)
            print("OCC display context initialized successfully.")
        except Exception as e:
            print(f"Could not initialize OCC display context. Image saving will be disabled. Error: {e}")
            display_context = None

    # --- Preparation: Clear and create the unified output directory ---
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    print(f"Cleared and created unified output directory: {OUTPUT_DIR}")

    # --- Staged Execution ---
    compressed_files, compress_failures = run_compression_stage(SOURCE_DIR, OUTPUT_DIR)
    decoded_files, decode_failures = run_decoding_stage(OUTPUT_DIR, compressed_files)
    reconstructed_files, reconstruction_failures = run_reconstruction_stage(OUTPUT_DIR, display_context)

    # --- Final Summary Report ---
    all_failures = compress_failures + decode_failures + reconstruction_failures
    source_file_count = len([f for f in os.listdir(SOURCE_DIR) if f.lower().endswith('.json')]) if os.path.isdir(SOURCE_DIR) else 0

    print("\n" + "=" * 20 + " Final Summary Report " + "=" * 20)
    print(f"Total source files: {source_file_count}")
    print("-" * 55)
    print(f"Compression Stage: {len(compressed_files)} / {source_file_count} succeeded")
    print(f"Decoding Stage: {len(decoded_files)} / {len(compressed_files)} succeeded")
    print(f"Reconstruction Stage: {len(reconstructed_files)} / {len(decoded_files)} succeeded")
    print("-" * 55)
    print(f"Total failures: {len(all_failures)}")

    if all_failures:
        print("\n--- Failure Case Details ---")
        for case in all_failures:
            print(f"  - File: {case['file']}, Stage: {case['stage']}, Error: {case['error']}")

    print("\n--- Script execution finished ---")


if __name__ == "__main__":
    # This line is recommended for using multiprocessing on Windows to avoid potential issues.
    multiprocessing.freeze_support()
    main()
