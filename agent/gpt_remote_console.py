#!/usr/bin/python3
"""Open an interactive Ptyxis terminal for the configured GPT remote connector.

No arbitrary phone-supplied shell command. When Desktop Commander Remote is
already running, preserve it and open a normal user terminal instead of
starting a conflicting duplicate.
"""

import os
from pathlib import Path
import sys


def main():
    if sys.stdin is None:
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desktop_actions import _gpt_remote_running

    print("\033[1;36mGPT Remote · Ubuntu Control\033[0m", flush=True)
    if _gpt_remote_running():
        print("Desktop Commander Remote is already running.", flush=True)
        print("The existing ChatGPT connection will not be restarted.", flush=True)
        print("Opening a standard terminal for local commands.", flush=True)
        shell=Path("/usr/bin/zsh")
        if not shell.is_file():
            shell=Path("/bin/bash")
        os.execv(str(shell), [shell.name, "-l"])
    npm=Path("/usr/bin/npm")
    if not npm.is_file() or npm.is_symlink():
        print("Desktop Commander launcher unavailable. Run local package setup first.",file=sys.stderr)
        return 2
    print("No existing Desktop Commander Remote instance detected.", flush=True)
    print("Starting the installed remote connector in this terminal.", flush=True)
    os.execv(str(npm), [str(npm),"exec","@wonderwhy-er/desktop-commander@latest","remote"])


if __name__=="__main__":
    raise SystemExit(main())
