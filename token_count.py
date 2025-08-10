import json
import os
import glob  # Import the glob module for file path matching
from google import genai
from google.genai.types import HttpOptions

# --- Configuration ---
API_KEY = "YOUR_ACTUAL_API_KEY_HERE"  # <-- **Important: Replace with your actual API Key**

# --- Automatically Find JSON File ---
script_dir = os.path.dirname(__file__)  # Get the directory where the current script is located
json_files = glob.glob(os.path.join(script_dir, '*.json'))  # Find all .json files

if not json_files:
    print(f"Error: No JSON files found in the script directory '{script_dir}'. Please ensure a .json file exists.")
    exit()
elif len(json_files) > 1:
    print(f"Error: Multiple JSON files found in the script directory. Please ensure only one .json file exists, or manually specify the filename to use.")
    print("Files found:", [os.path.basename(f) for f in json_files])
    exit()

# Use the single JSON file found
json_filepath = json_files[0]
print(f"Detected and using JSON file: {os.path.basename(json_filepath)}")

# --- Read and Format JSON File Content ---
request_content = ""
try:
    with open(json_filepath, 'r', encoding='utf-8') as f:
        # json.load() parses the JSON content into a Python object (dict, list, etc.)
        data = json.load(f)
        # json.dumps() converts the Python object back into a JSON formatted string.
        # ensure_ascii=False ensures correct display of non-ASCII characters, indent=2 makes the output more readable.
        request_content = json.dumps(data, ensure_ascii=False, indent=2)

except json.JSONDecodeError:
    print(f"Error: Could not parse the file '{os.path.basename(json_filepath)}'. Please check if it is a valid JSON format.")
    exit()
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    exit()

if not request_content:
    print("Error: The request content extracted from the JSON file is empty. Please check if your JSON file is empty or incorrectly formatted.")
    exit()

# --- Initialize GenAI Client ---
client = genai.Client(
    api_key=API_KEY,
)

# --- Send Request to the Large Language Model ---
print(f"\nSending the full JSON content as a request (first 200 characters shown):\n---\n{request_content[:200]}...\n---\n")
try:
    # The `count_tokens` method is used here to calculate the number of tokens.
    # If you want the model to generate a response based on this JSON content,
    # you would likely use the `client.models.generate_content` method instead.
    response = client.models.count_tokens(
        model="gemini-2.0-flash",  # Choose the appropriate model for your needs
        contents=request_content,
    )
    print(response)
except Exception as e:
    print(f"An error occurred while sending the request to the language model: {e}")

# Example output from the API:
# total_tokens=10
# cached_content_token_count=None
