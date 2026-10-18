# GUI-of-Edge-TTS - v2.0.1

v2.0.0 之后的一轮修正：**默认文件名带上语音**、「输出目录」直接进入文件夹，
以及一批性能与健壮性修复。用法、设置文件与产物格式都不变——替换 exe 即可。

## 改进

- **默认文件名带上所选语音。** 形如
  `End like ..._en-US-Emma-multi_语速+30%.mp3`：语音后缀在参数后缀之前。
  普通模型写作 `_en-US-Emma`；多语言模型带 `-multi`（`_en-US-Emma-multi`），
  同一个人有两套模型时名字不会撞。
- **「输出目录」直接进入文件夹。** 点它会在资源管理器里打开并进入产物所在目录，
  不再"在父目录里选中它"。
- **英文界面「Pick...」**（原为 `Pick`）。
- **生成过程更顺。** 进度条每换一个宽度不再重画整张位图（单次 30.55 ms → 0.22 ms）；
  大文档里打字不再每个键都整段数字数；第一次点「生成语音」的停顿从
  280–370 ms 降到约 5 ms（按钮位图在启动后空闲时预热）。
- **代理输入**失焦或回车时立即保存并重新拉取语音列表。

## 修复

- **取消生成后关闭程序，终端会打印** `Task was destroyed but it is pending!`、
  `Unclosed client session`、`Event loop is closed`。现在关闭事件循环前会先收掉
  内层的异步生成器与挂起的任务，终端干净退出。
- **冻结包在 cmd 里 `--help` / `--version` 没有输出。** onefile 的直属父进程是
  引导器、没有控制台；现在会沿父进程链找到真正的控制台，同时保留
  `> 文件` / `| 管道` 的输出。
- **进度条中间直段比两端圆头细 1 像素。**
- **弹窗里按 Esc 会连带取消正在进行的生成**（例如关设置窗口时）。
- **错误弹窗里的长路径被输出两遍、并把弹窗撑宽。**
- **音频已保存、字幕写入失败**时，现在会明确告诉用户音频在哪里；
  这次没有词边界时，同名的旧 `.srt` 会被移除（否则播放器会配上一版字幕），
  状态栏会说明。
- **非法参数**（如 `inf`、`1e400`）在冻结包里点「生成语音」没有反应——
  现在和其它非法参数一样弹提示并恢复上次有效值。
- **设置文件带 UTF-8 BOM、或存成 UTF-16** 时不再被当成坏文件；真的读不出来
  才留档 `settings.json.bad`。
- **全新安装时点设置里的「配置文件」没有反应**——现在会先建出配置目录再打开。
- **环境变量 `ETTS_THEME` / `ETTS_LANG` 只影响运行期**，不会被写进用户配置。
- **多显示器**：设置/帮助弹窗按主窗口所在显示器的可用区域摆放；标题栏与
  任务栏图标按窗口 DPI 选取并缓存。（本机只有一块屏，多屏未实测。）
- **事件泵**：后台消息处理里出现一次异常，不会再让进度/完成/失败永久停住。

## 兼容性

- 设置文件与 v2.0.0 兼容；`.mp3` / `.srt` 的格式与用法不变。
- 新增的默认文件名只在**新生成**时生效，已有的文件不会被改名。
- 版本字符串形如 `Edge-TTS 2.0.1+<提交>`。

---

**English**

A maintenance release after v2.0.0: the default file name now includes the
chosen voice, "Output" opens the folder itself, plus a batch of performance and
robustness fixes. Usage, settings and output formats are unchanged — just
replace the exe.

## Improvements

- **The chosen voice is part of the default file name.** For example
  `End like ..._en-US-Emma-multi_语速+30%.mp3`; the voice comes before the
  parameter suffixes. Plain models use `_en-US-Emma`; multilingual models add
  `-multi` (`_en-US-Emma-multi`) so the two models for the same speaker do not
  collide.
- **"Output" opens the output folder itself** instead of selecting the folder in
  its parent.
- **English UI: "Pick..."** (was `Pick`).
- **Smoother generation.** The progress bar no longer re-rasterises a bitmap for
  every new width (30.55 ms → 0.22 ms); typing in a large document no longer
  recounts the whole text on every key; the first "Generate" pause drops from
  280–370 ms to about 5 ms (button bitmaps are prewarmed while idle).
- **Proxy entry** saves and reloads the voice list immediately on focus-out or
  Enter.

## Fixes

- **After cancelling and closing the app, the terminal printed**
  `Task was destroyed but it is pending!`, `Unclosed client session` and
  `Event loop is closed`. Inner async generators and pending finalizer tasks are
  now drained before the loop is closed.
- **The frozen build printed nothing for `--help` / `--version` in cmd.** The
  onefile bootloader has no console; the app now walks the parent chain to find
  the real console while still honouring `> file` and `| pipe` redirection.
- **The progress bar's straight section was one pixel thinner than its round
  caps.**
- **Pressing Esc in a dialog also cancelled a running generation.**
- **Long paths in error dialogs were printed twice and widened the dialog.**
- **If the audio was saved but the subtitles failed**, the error now says where
  the audio is; when a run has no word boundaries, a stale same-named `.srt` is
  removed (players would otherwise load the old subtitles) and the status bar
  says so.
- **Invalid parameters** such as `inf` / `1e400` no longer make "Generate" do
  nothing in the packaged build.
- **Settings files saved with a UTF-8 BOM or as UTF-16** are read instead of
  being treated as corrupt; only unreadable files are archived as
  `settings.json.bad`.
- **"Config file" in Settings** works on a fresh install (the folder is created
  first).
- **`ETTS_THEME` / `ETTS_LANG` only affect the running session**, never the
  user's settings file.
- **Multi-monitor**: dialogs are placed within the monitor that owns the main
  window, and window/taskbar icons are chosen for the window's DPI (not tested
  on a multi-monitor setup here).
- **The event pump** no longer stops forever after one background message fails.

## Compatibility

- Settings files are compatible with v2.0.0; `.mp3` / `.srt` formats and usage
  are unchanged.
- The new default name only applies to newly generated files; existing files
  are not renamed.
- The version string looks like `Edge-TTS 2.0.1+<commit>`.

---

**完整说明见 [README](https://github.com/Neus117/GUI-of-Edge-TTS#readme)。**
