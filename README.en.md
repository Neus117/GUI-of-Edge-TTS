# :radio: GUI-of-Edge-TTS

<div align="center">

<img src="images/Edge-TTS.png" alt="GUI-of-Edge-TTS" width="256">

[简体中文](README.md) · [**English**](README.en.md)

<img src="images/GUI-of-Edge-TTS(v2.0)_preview.png" alt="GUI-of-Edge-TTS overview" width="880">

<br>

<img src="images/icon-evolution.png" alt="Icon evolution: v1.0 → v2.0 S1 → v2.0 S2 → final" width="720">

<sub>v1.0 → v2.0 S1 → v2.0 S2 → Final</sub>

</div>

## :earth_asia: What it is

Turns text into speech and produces a word-aligned `.srt` subtitle file at the same
time — **I use it to practise spoken English**. Paste the text, pick a voice, press
one button. Both files land in the same folder with the same base name, so players
pick the subtitles up automatically.

**The interface follows the system theme.** There are light and dark palettes, and you
can lock it to one of them.

| Light | Dark |
|---|---|
| <img src="images/GUI-of-Edge-TTS(v2.0)_light.png" alt="Light theme" width="420"> | <img src="images/GUI-of-Edge-TTS(v2.0)_dark.png" alt="Dark theme" width="420"> |

<br>

## :rocket: Quick start

1. Download `GUI-of-Edge-TTS.exe` from [Releases](https://github.com/Neus117/GUI-of-Edge-TTS/releases)
2. Double-click it (no installation)
3. Paste text → pick a voice → press "生成语音" (Generate)

A short usage hint appears on first run; dismiss it with "知道了" (Got it) and press
the `?` button in the top-right, or `Ctrl+H`.

<br>

## :sparkles: Features

### What v1.0 already had

| Feature | Notes |
|---|---|
| **Text to speech** | Microsoft Edge's online speech service, producing `.mp3` |
| **Word-level subtitles** | Writes an `.srt` too, at most 5 words per block; 2.0 also avoids splitting across sentences and long pauses |

### What changed from 1.0 to 2.0

| Feature | Notes |
|---|---|
| **New icon system** | New app, taskbar and title-bar icons; the README top shows the v1.0 → S1 → S2 → final evolution |
| **Light and dark themes** | Follow the system, or lock to light/dark; title bar, scrollbars, drop-down lists, Settings and Help follow |
| **中文 / English** | Follows the Windows UI language by default; switching in Settings applies immediately and is remembered |
| **Rebuilt interface** | A larger window and editor; one panel colour, one shared button look, reworked spacing and antialiasing |
| **Voice filter** | 322 voices plus a filter box; `en female`, `zh-CN` and `晓晓` all narrow the list |
| **Rate / volume / pitch** | Not available in 1.0; now accepts `20`, `+20%` and `1.2x`, with a live "original/adjusted" label |
| **Output folder** | Choose a default folder in Settings and keep it; the main window shows the current folder |
| **Progress and cancel** | A meaningful readout of seconds generated and bytes received; cancellable, **with no half-written file left behind** |
| **Results ready to use** | On success the status bar shows both paths plus "Open audio" / "Show in folder"; no blocking success dialog |
| **Usage hints** | First-run strip, shortcut line under the editor, full Help behind `?`; reopening the strip grows the window instead of clipping the footer |
| **Read / save text** | `Ctrl+O` reads `.txt`/`.md`/`.srt` (GBK fallback); `Ctrl+S` saves |
| **Smart default file name** | A title is extracted locally, with rate/volume/pitch suffix; still editable |
| **Settings window** | Proxy, hint switch, config-file location and UI language; applied and saved immediately |
| **Remembers preferences** | Last voice, parameters and output folder are restored |
| **Stable windows** | Settings has a fixed size, so language changes do not resize or flash; Help/Settings popups are frozen before first paint; showing the hint strip grows the main window |
| **Error handling** | Network/proxy errors go to the status bar instead of dialog stacks; a broken config is renamed `.bad` and defaults are used |

<br>

## :keyboard: Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` | Start generating |
| `Ctrl+O` | Open a text file |
| `Ctrl+S` | Save the editor contents as a text file |
| `Ctrl+L` | Clear the editor |
| `Ctrl+H` | Usage hints (same as the `?` button) |
| `Esc` | Cancel generation / close the hint window |

<br>

## :inbox_tray: How to use

| | |
|---|---|
| **Download** | Grab `GUI-of-Edge-TTS.exe` from [Releases](https://github.com/Neus117/GUI-of-Edge-TTS/releases) and double-click it — no installation |
| **Where files go** | You choose when pressing Generate; the default folder is your Music folder (changeable in Settings). Picking `xxx.mp3` also writes `xxx.srt` next to it |
| **Where settings live** | `%APPDATA%\GUI-of-Edge-TTS\settings.json`. A corrupt file will not stop the program: it is renamed to `settings.json.bad` and defaults are used |
| **Uninstall** | Delete the exe and that settings folder — nothing else is left behind |
| **Check the version** | `GUI-of-Edge-TTS.exe --version` prints something like `Edge-TTS 2.0.0+ae4a6f4`; the part after `+` is the commit it was built from |
| **Can it work offline?** | No. Speech is synthesised by Microsoft's online service; when the network is down the status bar says so |

<br>

## :warning: Known limitations

| Limitation | Status |
|---|---|
| **Needs a network** | Synthesis is online; there is no offline mode |
| **Native drop-downs are system-drawn** | The voice/filter drop-downs are still ttk controls, so the open list follows the system; buttons, switches, scrollbars and progress bars are self-drawn and antialiased |
| **Native dialogs follow the system theme** | The save/open dialog is drawn by Windows. The program matches its title bar, but the dialog body follows the system setting rather than this program's light/dark switch |
| **Chinese punctuation is converted** | `。，！？` and friends are turned into ASCII punctuation before synthesis, because the upstream service segments full-width punctuation worse. Subtitles therefore use ASCII punctuation |
| **One audio file per run** | There is no batch queue; run it again for another file |
| **The voice list is fetched online** | When that fails the program falls back to four built-in voices and says "list not loaded" in the status bar — **it never pretends that fallback is the whole list** |

<br>

## :wrench: Dependencies

| Dependency | Version | Why this version |
|---|---|---|
| Python | 3.12 | Pinned in `environment.yml`; the code itself works on 3.10+ |
| tkinter | bundled with Python | The UI toolkit; conda's python already has it |
| **edge-tts** | **7.3.1** | **Do not go back to 7.0.0**: since 7.3.x upstream ships its own SRT composer (`edge_tts.srt_composer`) and no longer needs the external `srt` package |
| PyInstaller | 6.22.3 | Builds the single-file exe |

```bash
conda env create -f environment.yml -p "<your path>\edge-tts-env"
conda activate "<your path>\edge-tts-env"
```

<br>

## :books: Documentation

| Document | Audience |
|---|---|
| [README.md](README.md) / [README.en.md](README.en.md) | Users — what it is, how to install, how to use, what it cannot do |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Maintainers — architecture, what changed, where the criteria came from, leftovers |
| [tools/README.md](tools/README.md) | Maintainers — what defect each tool looks for |

<br>

## :computer: For developers

### Run it

```bash
python src/GUI-of-Edge-TTS.py              # start the GUI
python src/GUI-of-Edge-TTS.py --selftest   # windowless self-check (15 items)
python src/GUI-of-Edge-TTS.py --version    # version + build commit
python src/GUI-of-Edge-TTS.py --help       # all command-line options
```

### Gates

```bash
python tools/check_all.py            # everything (includes the networked end-to-end smoke)
python tools/check_all.py --offline  # skip the networked one
```

| Check | Which defect it catches |
|---|---|
| `add_bom.py --check` | A `.ps1` without a UTF-8 BOM ⇒ Windows PowerShell 5.1 decodes it as GBK and reports bogus syntax errors |
| `--selftest` | Regressions in pure logic: parameter parsing, subtitle composition, themes, settings I/O |
| `unittest discover -s tests -t tests` | 164 cases; no window, no network |
| `check_forbidden.py` | Hard-coded absolute paths, hard-coded colours, a method defined twice in one class, settings fields nobody reads |
| `ui_layout_probe.py` | Widgets pushed outside the client area, cards the same colour as the window, gaps off the 4-pixel grid |
| `e2e_smoke.py` | **The path a real user takes** (networked): real widgets → real Generate button → real event loop → mp3 and srt actually on disk |

**The gates are tested too.** `check_forbidden.py --self-test` builds samples that
must be rejected and samples that must not be, because
**"returned clean" and "never ran that check" look identical in the output.**

### Code layout

```
src/GUI-of-Edge-TTS.py        entry point (puts src on sys.path, hands over to the package)
src/gui_of_edge_tts/
  bootstrap.py      command line, --selftest, creating the window
  ui.py             the only module that touches tkinter: layout, hints, action and display logic
  theme.py          colours and metrics: light/dark palettes, logical-pixel scaling, ttk styles
  platform_win.py   Windows details: theme detection, DPI, dark title bar, resource paths
  engine.py         synthesis engine: cancellable, writes to a temp file and renames
  voices.py         voice catalogue: ordering, search syntax, fallback list
  subtitles.py      WordBoundary → SRT (the merge rules live here, testable on their own)
  params.py         parsing and validating rate/volume/pitch
  text.py           text preprocessing and word counting
  lang.py           UI language: L(), system detection, persisted preference
  settings.py       settings I/O (atomic write, graceful degradation)
  version.py        version and build commit
tests/              164 unit tests
tools/              gates, probes, screenshots and the end-to-end smoke test
```

**The layering exists so that judgements can be automated.** Text preprocessing,
subtitle merge rules, parameter parsing and voice ordering used to be buried in window
callbacks; they now live in modules that do not import tkinter and are covered by
`tests/`. `ui.py` only wires them up and shows them.

### Building

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` runs the gates, writes the current commit hash into the package (so the
product can report which commit built it), calls PyInstaller, and finally **runs the
product's `--version` and checks the commit it reports matches this build**.
That last step is not optional: "I think I wrote it in" and "it is really in there"
are two different things.

<br>

## :handshake: Contributing

Issues and pull requests are welcome. Before touching the UI, read
[tools/README.md](tools/README.md) — every probe there records how something was
found out at the time.

<br>

## :page_facing_up: Licence and trademarks

- Licensed under GPL-3.0, see [LICENSE](LICENSE).
- Speech synthesis is provided by Microsoft Edge's online service. This project is
  not affiliated with Microsoft.
- The upstream library is [rany2/edge-tts](https://github.com/rany2/edge-tts).
