# --- Supported Type Constants ---
SUPPORTED_CURVE_TYPES = {"SketchLine", "SketchCircle", "SketchArc"}
SUPPORTED_PROFILE_SEGMENT_TYPES = {"Line3D", "Circle3D", "Arc3D"}
SUPPORTED_EXTENT_TYPES = {"DistanceExtentDefinition"}
SUPPORTED_EXTRUDE_TYPES = {"OneSideFeatureExtentType", "SymmetricFeatureExtentType", "TwoSidesFeatureExtentType"}
SUPPORTED_START_EXTENT_TYPES = {"ProfilePlaneStartDefinition"}


def check_support(entity_data):
    """
    Checks if the features within the given entity data are supported by the script.
    """
    e_type = entity_data.get("type")
    name = entity_data.get('name', 'Unnamed')
    supported = True

    if e_type == "Sketch":
        # Check for unsupported curve types within the sketch.
        if 'curves' in entity_data:
            for curve_uuid, curve_def in entity_data['curves'].items():
                if curve_def.get("type") not in SUPPORTED_CURVE_TYPES:
                    print(f"Warning: Sketch '{name}' contains an unsupported curve type '{curve_def.get('type')}'.")
                    supported = False
                    break
        # Check for unsupported segment types within the sketch profiles.
        if supported and 'profiles' in entity_data:
            for profile_uuid, profile_def in entity_data['profiles'].items():
                for loop in profile_def.get('loops', []):
                    for segment in loop.get('profile_curves', []):
                        if segment.get("type") not in SUPPORTED_PROFILE_SEGMENT_TYPES:
                            print(
                                f"Warning: Profile {profile_uuid} in sketch '{name}' contains an unsupported segment type '{segment.get('type')}'.")
                            supported = False
                            break
                    if not supported: break
                if not supported: break

    elif e_type == "ExtrudeFeature":
        # Check for various unsupported extrusion parameters.
        if entity_data.get("start_extent", {}).get("type") not in SUPPORTED_START_EXTENT_TYPES:
            print(f"Warning: Extrude feature '{name}' contains an unsupported start extent type.")
            supported = False
        if supported and entity_data.get("extent_type") not in SUPPORTED_EXTRUDE_TYPES:
            print(f"Warning: Extrude feature '{name}' contains an unsupported extent type.")
            supported = False
        if supported and entity_data.get("extent_one", {}).get("type") not in SUPPORTED_EXTENT_TYPES:
            print(f"Warning: extent_one in extrude feature '{name}' contains an unsupported extent definition.")
            supported = False
        if supported and entity_data.get("extent_type") == "TwoSidesFeatureExtentType" and \
                entity_data.get("extent_two", {}).get("type") not in SUPPORTED_EXTENT_TYPES:
            print(f"Warning: extent_two in extrude feature '{name}' contains an unsupported extent definition.")
            supported = False

        # Check for taper angles, which are noted but currently ignored by the reconstruction logic.
        t1 = entity_data.get("extent_one", {}).get("taper_angle", {}).get("value", 0.0)
        t2 = entity_data.get("extent_two", {}).get("taper_angle", {}).get("value", 0.0)
        if abs(t1) > 1e-7 or abs(t2) > 1e-7:
            print(f"Warning: Extrude feature '{name}' contains a taper angle, which will be ignored.")

    return supported
