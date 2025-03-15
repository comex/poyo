from typing import Literal, Union, Iterable, Any, Protocol, TYPE_CHECKING, Sequence
from io import TextIOBase
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
import typedload
from typedload.datadumper import Dumper
import json
import logging

from .common import log_dir

class Session(Protocol):
    def tokens_for_text(self, text: str) -> int: ...
    def tokens_for_image_size(self, size: tuple[int, int]) -> int: ...


@dataclass(frozen=True)
class ContentBase:
    pass


@dataclass(frozen=True)
class TextContent(ContentBase):
    text: str
    type: Literal['text'] = 'text'

    @cache
    def tokens(self, sess: Session) -> int:
        return sess.tokens_for_text(self.text)

@dataclass(frozen=True)
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
        with Image.open(self.path()) as image:
            return image.size

    @cache
    def tokens(self, sess: Session) -> int:
        return sess.tokens_for_image_size(self.size())

Content = Union[TextContent, ImageContent]

@dataclass(frozen=True)
class LogBase:
    time: float

@dataclass(frozen=True)
class Message:
    role: Literal['user', 'developer', 'assistant']
    content: Sequence[Content]
    ref: Sequence[LogBase]

    def _tldump(self, dumper: Dumper) -> Any:
        return {'role': self.role, 'content': dumper.dump(self.content)}

    @cache
    def tokens(self, sess: Session) -> int:
        return sum(c.tokens(sess) for c in self.content)

@dataclass(frozen=True)
class SendLog(LogBase, Message):
    type: Literal['send'] = 'send'
    tag: Any = None

@dataclass(frozen=True)
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
        # https://github.com/microsoft/pyright/issues/10091
        yield typedload.load(json.loads(line), Log) # type: ignore

def log_to_messages(logs: Iterable[Log]) -> Iterable[Message]:
    cur_recv: list[RecvLog] = []
    def finish_recv() -> Iterable[Message]:
        nonlocal cur_recv
        if cur_recv:
            m = Message(
                role='assistant',
                content=[TextContent(''.join(r.delta for r in cur_recv))],
                ref=cur_recv,
            )
            yield m
            cur_recv = []

    def discard_recv() -> None:
        nonlocal cur_recv
        if cur_recv:
            logging.warning(f'discarding cur_recv due to missing finish: {cur_recv}')
            cur_recv = []

    for log in logs:
        match log:
            case RecvLog():
                if not log.start and not cur_recv:
                    logging.warning(f'discarding recv log due to missing start: {log}')
                    cur_recv = []
                else:
                    if log.start:
                        discard_recv()
                    cur_recv.append(log)
                    if log.error:
                        logging.warning(f'discarding cur_recv due to error: {cur_recv}')
                        cur_recv = []
                    elif log.finish:
                        yield from finish_recv()
            case SendLog():
                discard_recv()
                m = Message(
                    role=log.role,
                    content=log.content,
                    ref=[log],
                )
                yield m

    discard_recv()

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
#def log_to_ascii(logs: Iterable[Log]) -> Iterable[str]:
    

@cache
def dumper() -> Dumper:
    ret = Dumper(hidedefault=False)
    ret.handlers.insert(0, (
        (lambda value: hasattr(value, '_tldump'), # type: ignore
         lambda dumper, value, ty: value._tldump(dumper)) # type: ignore
    ))
    return ret
if __name__ == '__main__':
    logs = list(load_jsonl(open('/tmp/test.jsonl')))
    # for log in logs:
    #     print(dumper().dump(log))
    for m in log_to_messages(logs):
        print(m)
        print(dumper().dump(m))
