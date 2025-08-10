# chosen_categories.py: Configuration for part categories.

# This is the single source of truth: defines the base names for all categories.
# These names are used to locate corresponding files and directories.
CATEGORY_BASE_NAMES = [
    "category_3_screws",
    "category_4_nuts",
    "category_7_shafts_cylinders",
    "category_8_gaskets_washers",
    "category_10_plates_disks",
    "category_11_beams",
    "category_12_housings_bushings",
    "category_18_blocks",
    "category_19_pipes",
]

# Generate a comprehensive configuration list based on the base names.
# Each script can use the keys from this list ('name', 'img_dir', 'json_dir', 'txt_file') as needed.
CATEGORIES_CONFIG = [
    {
        "name": base_name,
        "img_dir": f"{base_name}_png",
        "json_dir": f"{base_name}_json",
        "txt_file": f"{base_name}.txt"
    }
    for base_name in CATEGORY_BASE_NAMES
]
