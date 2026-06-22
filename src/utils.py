import json
import re
import os
import logging
import shutil
from logging import StreamHandler, FileHandler
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = os.path.join(ROOT_DIR, "templates/fewshot_prompt.txt")
DEFAULT_TEMPLATE_FS = os.path.join(ROOT_DIR, "templates/fewshot_prompt.txt")
DEFAULT_TEMPLATE_FS_GPT5 = DEFAULT_TEMPLATE_FS
DEFAULT_EXAMPLE_MODULES_DIR = os.path.join(ROOT_DIR, "fewshot/examples_raw")
DEFAULT_EXAMPLE_RESPONSES_DIR = os.path.join(ROOT_DIR, "fewshot/examples_full")
DEFAULT_REPAIR_TEMPLATE = os.path.join(ROOT_DIR, "templates/repair_template.txt")


class _ExperimentContext(logging.Filter):
    """Injects experiment_id into every log record."""

    def __init__(self, experiment_id: str):
        super().__init__()
        self.experiment_id = experiment_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "experiment_id"):
            record.experiment_id = self.experiment_id
        return True


def setup_logging(
    log_file: str,
    experiment_id: str,
    level: int = logging.INFO,
    to_console: bool = True,
):
    """
    Configure root logger once. Subsequent getLogger(__name__) calls in any module will inherit this setup.
    """
    # Make sure the directory exists
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # If re-running in the same process (e.g., notebooks), clear old handlers/filters
    for h in list(root.handlers):
        root.removeHandler(h)
    for f in list(root.filters):
        root.removeFilter(f)

    # Common formatter includes experiment id
    fmt = logging.Formatter(
        # "%(asctime)s %(levelname)s [%(experiment_id)s] %(name)s: %(message)s"
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    fh = FileHandler(log_file, mode="w", encoding="utf-8")  # added mode="w"
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if to_console:
        ch = StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # Inject experiment_id everywhere
    root.addFilter(_ExperimentContext(experiment_id))


def extract_json_block(llm_output):
    """Extracts JSON content from within <json>...</json> tags."""
    match = re.search(
        r"<json>\s*(\{.*?\})\s*</json>", llm_output, re.DOTALL | re.IGNORECASE
    )
    if match:
        json_text = match.group(1)
        try:
            return (True, json.loads(json_text))
        except json.JSONDecodeError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to parse JSON: {e}")
            return (False, e)
    else:
        return (False, "[ERROR] No JSON block found in LLM output.")


def extract_lemmas(json_data):
    """Parses lemmas from JSON output."""
    try:
        if "lemma" in json_data["lemmas"][0]:
            return [lemma["lemma"] for lemma in json_data["lemmas"]]
        else:
            return [list(lemma.values())[0] for lemma in json_data["lemmas"]]
    except (KeyError, TypeError, IndexError) as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Invalid JSON structure: {e}")
        return []


def read_file(file_path):
    """Reads the content of a file and returns it as a string."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def clear_directory(path):
    for filename in os.listdir(path):
        file_path = os.path.join(path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)  # remove file or symlink
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)  # remove directory
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")
