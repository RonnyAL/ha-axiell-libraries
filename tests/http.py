"""Keep aioresponses 0.7.9 compatible with Core's aiohttp 3.14 responses."""

import inspect
from types import SimpleNamespace

from aiohttp import ClientResponse
from aioresponses import aioresponses as _Aioresponses


class _Response(ClientResponse):
    """Represent an already sent, zero-byte mocked upload."""

    def __init__(self, *args, **kwargs):
        # aioresponses passes writer=None. aiohttp then reads output_size once
        # without retaining stream_writer; no writer methods are needed.
        super().__init__(*args, stream_writer=SimpleNamespace(output_size=0), **kwargs)


class AiohttpResponses(_Aioresponses):
    """Supply the missing constructor argument via response_class, including callbacks.

    Remove when upstream aioresponses supports aiohttp's stream_writer argument.
    The real ClientResponse still handles JSON, status and context-manager behavior.
    """

    def add(self, *args, callback=None, response_class=None, **kwargs):
        if callback is not None:
            original_callback = callback

            async def callback(*args, **kwargs):
                result = original_callback(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None and result.response_class is None:
                    result.response_class = _Response
                return result

        return super().add(
            *args,
            callback=callback,
            response_class=response_class or _Response,
            **kwargs,
        )
