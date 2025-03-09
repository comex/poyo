import datetime
import time
import re
import ast
from typing import Optional
from pathlib import Path

from common import get_unique_path, log_dir

_a = time.time()
import google.genai # :( this is super slow
_b = time.time()
print('genai import time is', _b-_a)

from google.genai.types import PartUnionDict, Part, GenerateContentConfig, Tool, FunctionDeclaration, Schema, Type as SType, Content

# why not just pickle it or something? because I want to be able to edit it if desired
def parse_log_bit(bit: str, ret: list[Content], parts: list[Part]) -> None:
    m = re.fullmatch(r'^20.*?  ([^:]*):(.*)', bit, flags=re.S)
    if not m:
        raise Exception('bad format 1')
    action, rest = m.groups()
    #print('^^', action)
    match action:
        case 'Sending':
            text = ast.literal_eval(rest)
            parts.append(Part.from_text(text=text))
        case 'Sending image':
            assert '/' not in rest
            image = log_dir / rest.strip()
            parts.append(Part.from_bytes(data=image.read_bytes(), mime_type='image/png'))
        case 'Response':
            resp = rest.replace('\n> ', '\n')
            assert resp.startswith('\n')
            resp = resp[1:]
            if not parts:
                raise Exception('No input for this response')
            ret.append(Content(role='user', parts=parts))
            parts.clear()
            ret.append(Content(role='model', parts=[Part.from_text(text=resp)]))
        case 'Loading log':
            m = re.fullmatch(r'^([^/]*) \(([0-9]+)\)$', rest.strip())
            assert m
            log_name, log_size = m.groups()
            ret.extend(parse_log(log_dir / log_name, int(log_size)))
        case _:
            raise Exception(f'Unknown action {action!r}')

def parse_log(path: Path, size: int) -> list[Content]:
    with open(path, 'rb') as fp:
        data = fp.read(size)
        assert len(data) == size
        text = data.decode('utf-8')
        bits = re.split(r'\n(?!>)', text)
        ret: list[Content] = []
        parts: list[Part] = []
        for bit in bits:
            bit = bit.strip()
            if not bit:
                continue
            try:
                parse_log_bit(bit, ret, parts)
            except:
                print('** while parsing bit:')
                print(bit)
                print('**')
                raise
        if parts:
            print('** Warning: Ignoring leftover send parts:', parts)
        return ret
next_log_id = 1

class ChatWrap:
    def __init__(self, base_log_path: Optional[Path] = None):
        global next_log_id
        gac = google.genai.Client(
            api_key=open('api_key.txt').read().strip(),
            http_options={'api_version':'v1alpha'}
        )
        # config = GenerateContentConfig(
        #     tools=[
        #         Tool(
        #             function_declarations=[
        #                 BUTTON_PRESS_FD(),
        #             ]
        #         )
        #     ]
        # )
        self.log_path, next_log_id = get_unique_path(next_log_id, log_dir, 'log', 2, '.txt')
        self.log_fp = self.log_path.open('w')
        print(f'Logging to {self.log_path}')
        if base_log_path is not None:
            history = self.load_log(base_log_path)
        else:
            history = []
        self.chat = gac.chats.create(
            model='gemini-2.0-flash-thinking-exp',
            # config=config
            history=history
        )
    def log(self, what: str, add_time: bool = True) -> None:
        if add_time:
            now = str(datetime.datetime.now())
            what = f'{now}  {what}'
        print(what, end='', flush=True)
        print(what, end='', flush=True, file=self.log_fp)
    def load_log(self, path: Path) -> list[Content]:
        size = path.stat().st_size
        self.log(f'Loading log: {path.name} ({size})\n')
        return parse_log(path, size)

    def send(self, text: str, image: Optional[Path] = None) -> str:
        self.log(f'Sending: {text!r}\n')
        if image:
            self.log(f'Sending image: {image.name}\n')
        parts: list[PartUnionDict] = [Part.from_text(text=text)]
        if image:
            parts.append(Part.from_bytes(data=image.read_bytes(), mime_type='image/png'))
        self.log(f'Response:\n> ')
        last_was_nl = False
        full_text = ''
        for chunk in self.chat.send_message_stream(parts):
            text = chunk.text or ''
            #print('?', chunk, repr(chunk.text))
            full_text += text
            if last_was_nl:
                text = '\n' + text
            last_was_nl = text.endswith('\n')
            if last_was_nl:
                text = text[:-1]
            self.log(text.replace('\n', '\n> '), add_time=False)
        self.log('\n', add_time=False)
        return full_text
