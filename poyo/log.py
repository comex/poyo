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
import time
from datetime import datetime

from .common import log_dir, operation

class StatelessSession(Protocol):
    def tokens_for_text(self, text: str) -> int: ...
    def tokens_for_image_size(self, size: tuple[int, int]) -> int: ...
    def send(self, ml: 'MessageList') -> Iterable['RecvLog']: ...

@dataclass(eq=False)
class ContentBase:
    pass


@dataclass(eq=False)
class TextContent(ContentBase):
    text: str
    type: Literal['text'] = 'text'

    @cache
    def tokens(self, sess: StatelessSession) -> int:
        return sess.tokens_for_text(self.text)

    def dump_for_openai(self) -> Any:
        return {'type': 'text', 'text': self.text}

@dataclass(eq=False)
class ImageContent(ContentBase):
    name: str
    width: int
    height: int
    type: Literal['image'] = 'image'

    @staticmethod
    def from_name(name: str) -> 'ImageContent':
        from PIL import Image
        ret = ImageContent(name=name, width=0, height=0)
        path = ret.path()
        with operation(f'getting size of {path}'):
            with Image.open(path) as image:
                ret.width, ret.height = image.size
        return ret

    def __post_init__(self) -> None:
        assert '/' not in self.name

    def path(self) -> Path:
        return log_dir / self.name

    @cache
    def tokens(self, sess: StatelessSession) -> int:
        return sess.tokens_for_image_size((self.width, self.height))

    @lru_cache
    def dump_for_openai(self) -> Any:
        b64 = base64.b64encode(self.path().read_bytes()).decode('utf-8')
        return {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}

Content = Union[TextContent, ImageContent]

@dataclass
class LogBase:
    time: float = 0.0

@dataclass(eq=False)
class Message:
    role: Literal['user', 'developer', 'assistant']
    content: list[Content]
    if TYPE_CHECKING:
        ref: Sequence[LogBase] = field(init=False)

    @cache
    def tokens(self, sess: StatelessSession) -> int:
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
        ret: Any = {'time': self.time, 'type': self.type, 'delta': self.delta}
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

    css = (Path(__file__).parent / '../poyo.css').read_text()
    yield f'''
<html>
<head>
    <meta charset=utf-8>
    <style>
{css}
    </style>
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
                            yield '<div class="send-image send-content content">\n'
                            yield f'<a href="{html.escape(src)}"><img src="{html.escape(src)}" width="{c.width}" height="{c.height}"></a>\n'
                            yield '</div>\n'
                yield '</div>\n'
    yield '''
</body>
</html>
'''

class MessageList:
    def __init__(self, sess: StatelessSession):
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
    def __len__(self) -> int:
        return len(self._messages)
    def __repr__(self):
        return f'MessageList({len(self._messages)} messages, {self.total_tokens} total_tokens)'

    def __iter__(self) -> Iterator[Message]:
        return self._messages.__iter__()

class StatelessWrapper:
    def __init__(self, sess: StatelessSession, log_path: Path):
        self.sess = sess

        self.token_limit = 32000
        self.max_history_images = 0

        self.message_list = MessageList(sess)
        self.fp = open(log_path, 'r+')
        for m in filtered_log_to_messages(load_jsonl(self.fp)):
            self.message_list.append(m)

    def trim(self) -> None:
        n = 0
        while self.message_list.total_tokens > self.token_limit:
            self.message_list.pop(0)
            n += 1
        if n:
            logging.warning(f'Trimmed {n} messages to get total_tokens down to {self.message_list.total_tokens}')
    def remove_images(self) -> None:
        remaining = self.max_history_images
        for i, m in reversed(list(enumerate(self.message_list))):
            if any(isinstance(c, ImageContent) for c in m.content):
                if remaining > 0:
                    remaining -= 1
                    continue
                new_m = Message(
                    role=m.role,
                    content=[(c if isinstance(c, TextContent) else
                              TextContent('[image]'))
                             for c in m.content]
                )
                self.message_list[i] = new_m

    def log(self, log: Log) -> None:
        logging.info(str(log))
        j = dumper().dump(log)
        self.fp.write(json.dumps(j) + '\n')
        self.fp.flush()

    def send(self, m: Message) -> str:
        self.remove_images()
        self.message_list.append(m)
        self.trim()
        logging.info(f'when sending, total_tokens is now at {self.message_list.total_tokens}')
        self.log(SendLog(time=time.time(), role=m.role, content=m.content))
        ret = ''
        rlogs: list[RecvLog] = []
        for rlog in self.sess.send(self.message_list):
            rlogs.append(rlog)
            self.log(rlog)
            ret += rlog.delta
        for m in filtered_log_to_messages(filter_log(rlogs)):
            self.message_list.append(m)
        return ret

@cache
def dumper() -> Dumper:
    ret = Dumper(hidedefault=False)
    ret.handlers.insert(0, (
        (lambda value: hasattr(value, '_tldump'), # type: ignore
         lambda dumper, value, ty: value._tldump(dumper)) # type: ignore
    ))
    return ret

def main():
    logging.basicConfig(level=logging.DEBUG)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['messages', 'html', 'logs', 'ml'])
    ap.add_argument('filename')
    ap.add_argument('--tail', action='store_true')
    args = ap.parse_args()

    #mode_messages = sp.add_parser('messages'); mode_messages.set_defaults(mode='messages')
    #mode_html = sp.add_parser('html'); mode_html.set_defaults(mode='html')

    fp = Tail(args.filename) if args.fail else open(args.filename)
    logs = load_jsonl(fp)
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
