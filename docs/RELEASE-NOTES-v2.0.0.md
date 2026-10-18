# GUI-of-Edge-TTS - v2.0.0

v1.0 是一个能用的文字转语音小工具；v2.0 把它补成了一套完整的桌面应用：
图标、主题、双语、设置、提示、生成过程和结果展示都重新做了一遍，底层仍是
同一个 Edge-TTS 引擎，生成的 `.mp3` / `.srt` 用法不变。

## 2.0 新增了什么

- **全新的图标系统。** 应用图标、任务栏图标、标题栏图标全部重制；README
  顶部按 v1.0 → S1 → S2 → 最终版的顺序展示了这条演进路线。
- **中文 / English 双语界面。** 默认跟随 Windows 的界面语言，也可以在设置里
  手动切换；切换后立即生效，并记住选择。
- **深浅主题。** 可以跟随系统，也可以锁定浅色或深色。标题栏、滚动条、
  下拉列表、设置窗口和帮助窗口会一起变化。
- **主界面重做。** 窗口更大、编辑区更宽；面板统一成一个底色，按钮、间距、
  抗锯齿全部重新处理，可点击的东西一眼能看出来。
- **语音筛选。** 322 个语音加了筛选框，输入 `en 女`、`zh-CN`、`晓晓`
  都能快速缩小范围。
- **语速 / 音量 / 音调。** v1.0 没有这三个参数；现在可以填 `20`、`+20%`、
  `1.2x`，旁边实时显示“原声”或“已调整”。
- **输出目录。** 可以在设置里选默认目录并记住；主界面直接显示当前输出目录，
  不用每次生成都重新找文件夹。
- **真正的生成进度。** 不是来回跑的进度条，而是显示已经生成了多少秒音频、
  已经接收了多少字节；可以随时取消，**取消后不会留下半截文件**。
- **结果直接可用。** 生成完成后状态栏给出音频和字幕的完整路径，并提供
  「打开音频」「所在文件夹」；不再弹一个挡住界面的“成功”框。
- **使用提示与完整帮助。** 首次运行有顶部提示条，编辑区下方有快捷键提示，
  右上角「?」可以打开完整帮助；在设置里重新打开提示条时，主窗口会同步长高，
  不会遮住状态栏和版本号。
- **读入 / 另存文本。** `Ctrl+O` 可以读 `.txt` / `.md` / `.srt`（UTF-8 读取
  失败会自动试 GBK），`Ctrl+S` 把编辑区内容另存为文本。
- **智能默认文件名。** 从粘贴的文字里本地提取标题，生成相关的默认文件名；
  改过语速/音量/音调时自动带参数后缀，仍然可以随意改名。
- **完整的设置窗口。** 网络代理、启动提示开关、配置文件位置、界面语言都在
  这里；修改立即生效并写入配置。
- **记住偏好。** 上次使用的语音、参数和输出目录，下次启动会恢复。
- **更稳定的窗口。** 设置窗口固定尺寸，切换语言不再缩放；帮助/设置弹窗
  先建完内容再一次性显示；重新打开提示条时主窗口同步长高，状态栏和页脚
  不再被截断。
- **更安静的错误处理。** 网络或代理错误写进状态栏，不弹一串对话框；配置文件
  损坏时改名成 `.bad` 留档，然后用默认值继续启动。

## 1.0 已有、2.0 继续保留

- 微软 Edge 在线语音合成，输出 `.mp3`。
- 同时生成逐词对齐的 `.srt`，每块最多 5 个词；2.0 进一步保证不跨句、
  不跨长停顿。
- 单文件 exe，下载后双击即用，不需要安装。

## 修复

- 设置窗口切语言时右侧出现黑条：改为固定窗口尺寸，语言切换只换文字，
  不再改变宽高。
- 首次打开设置/帮助时左上角闪一下小窗：改为先隐藏、完成内容和布局，
  再在一个冻结事务里一次性显示。
- 重新打开顶部提示条时窗口不长高、页脚被裁：现在按提示条实际高度补高，
  补高过程也放在冻结事务里，底部不会出现黑色中间带。

---

**English**

v1.0 was a small but working text-to-speech utility. v2.0 turns it into a
complete desktop app: icons, themes, bilingual UI, settings, hints, progress
and results have all been rebuilt. The engine is the same, and the generated
`.mp3` / `.srt` files work exactly as before.

## What is new in 2.0

- **A new icon system.** New app, taskbar and title-bar icons; the README top
  shows the v1.0 → S1 → S2 → final evolution.
- **Chinese / English UI.** Follows the Windows UI language by default, or
  switch manually in Settings; changes apply immediately and are remembered.
- **Light and dark themes.** Follow the system or lock to light/dark; the title
  bar, scrollbars, drop-down lists, Settings and Help all change together.
- **A rebuilt main window.** Larger window and editor; one panel colour, one
  shared button look, reworked spacing and antialiasing, so clickable things
  are obvious at a glance.
- **Voice filter.** A filter box for the 322 voices; `en female`, `zh-CN` and
  `晓晓` all narrow the list quickly.
- **Rate / volume / pitch.** Not available in 1.0; now accepts `20`, `+20%` and
  `1.2x`, with a live "original/adjusted" label.
- **Output folder.** Choose a default folder in Settings and keep it; the main
  window shows the current folder, so you do not hunt for it on every run.
- **Real progress.** Not an indeterminate bar: it shows seconds of audio
  generated and bytes received; cancellable, **with no half-written file left
  behind**.
- **Results ready to use.** On success the status bar shows both full paths and
  offers "Open audio" / "Show in folder"; no blocking success dialog.
- **Hints and full Help.** A first-run strip, a shortcut line under the editor,
  and full Help behind `?`; reopening the strip grows the window instead of
  clipping the status bar and version number.
- **Read / save text.** `Ctrl+O` reads `.txt` / `.md` / `.srt` (GBK fallback);
  `Ctrl+S` saves the editor as text.
- **Smart default file name.** A title is extracted locally, with a
  rate/volume/pitch suffix when parameters changed; still fully editable.
- **A complete Settings window.** Proxy, hint switch, config-file location and
  UI language; changes apply and are written immediately.
- **Remembers preferences.** Last voice, parameters and output folder are
  restored on the next launch.
- **More stable windows.** Settings has a fixed size, so language changes do
  not resize; Help/Settings popups finish their content before the first
  paint; reopening the hint strip grows the main window, so the status bar and
  footer are no longer cut off.
- **Quieter error handling.** Network/proxy errors go to the status bar instead
  of dialog stacks; a broken config is renamed `.bad` and defaults are used.

## Kept from 1.0

- Microsoft Edge online speech synthesis, producing `.mp3`.
- Word-aligned `.srt` with at most 5 words per block; 2.0 also avoids splitting
  across sentences and long pauses.
- A single exe, ready to run after download, with no installation.

## Fixed

- The black strip at the right edge of Settings during a language switch. The
  window now has a fixed size; switching only changes text, never width or
  height.
- The small top-left flash on the first Settings/Help open. The window is now
  hidden while its content and layout are built, then shown in one frozen
  transaction.
- Reopening the hint strip did not grow the window, so the footer was clipped.
  The window now grows by the strip's actual height, and the resize is also
  wrapped in a frozen transaction so no black strip appears at the bottom.

---

**中文 / English 的完整说明见 [README](https://github.com/Neus117/GUI-of-Edge-TTS#readme)。**
