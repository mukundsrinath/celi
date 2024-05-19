# TODO -> Put stuff in utils/common where it makes sense

import sys
import os
import requests
from dotenv import load_dotenv
load_dotenv()
ROOT_DIR = os.getenv("ROOT_DIR")
sys.path.append(ROOT_DIR)

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from celi_framework.core.job_description import ToolImplementations
from celi_framework.utils.log import app_logger as logger
from celi_framework.utils.utils import load_json, load_text_file, write_string_to_file

ROOT_DIR = os.getenv("ROOT_DIR")

@dataclass
class LitReviewToolImplementations(ToolImplementations):

    def __post_init__(self):
        self.schema = load_json(f'{ROOT_DIR}/celi_framework/examples/lit-review/schema.json')
    
    def get_draft_progress():
        """
        Retrieves the draft progress from the draft file.

        Returns:
            dict: The draft progress as a dictionary.
        """

        draft_path = os.path.join(ROOT_DIR, 'celi_framework/examples/lit-review/output/draft.txt')
        draft = load_text_file(draft_path)
    
        return draft

    def get_special_instructions(self, current_scection) -> str:
        """
        Retrieves the special instructions for the provided section.

        Args:
            section (str): The section to retrieve special instructions for.

        Returns:
            str: The special instructions for the provided section.
        """

        pass

    def outline_scope_definition(self, current_section: str, scope_definition) -> str:
        """
        Outputs current section's scope definition based on the query. 

        Args:
            current_section (str): The current section to set the scope definition for.

        Returns:
            None
        """
        write_string_to_file(scope_definition, f'{ROOT_DIR}/celi_framework/examples/lit-review/output/working_directory/{current_section}.txt')

    def execute_query():
        pass
    
    def retrieve_relevant_literature(self, queries, limit=20, fields=["title", "abstract", "venue", "year"]) -> json:
        """
        Retrieves relevant literature based on the provided queries.

        Args:
            queries (list): The list of serach queries to retrieve relevant literature.
            limit (int): The maximum number of results to return.
            fields (List[str]): The fields to include in the response.

        Returns:
            json: The JSON response containing relevant literature.
        """

        for query in queries:
            query = query.replace(" ", "+")
            url = f'https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={limit}&fields={",".join(fields)}'
            #headers = {"x-api-key": S2_KEY}
            #response = requests.get(url, headers=headers)

            response = requests.get(url)
            response = response.json()

        response = requests.get(url)
        return response.json()

    def save_draft(self, draft_dict: str) -> dict:

        """
        Saves the provided draft as a JSON file and returns a structured dictionary.

        Args:
            draft_dict (str): A string representation of a dictionary containing the draft text under the 'draft_dict' key.

        Returns:
            dict: The structured dictionary that was saved.
        """

        timestamp = datetime.now().strftime("%m%d%y-%H%M%S")
        logger.info(f"DRAFT DICT TEXT LOOKS LIKE THIS\n{draft_dict}", extra={'color':'cyan'})


        output_path = os.path.join(ROOT_DIR, 'celi_framework/examples/lit-review/output/draft/',
                                     f'response-{timestamp}.txt')

        try:
            # Assuming draft_dict is a JSON string
            structured_dict = json.loads(draft_dict)

        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON: {e}")
            # Handle the error or fix the data as needed
            return None

        # Define the full path for the saved file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)  # Ensure directory exists

        # Save the JSON file
        with open(output_path, "w") as json_file:
            json.dump(structured_dict, json_file)

        return structured_dict