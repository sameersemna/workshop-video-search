import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable


MAX_EXECUTOR_WORKERS = int(os.getenv("MAX_EXECUTOR_WORKERS", "4"))
shared_executor = ThreadPoolExecutor(max_workers=MAX_EXECUTOR_WORKERS)


async def run_blocking(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run blocking call in the shared thread pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(shared_executor, partial(func, *args, **kwargs))


def shutdown_shared_executor(wait: bool = True) -> None:
    shared_executor.shutdown(wait=wait)
