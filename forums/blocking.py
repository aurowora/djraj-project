import asyncio
import functools


async def spawn_blocking(func, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(functools.partial(func, *args, **kwargs))
