import json
import re
import os


def format_value(value):
    """Formats a numerical value to a string with up to 8 decimal places, omitting trailing zeros."""
    # Use a threshold smaller than our precision to decide if a number is effectively zero.
    if abs(value) < 1e-9:
        return "0"

    # Format to 8 decimal places, then strip trailing zeros.
    # If the result ends with a decimal point (e.g., "12."), strip that too.
    s = f"{value:.8f}".rstrip('0')
    if s.endswith('.'):
        return s[:-1]
    return s


def process_sketch(sketch_data, sketch_id, indent_level=0):
    """Processes a single sketch entity and generates its compressed string representation."""
    output = []
    indent = "  " * indent_level

    # S command: Marks the beginning of a new sketch entity.
    output.append(f"{indent}S ({sketch_id})")

    if 'profiles' in sketch_data and sketch_data['profiles']:
        # Sort profiles by their ID to ensure consistent processing order.
        sorted_profiles = sorted(sketch_data['profiles'].items(), key=lambda item: int(re.findall(r'\d+', item[0])[0]))

        for profile_name, profile_data in sorted_profiles:
            profile_id = re.findall(r'\d+', profile_name)[0]

            # P command: Marks the beginning of a new profile within a sketch.
            output.append(f"{indent}  - P ({profile_id})")

            if 'loops' in profile_data and profile_data['loops']:
                for loop in profile_data['loops']:
                    # O command: Defines the loop type (outer or inner).
                    is_outer_str = str(loop.get('is_outer', False)).lower()
                    output.append(f"{indent}    - O ({is_outer_str})")

                    if 'profile_curves' in loop and loop['profile_curves']:
                        for curve in loop['profile_curves']:
                            curve_type = curve.get('type')

                            if curve_type == 'Line3D':
                                # L command: Defines a straight line using absolute coordinates.
                                start_point = curve['start_point']
                                end_point = curve['end_point']
                                line_str = (f"L ({format_value(start_point['x'])}, {format_value(start_point['y'])}, "
                                            f"{format_value(end_point['x'])}, {format_value(end_point['y'])})")
                                output.append(f"{indent}      - {line_str}")

                            elif curve_type == 'Circle3D':
                                # C command: Defines a full circle.
                                center_point = curve['center_point']
                                radius = curve['radius']
                                circle_str = (
                                    f"C ({format_value(center_point['x'])}, {format_value(center_point['y'])}, "
                                    f"{format_value(radius)})")
                                output.append(f"{indent}      - {circle_str}")

                            elif curve_type == 'Arc3D':
                                # A command: Defines an arc.
                                start_point = curve['start_point']
                                end_point = curve['end_point']
                                center_point = curve['center_point']
                                ref_vector = curve['reference_vector']
                                radius = curve['radius']
                                start_angle = curve['start_angle']
                                end_angle = curve['end_angle']
                                arc_str = (f"A ({format_value(start_point['x'])}, {format_value(start_point['y'])}, "
                                           f"{format_value(end_point['x'])}, {format_value(end_point['y'])}, "
                                           f"{format_value(center_point['x'])}, {format_value(center_point['y'])}, "
                                           f"{format_value(ref_vector['x'])}, {format_value(ref_vector['y'])}, "
                                           f"{format_value(radius)}, "
                                           f"{format_value(start_angle)}, {format_value(end_angle)})")
                                output.append(f"{indent}      - {arc_str}")

    if 'transform' in sketch_data:
        transform = sketch_data['transform']
        # T command: Defines the 3D spatial pose (origin and axis vectors) of the sketch.
        transform_str = (
            f"T ({format_value(transform['origin']['x'])}, {format_value(transform['origin']['y'])}, {format_value(transform['origin']['z'])}, "
            f"{format_value(transform['x_axis']['x'])}, {format_value(transform['x_axis']['y'])}, {format_value(transform['x_axis']['z'])}, "
            f"{format_value(transform['y_axis']['x'])}, {format_value(transform['y_axis']['y'])}, {format_value(transform['y_axis']['z'])}, "
            f"{format_value(transform['z_axis']['x'])}, {format_value(transform['z_axis']['y'])}, {format_value(transform['z_axis']['z'])})")
        output.append(f"{indent}  - {transform_str}")

    return "\n".join(output)


def process_extrude(extrude_data, extrude_id, indent_level=0):
    """Processes a single extrude feature and generates its compressed string representation."""
    indent = "  " * indent_level

    operation_map = {"NewBodyFeatureOperation": "New", "JoinFeatureOperation": "Join", "CutFeatureOperation": "Cut"}
    extent_type_map = {"OneSideFeatureExtentType": "One", "TwoSidesFeatureExtentType": "Two",
                       "SymmetricFeatureExtentType": "Symmetric"}

    operation = operation_map.get(extrude_data.get('operation'), 'Unknown')
    extent_type = extent_type_map.get(extrude_data.get('extent_type'), 'Unknown')
    d1 = extrude_data.get('extent_one', {}).get('distance', {}).get('value', 0.0)
    d2 = extrude_data.get('extent_two', {}).get('distance', {}).get('value', 0.0)

    output_lines = []
    # Generate a separate E command for each profile being extruded.
    for profile_info in extrude_data.get('profiles', []):
        profile_id = re.findall(r'\d+', profile_info['profile'])[0]
        sketch_id = re.findall(r'\d+', profile_info['sketch'])[0]
        # E command: Defines an extrusion feature.
        extrude_str = f"E ({profile_id}, {sketch_id}, {operation}, {extent_type}, {format_value(d1)}, {format_value(d2)})"
        output_lines.append(f"{indent}{extrude_str}")

    return "\n".join(output_lines)


def compress_cad_json(file_path):
    """Loads a JSON CAD file and converts it into the compressed command format based on its 'sequence'."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return f"Error: The specified file was not found: '{file_path}'."
    except json.JSONDecodeError:
        return f"Error: Failed to decode the JSON file '{file_path}'. Please check its format."

    entities = data.get('entities', {})
    sequence = data.get('sequence', [])
    if not entities or not sequence:
        return "Error: 'entities' or 'sequence' not found in the JSON file."

    output = []
    processed_entities = set()

    # Iterate through the 'sequence' array to ensure the correct feature creation order.
    for item in sequence:
        entity_key = item.get('entity')
        # If the entity key is missing or has already been processed, skip it.
        if not entity_key or entity_key in processed_entities:
            continue

        processed_entities.add(entity_key)
        entity_data = entities.get(entity_key)

        if not entity_data:
            continue

        entity_type = entity_data.get('type')
        # Extract the numerical ID from the entity key (e.g., 'Sketch1' -> '1').
        entity_id = re.findall(r'\d+', entity_key)[0]

        if entity_type == 'Sketch':
            output.append(process_sketch(entity_data, entity_id))
        elif entity_type == 'ExtrudeFeature':
            output.append(process_extrude(entity_data, entity_id))

    return "\n".join(output)


def find_and_process_first_json():
    """Finds and processes the first JSON file in the current directory for testing purposes."""
    json_file_path = None
    try:
        # Sort files to get a deterministic order, useful for consistent testing.
        for filename in sorted(os.listdir('.')):
            if filename.lower().endswith('.json'):
                json_file_path = filename
                break
    except FileNotFoundError:
        print("Error: Cannot access the current directory.")
        return

    if json_file_path:
        print(f"Found and processing JSON file: {json_file_path}\n")
        compressed_output = compress_cad_json(json_file_path)
        print("--- Compressed Output ---")
        print(compressed_output)
    else:
        print("No JSON file found in the current directory.")


# --- Main Execution ---
if __name__ == "__main__":
    find_and_process_first_json()
