import os
import time
import re
from google import genai
from google.genai import types

# --- Configuration Section ---
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"  # Please replace with your actual Gemini API Key
INPUT_DIRECTORY = "compressed_json"  # Directory containing the CAD image files
OUTPUT_FILE = "labels.txt"  # Name of the TXT file to save the results
MAX_RETRY = 5  # Maximum number of retries for each image

# --- Prompt Definition ---
TEXT_PROMPT = """
[System]: You are a CAD geometry recognition expert. Your tasks are:
1. Identify the part's continuity and provide structured tags
2. Add a one-sentence description of the part

[User]: Based on the provided CAD figure:
1. Determine if the model represents a single continuous part or multiple separate components
2. Identify the part's most salient geometric or functional features
   Return exactly 4 structured tags using the strict format: [continuity/primary_type/secondary_type/key_feature]
3. Provide a one-sentence description of the part within 20 words, ignore colour and focus on geometric features

Strict output requirements:
- Line 1: Only the bracketed tags
- Line 2: Only the description sentence
- Do not include any other text, numbering, or explanations

Valid tag types include:
- Continuity: single or multiple
- Primary type (e.g., shaft, bracket, housing, gear, plate)
- Secondary or sub-type (e.g., flanged, stepped, ribbed, mounting)
- Key geometric or functional feature (e.g., cylindrical hole, threaded slot, coupling face)

Example with multiple parts:
[multiple/bracket/mounting/holes]
a mounting bracket with two separate attachment plates.
"""

# --- Initialize Gemini Client ---
# Note: The user provided a placeholder key in the original script.
# It's kept here, but should be replaced with a valid one for the script to run.
client = genai.Client(api_key=GEMINI_API_KEY)


# --- Format Validation Function ---
def is_valid_response(response_text):
    """
    Checks if the response from the LLM conforms to the required format.
    """
    lines = response_text.strip().split('\n')

    # Check for the minimum number of lines.
    if len(lines) < 2:
        print("Format Error: Insufficient number of lines in response.")
        return False

    # Validate the tag format using regex.
    tag_line = lines[0].strip()
    if not re.fullmatch(r"\[[a-z0-9_\-]+/[a-z0-9_\-]+/[a-z0-9_\-]+/[a-z0-9_\-]+\]", tag_line):
        print(f"Format Error: Invalid tag format - {tag_line}")
        print(f"Debug Info: Regex did not match: {tag_line}")
        return False

    # Validate the description format.
    description = lines[1].strip()
    if not description:
        print("Format Error: Description is empty.")
        return False

    return True

# --- Main Logic Function ---
def process_images_in_directory(directory_path, output_file):
    """
    Processes all PNG images in a directory, generates labels using the Gemini API,
    and saves them to an output file.
    """
    processed_count = 0
    skipped_count = 0

    print(f"Starting to batch process images in directory: {directory_path}")
    print(f"Results will be saved to: {output_file}")

    # Clear the existing output file before starting.
    if os.path.exists(output_file):
        print(f"Clearing existing file: {output_file}...")
        open(output_file, 'w', encoding='utf-8').close()

    for filename in os.listdir(directory_path):
        if filename.lower().endswith(".png"):
            file_path = os.path.join(directory_path, filename)
            try:
                with open(file_path, 'rb') as f:
                    image_bytes = f.read()

                retry_count = 0
                valid_result = False
                result_text = ""

                # Loop until a valid result is obtained or max retries are reached.
                while retry_count < MAX_RETRY:
                    print(f"Analyzing image: {filename} (Attempt {retry_count + 1})")
                    try:
                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=[
                                types.Part.from_bytes(
                                    data=image_bytes,
                                    mime_type='image/png',
                                ),
                                TEXT_PROMPT
                            ]
                        )
                        time.sleep(0.1)  # Avoid sending requests too quickly.
                        result_text = response.text.strip()

                        if is_valid_response(result_text):
                            valid_result = True
                            break  # Success, exit the retry loop.
                        else:
                            print(f"Invalid format in response or API error: {result_text}")
                    except Exception as api_e:
                        print(f"An API call error occurred: {api_e}")
                        result_text = ""  # Clear the result to avoid using invalid data.

                    retry_count += 1

                if valid_result:
                    part_number = os.path.splitext(filename)[0]
                    lines = result_text.strip().split('\n')
                    tag_line = lines[0].strip()
                    description = lines[1].strip()
                    output_string = f"{part_number};{tag_line};{description}\n"

                    with open(output_file, 'a', encoding='utf-8') as outfile:
                        outfile.write(output_string)
                    print(f"Success: {output_string.strip()}")
                    processed_count += 1
                else:
                    print(f"Max retries exceeded or API failed continuously, skipping file: {filename}")
                    skipped_count += 1
            except Exception as e:
                print(f"An unknown error occurred while processing {filename}: {e}")
                skipped_count += 1
        else:
            print(f"Skipping non-PNG file: {filename}")

    print("\nBatch processing complete.")
    print(f"Successfully processed images: {processed_count}. Skipped images: {skipped_count}.")

# --- Program Entry Point ---
if __name__ == "__main__":
    if not os.path.exists(INPUT_DIRECTORY):
        print(f"Directory '{INPUT_DIRECTORY}' does not exist. It has been created.")
        os.makedirs(INPUT_DIRECTORY)
        print(f"Please place PNG images into this directory and run the script again.")
    else:
        process_images_in_directory(INPUT_DIRECTORY, OUTPUT_FILE)
