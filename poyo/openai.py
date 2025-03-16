import json
import logging
from pathlib import Path
import time
from typing import Iterable
import requests
import requests.adapters
from functools import cached_property
from math import ceil

from .common import operation
from .log import ImageContent, Message, MessageList, RecvLog, TextContent, filtered_log_to_html

class OpenAISession:
    def __init__(self):
        api_key = (Path(__file__).parent / '../secrets/openai_api_key.txt').read_text().strip()
        self.s = requests.Session()
        self.s.headers['Authorization'] = f'Bearer {api_key}'
        #self.model = 'gpt-4.5-preview'
        #self.model = 'o3-mini'
        self.model = 'o1'
        #self.model = 'gpt-4o'
        retry = requests.adapters.Retry(
            10000,
            status_forcelist={429, 503},
            backoff_factor=0.1,
            allowed_methods={'HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE', 'POST'},
        )
        self.s.mount('https://', requests.adapters.HTTPAdapter(max_retries=retry))


    @cached_property
    def encoding(self):
        with operation(f'loading encoding for {self.model}'):
            import tiktoken
            model = self.model
            if model.startswith('gpt-4.5'):
                # https://github.com/dotnet/machinelearning/issues/7404
                logging.warning(f'Using gpt-4o tokenizer for {model}')
                model = 'gpt-4o'
            return tiktoken.encoding_for_model(model)

    def tokens_for_text(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def tokens_for_image_size(self, size: tuple[int, int]) -> int:
        tiles = ceil(size[0] / 512) * ceil(size[1] / 512)
        return 85 + 170 * tiles

    def send(self, ml: MessageList) -> Iterable[RecvLog]:
        req = {
            'model': self.model,
            'messages': [m.dump_for_openai() for m in ml],
            'stream': True,
        }
        if self.model == 'o1':
            req['reasoning_effort'] = 'low'
        print('>>>>', req)
        yielded_any = False
        with self.s.post(
            'https://api.openai.com/v1/chat/completions',
            json=req,
            stream=True,
        ) as resp:
            lines: Iterable[bytes]
            match resp.headers['Content-Type'].split(';')[0]:
                case 'application/json':
                    lines = [resp.content]
                case 'text/event-stream':
                    lines = resp.iter_lines()
                case x:
                    raise Exception(f'unexpected content-type {x!r}')
            for line in lines:
                rdata = None
                try:
                    if line.startswith(b'data: '):
                        line = line[6:]
                    if line == b'[DONE]':
                        break
                    if not line.strip():
                        continue
                    rdata = json.loads(line)
                    rlog = RecvLog(time=time.time(), orig_resp=rdata)

                    assert rdata['object'] == 'chat.completion.chunk'
                    assert len(rdata['choices']) == 1
                    choice = rdata['choices'][0]


                    if choice['delta']:
                        content = choice['delta']['content']
                        assert isinstance(content, str)
                        rlog.delta = content

                    rlog.start = not yielded_any
                    if choice['finish_reason'] == 'stop':
                        rlog.finish = True
                    elif choice['finish_reason']:
                        rlog.error = True

                    yielded_any = True
                    yield rlog

                except BaseException as e:
                    if isinstance(e, Exception):
                        logging.exception(f'Got exception while parsing line {line!r}')
                    if yielded_any:
                        logging.warning(f'Yielding fake RecvLog due to exception {type(e)}')
                        yield RecvLog(time=time.time(), orig_resp=rdata, error=True)
                    raise



def main() -> None:
    sess = OpenAISession()
    ml = MessageList(sess)
    ml.append(Message(role='user', content=[
        TextContent(text='Analyze the contents of this image.'),
        ImageContent.from_name('ss00180.annotated.png'),
    ]))
    for bit in filtered_log_to_html(sess.send(ml)):
        print(bit, end='', flush=True)
if __name__ == '__main__': main()

