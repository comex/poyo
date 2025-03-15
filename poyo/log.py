from typing import Literal, Union, TypedDict, Iterable, Any
from io import TextIOBase

class TextContent(TypedDict):
    type: Literal['text']
    text: str
class ImageContent(TypedDict):
    type: Literal['image']
    name: str
Content = Union[TextContent, ImageContent]

class Message(TypedDict):
    content: list[Content]

class LogBase(TypedDict):
    time: float

class SendLog(LogBase):
    type: Literal['send']
    role: Literal['user', 'developer', 'assistant']
    content: list[Content]

class RecvLog(LogBase):
    type: Literal['recv']
    delta: str
    orig_resp: Any

Log = Union[
    SendLog,
    RecvLog,
]

def load_jsonl(fp: TextIOBase) -> Iterable[Log]:


def log_to_ascii(logs: Iterable[Log]) -> Iterable[str]:
    
