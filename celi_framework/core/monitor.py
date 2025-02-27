"""
Module: celi_framework.monitor

The MonitoringAgent class within this module is tasked with observing and evaluating the performance and output of a ProcessRunner instance. It leverages real-time data to provide insights and potentially influence the direction of ongoing processes. This class plays a pivotal role in ensuring the quality and efficiency of automated tasks by analyzing log files, processing queue messages, and utilizing AI models for deeper analysis.

Current Capabilities:
- Dynamically reads and analyzes log files generated by the ProcessRunner to monitor its progress and detect issues.
- Processes messages from a shared queue to act upon specific events or states identified during the ProcessRunner's operation.
- Interfaces with AI models to assess the quality of task completions and makes decisions based on predefined criteria.

Immediate Enhancements Planned:
- Ensure function call evaluations are appropriately managed and not inadvertently stored, maintaining clarity and relevance in the logs.
- Guarantee that each task is paired with a unique prompt completion document, enhancing traceability and review efficiency.
- Standardize evaluations across different task types for consistency in quality assessment.
- Address and gracefully handle exceptions within evaluations to maintain process integrity.
- Collaborate with domain experts to refine evaluation quality criteria, ensuring they meet high standards.
- Resolve issues related to token limits in AI model interactions, optimizing for both performance and cost.
- Integrate MongoDB more closely with the ProcessRunner for seamless template management and state tracking.
- Facilitate the creation and use of master templates through automated adjustments based on monitoring feedback.

Future Directions (Less Immediate):
- Implement advanced monitoring capabilities to identify and correct disturbing patterns in real-time, enhancing process adaptability.
- Modularize control mechanisms for easier management and updating of prompt templates, supporting continuous improvement.
- Utilize version control for prompt templates, ensuring traceability and ease of rollback if needed.
- Extend logging functionalities to include detailed activity logs of the MonitoringAgent, providing deeper insights into its operations.

Classes:
    MonitoringAgent: Monitors the ProcessRunner's operations by analyzing log updates and queue messages. It utilizes AI models to evaluate task completions and recommends adjustments to improve future task performances.

This module reflects an ongoing effort to enhance automated process monitoring and management, aiming for a dynamic, responsive, and efficient system capable of self-improvement over time.
"""

import os
import queue
import time
from contextlib import contextmanager

from celi_framework.core.templates import (
    make_prompt_for_secondary_analysis,
    make_prompt_for_function_call_analysis,
    # make_prompt_for_third_analysis,
)
from celi_framework.utils.exceptions import ContextLengthExceededException
from celi_framework.utils.llmcore_utils import SecondaryAnalysisReport, parse
from celi_framework.utils.llms import quick_ask
from celi_framework.utils.log import app_logger
from celi_framework.utils.token_counters import TokenCounter


class MonitoringAgent:
    """
    The MonitoringAgent class is designed to monitor and analyze the progress and outputs of a ProcessRunner instance, ensuring the efficiency and effectiveness of the process execution. It is integral to a system that dynamically adjusts to maintain quality and performance in automated tasks.

    Key Responsibilities:
    - Polls log files for real-time updates on the process execution, enabling immediate responses to critical events.
    - Processes messages from a queue, facilitating inter-component communication and synchronization within the system.
    - Utilizes advanced language models to analyze chat interactions and task completions, providing insights for quality assessments and potential improvements.
    - Implements decision-making mechanisms based on analysis results, which can influence the direction of the ProcessRunner's operations.

    Attributes:
        codex (MongoDBUtilitySingleton): Utility to interact with MongoDB, used for data retrieval and storage.
        update_queue (Queue): Queue for receiving updates from the ProcessRunner, used for communication between components.
        keep_running (bool): Controls the continuous operation of the monitoring loop.
        token_counter (TokenCounter): Utility for managing and tracking API token usage, ensuring efficient use of resources.
        prompt_completions_file (str), function_calls_file (str): Paths to files used for logging specific types of interactions for analysis.

    Methods:
        start(): Initializes monitoring activities, including file polling and queue processing.
        process_queue(): Handles incoming messages from the update_queue, managing tasks based on their content.
        analyze_prompt_completions(document_id): Analyzes the quality of prompt completions using secondary analysis and updates the system based on findings.
        periodic_review_with_third_llm(): Conducts periodic reviews using a tertiary language model to gain additional insights and make further adjustments.

    Future Enhancements:
    - Implementation of a more robust template editing and version control mechanism, directly influenced by monitoring feedback.
    - Integration of MongoDB for enhanced template management, allowing for dynamic adjustments based on performance evaluations.
    - Development of a sophisticated evaluation system to standardize quality assessments across different types of tasks.

    The MonitoringAgent acts as a critical component in a self-improving system, ensuring tasks are completed with high quality by continuously monitoring, analyzing, and adjusting the process flow based on real-time data.
    """

    def __init__(self, codex, parser_factory, update_queue, evaluations_dir):
        """ "
        Initializes the MonitoringAgent with dependencies for monitoring and analysis.

        Args:
            codex (MongoDBUtilitySingleton): The MongoDB utility instance for database interactions.
            update_queue (Queue): The queue from which updates and commands are received for processing.
        """
        self.codex = codex
        self.parser_factory = parser_factory
        self.secondary_ongoing_chat = ""
        self.update_queue = update_queue
        self.keep_running = True  # Flag to control the loop
        self.last_mod_time = 0  # Initialize last modification time
        self.current_log_update = ""
        self.last_position = 0  # Track the last read position in the file
        self.token_counter = TokenCounter(counter_type="monitor")
        self.prompt_completions_file = os.path.join(
            evaluations_dir, "prompt_completions_log.txt"
        )
        self.function_calls_file = os.path.join(
            evaluations_dir, "function_calls_log.txt"
        )
        app_logger.info(
            f"Initialized global_token_counter: {self.token_counter.counter_type}",
            extra={"color": "dark_grey"},
        )

    async def start(self):
        """
        Initiates the monitoring activities for the `MonitoringAgent`. This includes starting threads for both
        polling the log files for updates and processing messages from the update queue. The method sets up a
        continuous monitoring loop that runs asynchronously, allowing the `MonitoringAgent` to respond to events
        and updates in real-time without interrupting the main processing flow of the `ProcessRunner`.

        The log file polling thread continuously checks for new entries in the specified log file, aiming to
        detect and respond to events or errors logged by the `ProcessRunner`. Simultaneously, the queue processing
        thread listens for messages placed in the update queue, handling them as per the operational logic defined
        for various message types, such as document saves or context changes.

        Together, these threads enable the `MonitoringAgent` to maintain a comprehensive overview of the
        `ProcessRunner`'s activities, facilitating immediate responses to critical events and providing insights
        that may influence the direction of ongoing processes.
        """

        self.process_queue()

    def process_queue(self):
        """
        Processes incoming messages from the update queue continuously. This method acts as a consumer for the
        queue, where messages regarding the `ProcessRunner`'s activities — such as task completions, errors,
        and system notifications — are received and handled.

        The method implements a non-blocking fetch operation on the queue, ensuring that the monitoring activities
        remain responsive and efficient. Each message is processed based on its type, triggering appropriate actions
        such as logging, analysis, or adjustments to the monitoring strategy.

        This responsive mechanism allows the `MonitoringAgent` to adapt to the `ProcessRunner`'s current state,
        providing a dynamic and interactive monitoring experience. It plays a crucial role in maintaining the
        system's integrity, performance, and reliability by ensuring timely responses to process updates and anomalies.
        """

        while self.keep_running:
            try:
                # update_type, prompt_data = self.update_queue.get(block=False)
                update_type, prompt_data = (
                    self.update_queue.get_nowait()
                )  # Non-blocking get
                if update_type == "doc_save":
                    print("Processing prompt completion from queue.")
                    # Handle prompt_completion update here
                    # logger.info(f"Dequeued prompt_completion: {prompt_data}", extra={'color': 'blue'})
                    app_logger.info(
                        f"Dequeued document ID {prompt_data} to monitor",
                        extra={"color": "blue"},
                    )
                    self.analyze_prompt_completions(prompt_data)
                    # self.periodic_review_with_third_llm()
                elif update_type == "pop_context_triggered":
                    print("pop_context_triggered received in Monitor")
                    # Trigger the poll_log_file logic when pop_context is called
                    # self.poll_log_file() # TODO -> Comment back in when ready
            except queue.Empty:
                time.sleep(0.1)

    def analyze_prompt_completions(self, document_id):
        doc = self.codex.get_document_by_id(
            document_id=document_id, collection_name="process_executions"
        )
        # """
        # Analyzes the quality of prompt completions based on the document ID. This method fetches the document
        # associated with the given ID from MongoDB, evaluates its content using secondary analysis, and updates
        # the system based on the findings.

        # The analysis may involve checking the completion against quality criteria, extracting insights using
        # AI models, and determining if any adjustments to the process or content are necessary. The method may
        # also flag documents for review, trigger alerts for significant issues, or recommend specific actions
        # to improve task performance and completion quality.

        # Args:
        #     document_id (str): The unique identifier of the document to be analyzed, typically representing
        #                        a prompt completion or related output from the `ProcessRunner`.

        # The outcomes of this analysis contribute to continuous improvement efforts, informing decisions on
        # prompt adjustments, process refinements, and strategic planning for future tasks. It underscores the
        # `MonitoringAgent`'s role in ensuring high-quality outputs through proactive and data-driven oversight.
        # """

        if not doc:
            app_logger.error(
                f"Document with ID {document_id} not found.", extra={"color": "red"}
            )
            return

        prompt_exception = doc.get("prompt_exception", True)

        if prompt_exception:
            app_logger.info(
                f"Handling exception by analyzing the prompt completion:\n{doc['prompt_completion']}",
                extra={"color": "orange"},
            )

        # Choose the appropriate template based on whether it's a function call or not
        if doc["finish_reason"] == "function_call":
            prompt = make_prompt_for_function_call_analysis(
                system_message=doc["system_message"],
                ongoing_chat=doc["ongoing_chat"],
                function_name=doc.get("function_name", "Unknown function name"),
                function_arguments=doc.get(
                    "function_arguments", "Unknown arguments"
                ),  # Use 'task' as function_call_info
                prompt_completion=doc["prompt_completion"],
            )
        else:
            prompt = make_prompt_for_secondary_analysis(
                system_message=doc["system_message"],
                ongoing_chat=doc["ongoing_chat"],
                prompt_completion=doc["prompt_completion"],
                response=doc["response_msg"],
            )

        # Attempt secondary analysis with the first model choice
        try:
            if prompt_exception:
                model_name = "gpt-4-32k"
            else:
                model_name = "gpt-4-0125-preview"
            response = quick_ask(
                prompt, token_counter=self.token_counter, model_name=model_name
            )
        except ContextLengthExceededException as e:
            app_logger.info(
                f"Context length issue with model {model_name}: {e}",
                extra={"color": "orange"},
            )
            # Attempt with an alternative model if the primary model exceeds context length
            try:
                model_name = "gpt-4-1106-preview"
                app_logger.info(
                    f"Trying {model_name} instead: {e}", extra={"color": "orange"}
                )
                response = quick_ask(
                    prompt, token_counter=self.token_counter, model_name=model_name
                )
            except ContextLengthExceededException as e:
                app_logger.error(
                    f"Failed again with model {model_name}: {e}", extra={"color": "red"}
                )
                response = None  # Ensure graceful handling of failure

        # Writing to text files:
        app_logger.info(
            f"Secondary Analysis for {document_id}:\n{response}",
            extra={"color": "orange"},
        )
        # Determine file paths for logging
        # Choose the appropriate file based on the completion type
        log_file = (
            self.function_calls_file
            if doc["finish_reason"] == "function_call"
            else self.prompt_completions_file
        )
        # Prepare log content
        log_content = f"Document ID: {document_id}\nPrompt Completion:{doc['prompt_completion']}\nEvaluation: {response}\n\n"
        # Write to the appropriate log file
        with self.append_to_file(log_file) as file:
            file.write(log_content)
        app_logger.info(f"Logged analysis to {log_file}", extra={"color": "green"})

        # Process the response if available
        if response:
            app_logger.info(
                f"Response from secondary analysis for task {doc.get('task', 'Unknown task')}-{doc.get('task_desc', '')}",
                extra={"color": "orange"},
            )
            # Assuming parse_secondary_analysis_with_openai_parser exists and works as intended
            secondary_analysis = parse(
                self.parser_factory, target_cls=SecondaryAnalysisReport, msg=response
            )

            # Update MongoDB document with the analysis report
            try:
                report = {
                    k: v for k, v in vars(secondary_analysis).items() if v is not None
                }
                app_logger.info(
                    f"Parsed Evaluation Report:\n{report}", extra={"color": "orange"}
                )
                self.codex.add_or_update_fields_in_document(
                    collection_name="process_executions",
                    document_id=document_id,
                    new_fields=report,
                )
                app_logger.info(
                    f"Updated document with analysis report for doc {document_id}.",
                    extra={"color": "cyan"},
                )
            except Exception as e:
                app_logger.error(
                    f"Failed to update document {document_id} with analysis report: {e}"
                )
        else:
            app_logger.error("No response received from secondary analysis.")

    # def periodic_review_with_third_llm(self):
    #     """
    #     Conducts periodic reviews of the chat interactions using a tertiary language model (LLM) to gain additional insights
    #     and identify opportunities for improvements in the process. This method is designed to leverage a more advanced or
    #     differently specialized LLM to analyze the accumulated chat history, evaluate the effectiveness of interactions,
    #     and suggest modifications to the prompts or the drafting strategy.
    #
    #     The review process involves constructing a comprehensive prompt that summarizes the ongoing chat or highlights
    #     specific areas of concern, then submitting this prompt to the tertiary LLM. The response from this LLM is analyzed
    #     to extract actionable insights, such as recommendations for changing prompts, adjusting the conversation flow,
    #     or addressing identified issues directly within the chat content.
    #
    #     This method allows the `MonitoringAgent` to implement a layered analysis sapproach, where multiple models contribute
    #     to a deeper understanding and continuous refinement of the process. It underscores the system's capability for
    #     self-improvement and adaptation, ensuring that the drafting process remains aligned with quality standards and
    #     efficiency goals.
    #
    #     Returns:
    #         None. The primary outcome of this method is the application of insights gained from the tertiary LLM analysis
    #         to the monitoring and adjustment strategies. Any specific actions taken as a result of the review are handled
    #         internally and reflected in the operational adjustments or recommendations provided to the `ProcessRunner`.
    #
    #     This method plays a critical role in maintaining a high standard of quality and efficiency in the automated drafting
    #     process. By periodically reviewing the interaction history with an advanced analytical perspective, the
    #     `MonitoringAgent` ensures that the system's performance evolves in response to both explicit feedback and
    #     nuanced insights derived from AI-driven analysis.
    #     """
    #
    #     # TODO -> Just testing that I can pass through the info - will uncomment and activate
    #     # Use quick_ask for periodic review with the third LLM
    #     secondary_ongoing_chat = copy.deepcopy(self.secondary_ongoing_chat)
    #
    #     prompt = make_prompt_for_third_analysis(
    #         secondary_ongoing_chat
    #     )  # TODO -> Create prompt func
    #     prompt = secondary_ongoing_chat + " json"
    #     # response_str = quick_ask(prompt, token_counter, json_output=True)
    #     response_str = prompt
    #     app_logger.info(
    #         f"Response from quick ask: {response_str}", extra={"color": "blue"}
    #     )
    #
    #     response_str = {}
    #     response_str["response"] = prompt
    #     response_str = str(response_str)
    #
    #     print("throughput of periodic_review_with_third_llm")
    #     print(secondary_ongoing_chat)
    #
    #     try:
    #         response = (
    #             json.loads(response_str)
    #             if isinstance(response_str, str)
    #             else response_str
    #         )
    #     except json.JSONDecodeError:
    #         err_msg = (
    #             f"Error parsing response for quick ask json response: {response_str}"
    #         )
    #         prmpt_msg = f"Prompt was: \n{prompt}"
    #         response = f"{err_msg}\n{prmpt_msg}"
    #         app_logger.error("periodic_review_with_third_llm")
    #         app_logger.error(response)
    #
    #     # To be uncommented
    #     # logger.info(f"Decoded response from quick ask: {response}", extra={'color': 'blue'})
    #
    #     # Use the third LLM to analyze secondary_ongoing_chat
    #     # Process the decision, e.g., stop the process_runner if needed
    #     def enqueue_decision_based_on_analysis(self, analysis_result):
    #         if "stop" in analysis_result.lower():
    #             self.update_queue.put({"command": "stop"})
    #             # Add logic here
    #         elif "make_prompt" in analysis_result.lower():
    #             # Assuming the analysis result contains the new prompt information
    #             self.update_queue.put(
    #                 {"command": "make_prompt", "data": analysis_result}
    #             )
    #             # Add logic here
    #
    #     # make_decision_based_on_chat(response)  # TBD

    def read_log_file(self, file_path):
        """
        Reads the entire log file.

        Args:
            file_path (str): The path to the log file.

        Returns:
            str: The content of the log file.
        """

        app_logger.info(f"Reading log file: {file_path}", extra={"color": "orange"})
        with open(file_path, "r") as file:
            return file.read()

    def is_green_log(self, log_message):
        """
        Checks if a log message contains a green color code.

        Args:
            log_message (str): The log message to check.

        Returns:
            bool: True if the log message contains the green color code, False otherwise.
        """

        # Check if the log message contains the green color ANSI code
        green_color_code = "\033[92m"
        return green_color_code in log_message

    def stop(self):
        """
        Stops the monitoring agent.

        Sets the keep_running flag to False, effectively terminating the monitoring loops.
        """

        app_logger.info("Stopped monitor", extra={"color": "orange"})
        self.keep_running = False

    # Helper context manager for file operations
    @contextmanager
    def append_to_file(self, filename):
        """
        Context manager for appending to a file.

        Args:
            filename (str): Path to the file.
        """
        with open(filename, "a") as file:  # Open file in append mode
            yield file
