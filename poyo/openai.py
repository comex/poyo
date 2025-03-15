from pathlib import Path
from . import log, common
import requests
import requests.adapters
from functools import cached_property
from math import ceil

class OpenAISession:
    def __init__(self):
        api_key = (Path(__file__).parent / '../secrets/openai_api_key.txt').read_text().strip()
        self.s = requests.Session()
        self.s.headers['Authorization'] = f'Bearer {api_key}'
        self.model = 'gpt-4o'
        retry = requests.adapters.Retry(
            10000,
            status_forcelist={429, 503},
            backoff_factor=0.1,
            allowed_methods={'HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE', 'POST'},
        )
        self.s.mount('https://', requests.adapters.HTTPAdapter(max_retries=retry))


    @cached_property
    def encoding(self):
        with common.operation(f'loading encoding for {self.model}'):
            import tiktoken
            return tiktoken.encoding_for_model(self.model)

    def tokens_for_text(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def tokens_for_image_size(self, size: tuple[int, int]) -> int:
        tiles = ceil(size[0] / 512) * ceil(size[1] / 512)
        return 85 + 170 * tiles

