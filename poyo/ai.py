import datetime
import time
import re
import ast
from typing import Optional, Iterator
from pathlib import Path
from functools import cache
# import hashlib

from .common import get_unique_path, log_dir

_a = time.time()
import google.genai # :( this is super slow
_b = time.time()
print('genai import time is', _b-_a)

from google.genai.types import PartUnionDict, Part, Content, UserContent, ModelContent, GenerateContentResponse, UploadFileConfig, File
from google.genai.errors import ClientError
# GenerateContentConfig,  FunctionDeclaration, Schema, Type as SType, Content

# why not just pickle it or something? because I want to be able to edit it if desired
def parse_log_bit(bit: str, ret: list[Content], parts: list[PartUnionDict], file_manager: 'FileManager') -> None:
    m = re.fullmatch(r'^20.*?  ([^:]*):(.*)', bit, flags=re.S)
    if not m:
        raise Exception('bad format 1')
    action, rest = m.groups()
    #print('^^', action)
    if '\n' in rest:
        rest = rest.replace('\n> ', '\n')
        assert rest.startswith('\n')
        rest = rest[1:]
    match action:
        case 'Sending':
            parts.append(Part.from_text(text=rest))
        case 'Sending image':
            assert '/' not in rest
            image = log_dir / rest.strip()
            parts.append(file_manager.get_or_upload(image))
        case 'Response':
            if not parts:
                raise Exception('No input for this response')
            ret.append(UserContent(parts=parts))
            parts.clear()
            ret.append(ModelContent(parts=[Part.from_text(text=rest)]))
        case 'Loading log':
            m = re.fullmatch(r'^([^/]*) \(([0-9]+)\)$', rest.strip())
            assert m
            log_name, log_size = m.groups()
            ret.extend(parse_log(log_dir / log_name, int(log_size), file_manager))
        case _:
            raise Exception(f'Unknown action {action!r}')

# XXX: this is dumb, I should be lazily uploading when needed
def parse_log(path: Path, size: int, file_manager: 'FileManager') -> list[Content]:
    with open(path, 'rb') as fp:
        data = fp.read(size)
        assert len(data) == size
        text = data.decode('utf-8')
        bits = re.split(r'\n(?!>)', text)
        ret: list[Content] = []
        parts: list[PartUnionDict] = []
        for bit in bits:
            bit = bit.strip()
            if not bit:
                continue
            try:
                parse_log_bit(bit, ret, parts, file_manager)
            except:
                print('** while parsing bit:')
                print(bit)
                print('**')
                raise
        if parts:
            print('** Warning: Ignoring leftover send parts:', parts)
        return ret
next_log_id = 1

@cache
def gac() -> google.genai.Client:
    return google.genai.Client(
        api_key=open('api_key_free.txt').read().strip(),
        http_options={'api_version':'v1alpha'}
    )

# @cache
# def sha256_of_path(path: Path) -> str:
#     return hashlib.sha256(path.read_bytes()).hexdigest()

PREPOPULATE = False
class FileManager:
    def __init__(self):
        self.gac = gac()
        self.files: dict[str, File] = {}

        if PREPOPULATE:
            self.populate_from_list()
    def populate_from_list(self) -> None:
        print('FileManager: list files start')
        for file in self.gac.files.list():
            print('got file', file)
            assert file.name is not None
            assert file.sha256_hash is not None
            assert file.expiration_time is not None
            self.files[file.name] = file
        print('FileManager: list files done')
    def get(self, path: Path) -> Optional[File]:
        name = self.google_name_for_path(path)
        file = self.files.get(name)
        if file is None and not PREPOPULATE:
            try:
                file = self.gac.files.get(name=name)
            except ClientError as e:
                if e.status != 'PERMISSION_DENIED':
                    raise e
                file = None
        if file is None:
            print(f'FileManager: no existing file: {path!r} / {name!r}')
            return None
        if not self.check(file, path):
            return None
        return file

    def check(self, file: File, path: Path) -> bool:
        assert file.size_bytes is not None
        real_size = path.stat().st_size
        if file.size_bytes != real_size:
            print(f'FileManager: size mismatch!: {path.name!r}: {file.size_bytes} / {real_size}')
            return False

        # XXX: I don't know wtf this is supposed to be.  It says sha256_hash
        # but it's base64 of a 512-bit hash, and it's not SHA-512 either.
        # assert file.sha256_hash is not None
        # if (a := file.sha256_hash.lower()) != (b := sha256_of_path(path)):
        #     print(f'FileManager: hash mismatch!: {path.name!r}: {a!r} / {b!r}')
        #     return False
        # return True

        assert file.expiration_time is not None
        if file.expiration_time < (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)):
            print(f'FileManager: file is expired or expiring soon: {path.name!r}: {file.expiration_time}')
            return False
        return True

    def get_or_upload(self, path: Path) -> File:
        name = self.google_name_for_path(path)
        exfile = self.get(path)
        if exfile is not None:
            return exfile
        a = time.time()
        config = UploadFileConfig(
            name=self.google_name_for_path(path),
            mime_type='image/png',
        )
        file: File = self.gac.files.upload(file=path, config=config) # type: ignore
        b = time.time()
        print(f'FileManager: uploaded {path} in {b - a}')
        assert self.check(file, path)
        self.files[name] = file
        return file

    def google_name_for_path(self, path: Path) -> str:
        return path.name.replace('.', '-')

class ChatWrap:
    def __init__(self, base_log_path: Optional[Path] = None):
        global next_log_id
        # config = GenerateContentConfig(
        #     tools=[
        #         Tool(
        #             function_declarations=[
        #                 BUTTON_PRESS_FD(),
        #             ]
        #         )
        #     ]
        # )
        self.file_manager = FileManager()
        self.log_path, next_log_id = get_unique_path(next_log_id, log_dir, 'log', 2, '.txt')
        self.log_fp = self.log_path.open('w')
        print(f'Logging to {self.log_path}')
        if base_log_path is not None:
            history = self.load_log(base_log_path)
        else:
            history = []
        self.chat = gac().chats.create(
            model='gemini-2.0-flash-thinking-exp',
            # model='gemini-2.0-pro-exp-02-05',
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
        return parse_log(path, size, self.file_manager)

    def send(self, text: str, image: Optional[Path] = None) -> str:
        self.log(f'Sending:\n> ' + text.replace('\n', '\n> ') + '\n')
        if image:
            self.log(f'Sending image: {image.name}\n')
        parts: list[PartUnionDict] = [Part.from_text(text=text)]
        if image:
            parts.append(self.file_manager.get_or_upload(image))
        self.log(f'Response:\n> ')
        last_was_nl = False
        full_text = ''
        it: Iterator[GenerateContentResponse] = self.chat.send_message_stream(parts)
        for chunk in it:
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

if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1])
    print(parse_log(path, path.stat().st_size, FileManager()))
