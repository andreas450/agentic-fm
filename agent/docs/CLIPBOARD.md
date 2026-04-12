# Clipboard Interaction

FileMaker does not use plain text for clipboard objects. When you copy scripts, steps, fields, custom functions, or other objects in FileMaker, they are placed on the macOS clipboard as proprietary binary descriptor classes — not as readable text. Converting between those classes and the fmxmlsnippet XML format that this project uses requires AppleScript.

**Do not use `pbpaste` or `pbcopy` for FileMaker objects.** Both tools silently corrupt multi-byte UTF-8 characters (such as `≠`, `≤`, `≥`, `¶`) that are common in FileMaker calculations.

---

## Clipboard class codes

Each FileMaker object type corresponds to a four-letter AppleScript class code:

| Code   | FileMaker object          | fmxmlsnippet element       |
|--------|---------------------------|----------------------------|
| `XMSS` | Script Steps              | `<Step>`                   |
| `XMSC` | Script                    | `<Script>`                 |
| `XML2` | Layout Objects            | `<Layout>` (v12+)          |
| `XMLO` | Layout Objects (legacy)   | `<Layout>`                 |
| `XMFD` | Field Definition          | `<Field>`                  |
| `XMFN` | Custom Function           | `<CustomFunction>`         |
| `XMTB` | Table                     | `<BaseTable>`              |
| `XMVL` | Value List                | `<ValueList>`              |
| `XMTH` | Theme                     | `<Theme>`                  |

This project primarily works with `XMSS` (the output format is steps-only inside `<fmxmlsnippet type="FMObjectList">`).

### CorePasteboardFlavorType values

When accessing the clipboard via the macOS Pasteboard API directly (e.g. via PyObjC's `NSPasteboard`), each class code maps to a `CorePasteboardFlavorType` string. The hex value is simply the four ASCII bytes of the class code interpreted as a big-endian 32-bit integer:

| Code   | Hex value    | Pasteboard type string                         |
|--------|--------------|------------------------------------------------|
| `XMSS` | `0x584D5353` | `CorePasteboardFlavorType 0x584D5353`          |
| `XMSC` | `0x584D5343` | `CorePasteboardFlavorType 0x584D5343`          |
| `XML2` | `0x584D4C32` | `CorePasteboardFlavorType 0x584D4C32`          |
| `XMLO` | `0x584D4C4F` | `CorePasteboardFlavorType 0x584D4C4F`          |
| `XMFD` | `0x584D4644` | `CorePasteboardFlavorType 0x584D4644`          |
| `XMFN` | `0x584D464E` | `CorePasteboardFlavorType 0x584D464E`          |
| `XMTB` | `0x584D5442` | `CorePasteboardFlavorType 0x584D5442`          |
| `XMVL` | `0x584D564C` | `CorePasteboardFlavorType 0x584D564C`          |
| `XMTH` | `0x584D5448` | `CorePasteboardFlavorType 0x584D5448`          |
| `ut16` | `0x75743136` | `CorePasteboardFlavorType 0x75743136`          |

---

## Using clipboard.py

A Python helper script is provided at `agent/scripts/clipboard.py`. It handles both read and write directions and auto-detects the correct class code from the XML content.

### Read: FM objects on clipboard → XML file

After copying objects in FileMaker (`⌘C`), run:

```bash
# Print to stdout
python3 agent/scripts/clipboard.py read

# Save directly to the sandbox
python3 agent/scripts/clipboard.py read agent/sandbox/myscript.xml
```

### Write: XML file → FM objects on clipboard

After generating or editing a snippet, send it to the clipboard so it can be pasted into FileMaker (`⌘V`):

```bash
# Class is auto-detected from the XML content
python3 agent/scripts/clipboard.py write agent/sandbox/myscript.xml

# Override the class explicitly if needed
python3 agent/scripts/clipboard.py write agent/sandbox/myscript.xml --class XMSC
```

Auto-detection reads the first XML element inside the fmxmlsnippet wrapper and maps it to the correct class (e.g. `<Step>` → `XMSS`, `<CustomFunction>` → `XMFN`).

---

## How it works (low-level)

Understanding the encoding helps when diagnosing issues or working outside of `clipboard.py`.

### Reading (FM → XML)

FileMaker stores clipboard data as a record keyed by the full AppleScript class notation: `{«class XMSS»: «data XMSS3C...»}`. The key point is that you must use `«class XMSS»` (not bare `XMSS`) as the property accessor — otherwise AppleScript cannot find the key in the record.

The `clipboard.py` script detects the class, then fetches the value using `osascript -e 'the clipboard as «class XMSS»'`. The `as` coercion form is used rather than `«class XMSS» of (the clipboard)` — the `of` form treats the clipboard as a record and fails when the clipboard's primary type is plain text (which happens when a single text label is copied in Layout Mode). The `as` form locates the requested type regardless of what the primary type is. osascript prints the binary descriptor as:

```
«data XMSS3C666D786D6C736E69707065743C...»
```

The script then:
1. Extracts the hex portion with a regex
2. Converts hex → bytes with `bytes.fromhex()`
3. Decodes as UTF-8
4. Pretty-prints with `xmllint --format -` (included with macOS Xcode command line tools)

The equivalent AppleScript pipeline (as used by the [Typinator](https://www.ergonis.com/typinator) approach and [FmClipTools](https://github.com/DanShockley/FmClipTools)) is:

```applescript
try
    set allowed to {«class XMSS», «class XML2», «class XMLO», «class XMSC», «class XMFD», «class XMFN», «class XMTB», «class XMVL», «class XMTH»}
    set clipboardType to item 1 of item 1 of (clipboard info) as class
    if clipboardType is in allowed then
        -- classString will be e.g. "«class XMSS»" — must use this full form, not bare "XMSS"
        set classString to clipboardType as string
        return do shell script "osascript -e '" & classString & " of (the clipboard)' | sed 's/«data ....//; s/»//' | xxd -r -p | iconv -f UTF-8 -t UTF-8 | xmllint --format -"
    end if
on error errMsg
    return "ERROR: " & errMsg
end try
```

### Writing (XML → FM)

To place an fmxmlsnippet on the clipboard in the correct class for FileMaker to accept:

```applescript
-- Replace XMSS with the appropriate class code and hexdata with the hex-encoded XML
set the clipboard to «data XMSShexdata»
```

From the shell (replace `XMSS` and the file path as needed):

```bash
osascript -e "set the clipboard to «data XMSS$(xxd -p < agent/sandbox/myscript.xml | tr -d '\n')»"
```

`xxd -p` produces the raw hex encoding of the file bytes. The `tr -d '\n'` removes newlines so the hex is a single unbroken string.

---

## Detecting what is on the clipboard

To check whether the clipboard currently holds FileMaker objects (and which type):

```applescript
try
    set allowed to {«class XMSS», «class XML2», «class XMLO», «class XMSC», «class XMFD», «class XMFN», «class XMTB», «class XMVL», «class XMTH»}
    set clipboardType to item 1 of item 1 of (clipboard info) as class
    if clipboardType is in allowed then
        return clipboardType as string  -- returns e.g. "XMSS"
    else
        return "No FileMaker objects on clipboard"
    end if
on error
    return "Clipboard is empty or unreadable"
end try
```

---

## NSPasteboard / PyObjC fast path

`clipboard.py` automatically uses a faster, subprocess-free clipboard path when `pyobjc-framework-Cocoa` is installed. Install it into the project venv:

```bash
pip install pyobjc-framework-Cocoa
```

When available, all clipboard reads and writes go through `NSPasteboard` directly instead of spawning `osascript` subprocesses. This eliminates:
- The `osascript` process launch overhead (significant for large snippets)
- The hex-encode/decode round-trip (`«data XMSS3C...»` → regex → `bytes.fromhex()`)
- Argument-length pressure from very large hex strings passed on the shell command line

Without PyObjC installed the script falls back to the original `osascript` path automatically — no configuration needed.

### How NSPasteboard reads FM binary data

```python
pb = NSPasteboard.generalPasteboard()
pb_type = "CorePasteboardFlavorType 0x584D5353"   # XMSS
data = pb.dataForType_(pb_type)
xml = data.bytes().tobytes().decode('utf-8')
```

### How NSPasteboard reads ut16 menu data

```python
raw_bytes = pb.dataForType_("CorePasteboardFlavorType 0x75743136").bytes().tobytes()
xml = raw_bytes.decode('utf-16')   # BOM is present; Python handles it automatically
```

### How NSPasteboard writes FM data

```python
pb.clearContents()
ns_data = NSData.dataWithBytes_length_(xml_bytes, len(xml_bytes))
pb.setData_forType_(ns_data, "CorePasteboardFlavorType 0x584D5353")
```

Note that `pb.clearContents()` is required before writing — without it, stale data from a previous copy may persist alongside the new data.

---

## Reference

The approach above is derived from [FmClipTools](https://github.com/DanShockley/FmClipTools) by Daniel A. Shockley and Erik Shagdar, which provides a complete AppleScript library for FileMaker clipboard operations including batch conversion, prettifying, and class detection.

---

## Windows and WSL support

`clipboard.py` automatically detects the runtime environment and delegates to
`clipboard_win.py` on Windows and WSL. No configuration is required.

| Environment | Detection | Handler |
|---|---|---|
| macOS | `sys.platform == 'darwin'` | `osascript` / `NSPasteboard` (existing) |
| Windows (VS Code native) | `sys.platform == 'win32'` | `clipboard_win.py` via `sys.executable` |
| WSL (Cursor, Claude Code) | `/proc/version` contains `microsoft` | `clipboard_win.py` via `python.exe` interop |

All existing call sites (`companion_server.py`, `deploy.py`, webviewer) require no changes.

### Prerequisites

- **Windows Python** must be installed and accessible. Verify from a WSL terminal:
  ```bash
  python.exe --version
  ```
- On WSL, `python.exe` is available when Windows Python is in the Windows PATH and
  WSL interop is enabled (default on Windows 11).

### One-time: discover FileMaker's clipboard format name

Before first use, confirm the format name FileMaker registers on your Windows installation:

1. In FileMaker Script Workspace, select all steps (`Ctrl+A`) and copy (`Ctrl+C`)
2. Run from any terminal (Windows cmd, PowerShell, or WSL):
   ```
   python.exe agent/scripts/clipboard_win.py discover
   ```
3. Expected output:
   ```
   ID            Name                 Preview
   ────────────────────────────────────────────────────────────────────────
   0xC123        XMSC                 3c666d786d6c736e697070657...  (<?fmxmlsnip...)
     ^ FileMaker format (Script) *

   * = Known FileMaker format — use this name with --class if needed
   ```
4. If format names differ from the 4-letter codes, pass `--class <name>` when calling
   `write` or `read` directly.

### Calling `clipboard_win.py` directly

On Windows, `clipboard_win.py` can be called directly by Windows Python:

```
python.exe agent\scripts\clipboard_win.py discover
python.exe agent\scripts\clipboard_win.py write agent\sandbox\myscript.xml
python.exe agent\scripts\clipboard_win.py read agent\sandbox\output.xml
```

From WSL (paths converted automatically):

```bash
python3 agent/scripts/clipboard.py write agent/sandbox/myscript.xml
python3 agent/scripts/clipboard.py read agent/sandbox/output.xml
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `Windows Python not found` | Run `python.exe --version` from WSL to verify interop; ensure Python is in Windows PATH |
| `Path conversion failed` | `wslpath` failed — check the file path exists in WSL |
| `OpenClipboard failed` | Another app has the clipboard locked — close clipboard viewers or try again |
| `No FileMaker objects found` | Copy something in FM first (`Ctrl+A`, `Ctrl+C` in Script Workspace) |
| Format name not `XMSC`/`XMSS` | Run `discover` to find the real name, then use `--class <name>` |
