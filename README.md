# LLM for CAD: From Natural Language to 3D Models

This project aims to explore and implement a Large Language Model (LLM) workflow capable of automatically translating a user's design intent, described in natural language, into a sequence of parametric commands executable by Computer-Aided Design (CAD) software.

The entire process covers the full pipeline from raw CAD data processing, model reconstruction, image and text annotation, data classification, and detailed build plan generation, to the final preparation of fine-tuning datasets and model performance evaluation.

## Core Features

* **CAD Data Processing**: Automatically cleans, prunes, and renames raw CAD data files.
* **3D Model Reconstruction**: Reconstructs 3D models from processed JSON data using `python-occ-core` and generates preview images.
* **AI-Powered Data Annotation**: Utilizes the Gemini model to generate semantic tags, brief descriptions, and detailed build plans for part images.
* **Automated Classification**: Automatically categorizes a large number of parts based on their geometric and functional features.
* **Data Visualization**: Provides a Graphical User Interface (GUI) to display and analyze the classified part data.
* **Fine-Tuning Dataset Generation**: Generates structured fine-tuning datasets for three different model training strategies (Routes A/B/C).
* **Performance Evaluation**: Provides comprehensive scripts to evaluate the accuracy of the model's output under different strategies.

## Project Workflow & Script Execution Order

This project consists of a series of Python scripts that must be executed in a specific order. Please follow the workflow below:

1.  **Data Preprocessing and Reconstruction**
    * `1_prune_json.py`: Cleans and simplifies the original CAD JSON files.
    * `2_batch_reconstruction.py`: Batch reconstructs models, compresses the simplified JSON data into a custom format, and generates `.png` preview images.

2.  **AI Annotation and Classification**
    * `3_batch_labeling.py`: Calls the Gemini API to generate semantic tags and brief descriptions for each part's `.png` image.
    * `4_batch_clustering.py`: Calls the API again to classify parts based on the tags and descriptions from the previous step.
    * `5_copy_by_category.py`: Copies the corresponding `.json` and `.png` files into their respective category folders based on the classification results.

3.  **Data Visualization and Analysis**
    * `6_visualize_catagories.py`: Launches a GUI application to display the classification results with charts and an image gallery.

4.  **Detailed Description and Fine-Tuning Data Generation**
    * `7_batch_description.py`: Generates a detailed, step-by-step "build plan" for each part.
    * `8_fine_tuning_data_prep.py`: Integrates all data to prepare the final training and test datasets for model fine-tuning.

5.  **Model Performance Evaluation**
    * `9_assessment_A.py`: Evaluates the model's performance in generating the full JSON format (Route A).
    * `10_assessment_B_C.py`: Evaluates the model's performance in generating the simplified command set (Routes B/C).

## Environment Setup & Installation

1.  **Create and Activate Conda Environment** (Recommended):
    ```bash
    conda create -n cad_llm python=3.9
    conda activate cad_llm
    ```

2.  **Install Dependencies**:
    All Python dependencies for this project are listed in the `requirements.txt` file. Run the following command to install them:
    ```bash
    pip install -r requirements.txt
    ```
    * **Special Note**: The installation of `tkinter` and `python-occ-core` may have special requirements. Please refer to the detailed instructions in the `requirements.txt` file.

3.  **Configure API Key**:
    In the following scripts, you need to replace the placeholder with your own Google Gemini API key:
    * `3_batch_labeling.py`
    * `4_batch_clustering.py`
    * `7_batch_description.py`
    * `token_count.py`
    ```python
    GEMINI_API_KEY = "YOUR_ACTUAL_API_KEY_HERE"
    ```

## Detailed Script Descriptions

* `1_prune_json.py`: **Data Pruner**. Removes redundant information from the original JSON and renames entity IDs for better readability.
* `2_batch_reconstruction.py`: **Batch Reconstructor**. Executes the full pipeline of compressing, decoding, and reconstructing models, saving `.step` files and `.png` previews.
* `3_batch_labeling.py`: **Batch Labeler**. Generates initial natural language descriptions and structured tags for each part image.
* `4_batch_clustering.py`: **Batch Classifier**. Sorts parts into predefined categories based on their labels.
* `5_copy_by_category.py`: **File Organizer**. Organizes files into a structured directory based on classification results for easier subsequent processing.
* `6_visualize_catagories.py`: **Category Visualizer**. A Tkinter GUI to intuitively display the quantity and samples of parts in each category.
* `7_batch_description.py`: **Detailed Description Generator**. Creates detailed geometric construction steps to guide model learning.
* `8_fine_tuning_data_prep.py`: **Fine-Tuning Data Preparer**. The final data processing step that generates `.jsonl` files formatted for model fine-tuning.
* `9_assessment_A.py`: **Assessment Script (Route A)**. Evaluates the model's ability to generate a complete JSON sequence.
* `10_assessment_B_C.py`: **Assessment Script (Routes B/C)**. Evaluates the model's ability to generate a simplified command sequence.
* `check_support.py`: **Feature Support Checker** (Auxiliary Module). Checks if a CAD file contains geometric features supported by the current scripts.
* `chosen_categories.py`: **Category Config** (Auxiliary Module). Defines the part categories used in the project.
* `compress_json.py`: **JSON Compressor** (Auxiliary Module). Converts the JSON structure into a simplified, custom command format.
* `decode_json.py`: **JSON Decoder** (Auxiliary Module). Converts the simplified command format back into a JSON structure.
* `reconstruction.py`: **Model Reconstruction Core** (Auxiliary Module). Encapsulates the core logic for 3D model reconstruction using `python-occ-core`.
* `token_count.py`: **Token Counter** (Utility Script). Calculates the number of API tokens required for a given JSON file's content.
