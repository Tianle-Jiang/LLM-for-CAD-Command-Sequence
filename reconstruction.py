import json
import os
import sys
import io
import check_support  # Import the shared module

from OCC.Core import gp
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax3, gp_Circ, gp_Trsf, gp_Vec, gp_Identity, gp_XYZ
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                     BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform)
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common
from OCC.Core.TopoDS import TopoDS_Wire, TopoDS_Face, TopoDS_Shape, TopoDS_Compound
from OCC.Core import TopoDS
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_SOLID, TopAbs_COMPOUND, TopAbs_SHELL
from OCC.Core.BRep import BRep_Tool, BRep_Builder
from OCC.Core.ShapeFix import ShapeFix_Wire, ShapeFix_Shape
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.Standard import Standard_Failure
from OCC.Core.Quantity import Quantity_Color, Quantity_NOC_GREEN, Quantity_NOC_RED, Quantity_NOC_BLUE, \
    Quantity_NOC_YELLOW, Quantity_NOC_GRAY60, Quantity_NOC_BLACK
from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCC.Core.Interface import Interface_Static

# For display purposes
try:
    from OCC.Display.SimpleGui import init_display

    display_available = True
except ImportError:
    display_available = False
    print("Warning: OCC.Display.SimpleGui not found. Result preview will be unavailable.")

# --- Global Variables ---
script_dir = os.path.dirname(os.path.abspath(__file__))


# --- Helper Functions ---

def create_gp_point(point_data):
    """Creates a gp_Pnt from a dictionary if the data is valid."""
    return gp_Pnt(point_data.get("x", 0.0), point_data.get("y", 0.0), point_data.get("z", 0.0)) \
        if point_data and point_data.get("type") == "Point3D" else None


def get_sketch_transform(transform_data):
    """Creates a gp_Trsf transformation object from sketch transform data."""
    trsf = gp_Trsf()
    required_keys = ['origin', 'x_axis', 'y_axis', 'z_axis']
    if not transform_data or not all(key in transform_data for key in required_keys):
        return None  # Return None if data is incomplete
    try:
        origin = create_gp_point(transform_data['origin'])
        if not origin: return None
        x_dir_data, z_dir_data = transform_data['x_axis'], transform_data['z_axis']
        if not (isinstance(x_dir_data, dict) and all(k in x_dir_data for k in ['x', 'y', 'z'])) or \
                not (isinstance(z_dir_data, dict) and all(k in z_dir_data for k in ['x', 'y', 'z'])):
            return None

        x_vec = gp_Vec(x_dir_data['x'], x_dir_data['y'], x_dir_data['z'])
        z_vec = gp_Vec(z_dir_data['x'], z_dir_data['y'], z_dir_data['z'])

        if x_vec.Magnitude() < 1e-7 or z_vec.Magnitude() < 1e-7: return None
        x_dir, z_dir = gp_Dir(x_vec.XYZ()), gp_Dir(z_vec.XYZ())

        # Handle cases where X and Z axes might be parallel by creating a valid perpendicular X axis.
        if x_dir.IsParallel(z_dir, 1e-7):
            temp_x_vec_candidate1 = z_dir.Crossed(gp_Dir(0, 0, 1))
            if temp_x_vec_candidate1.Magnitude() < 1e-7:
                temp_x_vec_candidate2 = z_dir.Crossed(gp_Dir(1, 0, 0))
                if temp_x_vec_candidate2.Magnitude() < 1e-7:
                    x_dir = gp_Dir(z_dir.Crossed(gp_Dir(0, 1, 0)).XYZ())
                else:
                    x_dir = gp_Dir(temp_x_vec_candidate2.XYZ())
            else:
                x_dir = gp_Dir(temp_x_vec_candidate1.XYZ())

        local_ax3 = gp_Ax3(origin, z_dir, x_dir)
        trsf.SetTransformation(local_ax3, gp_Ax3())  # Set transformation from local to global coordinate system
        return trsf
    except Exception as e:
        print(f"Error creating transformation: {e}")
        return None


def fix_shape_occ(shape_to_fix, name_for_debug=""):
    """Applies ShapeFix_Shape to repair a given TopoDS_Shape."""
    if not shape_to_fix or shape_to_fix.IsNull(): return None
    try:
        fixer = ShapeFix_Shape(shape_to_fix)
        fixer.Perform()
        return fixer.Shape()
    except Exception as e_fix:
        print(f"    ShapeFix ({name_for_debug}) exception: {e_fix}")
        return shape_to_fix


def build_sketch_geometry(sketch_data, sketch_entity_uuid_for_debug=""):
    """Builds all profile faces from a sketch entity, returning them in global coordinates."""
    sketch_name = sketch_data.get('name', sketch_entity_uuid_for_debug)
    sketch_transform = get_sketch_transform(sketch_data.get('transform', {}))
    if sketch_transform is None:
        print(f"Warning: Invalid transform for sketch '{sketch_name}'. Using identity transform.")
        sketch_transform = gp_Trsf()

    profile_faces_local = {}
    for profile_uuid, profile_def in sketch_data.get('profiles', {}).items():
        if not check_support.check_support(
                {"type": "Sketch", "profiles": {profile_uuid: profile_def}, "name": sketch_name}): continue

        wires_local = []
        profile_valid = True
        for loop in profile_def.get('loops', []):
            wire_builder = BRepBuilderAPI_MakeWire()
            for segment in loop.get('profile_curves', []):
                edge = None
                segment_type = segment.get("type")
                if segment_type not in check_support.SUPPORTED_PROFILE_SEGMENT_TYPES:
                    continue
                try:
                    if segment_type == "Line3D":
                        p1, p2 = create_gp_point(segment.get("start_point")), create_gp_point(segment.get("end_point"))
                        if p1 and p2 and p1.Distance(p2) > 1e-7: edge = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
                    elif segment_type == "Circle3D":
                        center_pt, radius, normal_data = create_gp_point(segment.get("center_point")), segment.get(
                            "radius"), segment.get("normal", {"x": 0, "y": 0, "z": 1})
                        if center_pt and radius is not None and radius > 1e-7:
                            normal_dir = gp_Dir(normal_data.get('x', 0), normal_data.get('y', 0),
                                                normal_data.get('z', 1))
                            edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(center_pt, normal_dir), radius)).Edge()
                    elif segment_type == "Arc3D":
                        p1, p2, center = create_gp_point(segment.get("start_point")), create_gp_point(
                            segment.get("end_point")), create_gp_point(segment.get("center_point"))
                        if p1 and p2 and center:
                            normal_data = segment.get("normal", {"x": 0, "y": 0, "z": 1})
                            normal_dir = gp_Dir(normal_data.get('x', 0), normal_data.get('y', 0),
                                                normal_data.get('z', 1))
                            circ = gp_Circ(gp_Ax2(center, normal_dir), p1.Distance(center))
                            edge = BRepBuilderAPI_MakeEdge(circ, p1, p2).Edge()

                    if edge and not edge.IsNull():
                        wire_builder.Add(edge)
                except Exception:
                    profile_valid = False
                    break
            if not profile_valid: break

            if wire_builder.IsDone():
                fixer = ShapeFix_Wire(wire_builder.Wire(), TopoDS_Face(), 1e-6)
                fixer.Perform()
                if fixer.Wire() and not fixer.Wire().IsNull():
                    wires_local.append({"wire": fixer.Wire(), "is_outer": loop.get('is_outer', False)})

        if not profile_valid: continue

        if wires_local:
            outer_wire = next((w['wire'] for w in wires_local if w['is_outer']), None)
            if outer_wire:
                face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
                for w_info in wires_local:
                    if not w_info['is_outer']: face_builder.Add(w_info['wire'])

                if face_builder.IsDone() and not face_builder.Face().IsNull():
                    face = fix_shape_occ(face_builder.Face(), f"Face_{profile_uuid[:8]}")
                    if face and not face.IsNull():
                        profile_faces_local[profile_uuid] = face

    profile_faces_global = {}
    for uuid, face_local in profile_faces_local.items():
        if face_local and not face_local.IsNull():
            transformed_shape = BRepBuilderAPI_Transform(face_local, sketch_transform, True).Shape()
            if not transformed_shape.IsNull() and transformed_shape.ShapeType() == TopAbs_FACE:
                profile_faces_global[uuid] = TopoDS.Face(transformed_shape)

    return profile_faces_global


def perform_boolean(base_solids, tool_shape, operation_type, step_name_for_debug=""):
    """Performs a boolean operation (Fuse, Cut, Common) on a list of base solids with a tool shape."""
    if not tool_shape or tool_shape.IsNull(): return base_solids
    fixed_tool = fix_shape_occ(tool_shape, f"Tool_{step_name_for_debug}")
    if not fixed_tool or fixed_tool.IsNull(): return base_solids

    if operation_type == "NewBodyFeatureOperation":
        return list(base_solids) + [fixed_tool]

    if not base_solids:
        return [fixed_tool] if operation_type == "JoinFeatureOperation" else []

    base_solid = base_solids[0]
    if len(base_solids) > 1:  # Fuse base solids if there are multiple
        fuse = BRepAlgoAPI_Fuse(base_solids[0], base_solids[1])
        for i in range(2, len(base_solids)):
            fuse = BRepAlgoAPI_Fuse(fuse.Shape(), base_solids[i])
        base_solid = fuse.Shape()

    result_shape = None
    try:
        if operation_type == "JoinFeatureOperation":
            op = BRepAlgoAPI_Fuse(base_solid, fixed_tool)
        elif operation_type == "CutFeatureOperation":
            op = BRepAlgoAPI_Cut(base_solid, fixed_tool)
        elif operation_type == "IntersectFeatureOperation":
            op = BRepAlgoAPI_Common(base_solid, fixed_tool)
        else:
            return base_solids

        op.Build()
        if op.IsDone() and not op.Shape().IsNull():
            result_shape = op.Shape()
    except Exception as e:
        print(f"      - Boolean ({operation_type}) operation failed: {e}")
        return base_solids

    return [result_shape] if result_shape and not result_shape.IsNull() else []


def perform_extrude(extrude_data, all_sketch_faces, current_solids, sketch_entity_data, extrude_name_for_debug=""):
    """Creates extruded solids from profile faces and applies boolean operations."""
    profile_refs = extrude_data.get('profiles', [])
    if not profile_refs: return current_solids

    input_faces = [all_sketch_faces.get(pref.get('profile')) for pref in profile_refs]
    input_faces = [f for f in input_faces if f and not f.IsNull()]
    if not input_faces: return current_solids

    extent_type = extrude_data.get("extent_type")
    operation_type = extrude_data.get("operation")
    mag1 = extrude_data.get("extent_one", {}).get("distance", {}).get("value", 0.0)
    mag2 = extrude_data.get("extent_two", {}).get("distance", {}).get("value",
                                                                      0.0) if extent_type == "TwoSidesFeatureExtentType" else 0.0

    sketch_trsf = get_sketch_transform(sketch_entity_data.get('transform', {}))

    if sketch_trsf is None:
        print(
            f"      - Error: Invalid transform for the sketch. Skipping extrude operation '{extrude_name_for_debug}'.")
        return current_solids

    direction = gp_Dir(0, 0, 1).Transformed(sketch_trsf)

    vec1 = gp_Vec(direction.XYZ()).Scaled(mag1)
    vec2 = gp_Vec(direction.Reversed().XYZ()).Scaled(mag2)

    all_prisms = []
    for face in input_faces:
        if abs(mag1) > 1e-7:
            prism = BRepPrimAPI_MakePrism(face, vec1).Shape()
            if prism and not prism.IsNull(): all_prisms.append(prism)
        if extent_type == "TwoSidesFeatureExtentType" and abs(mag2) > 1e-7:
            prism = BRepPrimAPI_MakePrism(face, vec2).Shape()
            if prism and not prism.IsNull(): all_prisms.append(prism)

    if not all_prisms: return current_solids

    tool_shape = all_prisms[0]
    if len(all_prisms) > 1:
        fuse = BRepAlgoAPI_Fuse(all_prisms[0], all_prisms[1])
        for i in range(2, len(all_prisms)):
            fuse = BRepAlgoAPI_Fuse(fuse.Shape(), all_prisms[i])
        tool_shape = fuse.Shape()

    return perform_boolean(current_solids, tool_shape, operation_type, extrude_name_for_debug)


def display_reconstructed_shape(shapes_to_display, window_title="Model Preview", **kwargs):
    """Displays the reconstructed shape(s) in a GUI window if available."""
    if display_available:
        try:
            display, start_display, _, _ = init_display()
            display.EraseAll()
            if isinstance(shapes_to_display, list):
                for shape in shapes_to_display:
                    display.DisplayShape(shape, update=False, **kwargs)
            else:
                display.DisplayShape(shapes_to_display, update=True, **kwargs)
            display.FitAll()
            start_display()
        except Exception as e:
            print(f"An error occurred during preview: {e}")


# --- Main Reconstruction Logic ---

def build_model_from_data(data):
    """
    Builds a 3D model from a JSON data dictionary.
    This function is 'pure' and does not perform file I/O.
    Returns the final TopoDS_Shape.
    """
    sequence, entities = data.get("sequence"), data.get("entities")
    if not sequence or not entities:
        print("Error: Invalid JSON data.")
        return None

    all_sketch_faces, current_solids = {}, []
    sketch_entities_map = {uuid: edata for uuid, edata in entities.items() if edata.get("type") == "Sketch"}
    processed_sketch_entity_uuids = set()

    for i, step in enumerate(sequence):
        step_type, entity_uuid = step.get("type"), step.get("entity")
        if not entity_uuid or entity_uuid not in entities:
            continue

        entity_data = entities[entity_uuid]
        entity_name = entity_data.get('name', 'Unnamed')

        if not check_support.check_support(entity_data):
            print(f"  Unsupported feature found in '{entity_name}'. Stopping reconstruction.")
            return None

        if step_type == "ExtrudeFeature":
            extrude_entity_data = entity_data

            required_sketches, source_sketch_for_extrude = set(), None
            for prof_ref in extrude_entity_data.get('profiles', []):
                sketch_uuid = prof_ref.get('sketch')
                if sketch_uuid:
                    required_sketches.add(sketch_uuid)
                    if not source_sketch_for_extrude:
                        source_sketch_for_extrude = sketch_entities_map.get(sketch_uuid)

            # Ensure all required sketches for this extrude are built before proceeding.
            for sketch_uuid_build in required_sketches:
                if sketch_uuid_build not in processed_sketch_entity_uuids and sketch_uuid_build in sketch_entities_map:
                    current_sketch = sketch_entities_map[sketch_uuid_build]
                    built_faces = build_sketch_geometry(current_sketch, sketch_uuid_build)
                    all_sketch_faces.update(built_faces)
                    processed_sketch_entity_uuids.add(sketch_uuid_build)

            if source_sketch_for_extrude:
                current_solids = perform_extrude(extrude_entity_data, all_sketch_faces, current_solids,
                                                 source_sketch_for_extrude, entity_name)

        elif step_type == "Sketch":
            # Build sketches that are defined in the sequence but not used by an extrude.
            if entity_uuid not in processed_sketch_entity_uuids and entity_uuid in sketch_entities_map:
                current_sketch_seq = sketch_entities_map[entity_uuid]
                built_faces_seq = build_sketch_geometry(current_sketch_seq, entity_uuid)
                all_sketch_faces.update(built_faces_seq)
                processed_sketch_entity_uuids.add(entity_uuid)

    final_shape = None
    if not current_solids:
        return None
    elif len(current_solids) == 1:
        final_shape = current_solids[0]
    else:
        # Fuse multiple bodies into one compound if needed.
        if len(current_solids) > 1:
            res = current_solids[0]
            for i in range(1, len(current_solids)):
                res = BRepAlgoAPI_Fuse(res, current_solids[i]).Shape()
            final_shape = res
        else:
            final_shape = current_solids[0]

    if final_shape and not final_shape.IsNull():
        return final_shape
    return None


def reconstruct_model(json_file_path):
    """
    Reads a JSON file, reconstructs the model, and handles file-based side effects
    (like saving STEP files and logs).
    """
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read or parse JSON '{json_file_path}': {e}")
        return None

    base_filename = os.path.splitext(os.path.basename(json_file_path))[0]
    print(f"Starting reconstruction for: {base_filename} (from {os.path.basename(json_file_path)})")

    final_shape = build_model_from_data(data)

    if final_shape and not final_shape.IsNull():
        output_dir = os.path.join(script_dir, "reconstruction_results")
        os.makedirs(output_dir, exist_ok=True)

        step_file_path = os.path.join(output_dir, f"{base_filename}.step")
        step_writer = STEPControl_Writer()
        Interface_Static.SetCVal("write.brep.mode", "1")
        step_writer.Transfer(final_shape, STEPControl_AsIs)
        if not step_writer.Write(step_file_path):
            print(f"Failed to save STEP file: {step_file_path}")
        else:
            print(f"Successfully saved model to STEP file: {step_file_path}")

    else:
        print(f"Component '{base_filename}' failed to reconstruct or did not produce a valid result.")

    return final_shape


# --- Main Execution Block (for standalone execution) ---
if __name__ == "__main__":
    json_filename = None
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith('.json'):
        candidate_path = sys.argv[1]
        if os.path.exists(candidate_path):
            json_filename = candidate_path
        elif os.path.exists(os.path.join(script_dir, candidate_path)):
            json_filename = os.path.join(script_dir, candidate_path)

    if not json_filename:
        json_files = [f for f in os.listdir(script_dir) if
                      f.lower().endswith('.json') and os.path.isfile(os.path.join(script_dir, f))]
        if json_files:
            json_filename = os.path.join(script_dir, json_files[0])

    if not json_filename:
        print("Error: Could not find a valid JSON input file.")
        sys.exit(1)

    print(f"Using JSON file: {os.path.basename(json_filename)}")
    final_model = reconstruct_model(json_filename)

    if final_model and not final_model.IsNull():
        print("\nModel reconstruction complete. Previewing final model:")
        display_reconstructed_shape(final_model, window_title="Final Model Preview")
