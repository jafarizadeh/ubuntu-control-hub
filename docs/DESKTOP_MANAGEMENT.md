# Files & Folders · Desktop and GPT Remote (v1.2)

The iPhone PWA Control Center supports a fixed, authenticated set of desktop
operations through the existing private Pi Hub and signed Ubuntu Agent.
There is no arbitrary remote shell, file deletion API, filesystem traversal,
user-supplied command or user-supplied PID.

## Three requested workflows

1. Close all open files and web pages: native GNOME Wayland AT-SPI close
   actions for supported file managers, editors and document viewers.
   Chrome/Firefox native Wayland may have no accessibility Close action,
   so a constrained fallback sends SIGTERM to the validated same-owner
   MAIN browser process only, not renderers, arbitrary apps or services.
   Browser tabs and unsaved web forms may be lost. Files are not deleted.
2. Close all terminal windows: native Ptyxis/other allowlisted application
   window.close accessibility action. No killall, SIGKILL, shell, or broad
   system service action. This can stop shell-attached commands. If GPT Remote
   runs inside a terminal, closing that terminal can disconnect it.
3. Open a local terminal with GPT Remote: exact Ptyxis launcher and existing
   Desktop Commander Remote command (npm Desktop Commander remote).
   It preserves the existing connector if active; no duplicate is started.
   A fourth secondary action opens an ordinary terminal.

## Security, accuracy and user confirmation

Verified Tailnet owner, same-origin CSRF, signed Agent command queue, and
strict allowlisted action names are required. Destructive actions require a
second explicit iPhone confirmation of permanent loss of unsaved work.
The native desktop helper independently requires Atlas and its three Codex
agents to be owner-stopped, no unfinished model jobs, CPUWM idle and no
known Codex/simulation process.

Signed telemetry shares only browser/document/terminal window counts and
the boolean GPT Remote connection status. It never transmits window titles,
file contents, paths or process IDs. A sanitized last-action receipt is stored
privately with permissions 0600, reporting requested and remaining windows.
Unsupported Wayland apps may require manual closing, and partial completion
is reported honestly.

Automated tests use mock windows, mock signals, mock program launch and a
local fake Hub. No real user window was closed during deployment or CI.

## Timer timing correction

Before v1.2, a transient readiness failure precisely at the power countdown
boundary could permanently block the timer. Pi now waits up to 30 further
seconds for the next fresh signed Ubuntu safety report, while Cancel remains
available. A definite Atlas resume or active job aborts immediately.
No request can execute outside the 30-second bound. The fixed root-owned
Ubuntu helper independently re-checks all real power gates before execution.
