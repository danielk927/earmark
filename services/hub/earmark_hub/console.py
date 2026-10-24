"""Keyboard input for --step and --interactive without blocking the event loop.

A daemon thread reads stdin and hands lines (or single keys, in cbreak mode) to the
event loop. One reader per process.
"""
from __future__ import annotations

import asyncio
import atexit
import os
import sys
import threading
from typing import AsyncIterator, Callable

_EOF = object()


class StdinReader:
    def __init__(self, cbreak: bool = False) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue = asyncio.Queue()
        self.cbreak = cbreak and sys.stdin.isatty()
        self._saved = None
        if self.cbreak:
            import termios
            import tty

            fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            atexit.register(self.restore)
        threading.Thread(target=self._run, name="stdin", daemon=True).start()

    def restore(self) -> None:
        if self._saved is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)
            self._saved = None

    def _run(self) -> None:
        try:
            if self.cbreak:
                fd = sys.stdin.fileno()
                while chunk := os.read(fd, 1):
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk.decode(errors="ignore"))
            else:
                for line in sys.stdin:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, line.rstrip("\n"))
        finally:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _EOF)

    async def get(self) -> str | None:
        """Next line (or key in cbreak mode); None at end of input."""
        item = await self._queue.get()
        if item is _EOF:
            self._queue.put_nowait(_EOF)
            return None
        return item


async def line_commands(reader: StdinReader) -> AsyncIterator[str]:
    while (line := await reader.get()) is not None:
        yield line.strip()


async def key_commands(reader: StdinReader, out: Callable[[str], None]) -> AsyncIterator[str]:
    """Single-key commands; `m` waits for a digit, `t` reads a line of text (echoed)."""
    while (key := await reader.get()) is not None:
        if key == "m":
            out("move held object to spot: ")
            digit = await reader.get()
            if digit is None:
                return
            out(digit + "\n")
            yield "m" + digit
        elif key == "t":
            out("say: ")
            text = ""
            while (ch := await reader.get()) not in (None, "\n", "\r"):
                if ch in ("\x7f", "\b"):
                    if text:
                        text = text[:-1]
                        out("\b \b")
                    continue
                text += ch
                out(ch)
            out("\n")
            yield "t " + text
        elif key.strip():
            yield key


def make_commands(out: Callable[[str], None]) -> AsyncIterator[str]:
    reader = StdinReader(cbreak=True)
    return key_commands(reader, out) if reader.cbreak else line_commands(reader)


def make_step_gate(out: Callable[[str], None]) -> Callable[[str], "asyncio.Future"]:
    """Gate for --step: print the prompt, wait for Enter. At end of input, stop pausing."""
    reader: StdinReader | None = None
    done = False

    async def gate(prompt: str) -> None:
        nonlocal reader, done
        if done:
            return
        if reader is None:
            reader = StdinReader(cbreak=False)
        out(prompt + "  [Enter] ")
        if await reader.get() is None:
            done = True
            out("\n(end of input: playing the rest without pausing)\n")

    return gate
