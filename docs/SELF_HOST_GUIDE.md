# Self-Host Guide (Windows/WSL2 + Mac, single author)

This is the practical guide for running agentic-fm on **your own machines** — some
Mac, some Windows/WSL2 — as the **sole person authoring FileMaker scripts**. It
covers first-time setup on each OS, the daily workflow, and how to keep your
machines in sync.

For the upstream, macOS-native reference, see [`QUICKSTART.md`](../QUICKSTART.md).
This guide **complements** it: it fills the Windows/WSL2 gap, documents the
multi-machine sync, and reflects the local hardening applied to this clone.

---

## 1. What this is — and what it isn't

agentic-fm is a **developer authoring tool**: you describe a FileMaker script in
plain English, an AI writes the `fmxmlsnippet` XML, and you paste it into the
Script Workspace. It is **not** part of the finished solution your shop staff
use — they only ever touch the deployed FileMaker app, never this tool.

Two consequences shape everything below:

- **It runs locally, per machine.** The webviewer is a local server bound to
  `127.0.0.1:8090` on the machine you're sitting at. It reads and writes the
  local `agent/` folder and (via the Claude Code provider) spawns your local
  `claude` CLI. Nothing is shared over the network.
- **This is multi-*machine*, not multi-*user*.** You are one person who happens
  to work from several computers. So there is no team, no shared server, no seat
  contention. One Claude login, signed in on each machine, is enough — you can
  only author from one machine at a time anyway.

> **Explicitly out of scope:** onboarding other people, running one shared server
> for many clients (the API has no per-user isolation and would be a security
> risk exposed beyond localhost — see §8), and local/offline AI models (the
> provider is hardcoded to Anthropic/OpenAI/Claude-CLI; a local model would need
> a code change first).

---

## 2. The shared FileMaker file vs. the per-machine tool

Your FileMaker **solution file is shared normally** through FileMaker Server —
including the layout that hosts the Web Viewer and the `agentic-fm` companion
scripts. That part is genuinely multi-machine: open the same hosted file from any
computer.

The Web Viewer object's URL is `http://localhost:8090`. Because it's
`localhost`, it resolves to **whatever machine you're currently on** — so the one
shared solution "just works" on every computer, *provided each machine runs its
own webviewer server on port 8090*.

> **Port must match everywhere.** The `localhost:8090` URL is stored inside the
> shared solution. If one machine ran the server on a different port, the Web
> Viewer would be blank there. Keep every machine on **8090**. (Upstream docs
> still say `8080`; this clone standardizes on 8090 because port 8080 is taken by
> another local service.)

---

## 3. Prerequisites (per machine)

| Requirement | Mac | Windows/WSL2 |
| --- | --- | --- |
| FileMaker Pro **21.0+** | native | native (Windows) |
| Python 3 (stdlib only) | ships / `brew install python` | inside WSL: `python3` |
| Node.js **18+** (webviewer) | `brew install node` | inside WSL |
| `claude` CLI, authenticated | `claude` login | inside WSL: `claude` login |
| `fm-xml-export-exploder` | macOS binary in `~/bin` | Linux build on PATH / `FM_XML_EXPLODER_BIN` (setup-time only) |
| git | ships | inside WSL |

On Windows the AI tooling (Python, Node, Claude, git, the webviewer) all lives
**inside WSL2 (Ubuntu)**; FileMaker Pro runs on the Windows side and reaches the
WSL server over `localhost`.

---

## 4. First-time setup — pick your OS

### 4a. Mac

Follow [`QUICKSTART.md`](../QUICKSTART.md) as written, with **one delta**: when you
start the webviewer, run it on **port 8090** (this clone's `vite.config.ts`
already sets `port: 8090`, so `npm run dev` does the right thing). Everything else
— `~/bin/fm-xml-export-exploder`, Gatekeeper, `clipboard.py`, `Cmd+V` — is exactly
the macOS path.

### 4b. Windows / WSL2

This is the path `QUICKSTART.md` does not cover.

1. **Clone into WSL** (not the Windows filesystem — keep it under the Linux home
   for speed and correct permissions):
   ```bash
   git clone https://github.com/andreas450/agentic-fm.git ~/Projects/agentic-fm
   cd ~/Projects/agentic-fm
   ```
   Cloning the **fork** (`andreas450/agentic-fm`) gives you the Windows clipboard
   port and the port/security config out of the box. See §6 for keeping it in
   sync and tracking upstream.

2. **Install dependencies inside WSL:** Node 18+, Python 3, the `claude` CLI, then
   `cd webviewer && npm install`.

3. **Clipboard just works.** `agent/scripts/clipboard.py` auto-detects WSL and
   delegates to `clipboard_win.py` via `python.exe`, so
   `python3 agent/scripts/clipboard.py write agent/sandbox/foo.xml` puts objects on
   the **Windows** clipboard ready to paste into FileMaker. No extra step.

4. **`.wslconfig` — keep WSL alive.** The webviewer runs as a long-lived service;
   WSL must not sleep out from under it. In `C:\Users\<You>\.wslconfig`:
   ```ini
   [wsl2]
   networkingMode=Mirrored
   vmIdleTimeout=-1
   ```
   Then, from **Windows** (PowerShell/CMD), once: `wsl --shutdown` (it restarts on
   next use). `vmIdleTimeout=-1` stops WSL from killing the service when idle;
   `Mirrored` networking makes `localhost` shared between Windows and WSL so the
   Web Viewer can reach the server (see §8 if it can't).

5. **Run the webviewer as a systemd user service** so it survives reboots and
   restarts on failure, bound to localhost only:
   ```bash
   systemctl --user status agentic-fm-webviewer     # check
   systemctl --user restart agentic-fm-webviewer    # after any webviewer/ change
   ```
   Linger must be enabled (`loginctl enable-linger $USER`) so the service runs
   without an interactive login. The service runs Vite on `127.0.0.1:8090`.

6. **Companion server** (port 8765) is only needed for setup-time actions
   (**Explode XML**, the debug script). Start it in a WSL terminal when you need
   it: `python3 agent/scripts/companion_server.py`.

---

## 5. FileMaker side (once per solution — shared file, both OSes)

Identical to `QUICKSTART.md` → *One-time FileMaker setup*, summarized:

1. **Context custom function** — `File > Manage > Custom Functions`, new function
   `Context ( task )`, paste `filemaker/Context.fmfn`.
2. **Companion scripts** — open `filemaker/agentic-fm.fmp12`, copy the `agentic-fm`
   script folder into your solution (or paste `filemaker/agentic-fm.xml` via
   `clipboard.py write`).
3. **Get agentic-fm path** — run once per FileMaker session; point the picker at
   your repo. On Windows the repo lives at
   `\\wsl$\Ubuntu\home\<you>\Projects\agentic-fm`.
4. **Web Viewer object** — on a dedicated, resizable layout, add a Web Viewer
   named exactly **`agentic-fm`**, URL **`http://localhost:8090`**.
5. **Push Context** — run it on the layout you're working on to write
   `agent/CONTEXT.json`.

---

## 6. Working across your machines

Your machines stay in sync through the **`andreas450/agentic-fm` fork**, which is
your off-laptop home for the clipboard port and local config.

- **Remotes:** `origin` → `petrowsky/agentic-fm` (upstream, for updates),
  `fork` → `andreas450/agentic-fm` (your work). If you cloned the fork in §4b,
  add upstream: `git remote add origin https://github.com/petrowsky/agentic-fm.git`.
- **Switching machines:** `git pull fork main` to get your latest config/work
  before you start; commit and `git push fork main` when you finish, so the other
  machine can pull it.
- **Updating from upstream:** `git fetch origin && git merge origin/main`
  (a merge, not fast-forward — your `main` carries local patches on top of
  upstream). See `UPDATES.md`.
- **Not synced (stays local, and should):** `webviewer/.env.local` (AI provider
  choice/keys) and the systemd unit are per-machine. The port/security config
  *is* committed, so it travels with the branch.
- **Preservation branches on the fork:** `windows-clipboard-port` (clean copy of
  the clipboard work) and `backup/pre-reconcile-20260702` (safety snapshot).

---

## 7. AI access (one Claude login)

Since you're the only author, use the **Claude Code CLI** provider — no API key,
no per-token billing. Just sign in to `claude` once on each machine:

```bash
claude   # follow the login prompt
```

One Claude subscription covers all your machines because you only ever author from
one at a time. You do **not** need a shared Anthropic API key or local models.
(For the record: a shared key would land in plaintext in `.env.local`, and local
models aren't supported without a code change — `openai.ts` is hardcoded to
OpenAI's endpoint — and a 14B model on 16 GB VRAM would struggle with the
~31–33k-token system prompt this tool injects.)

---

## 8. Security

This clone has been hardened for the self-host case:

- **Localhost-only binding.** `vite.config.ts` sets `host: '127.0.0.1'`,
  `port: 8090`, `strictPort: true`. The server is not reachable from the LAN.
  `networkingMode=Mirrored` does **not** widen this — a loopback bind stays
  loopback.
- **Same-origin (CSRF) guard.** Even bound to localhost, any web page open in a
  browser *on the same machine* could otherwise POST to `localhost:8090/api/chat`,
  which spawns the `claude` CLI = a drive-by code-execution vector. The API now
  rejects any request whose `Origin` isn't `http://localhost:8090` /
  `http://127.0.0.1:8090` (`webviewer/server/api.ts`). This also defeats DNS
  rebinding.
- **Vite upgraded to 6.4.3** — clears the dev-server file-read / `fs.deny`-bypass
  advisories that affected 6.1.0. `npm audit` reports 0 vulnerabilities.

**Remaining, lower-priority hardening (optional):** two GET endpoints
(`/api/snippet`, `/api/index`) lack the path-traversal guard the sandbox/library
routes have; bounded impact (only `.xml`/`.index` files, same-origin only). API
keys, if ever added via Settings, are stored plaintext in `.env.local`.

---

## 9. Daily workflow

Once set up, per script (see `QUICKSTART.md` → *Every session* for the full
version):

1. In FileMaker, go to the layout you're working on → run **Push Context**, enter
   a plain-English task.
2. Open the layout with the `agentic-fm` Web Viewer (or use the Claude Code CLI in
   the repo directly).
3. Ask in plain English ("add a line item to the current invoice").
4. Review the generated script / XML preview → **Clipboard** → in Script
   Workspace, `Cmd+V` (Mac) / `Ctrl+V` (Windows).

---

## 10. Troubleshooting (Windows/WSL additions)

| Problem | Fix |
| --- | --- |
| Web Viewer blank after WSL was idle | Service died — set `vmIdleTimeout=-1` in `.wslconfig` (§4b), `wsl --shutdown` once, then `systemctl --user restart agentic-fm-webviewer`. |
| Web Viewer blank, service *is* running | `localhost:8090` not reachable from Windows. First confirm `curl http://localhost:8090` works from Windows. If not, add a Windows port proxy: `netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8090 connectaddress=<WSL-IP> connectport=8090`. **Do not** re-expose the server with `host: true` — that undoes the security fix. |
| Chat / validate / clipboard returns **403 inside FileMaker** | The FM Web Viewer sent an `Origin` not in the allowlist. Capture the Origin it sends (log it in `api.ts`) and add it to `ALLOWED_ORIGINS`. Requests from a normal browser at `localhost:8090` are unaffected. |
| `port 8090 already in use` | `strictPort` makes Vite exit rather than drift. Find the holder: `ss -tlnp | grep 8090`; stop it or restart the service. |
| Paste does nothing | Confirm `clipboard.py write` succeeded; on WSL it delegates to `clipboard_win.py` via `python.exe` — check that Windows interop is enabled. |
| Edits to `webviewer/` don't take effect | Restart the service: `systemctl --user restart agentic-fm-webviewer`. |

---

*This guide describes a local self-host of the OSS webviewer using the Claude Code
CLI provider — no paid plug-in required.*
