from pathlib import Path
from typing import AsyncIterable, Iterable, Iterator, Optional, TypeAlias, Union
import re
import time
import select
import aiohttp
from aiohttp import web
import asyncio
import queue
from typing import TypeVar

from poyo.log import filter_log, filtered_log_to_html, load_jsonl

from .common import Tail, latest_log, log_dir, open_tail

T = TypeVar('T')
QueueItem: TypeAlias = Union[tuple[T], BaseException, None]
# started as lowest effort possible
# this sucks
async def asyncify_iterable(itr: Iterable[T]) -> AsyncIterable[T]:
    q: queue.Queue[QueueItem[T]] = queue.Queue(maxsize=5)
    event = asyncio.Event()
    loop = asyncio.get_event_loop()
    def bg_thread() -> None:
        async def wake():
            event.set()
        def put(x: QueueItem[T]) -> None:
            #print('>put')
            q.put((t,))
            asyncio.run_coroutine_threadsafe(wake(), loop)
        try:
            for t in itr:
                try:
                    put((t,))
                except queue.ShutDown:
                    break
        except BaseException as e:
            put(e)
        else:
            put(None)
    asyncio.create_task(asyncio.to_thread(bg_thread))
    try:
        while True:
            await event.wait()
            event.clear()
            while not q.empty():
                x = q.get_nowait()
                #print('>get')
                match x:
                    case (t,):
                        yield t
                    case BaseException():
                        raise x
                    case None:
                        break
    finally:
        q.shutdown(immediate=True)

async def buffer_aiterable(itr: AsyncIterable[T]) -> AsyncIterable[T]:
    queue: asyncio.Queue[Union[tuple[T], BaseException, None]] = asyncio.Queue(maxsize=5)
    async def bg_task() -> None:
        try:
            async for t in itr:
                await queue.put((t,))
        except BaseException as e:
            await queue.put(e)
        else:
            await queue.put(None)
    task = asyncio.create_task(bg_task())
    try:
        while True:
            x = await queue.get()
            match x:
                case BaseException():
                    raise x
                case None:
                    break
                case (t,):
                    yield t
    finally:
        task.cancel()

async def handle_render(request: web.Request) -> web.StreamResponse:
    name = request.match_info['name']
    tail = 'tail' in request.query

    if name == 'latest':
        name = latest_log().name
    assert '/' not in name and name.endswith('.txt')

    log_path = log_dir / name
    try:
        fp = open_tail(log_path) if tail else open(log_path)
    except FileNotFoundError:
        return web.StreamResponse(status=404, reason='txt not found')
    resp = web.StreamResponse()
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    await resp.prepare(request)
    # Weird hack where we can't return the response yet because then we
    # wouldn't get the cancel.
    try:
        it = await asyncio.to_thread(lambda: filtered_log_to_html(filter_log(load_jsonl(fp))))
        async for blob in asyncify_iterable(it):
            #print('##', blob)
            await resp.write(blob.encode('utf-8'))
    finally:
        def cthread():
            print('closing...', fp, fp.buffer)
            fp.close()
            print('did close', fp)
        asyncio.create_task(asyncio.to_thread(cthread))
        print('all gone')

def create_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get(r'/render/{name:(log([0-9]+)\.txt|latest)}', handle_render),
    ])
    app.router.add_static('/', '.', show_index=True)
    app.router.add_static('/render/log', 'log', show_index=True)

    return app

if __name__ == '__main__':
    web.run_app(
        create_app(),
        #host='127.0.0.1',
        port=8002,
        handler_cancellation=True
    )
