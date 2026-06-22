import json
from diskcache import Cache
import hashlib
import random
import argparse
from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Union
import os
import time
import re
import copy
import logging


class LLMBase(ABC):
    def __init__(self, model_name: str, storage_dir, cache=None):
        self.model_name = model_name
        self.cache = (
            Cache(os.path.join(storage_dir, "llm_cache")) if cache is None else cache
        )
        self.normalized_model_name = self._normalize_model_name(model_name)

    def _normalize_model_name(self, model_name):
        # Match anthropic.<short-name> where <short-name> ends with either
        #   * old style with version suffix:  claude-3-7-sonnet-20250219-v1
        #   * new style without -v suffix:    claude-opus-4-7
        match = re.search(
            r"(?<=anthropic\.)(claude-\d+-\d+-\w+-\d+)(?=-v\d+)", model_name
        )
        if match:
            return match.group(1)
        match = re.search(r"(?<=anthropic\.)(claude-[\w-]+)$", model_name)
        return match.group(1) if match else model_name

    def _hash_query(
        self, messages: Union[str, List[Dict[str, str]]], normalized=True
    ) -> str:
        """Generate a hash for the prompt and model name to use as a cache key."""
        if isinstance(messages, str):
            prompt_str = messages
        elif isinstance(messages, list):
            if len(messages) > 1:
                prompt_str = json.dumps(
                    messages, separators=(",", ":")
                )  # preserves order
            else:
                prompt_str = self.get_single_string_from_messages(messages)
        else:
            raise TypeError(f"Unsupported prompt type: {type(messages)}")

        name = self.normalized_model_name if normalized else self.model_name
        key = hashlib.sha256(f"{prompt_str}-{name}".encode()).hexdigest()
        return key

    @staticmethod
    def _validate_messages(messages: List[Dict[str, str]]) -> None:
        """Validate that each message has exactly 'role' and 'content' keys, both of which must be strings."""
        for i, message in enumerate(messages):
            if not isinstance(message, dict):
                raise TypeError(f"Message at index {i} is not a dict: {message}")
            if set(message.keys()) != {"role", "content"}:
                raise ValueError(
                    f"Message at index {i} must have exactly 'role' and 'content' keys: {message}"
                )
            if not all(isinstance(message[k], str) for k in ("role", "content")):
                raise TypeError(
                    f"Both 'role' and 'content' must be strings in message at index {i}: {message}"
                )

    def _sample_from_responses(
        self,
        responses: List[Tuple[str, float]],
        temperature: float,
        num_responses_to_return=1,
    ) -> Tuple[str, float]:
        """Sample a response uniformly at random."""
        random.seed(42)
        k = (
            num_responses_to_return
            if num_responses_to_return <= len(responses)
            else len(responses)
        )

        if temperature == 0:
            return responses[0:k]
        samples = random.sample(responses, k=k)
        assert samples is not None
        assert len(samples) == k

        return samples

    @abstractmethod
    def get_single_string_from_messages(self, messages):
        pass

    def get_response(
        self,
        messages: Union[str, List[Dict[str, str]]],
        temperature: float = 0.7,
        clear=False,
        force_cached=False,
        num_responses_to_return=1,
        cache_more=False,
        **kwargs,
    ):
        """
        Check cache or generate new responses.
        Returns the response and whether it was in the cache.
        If clear == True, the corresponding entry in the cache is deleted and get_response returns
        whether the entry existed in the cache, together with the newly generated response.
        """
        assert not (force_cached and cache_more)
        if clear:
            self.delete_from_cache(messages)

        num_responses_to_return = int(num_responses_to_return)
        cache_hit, responses = self.get_from_cache(messages).values()

        assert not clear or not cache_hit
        if (
            not cache_hit
            and (
                self.model_name.startswith("anthropic")
                or self.model_name.startswith("us.anthropic")
            )
            and not isinstance(messages, str)
        ):
            messages_copy = copy.deepcopy(messages)
            self._normalize_messages(messages_copy)
            cache_hit, responses = self.get_from_cache(messages_copy).values()

        assert not clear or not cache_hit
        assert cache_hit or not responses
        num_cached = len(responses) if responses else 0
        if not force_cached and (
            not cache_hit or cache_more or num_responses_to_return > num_cached
        ):
            more_responses = self._generate_responses(
                messages, num_samples=num_responses_to_return - num_cached
            )
            assert (
                len(more_responses) == num_responses_to_return - num_cached
            )  # intolerant to throttling exceptions
            self.store_in_cache(messages, more_responses)
            responses = list(self.get_from_cache(messages).values())[1]
            # responses = self.get_from_cache(messages).values()
            # print(responses)
            # responses = responses[1]
            assert len(responses) == num_responses_to_return

        sampled = (
            self._sample_from_responses(responses, temperature, num_responses_to_return)
            if responses
            else None
        )

        return {"cache_hit": cache_hit, "response": sampled}

    def get_from_cache(self, messages: Union[str, List[Dict[str, str]]]):

        query_hash = self._hash_query(messages)

        if query_hash not in self.cache:
            unnormalized_hash = self._hash_query(messages, normalized=False)
            if unnormalized_hash in self.cache:
                self.store_in_cache(messages, self.cache[unnormalized_hash])

        if query_hash in self.cache:
            return {"cache_hit": True, "response": self.cache[query_hash]}

        return {"cache_hit": False, "response": None}

    def delete_from_cache(self, messages: Union[str, List[Dict[str, str]]]):

        query_hash = self._hash_query(messages)

        if query_hash in self.cache:
            self.cache.delete(query_hash)

    def store_in_cache(self, messages: Union[str, List[Dict[str, str]]], responses):
        query_key = self._hash_query(messages)
        assert len(responses) and responses[0] != ""  # TODO: ADAPT TO DICT RESPONSES
        self.cache[query_key] = self.cache.get(query_key, []) + responses

    def get_num_samples(self, prompt: str) -> int:
        query_hash = self._hash_query(prompt)
        if query_hash not in self.cache:
            return 0
        else:
            return len(self.cache[query_hash])

    @abstractmethod
    def _generate_responses(
        self,
        messages: Union[str, List[Dict[str, str]]],
        num_samples: int = 5,
        temperature=0.7,
    ):  # -> List[Tuple[str, float]]:
        """Generate multiple responses. Will maybe support probabilities for a prompt as well."""
        pass


class Claude(LLMBase):
    def __init__(self, model_name: str, storage_dir: str, cache=None):
        super().__init__(model_name=model_name, storage_dir=storage_dir, cache=cache)

    def _normalize_messages(self, messages):

        if isinstance(messages, str):
            return messages

        for msg in messages:
            if isinstance(msg.get("content"), str):
                msg["content"] = [{"text": msg["content"]}]
        return messages

    @staticmethod
    def claudify(prompt):
        return "\n\nHuman: " + prompt + "\n\nAssistant: "

    def get_single_string_from_messages(self, messages):
        assert len(messages) == 1

        if isinstance(messages[0]["content"], str):
            return messages[0]["content"]
        else:
            assert isinstance(messages[0]["content"], list)
            assert len(messages[0]["content"]) == 1
            assert "text" in messages[0]["content"][0]
            return messages[0]["content"][0]["text"]

    # TODO: max retries for anthropic.claude-v2:1 is 4? Throws throttling exception.
    def _generate_responses(
        self,
        messages: Union[str, List[Dict[str, str]]],
        num_samples: int = 1,
        temperature=0.7,
    ) -> List[Tuple[str, float]]:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": [{"text": messages}]}]

        else:
            messages = self._normalize_messages(messages)

        if not hasattr(self, "client"):
            import boto3
            try:
                self.client = boto3.client(
                    "bedrock-runtime",
                    region_name=os.getenv("AWS_REGION_NAME", "us-west-2"),
                )

            except Exception:
                aws_config = {
                    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
                    "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
                    "aws_session_token": os.getenv("AWS_SESSION_TOKEN"),
                    "region_name": os.getenv("AWS_REGION_NAME"),
                }
                self.client = boto3.client(
                    "bedrock-runtime",
                    **{k: v for k, v in aws_config.items() if v is not None},
                )

        responses = []
        last_error = None
        for _ in range(num_samples):
            time.sleep(20)
            try:
                start = time.perf_counter()
                response = self.client.converse(
                    modelId=self.model_name, messages=messages
                )
                end = time.perf_counter()
                result = response["output"]["message"]["content"][0]["text"]
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.error(f"Prompting {self.model_name}: {e}")
                last_error = e
                continue

            responses.append(
                {
                    "text": result,
                    "time": end - start,
                    "input_tokens": response["usage"]["inputTokens"],
                    "output_tokens": response["usage"]["outputTokens"],
                }
            )

        if responses == []:
            raise ValueError(last_error)
        return responses



class GPT(LLMBase):
    def __init__(self, model_name: str, storage_dir: str, cache=None):
        super().__init__(model_name=model_name, storage_dir=storage_dir, cache=cache)
        # self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.client = None

    def get_single_string_from_messages(self, messages):
        assert len(messages) == 1
        assert isinstance(messages[0]["content"], str)
        return messages[0]["content"]

    def _responses_api(
        self,
        input: Union[str, List[Dict[str, str]]],
        num_samples: int = 1,
        temperature=1,
    ):
        responses = []
        for _ in range(num_samples):
            start = time.perf_counter()
            response = self.client.responses.create(model=self.model_name, input=input)
            end = time.perf_counter()
            responses.append(
                {
                    "text": response.output[1].content[0].text,
                    "time": end - start,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
            )
        return responses

    def _generate_responses(
        self,
        messages: Union[str, List[Dict[str, str]]],
        num_samples: int = 5,
        temperature=1,
    ) -> List[Tuple[str, float]]:
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        responses = []
        if self.model_name.startswith("gpt-5"):
            responses = self._responses_api(messages, num_samples=num_samples)
        else:
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]

            responses = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_completion_tokens=4096,
                n=num_samples,
                temperature=temperature,
            )
            responses = [
                {"text": choice.message.content, "time": float("-inf")}
                for choice in responses.choices
            ]
            assert len(responses) == num_samples

        return responses


def get_model(model_name, storage_dir=None, cache=None):
    model_classes = {
        "claude": Claude,
        "anthropic": Claude,
        "us.anthropic": Claude,
        "gpt": GPT,
        "ft:gpt": GPT,
    }

    init_kwargs = {"cache": cache} if cache is not None else {}

    return next(
        (
            model_class(model_name, storage_dir, **init_kwargs)
            for prefix, model_class in model_classes.items()
            if model_name.startswith(prefix)
        ),
        None,
    )


def prompt_llms(config_file, **kwargs):
    # Load prompt and model name from the JSON file
    with open(config_file, "r") as f:
        params = json.load(f)

    model_name = params["model_name"]
    messages = params["prompt"] if "prompt" in params else params["messages"]

    model = get_model(model_name, kwargs.pop("storage_dir", None), kwargs.pop("cache", None))
    if model is None:
        raise ValueError(f"Unsupported model: {model_name}")

    result = model.get_response(messages, **kwargs)

    if result["response"] is not None and model_name != "gpt-4o-2024-08-06":
        logger = logging.getLogger(__name__)
        perf_time = sum(
            [sample["time"] for sample in result["response"] if sample["time"] > 0]
        )
        tokens_sum = sum(
            [
                sample["input_tokens"] + sample["output_tokens"]
                for sample in result["response"]
            ]
        )
        logger.info(
            f"Module: {params['module_name']} Inference time for sampled responses: {perf_time}"
        )
        logger.info(
            f"Module: {params['module_name']} Total tokens for sampled responses: {tokens_sum}"
        )
    return result


def main():
    # Initialize cache
    # cache = Cache('./cache')

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config_file",
        type=str,
        help="Path to the JSON file containing the prompt, model and parameter specifications.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear cache entry and force prompting underlying llm. Saves new response in cache",
    )
    parser.add_argument(
        "--force_cached", action="store_true", help="Return response only if cached"
    )
    parser.add_argument(
        "--return_all", action="store_true", help="Return all samples for given prompt"
    )
    parser.add_argument(
        "--temperature",
        help="Temperature according to which to sample, not supported yet",
    )

    args = parser.parse_args()
    args.storage_dir = os.getenv("STORAGE_DIR")
    kwargs = {
        key: value
        for key, value in vars(args).items()
        if key in {"clear", "force_cached", "temperature", "return_all", "storage_dir"}
        and value is not None
    }

    result = prompt_llms(args.config_file, **kwargs)
    print(result["response"])


if __name__ == "__main__":
    main()
