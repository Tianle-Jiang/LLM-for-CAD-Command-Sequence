import json
import os
import sys
import check_support  # Import the shared module


def rename_ids(data):
    """
    Renames all entity IDs to meaningful, sequential names and updates all references.
    """
    # Counters for each entity type to generate sequential names.
    counters = {
        "Sketch": 0,
        "Point3D": 0,
        "SketchCircle": 0,
        "SketchLine": 0,
        "SketchArc": 0,
        "ExtrudeFeature": 0,
        "Profile": 0
    }

    # Mapping dictionary: old_id -> new_name
    id_mapping = {}

    # First pass: Rename top-level entities (Sketches and ExtrudeFeatures).
    new_entities = {}
    for old_id, entity in data["entities"].items():
        entity_type = entity.get("type")
        if entity_type == "Sketch":
            counters["Sketch"] += 1
            new_name = f"Sketch{counters['Sketch']}"
            id_mapping[old_id] = new_name
            new_entities[new_name] = entity

        elif entity_type == "ExtrudeFeature":
            counters["ExtrudeFeature"] += 1
            new_name = f"Extrude{counters['ExtrudeFeature']}"
            id_mapping[old_id] = new_name
            new_entities[new_name] = entity

    # Second pass: Rename points, curves, and profiles within each sketch.
    for entity_name, entity in new_entities.items():
        if entity.get("type") == "Sketch":
            # Rename points
            new_points = {}
            for point_id, point_data in entity.get("points", {}).items():
                point_type = point_data.get("type")
                if point_type in counters:
                    counters[point_type] += 1
                    new_point_name = f"{point_type}{counters[point_type]}"
                else:
                    new_point_name = f"Point{counters['Point3D']}"

                id_mapping[point_id] = new_point_name
                new_points[new_point_name] = point_data
            entity["points"] = new_points

            # Rename curves
            new_curves = {}
            for curve_id, curve_data in entity.get("curves", {}).items():
                curve_type = curve_data.get("type")
                if curve_type in counters:
                    counters[curve_type] += 1
                    new_curve_name = f"{curve_type}{counters[curve_type]}"
                else:
                    # Handle potentially new curve types gracefully.
                    curve_type_name = curve_type.replace("Sketch", "")
                    counters.setdefault(curve_type, 0)
                    counters[curve_type] += 1
                    new_curve_name = f"{curve_type_name}{counters[curve_type]}"

                id_mapping[curve_id] = new_curve_name
                new_curves[new_curve_name] = curve_data
            entity["curves"] = new_curves

            # Rename profiles
            new_profiles = {}
            for profile_id, profile_data in entity.get("profiles", {}).items():
                counters["Profile"] += 1
                new_profile_name = f"Profile{counters['Profile']}"
                id_mapping[profile_id] = new_profile_name
                new_profiles[new_profile_name] = profile_data
            entity["profiles"] = new_profiles

    # Third pass: Update all references to use the new names.
    for entity in new_entities.values():
        # Update references within ExtrudeFeatures.
        if entity.get("type") == "ExtrudeFeature":
            for profile in entity.get("profiles", []):
                if "sketch" in profile and profile["sketch"] in id_mapping:
                    profile["sketch"] = id_mapping[profile["sketch"]]
                if "profile" in profile and profile["profile"] in id_mapping:
                    profile["profile"] = id_mapping[profile["profile"]]

        # Update references within Sketches.
        elif entity.get("type") == "Sketch":
            # Update point references in curves.
            for curve in entity.get("curves", {}).values():
                for point_ref in ["center_point", "start_point", "end_point"]:
                    if point_ref in curve and curve[point_ref] in id_mapping:
                        curve[point_ref] = id_mapping[curve[point_ref]]

            # Update curve references in profiles.
            for profile in entity.get("profiles", {}).values():
                for loop in profile.get("loops", []):
                    for curve_data in loop.get("profile_curves", []):
                        if "curve" in curve_data and curve_data["curve"] in id_mapping:
                            curve_data["curve"] = id_mapping[curve_data["curve"]]

    # Update references in the main sequence.
    if "sequence" in data:
        for item in data["sequence"]:
            # Update reference to the main entity (Sketch/ExtrudeFeature).
            if "entity" in item and item["entity"] in id_mapping:
                item["entity"] = id_mapping[item["entity"]]
            # Also update reference to a curve, if present.
            if "curve" in item and item["curve"] in id_mapping:
                item["curve"] = id_mapping[item["curve"]]

    data["entities"] = new_entities


def prune_sketch_entity(entity):
    """
    Prunes a single sketch entity, keeping only essential data and referenced points.
    """
    # Clean up curves and collect all point IDs that are in use.
    pruned_curves = {}
    used_point_ids = set()

    for cname, curve in entity.get("curves", {}).items():
        ctype = curve.get("type", "")
        if ctype == "SketchLine":
            pruned = {
                "type": "SketchLine",
                "start_point": curve["start_point"],
                "end_point": curve["end_point"]
            }
            used_point_ids.update([curve["start_point"], curve["end_point"]])
        elif ctype == "SketchCircle":
            pruned = {
                "type": "SketchCircle",
                "center_point": curve["center_point"],
                "radius": curve["radius"]
            }
            used_point_ids.add(curve["center_point"])
        elif ctype == "SketchArc":
            pruned = {
                "type": "SketchArc",
                "start_point": curve["start_point"],
                "end_point": curve["end_point"],
                "center_point": curve["center_point"],
                "radius": curve["radius"],
                "reference_vector": curve.get("reference_vector", {}),
                "start_angle": curve["start_angle"],
                "end_angle": curve["end_angle"]
            }
            used_point_ids.update([curve["start_point"], curve["end_point"], curve["center_point"]])
        else:
            continue  # Ignore unknown curve types.
        pruned_curves[cname] = pruned

    # Process profiles, keeping only curve references.
    pruned_profiles = {}
    for pname, profile in entity.get("profiles", {}).items():
        loops = []
        for loop in profile.get("loops", []):
            curves3d = []
            for pc in loop.get("profile_curves", []):
                pruned = {"type": pc.get("type", ""), "curve": pc.get("curve", "")}
                for k in ["start_point", "end_point", "center_point", "normal", "reference_vector", "radius",
                          "start_angle", "end_angle"]:
                    if k in pc:
                        pruned[k] = pc[k]
                curves3d.append(pruned)
            loops.append({"is_outer": loop.get("is_outer", True), "profile_curves": curves3d})
        pruned_profiles[pname] = {"loops": loops}

    # Clean up points, keeping only those referenced by the curves.
    cleaned_points = {
        pid: pdata for pid, pdata in entity.get("points", {}).items()
        if pid in used_point_ids
    }

    return {
        "type": "Sketch",
        "points": cleaned_points,
        "curves": pruned_curves,
        "profiles": pruned_profiles,
        "transform": entity.get("transform", {})
    }


def prune_json_data(input_json_path, output_json_path):
    """
    Loads a JSON file, prunes unnecessary data, and saves the result.
    """
    try:
        with open(input_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read JSON file: {e}")
        return

    # Skip pruning if the file contains unsupported features.
    if "entities" in data:
        for entity_data in data["entities"].values():
            if not check_support.check_support(entity_data):
                print(f"File contains unsupported features, skipping pruning: {input_json_path}")
                return

    # Remove top-level redundant fields.
    for key in ["metadata", "history", "viewport", "componentLibraries", "timeline", "properties"]:
        data.pop(key, None)

    # Process entities if they exist.
    if "entities" in data:
        sketch_uuids_in_use = set()
        new_entities = {}

        # First, identify all sketch UUIDs that are referenced by ExtrudeFeatures.
        for entity in data["entities"].values():
            if entity.get("type") == "ExtrudeFeature":
                for profile in entity.get("profiles", []):
                    if "sketch" in profile:
                        sketch_uuids_in_use.add(profile["sketch"])

        # Prune the entities data.
        for uuid, entity in data["entities"].items():
            entity_type = entity.get("type")

            if entity_type == "Sketch":
                # Only process and keep sketches that are actually used.
                if uuid in sketch_uuids_in_use:
                    new_entities[uuid] = prune_sketch_entity(entity)

            elif entity_type == "ExtrudeFeature":
                # Prune the ExtrudeFeature entity.
                pruned_entity = {
                    "type": "ExtrudeFeature",
                    "profiles": entity.get("profiles", []),
                    "operation": entity.get("operation"),
                    "extent_type": entity.get("extent_type"),
                    "start_extent": entity.get("start_extent", {})
                }
                if "extent_one" in entity:
                    extent_one = entity["extent_one"].copy()
                    if "distance" in extent_one and isinstance(extent_one["distance"], dict):
                        if "value" in extent_one["distance"]:
                            extent_one["distance"] = {"value": extent_one["distance"]["value"]}
                    if "taper_angle" in extent_one:
                        del extent_one["taper_angle"]
                    pruned_entity["extent_one"] = extent_one
                if "extent_two" in entity:
                    extent_two = entity["extent_two"].copy()
                    if "distance" in extent_two and isinstance(extent_two["distance"], dict):
                        if "value" in extent_two["distance"]:
                            extent_two["distance"] = {"value": extent_two["distance"]["value"]}
                    if "taper_angle" in extent_two:
                        del extent_two["taper_angle"]
                    pruned_entity["extent_two"] = extent_two
                new_entities[uuid] = pruned_entity

            # Note: Any other entity types will be automatically discarded.

        data["entities"] = new_entities

        # Prune the sequence data to only include valid steps.
        if "sequence" in data:
            new_sequence = []
            valid_entities = set(data["entities"].keys())

            for s in data["sequence"]:
                entity_id = s.get("entity")
                if entity_id in valid_entities:
                    # Create the basic sequence step.
                    new_step = {
                        "index": s["index"],
                        "type": s["type"],
                        "entity": entity_id
                    }
                    # If the original step has an associated curve ID, carry it over.
                    # Note: Its value is still the old UUID at this point.
                    if "curve" in s:
                        new_step["curve"] = s["curve"]
                    new_sequence.append(new_step)
            data["sequence"] = new_sequence

    # Rename all IDs from UUIDs to meaningful, sequential names.
    rename_ids(data)

    # Save the pruned and renamed JSON data.
    try:
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"Pruned and saved: {output_json_path}")
    except Exception as e:
        print(f"Failed to save: {e}")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Set the default output directory.
    default_output_dir = os.path.join(script_dir, "pruned_json")

    # Create the output directory if it doesn't exist.
    if not os.path.exists(default_output_dir):
        os.makedirs(default_output_dir)

    # Set the input directory.
    input_folder = os.path.join(script_dir, "reconstruction")

    # Process all JSON files in the input directory.
    json_files_in_dir = [f for f in os.listdir(input_folder) if f.lower().endswith('.json')]
    for filename in json_files_in_dir:
        input_file = os.path.join(input_folder, filename)
        output_file = os.path.join(default_output_dir, filename)
        prune_json_data(input_file, output_file)
