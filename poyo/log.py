from typing import TYPE_CHECKING, Iterator, Literal, Union, Iterable, Any, Protocol, Sequence
from io import TextIOBase
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path
import typedload
from typedload.datadumper import Dumper
import json
import logging
import html
import base64
from datetime import datetime

from .common import log_dir, operation

class Session(Protocol):
    def tokens_for_text(self, text: str) -> int: ...
    def tokens_for_image_size(self, size: tuple[int, int]) -> int: ...


@dataclass(eq=False)
class ContentBase:
    pass


@dataclass(eq=False)
class TextContent(ContentBase):
    text: str
    type: Literal['text'] = 'text'

    @cache
    def tokens(self, sess: Session) -> int:
        return sess.tokens_for_text(self.text)

    def dump_for_openai(self) -> Any:
        return {'type': 'text', 'text': self.text}

@dataclass(eq=False)
class ImageContent(ContentBase):
    name: str
    type: Literal['image'] = 'image'

    def __post_init__(self) -> None:
        assert '/' not in self.name

    def path(self) -> Path:
        return log_dir / self.name

    @cache
    def size(self) -> tuple[int, int]:
        from PIL import Image
        path = self.path()
        with operation(f'getting size of {path}'):
            with Image.open(path) as image:
                return image.size

    @cache
    def tokens(self, sess: Session) -> int:
        return sess.tokens_for_image_size(self.size())

    @lru_cache
    def dump_for_openai(self) -> Any:
        b64 = base64.b64encode(self.path().read_bytes()).decode('utf-8')
        return {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}

Content = Union[TextContent, ImageContent]

@dataclass
class LogBase:
    time: float

@dataclass(eq=False)
class Message:
    role: Literal['user', 'developer', 'assistant']
    content: list[Content]
    if TYPE_CHECKING:
        ref: Sequence[LogBase] = field(init=False)

    @cache
    def tokens(self, sess: Session) -> int:
        return sum(c.tokens(sess) for c in self.content)

    def dump_for_openai(self) -> Any:
        return {'role': self.role, 'content': [c.dump_for_openai() for c in self.content]}

@dataclass
class SendLog(LogBase, Message):
    type: Literal['send'] = 'send'
    tag: Any = None

@dataclass
class RecvLog(LogBase):
    type: Literal['recv'] = 'recv'
    delta: str = ''
    start: bool = False
    finish: bool = False
    error: bool = False
    orig_resp: Any = None

    def _tldump(self, dumper: Dumper) -> Any:
        ret: Any = {'type': self.type, 'delta': self.delta}
        for x in ['start', 'finish', 'error']:
            if getattr(self, x):
                ret[x] = True
        return ret



Log = Union[
    SendLog,
    RecvLog,
]

def load_jsonl(fp: TextIOBase) -> Iterable[Log]:
    for line in fp:
        if line.strip():
            # https://github.com/microsoft/pyright/issues/10091
            yield typedload.load(json.loads(line), Log) # type: ignore

def filter_log(logs: Iterable[Log]) -> Iterable[Log]:
    in_recv = False
    last_time: float
    def discard_recv() -> Iterable[Log]:
        nonlocal in_recv
        if in_recv:
            yield RecvLog(time=last_time, error=True, orig_resp='<fake log from discard_recv>')
        in_recv = False

    for log in logs:
        last_time = log.time
        #print('in_recv=', in_recv, log)
        match log:
            case RecvLog():
                if not log.start and not in_recv:
                    logging.warning(f'filter_log: discarding recv log due to missing start: {log}')
                    continue
                if log.start:
                    yield from discard_recv()
                    in_recv = True
                yield log
                if log.error or log.finish:
                    in_recv = False
            case SendLog():
                yield from discard_recv()
                yield log

    yield from discard_recv()

def filtered_log_to_messages(logs: Iterable[Log]) -> Iterable[Message]:
    cur_recv: list[RecvLog] = []
    for log in logs:
        match log:
            case RecvLog():
                cur_recv.append(log)
                if log.error:
                    logging.warning(f'discarding cur_recv due to error: {cur_recv}')
                    cur_recv = []
                elif log.finish:
                    m = Message(
                        role='assistant',
                        content=[TextContent(''.join(r.delta for r in cur_recv))],
                    )
                    m.ref = cur_recv
                    yield m
                    cur_recv = []
            case SendLog():
                m = Message(
                    role=log.role,
                    content=log.content,
                )
                m.ref=[log]
                yield m

def filtered_log_to_html(logs: Iterable[Log]) -> Iterable[str]:
    yield '''
<html>
<head>
    <link rel="stylesheet" href="poyo.css">
</head>
<body>
'''
    for log in logs:
        match log:
            case RecvLog():
                if log.start:
                    yield '<div class="recv log">\n'
                    time_render = str(datetime.fromtimestamp(log.time))
                    yield f'<div class="time">{html.escape(time_render)}</div>\n'
                    yield f'<div class="recv-body content">\n'

                yield html.escape(log.delta)

                if log.error or log.finish:
                    yield '\n</div>\n' # recv-body
                    if log.error:
                        yield '<div class="recv-error">[recv-error]</div>\n'
                    yield '</div>\n' # recv

            case SendLog():
                yield '<div class="send log">\n'
                time_render = str(datetime.fromtimestamp(log.time))
                yield f'<div class="time">{html.escape(time_render)}</div>\n'
                for c in log.content:
                    match c:
                        case TextContent():
                            yield '<div class="send-text send-content content">\n'
                            yield html.escape(c.text)
                            yield '</div>\n'
                        case ImageContent():
                            src = f'log/{c.name}'
                            width, height = c.size()
                            yield '<div class="send-image send-content content">\n'
                            yield f'<a href="{html.escape(src)}"><img src="{html.escape(src)}" width="{width}" height="{height}"></a>\n'
                            yield '</div>\n'
                yield '</div>\n'
    yield '''
</body>
</html>
'''

class MessageList:
    def __init__(self, sess: Session):
        self.sess = sess
        self._messages: list[Message] = []
        self._message_tokens: list[int] = []
        self.total_tokens = 0
    def append(self, m: Message):
        self._messages.append(m)
        tokens = m.tokens(self.sess)
        self._message_tokens.append(tokens)
        self.total_tokens += tokens
    def pop(self, index: int) -> Message:
        ret = self._messages.pop(index)
        self.total_tokens -= self._message_tokens.pop(index)
        return ret
    def __getitem__(self, index: int) -> Message:
        return self._messages[index]
    def __setitem__(self, index: int, m: Message) -> None:
        self.total_tokens -= self._message_tokens[index]
        self._messages[index] = m
        self._message_tokens[index] = m.tokens(self.sess)
        self.total_tokens += self._message_tokens[index]
    def __repr__(self):
        return f'MessageList({len(self._messages)} messages, {self.total_tokens} total_tokens)'

    def __iter__(self) -> Iterator[Message]:
        return self._messages.__iter__()

@cache
def dumper() -> Dumper:
    ret = Dumper(hidedefault=False)
    ret.handlers.insert(0, (
        (lambda value: hasattr(value, '_tldump'), # type: ignore
         lambda dumper, value, ty: value._tldump(dumper)) # type: ignore
    ))
    return ret

def main():
    logging.basicConfig(level=logging.INFO)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['messages', 'html', 'logs', 'ml'])
    args = ap.parse_args()

    #mode_messages = sp.add_parser('messages'); mode_messages.set_defaults(mode='messages')
    #mode_html = sp.add_parser('html'); mode_html.set_defaults(mode='html')

    logs = list(load_jsonl(open('data/test.jsonl')))
    match args.mode:
        case 'logs':
            for log in logs:
                print(log)
                print(dumper().dump(log))
        case 'messages':
            for m in filtered_log_to_messages(filter_log(logs)):
                print(m)
                print(dumper().dump(m))
        case 'html':
            for bit in filtered_log_to_html(filter_log(logs)):
                print(bit, flush=True, end='')
            print()
        case 'ml':
            from . import openai
            sess = openai.OpenAISession()
            ml = MessageList(sess)
            for m in filtered_log_to_messages(filter_log(logs)):
                ml.append(m)
                print('->', ml.total_tokens)
            ml.pop(0)
            print(ml)
        case _:
            raise Exception('?')

if __name__ == '__main__': main()
