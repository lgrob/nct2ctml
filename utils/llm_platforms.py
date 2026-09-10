"""
LLM Platform classes for different AI service providers.
Each platform class encapsulates its specific configuration, request/response handling.
"""
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from loguru import logger
import re


class LLMPlatform(ABC):
    """Base class for LLM platforms."""
    
    def __init__(self, model: str, hostname: str):
        self.model = model
        self.hostname = hostname
    
    @property
    @abstractmethod
    def port(self) -> int:
        """Return the port number for this platform."""
        pass
    
    @property
    @abstractmethod
    def chat_endpoint(self) -> str:
        """Return the chat endpoint path for this platform."""
        pass
    
    @abstractmethod
    def get_request_body(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Generate the request body for this platform."""
        pass
    
    @abstractmethod
    def parse_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse the response from this platform."""
        pass
    
    def get_endpoint_url(self) -> str:
        """Get the full endpoint URL."""
        import urllib.parse
        return urllib.parse.urljoin(f"{self.hostname}:{self.port}", self.chat_endpoint)


class SGLangPlatform(LLMPlatform):
    """SGLang platform implementation."""
    
    def __init__(self, model: str, hostname: str):
        super().__init__(model, hostname)
        self._port = 30000
    
    @property
    def port(self) -> int:
        return self._port
    
    @property
    def chat_endpoint(self) -> str:
        return "v1/chat/completions"
    
    def get_request_body(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Generate SGLang request body."""
        req_body: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a biomedical researcher."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {
                "type": "json_object"
            },
            "stream": False
        }

        model_lower = (self.model or "").lower()
        if "deepseek" in model_lower and "r1" in model_lower:
            # DeepSeek-R1
            req_body["temperature"] = 0.5
            req_body["max_tokens"] = 8192
        else:
            # Qwen defaults
            req_body["temperature"] = 0.5
            req_body["top_p"] = 0.95
            req_body["top_k"] = 20
            req_body["max_tokens"] = 32768
            req_body["chat_template_kwargs"] = {"enable_thinking": False}

        return req_body
    
    def parse_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse SGLang response."""
        response_dict = {}
        try: # todo: simplify it with a find_tag() function or extract_tag()
            if type(ai_response) is dict and 'choices' in ai_response.keys() and type(ai_response['choices']) is list:
                answer = ai_response['choices'][0]
                ai_response_content = self._safe_get(answer, ['message', 'content'])
                if ai_response_content:
                    prefix_pos = ai_response_content.find('```json')  # look for ```json in response string
                    if prefix_pos > -1:
                        begin_content = ai_response_content.find('```json') + len('```json')
                        end_content = ai_response_content.find('```', begin_content)
                        response_string = ai_response_content[begin_content:end_content].strip()
                    else:
                        prefix_pos = ai_response_content.find('</think>')  # else get everything after </think>
                        if prefix_pos > -1:
                            begin_content = ai_response_content.find('</think>') + len('</think>')
                            response_string = ai_response_content[begin_content:].strip()
                        else:
                            response_string = ai_response_content
                    
                    sanitized_res = self._sanitize_json_string(response_string)
                    
                    response_dict = json.loads(sanitized_res, strict=False)
                    if isinstance(response_dict, dict) and "error" in response_dict:
                        response_dict.pop("error", None)
        except json.JSONDecodeError as ex:
            logger.error(f"Unexpected response format: {ex=} | response_string = {sanitized_res}, {type(ex)=}")
        return response_dict
    
    def _safe_get(self, dict_data, keys):
        """Helper method to safely get nested dictionary values."""
        for key in keys:
            dict_data = dict_data.get(key, {})
        return dict_data

    def _sanitize_json_string(self, response_string: str) -> str:
    # Replace backslash-escapes that JSON doesn’t understand (e.g. "\<") with the bare char
    # Valid escapes per JSON spec: " \ / b f n r t u
        return re.sub(r'\\(?![\\"\/bfnrtu])', '', response_string.replace('\\\\', '\\'))
        #return re.sub(r'\\([^"\\/bfnrtu])', r'\1', response_string)


class VLLMPlatform(SGLangPlatform):
    """vLLM platform implementation (uses same format as SGLang)."""
    
    def __init__(self, model: str, hostname: str):
        super().__init__(model, hostname)
        self._port = 8000
    
    @property
    def chat_endpoint(self) -> str:
        return "v1/chat/completions"


def _ollama_num_ctx() -> int:
    """Context window for Ollama, overridable via config.OLLAMA_NUM_CTX."""
    try:
        import config
        return getattr(config, 'OLLAMA_NUM_CTX', 16384)
    except Exception:
        return 16384


def _ollama_num_predict() -> int:
    """Max tokens Ollama may generate, overridable via config.OLLAMA_NUM_PREDICT."""
    try:
        import config
        return getattr(config, 'OLLAMA_NUM_PREDICT', 2048)
    except Exception:
        return 2048


class OllamaPlatform(LLMPlatform):
    """Ollama platform implementation."""
    
    def __init__(self, model: str, hostname: str):
        super().__init__(model, hostname)
        self._port = 11434
    
    @property
    def port(self) -> int:
        return self._port
    
    @property
    def chat_endpoint(self) -> str:
        #return "api/generate"
        return "api/chat"

    def _safe_get(self, dict_data, keys):
        for key in keys:
            dict_data = dict_data.get(key, {})
        return dict_data

    def get_request_body(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:

        if self.chat_endpoint == "api/generate":
            req_body = {
            "model": self.model,
            "prompt": prompt,
            "system": "You are a biomedical researcher specializing in cancer genomics and clinical trials.",
            "stream": False,
            "keep_alive": -1,
            "options": {
                "think": True,
                "temperature": 0,
                "seed": 42,
                "top_k": 1
            }
        }
        elif self.chat_endpoint == "api/chat":
            req_body = {
                "model": self.model,            
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a biomedical researcher specializing in cancer genomics and clinical trials."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "stream": False,
                "think": False,
                "keep_alive": "15m",
                "options": {
                    #"think": True,
                    "temperature": 0,
                    "seed": 42,
                    "top_k": 1,
                    # Ollama defaults num_ctx to 4096, which the genomic prompts
                    # (criteria text plus the ~4.4 KB gene list) overflow; the
                    # model then sees truncated input and degenerates.
                    "num_ctx": _ollama_num_ctx(),
                    # Cap generation. With "format": "json" a confused model can
                    # loop indefinitely because constrained decoding will not let
                    # it stop until it closes the JSON.
                    "num_predict": _ollama_num_predict(),
                }
            }

        if self.model and "qwen3.6" in self.model.lower():  
            req_body["chat_template_kwargs"] = {"enable_thinking": False}

        if json_schema is not None:
            req_body["format"] = json_schema
        else:
            req_body["format"] = "json"
        
        return req_body
    
    def parse_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        
        response_dict = {}
        if self.chat_endpoint == "api/generate":
            try:
                if type(ai_response) is dict and 'response' in ai_response.keys():
                    ai_response_content = ai_response['response']
                    response_dict = json.loads(ai_response_content)
            except json.JSONDecodeError as ex:
                logger.error(f"Unexpected response format: {ex=}, {type(ex)=}")
        
        elif self.chat_endpoint == "api/chat":
            try:
                if type(ai_response) is dict and 'message' in ai_response.keys():
                    ai_response_content = self._safe_get(ai_response, ['message', 'content'])
                    response_dict = json.loads(ai_response_content)
            except json.JSONDecodeError as ex:
                logger.error(f"Unexpected response format: {ex=}, {type(ex)=}")
        return response_dict


class LocalAIPlatform(LLMPlatform):
    """Local AI platform implementation (not yet configured)."""
    
    def __init__(self, model: str, hostname: str):
        super().__init__(model, hostname)
        self._port = 49152
    
    @property
    def port(self) -> int:
        return self._port
    
    @property
    def chat_endpoint(self) -> str:
        return "chat/completions"
    
    def get_request_body(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Generate Local AI request body."""
        raise NotImplementedError("Local_ai platform is not configured yet.")
    
    def parse_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Local AI response."""
        raise NotImplementedError("Local_ai platform is not configured yet.")


def create_llm_platform(platform_name: str, model: str, hostname: str) -> LLMPlatform:
    """
    Function to create an LLM platform instance based on platform name.    
    """
    platform_name_lower = platform_name.lower()
    
    if platform_name_lower == "sglang":
        print( "Creating SGLang platform..." )
        return SGLangPlatform(model, hostname)
    elif platform_name_lower == "ollama":
        print( "Creating Ollama platform..." )
        return OllamaPlatform(model, hostname)
    elif platform_name_lower == "vllm":
        return VLLMPlatform(model, hostname)
    elif platform_name_lower == "local_ai":
        return LocalAIPlatform(model, hostname)
    elif platform_name_lower == "anthropic":
        print( "Creating Anthropic platform..." )
        return AnthropicPlatform(model, hostname)
    else:
        raise ValueError(f"Unsupported LLM platform: {platform_name}")



class AnthropicPlatform(LLMPlatform):
    """
    Anthropic (Claude) platform implementation.

    Unlike the self-hosted platforms above, this talks to a hosted API over
    HTTPS using the official `anthropic` SDK, so it bypasses the
    hostname:port + requests.post path in ai_helper.send_ai_request by
    exposing a `send()` method. Authentication is resolved by the SDK from
    ANTHROPIC_API_KEY (or an `ant auth login` profile) - never hardcode a key.
    """

    SYSTEM_PROMPT = "You are a biomedical researcher specializing in cancer genomics and clinical trials."

    def __init__(self, model: str, hostname: str):
        super().__init__(model, hostname)
        self._client = None

    @property
    def port(self) -> int:
        # Not used - send() bypasses the hostname:port construction entirely.
        return 443

    @property
    def chat_endpoint(self) -> str:
        return "v1/messages"

    def get_endpoint_url(self) -> str:
        return "https://api.anthropic.com/v1/messages"

    def get_request_body(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Build the Messages API request kwargs."""
        import config

        body: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": getattr(config, "ANTHROPIC_MAX_TOKENS", 16000),
            "system": self.SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "adaptive"},
        }

        output_config: Dict[str, Any] = {"effort": getattr(config, "ANTHROPIC_EFFORT", "high")}
        if json_schema:
            # Every prompt builder in this repo currently returns json_schema=None,
            # so this branch is untested against the live API.
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        body["output_config"] = output_config

        return body

    def send(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Call the Messages API and return a response dict for parse_response()."""
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic()

        body = self.get_request_body(prompt, json_schema)

        try:
            response = self._client.messages.create(**body)
        except anthropic.AuthenticationError:
            logger.error(
                "Anthropic authentication failed. Set ANTHROPIC_API_KEY or run `ant auth login`."
            )
            raise
        except anthropic.RateLimitError as ex:
            logger.error(f"Anthropic rate limit hit: {ex}")
            raise
        except anthropic.APIStatusError as ex:
            logger.error(f"Anthropic API error {ex.status_code}: {ex.message}")
            raise
        except anthropic.APIConnectionError as ex:
            logger.error(f"Could not reach the Anthropic API: {ex}")
            raise

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            logger.error(f"Anthropic declined the request (category={category})")
            return {"text": "", "stop_reason": "refusal"}

        if response.stop_reason == "max_tokens":
            logger.warning(
                f"Anthropic response hit max_tokens ({body['max_tokens']}); JSON is likely truncated."
            )

        text = "".join(block.text for block in response.content if block.type == "text")
        logger.debug(
            f"Anthropic usage | in={response.usage.input_tokens} out={response.usage.output_tokens}"
        )
        return {"text": text, "stop_reason": response.stop_reason}

    def parse_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the JSON object out of the model's text response."""
        response_dict: Dict[str, Any] = {}
        content = (ai_response or {}).get("text", "")
        if not content:
            return response_dict

        # Strip a ```json fence if the model wrapped its answer in one.
        prefix_pos = content.find('```json')
        if prefix_pos > -1:
            begin = prefix_pos + len('```json')
            end = content.find('```', begin)
            response_string = content[begin:end].strip()
        else:
            response_string = content.strip()

        sanitized_res = re.sub(r'\\(?![\\\\"/bfnrtu])', '', response_string.replace('\\\\', '\\'))
        try:
            response_dict = json.loads(sanitized_res, strict=False)
            if isinstance(response_dict, dict):
                response_dict.pop("error", None)
        except json.JSONDecodeError as ex:
            logger.error(f"Unexpected response format: {ex=} | response_string = {sanitized_res}")
        return response_dict
