"""Terminal input: Enter submits a line; Escape cancels immediately."""

import codecs
import getpass
import os
import sys
import termios
import tty


class InputCancelled(SystemExit):
    """Exit successfully when the user cancels a prompt."""


def read_input(prompt="", *, hidden=False):
    """Read an editable line, restoring terminal settings on every exit path."""
    # Without an interactive terminal, use input/getpass; check Escape after line submission.
    if not sys.stdin.isatty():
        value = getpass.getpass(prompt) if hidden else input(prompt)
        if "\x1b" in value:
            print("\nCancelled.")
            raise InputCancelled(0)
        return value

    # Save terminal settings before enabling raw mode to receive each key immediately.
    # The decoder combines UTF-8 bytes into characters to support Unicode input.
    fd = sys.stdin.fileno()
    settings = termios.tcgetattr(fd)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    characters = []
    try:
        tty.setraw(fd, termios.TCSADRAIN)
        print(prompt, end="", flush=True)
        while True:
            key = os.read(fd, 1)
            # Escape cancels, Ctrl-C interrupts, and Ctrl-D or exhausted input raises EOF.
            if key == b"\x1b":
                raise InputCancelled(0)
            if key == b"\x03":
                raise KeyboardInterrupt
            if not key or key == b"\x04":
                raise EOFError
            if key in (b"\r", b"\n"):
                return "".join(characters)
            if key in (b"\x7f", b"\x08"):
                decoder.reset()
                if characters:
                    characters.pop()
                    if not hidden:
                        print("\b \b", end="", flush=True)
                continue
            character = decoder.decode(key)
            if character and character.isprintable():
                characters.append(character)
                if not hidden:
                    print(character, end="", flush=True)
    except InputCancelled:
        print("\r\nCancelled.", end="", flush=True)
        raise
    finally:
        # Always restore the terminal, including on cancellation, EOF, or exceptions.
        termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        print()


def confirm_input(prompt):
    """Only an empty submitted line confirms; Escape or EOF cancels."""
    while True:
        try:
            value = read_input(f"\n{prompt} (Enter to confirm, Esc to cancel): ")
        except (InputCancelled, EOFError):
            return False
        if not value:
            return True
        print("Press Enter without typing to confirm, or Esc to cancel.")
