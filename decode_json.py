import json
import re
import os
from typing import List, Dict, Any


def parse_params(line: str) -> list:
    """
    Parses the list of parameters from within the parentheses of a command string.

    Args:
        line: A single line string containing a command and its parameters.

    Returns:
        A list containing the parsed parameters.
    """
    try:
        # Find the content within the parentheses.
        params_str = re.search(r'\((.*?)\)', line).group(1)
        # Split by comma and strip whitespace.
        params = [p.strip() for p in params_str.split(',')]
        # Attempt to convert numeric-looking strings to floats.
        return [float(p) if p.replace('.', '', 1).replace('-', '', 1).isdigit() else p for p in params]
    except (AttributeError, ValueError):
        # Return an empty list if parsing fails (e.g., no parentheses or conversion error).
        return []


def decompress_to_json(lines: List[str]) -> Dict[str, Any]:
    """
    Reconstructs a JSON structure from a list of compressed CAD data lines.
    This version includes strict format validation for all commands; format errors will raise a ValueError.
    """
    entities = {}
    sequence = []

    # State tracking variables
    current_sketch_key = None
    current_profile_key = None
    current_loop = None

    # ID counters
    point_counter = 1
    line_counter = 1
    circle_counter = 1
    arc_counter = 1
    extrude_counter = 1
    sequence_index = 0

    # Trackers to avoid creating duplicate entities
    point_tracker = {}
    curve_tracker = {}

    # Tracker to merge consecutive extrude features
    last_extrude_signature = None
    last_extrude_key = None

    # Reverse mapping from command strings to JSON types
    operation_map_rev = {"New": "NewBodyFeatureOperation", "Join": "JoinFeatureOperation", "Cut": "CutFeatureOperation"}
    extent_type_map_rev = {"One": "OneSideFeatureExtentType", "Two": "TwoSidesFeatureExtentType",
                           "Symmetric": "SymmetricFeatureExtentType"}

    # Decode line by line
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        # Use regex to find the command letter at the start of the line.
        match = re.search(r'^[ \-]*([A-Z])', line)
        if not match:
            continue
        command = match.group(1)

        # Parse parameters at the beginning of the loop.
        params = parse_params(line)

        # If the command is not an extrude, reset the last extrude signature to create a new feature.
        if command != 'E':
            last_extrude_signature = None
            last_extrude_key = None

        # --- Command Processing and Validation ---
        if command == 'S':
            if len(params) != 1:
                raise ValueError(
                    f"Line {line_num}: 'S' command expects 1 parameter, but got {len(params)}. Line: '{line}'")
            sketch_id = int(params[0])
            current_sketch_key = f"Sketch{sketch_id}"
            entities[current_sketch_key] = {"type": "Sketch", "points": {}, "curves": {}, "profiles": {},
                                            "transform": {}}
            point_tracker, curve_tracker = {}, {}

        elif command == 'P':
            if len(params) != 1:
                raise ValueError(
                    f"Line {line_num}: 'P' command expects 1 parameter, but got {len(params)}. Line: '{line}'")
            profile_id = int(params[0])
            current_profile_key = f"Profile{profile_id}"
            entities[current_sketch_key]['profiles'][current_profile_key] = {"loops": []}

        elif command == 'O':
            if len(params) != 1:
                raise ValueError(
                    f"Line {line_num}: 'O' command expects 1 parameter, but got {len(params)}. Line: '{line}'")
            is_outer = str(params[0]).lower() == 'true'
            entities[current_sketch_key]['profiles'][current_profile_key]['loops'].append(
                {"is_outer": is_outer, "profile_curves": []})
            current_loop = entities[current_sketch_key]['profiles'][current_profile_key]['loops'][-1]['profile_curves']

        elif command == 'L':
            if len(params) != 4:
                raise ValueError(
                    f"Line {line_num}: 'L' command expects 4 parameters, but got {len(params)}. Line: '{line}'")
            start_coord, end_coord = (params[0], params[1], 0.0), (params[2], params[3], 0.0)

            if start_coord not in point_tracker:
                point_tracker[start_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[start_coord]] = {"type": "Point3D",
                                                                                      "x": start_coord[0],
                                                                                      "y": start_coord[1],
                                                                                      "z": start_coord[2]}
                point_counter += 1
            start_point_key = point_tracker[start_coord]

            if end_coord not in point_tracker:
                point_tracker[end_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[end_coord]] = {"type": "Point3D",
                                                                                    "x": end_coord[0],
                                                                                    "y": end_coord[1],
                                                                                    "z": end_coord[2]}
                point_counter += 1
            end_point_key = point_tracker[end_coord]

            line_signature = tuple(sorted(('L', str(start_point_key), str(end_point_key))))
            if line_signature not in curve_tracker:
                curve_tracker[line_signature] = f"SketchLine{line_counter}"
                entities[current_sketch_key]['curves'][curve_tracker[line_signature]] = {"type": "SketchLine",
                                                                                         "start_point": start_point_key,
                                                                                         "end_point": end_point_key}
                sequence.append({"index": sequence_index, "type": "Sketch", "entity": current_sketch_key,
                                 "curve": curve_tracker[line_signature]})
                sequence_index += 1
                line_counter += 1
            curve_key = curve_tracker[line_signature]

            current_loop.append({"type": "Line3D", "curve": curve_key,
                                 "start_point": {"type": "Point3D", "x": start_coord[0], "y": start_coord[1],
                                                 "z": start_coord[2]},
                                 "end_point": {"type": "Point3D", "x": end_coord[0], "y": end_coord[1],
                                               "z": end_coord[2]}})

        elif command == 'C':
            if len(params) != 3:
                raise ValueError(
                    f"Line {line_num}: 'C' command expects 3 parameters, but got {len(params)}. Line: '{line}'")
            center_coord, radius = (params[0], params[1], 0.0), params[2]

            if center_coord not in point_tracker:
                point_tracker[center_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[center_coord]] = {"type": "Point3D",
                                                                                       "x": center_coord[0],
                                                                                       "y": center_coord[1],
                                                                                       "z": center_coord[2]}
                point_counter += 1
            center_point_key = point_tracker[center_coord]

            circle_signature = ('C', str(center_point_key), str(radius))
            if circle_signature not in curve_tracker:
                curve_tracker[circle_signature] = f"SketchCircle{circle_counter}"
                entities[current_sketch_key]['curves'][curve_tracker[circle_signature]] = {"type": "SketchCircle",
                                                                                           "center_point": center_point_key,
                                                                                           "radius": radius}
                sequence.append({"index": sequence_index, "type": "Sketch", "entity": current_sketch_key,
                                 "curve": curve_tracker[circle_signature]})
                sequence_index += 1
                circle_counter += 1
            curve_key = curve_tracker[circle_signature]

            current_loop.append({"type": "Circle3D", "curve": curve_key,
                                 "center_point": {"type": "Point3D", "x": center_coord[0], "y": center_coord[1],
                                                  "z": center_coord[2]},
                                 "normal": {"type": "Vector3D", "x": 0.0, "y": 0.0, "z": 1.0, "length": 1.0},
                                 "radius": radius})

        elif command == 'A':
            if len(params) != 11:
                raise ValueError(
                    f"Line {line_num}: 'A' command expects 11 parameters, but got {len(params)}. Line: '{line}'")
            start_coord = (params[0], params[1], 0.0)
            end_coord = (params[2], params[3], 0.0)
            center_coord = (params[4], params[5], 0.0)
            ref_vector_data = {"x": params[6], "y": params[7], "z": 0.0, "length": 1.0}
            radius = params[8]
            start_angle = params[9]
            end_angle = params[10]

            if start_coord not in point_tracker:
                point_tracker[start_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[start_coord]] = {"type": "Point3D",
                                                                                      "x": start_coord[0],
                                                                                      "y": start_coord[1],
                                                                                      "z": start_coord[2]}
                point_counter += 1
            start_point_key = point_tracker[start_coord]

            if end_coord not in point_tracker:
                point_tracker[end_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[end_coord]] = {"type": "Point3D",
                                                                                    "x": end_coord[0],
                                                                                    "y": end_coord[1],
                                                                                    "z": end_coord[2]}
                point_counter += 1
            end_point_key = point_tracker[end_coord]

            if center_coord not in point_tracker:
                point_tracker[center_coord] = f"Point3D{point_counter}"
                entities[current_sketch_key]['points'][point_tracker[center_coord]] = {"type": "Point3D",
                                                                                       "x": center_coord[0],
                                                                                       "y": center_coord[1],
                                                                                       "z": center_coord[2]}
                point_counter += 1
            center_point_key = point_tracker[center_coord]

            arc_signature = ('A', str(start_point_key), str(end_point_key), str(center_point_key))
            if arc_signature not in curve_tracker:
                curve_tracker[arc_signature] = f"SketchArc{arc_counter}"
                entities[current_sketch_key]['curves'][curve_tracker[arc_signature]] = {"type": "SketchArc",
                                                                                        "start_point": start_point_key,
                                                                                        "end_point": end_point_key,
                                                                                        "center_point": center_point_key,
                                                                                        "radius": radius,
                                                                                        "start_angle": start_angle,
                                                                                        "end_angle": end_angle,
                                                                                        "reference_vector": ref_vector_data}
                sequence.append({"index": sequence_index, "type": "Sketch", "entity": current_sketch_key,
                                 "curve": curve_tracker[arc_signature]})
                sequence_index += 1
                arc_counter += 1
            curve_key = curve_tracker[arc_signature]

            current_loop.append({"type": "Arc3D", "curve": curve_key,
                                 "start_point": {"type": "Point3D", "x": start_coord[0], "y": start_coord[1],
                                                 "z": start_coord[2]},
                                 "end_point": {"type": "Point3D", "x": end_coord[0], "y": end_coord[1],
                                               "z": end_coord[2]},
                                 "center_point": {"type": "Point3D", "x": center_coord[0], "y": center_coord[1],
                                                  "z": center_coord[2]},
                                 "normal": {"type": "Vector3D", "x": 0.0, "y": 0.0, "z": 1.0, "length": 1.0},
                                 "reference_vector": {"type": "Vector3D", **ref_vector_data}, "radius": radius,
                                 "start_angle": start_angle, "end_angle": end_angle})

        elif command == 'T':
            if len(params) != 12:
                raise ValueError(
                    f"Line {line_num}: 'T' command expects 12 parameters, but got {len(params)}. Line: '{line}'")
            entities[current_sketch_key]['transform'] = {
                "origin": {"type": "Point3D", "x": params[0], "y": params[1], "z": params[2]},
                "x_axis": {"type": "Vector3D", "x": params[3], "y": params[4], "z": params[5], "length": 1.0},
                "y_axis": {"type": "Vector3D", "x": params[6], "y": params[7], "z": params[8], "length": 1.0},
                "z_axis": {"type": "Vector3D", "x": params[9], "y": params[10], "z": params[11], "length": 1.0}}

        elif command == 'E':
            if len(params) != 6:
                raise ValueError(
                    f"Line {line_num}: 'E' command expects 6 parameters, but got {len(params)}. Line: '{line}'")
            profile_id, sketch_id, op, ext_type, d1, d2 = params
            current_extrude_signature = (int(sketch_id), op, ext_type, d1, d2)

            if current_extrude_signature == last_extrude_signature and last_extrude_key:
                sketch_key_ref = f"Sketch{int(sketch_id)}"
                profile_key_ref = f"Profile{int(profile_id)}"
                entities[last_extrude_key]['profiles'].append({"profile": profile_key_ref, "sketch": sketch_key_ref})
            else:
                extrude_key = f"Extrude{extrude_counter}"
                sketch_key_ref = f"Sketch{int(sketch_id)}"
                profile_key_ref = f"Profile{int(profile_id)}"

                entities[extrude_key] = {"type": "ExtrudeFeature",
                                         "profiles": [{"profile": profile_key_ref, "sketch": sketch_key_ref}],
                                         "operation": operation_map_rev.get(op, "NewBodyFeatureOperation"),
                                         "extent_type": extent_type_map_rev.get(ext_type, "OneSideFeatureExtentType"),
                                         "start_extent": {"type": "ProfilePlaneStartDefinition"},
                                         "extent_one": {"distance": {"value": d1}, "type": "DistanceExtentDefinition"}}
                if ext_type in ['Two', 'Symmetric']:
                    entities[extrude_key]["extent_two"] = {"distance": {"value": d2},
                                                           "type": "DistanceExtentDefinition"}

                sequence.append({"index": sequence_index, "type": "ExtrudeFeature", "entity": extrude_key})
                last_extrude_signature = current_extrude_signature
                last_extrude_key = extrude_key
                sequence_index += 1
                extrude_counter += 1

    return {"entities": entities, "sequence": sequence}


def decompress_to_json_with_validation(lines: List[str]) -> Dict[str, Any]:
    """
    A wrapper function to safely decode compressed data to JSON.
    It catches all errors during the decoding process and returns a dictionary
    containing a success status and the resulting data or error message.

    Args:
        lines: A list of strings containing the compressed commands.

    Returns:
        A dictionary in the format:
        - {'success': True, 'data': <json_object>} on success
        - {'success': False, 'data': '<error_message>'} on failure
    """
    try:
        # Call the core decoding function.
        json_data = decompress_to_json(lines)
        return {"success": True, "data": json_data}
    except (ValueError, IndexError, KeyError, TypeError) as e:
        # Catch all expected and unexpected decoding errors.
        error_message = f"Decoding failed: {str(e)}"
        return {"success": False, "data": error_message}
    except Exception as e:
        # Catch any other unexpected exceptions.
        error_message = f"An unexpected error occurred during decoding: {str(e)}"
        return {"success": False, "data": error_message}


def process_file(input_path: str):
    """
    Reads a compressed file, decodes it, and saves it as a JSON file.
    """
    print(f"--- Processing file: {input_path} ---")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"Found {len(lines)} lines to process.")

        # Use the new function with validation.
        result = decompress_to_json_with_validation(lines)

        if result['success']:
            output_filename = os.path.splitext(input_path)[0] + '_decoded.json'
            with open(output_filename, 'w', encoding='utf-8') as f:
                # Note: result['data'] is now a python dict and needs to be dumped to JSON.
                json.dump(result['data'], f, indent=2)
            print(f"Successfully decoded and saved to '{output_filename}'")
        else:
            print(f"Error during validation: {result['data']}")

    except FileNotFoundError:
        print(f"Error: The file was not found: '{input_path}'")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print("-" * (len(input_path) + 22))


# --- Main Execution ---
if __name__ == "__main__":
    # Find and process the first .txt file in the current directory.
    input_file = None
    for filename in sorted(os.listdir('.')):
        if filename.lower().endswith('.txt'):
            input_file = filename
            break

    if input_file:
        process_file(input_file)
    else:
        print("No .txt file found in the current directory to process.")
