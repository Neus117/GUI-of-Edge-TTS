# tools

**这里的每一件工具都对应一条"当时是怎么知道的"。**
加工具的时候请写清它**查什么缺陷**、以及**怎么证明它真的在查**。

---

## 🖥 界面测试：在 DeepSeek 专用桌面上随便开窗（2026-10-17 新规矩）

**旧铁律「工具不许打断用户」已由用户撤销。** 他准备了两个互不打扰的虚拟桌面，
并允许 harness 在 DeepSeek 专用桌面上做任何它认为必要的操作：

* `Win+Tab`：任务视图；把 DeepSeek Harness 窗口拖到另一个桌面；
* `Win+Ctrl+D` 新建桌面；`Win+Ctrl+F4` 关闭当前桌面；
* `Win+Ctrl+←` / `Win+Ctrl+→` 切换桌面。

**在专用桌面上**：可以开可见窗口、截图、抢焦点、模拟点击、把窗口置顶。
**收尾仍是硬要求**：测试结束关掉自己启动的窗口/进程，删除临时目录与临时文件。

下面这些仍然是**更安静的默认做法**，适合门禁和无人测试（更快、不闪）：

| 更安静的默认 | 说明 |
|---|---|
| `_probe_window.park()`：窗口映射到屏幕外 | 布局照算，屏幕上不闪 |
| `update_idletasks()`（只算布局，不处理输入） | 不会触发输入事件 |
| `event_generate()` 直接投递事件 | 不需要真实焦点 |
| `--method printwindow` 抓图 | 不要求窗口在最前面 |

`_probe_window.py` 提供三件东西：`park()` 把窗口停到屏幕外、`verify_offscreen()`
断言本进程没有窗口落在屏幕内、`visible_windows_on_screen()` 是它的实现。
探针开头/结尾调 `verify_offscreen()` 是好习惯——"我以为它在屏幕外"不算验证。

`capture_screenshot.py` 会开真实窗口、抢焦点，所以仍然要显式 `--allow-visible`；
它现在只是"确认你确实要可见截图"的开关，**不是用户授权门槛**。

只想核对"颜色/尺寸/版位"的话**不需要它**：

```bash
python tools/audit_theme_surfaces.py   # 反色一致性（含每个弹窗）
python tools/ui_layout_probe.py        # 几何与配色（默认中文）
python tools/ui_layout_probe.py --lang en --theme light  # 英文版位
```

---

## 一次跑完全部门禁

```bash
python tools/check_all.py            # 含联网的端到端冒烟
python tools/check_all.py --offline  # 跳过联网那一项
```

| 工具 | 查什么缺陷 | 阳性对照 |
|---|---|---|
| `add_bom.py` | `.ps1` 少 UTF-8 BOM ⇒ Windows PowerShell 5.1 按 GBK 解码，中文变假语法错误、`}` 被吃掉 | `--check` 本身就是判据；缺一个就退出码 2 |
| `check_forbidden.py` | 写死的绝对路径 / 写死的颜色 / 同一个类里重复定义的方法 / 没人读的设置字段 | `--self-test`：4 个必然被拦 + 5 个不该被拦的样本 |
| `ui_layout_probe.py` | 控件被挤出客户区、**面板出现两种底色**、按钮描边等于底色、文字对比度不足、**控件树里残留系统色**、提示语被截断、占位文字被裁 | `probe_layout_negative.py`：2 个阳性 + 1 个阴性 |
| `probe_paste_placeholder.py` | 占位提示与用户输入混在一起、粘贴之后校验说"编辑区是空的" | 用真剪贴板走 Ctrl+V；**第一版复现了 7 个问题** |
| `audit_theme_surfaces.py` | **全界面**反色不一致：主窗口 + 每一个弹窗，逐控件回读颜色、残留系统色、标题栏深浅、弹窗留白 | 它存在的理由是"我连续三轮只修了用户报出来的那一处" |
| `e2e_smoke.py` | 真实路径上的回归（联网） | 它本身就是"用户走的那条路"的对照 |
| `capture_screenshot.py` | —— | 只是把窗口拍下来供人眼核对观感，**不做自动判断** |
| `probe_async_warning.py` | 定位 `Task was destroyed but it is pending` 的来源 | 按用例名跑，把噪音隔离出来 |
| `build_info.py` | 版本号三处不一致、产物自报的提交不对 | `build.ps1` 会调它并核对 |

---

## check_forbidden.py

四条判据，每条都对应一次真实返工：

1. **写死的绝对路径** —— 只在这台机器上成立，换机器/进 CI 就废。
   判据落在 `ast` 里字符串的**值**上，不看源码的转义写法：
   `"D:\\a"` 与 `r"D:\a"` 都是绝对路径，按源码文本匹配会一漏一报。
2. **写死的颜色** —— 颜色必须来自 `Palette`（只有 `theme.py` 例外），
   否则深色主题下会出现低对比度灰字。判据在"去了注释"的行上匹配；
   **注释里提到 `#F0F0F0` 不算违规**（但字符串里的 `#` 不能被当成注释开头，
   否则 `background="#123456"` 会被截断，判据自己把证据删掉）。
3. **同一个类里定义两次同名方法** —— Python 静默用后一个，
   改前一个不会有任何效果。
4. **声明了却没人读的设置字段** —— 用户在设置里改了它，什么都不会发生。

```bash
python tools/check_forbidden.py
python tools/check_forbidden.py --self-test   # 阳性 + 阴性对照
python tools/check_forbidden.py --verbose
```

---

## ui_layout_probe.py

不抓图、不猜观感，只回答几个可验证的问题：

```bash
python tools/ui_layout_probe.py --theme light --out layout-light.json
python tools/ui_layout_probe.py --theme dark
```

它回读并断言：

* 每个控件的 `x / y / 宽 / 高`，以及它是否 `viewable`
  （嵌套控件要用 `winfo_viewable`，`winfo_ismapped` 只对顶层子控件为真）；
* 有没有控件落在客户区之外——**这一条抓出过真缺陷**：
  720 高的窗口里，操作区与底栏被 `pack` 挤到了 y = -337；
* 相邻分区的间距是否落在 4 逻辑像素网格上（168 DPI 下等于 7 物理像素）；
* 提示语会不会被截断（按**容器**分到的宽度算，不是按 Label 自己的宽度——
  Label 会跟着文字长，那等于永远相等）；
* 占位文字放不放得下（用 `yview()` 的上界，**不要用 `dlineinfo` 数行**：
  越出视口的行它返回 `None`，被裁掉的那几行根本数不到）；
* **弹窗也要查**：打开设置窗口与提示窗口，对它们各跑一遍系统色检查与
  留白检查（`窗口高度 − 内容需要高度 > 40 px` 就报错）。

> 弹窗那一条是补出来的：主窗口一片绿，而设置窗口里的按钮因为**没传 `theme`**
> 一直停在 `SystemButtonFace`——**检查器从来没看过那个地方**。

### 配色判据（v1.1.0 用户定稿）

**面板只有一种底色**，所以判据写死了三条：

```
card == background           # 出现两种底色就报错
surface != background        # 否则看不出哪里能打字
border_strong != background  # 否则按钮会和背景融在一起
```

另外两条是文字可读性（正文对比度 ≥ 4.5、次要 ≥ 3.0）。

还有一条最值钱的：**走一遍控件树，找出底色仍是系统色的控件**。

```
[PROBLEM] 语速 %（Label）还是系统色 SystemButtonFace：主题没刷到它
```

这是"漏设一个控件"的**可查证据**——比肉眼看"深色下有那么一块浅的"可靠得多。
实测就是靠这一类检查发现"语速 % / 音量 % / 音调 Hz"三个标签从未被设色。

---

## probe_paste_placeholder.py

用**真剪贴板 + 真实的 `<<Paste>>` 事件**（不是 `text.insert()`）走四条路：
Ctrl+V、之后继续输入、清空后再粘贴、带坐标粘贴。每一步都回读
`_placeholder_active`、`get_text()` 与控件里的原文。

它存在的理由：**单元测试证明"规则对"，不能证明"程序会那样用它"。**
而这一条缺陷恰恰绕过了当时的端到端冒烟——因为冒烟里有一句
`app._placeholder_active = False` 在**绕开被测代码**。现在冒烟改走
`app.set_editor_content()`（"读入文件"按钮的同一条路）。

---

## e2e_smoke.py / `--smoke`

```bash
python tools/e2e_smoke.py --out <目录>   # 命令行入口
GUI-of-Edge-TTS.exe --smoke --out <目录> # 冻结态同一条判据
```

逻辑住在包里（`gui_of_edge_tts._smoke`），所以**打包成 exe 之后还能再跑一遍**。
冻结态与源码态的环境不一样（没有控制台、Tcl/Tk 从包里加载、依赖被裁剪过），
只有真的跑一次才知道它行不行。

它**会联网**，这正是在重点。判据全部是**磁盘上的事实与界面上的文字**：

* 真的生成了 `.mp3`，头部字节像 mp3，大小合理；
* 真的生成了 `.srt`，从序号 1 开始、有时间轴、每块不超过 5 个词；
* **字幕结束时间与音频长度对齐**（上游是 CBR 48 kbps，所以文件大小能换算时长）；
* 状态栏里写着那两个文件的**完整路径**；
* 「打开音频 / 所在文件夹」真的指向产物；
* 填完内容之后**占位提示不在控件里**（这一条是用户实测报回来的那个缺陷）。

---

## audit_theme_surfaces.py

```bash
python tools/audit_theme_surfaces.py             # 两个主题都查
python tools/audit_theme_surfaces.py --theme dark
```

**它存在的理由是一段代价**：用户连续报了三轮"没有正确反色"，而我每一轮
只修了**他报出来的那一处**：

| 轮次 | 报的是 | 我的问题 |
|---|---|---|
| 1 | 深色下三个参数框没变深 | 我用手写控件清单设色，漏了那三个标签 |
| 2 | 设置窗口视觉不统一 | 弹窗按钮没传 `theme`，而主窗口的遍历看不到弹窗 |
| 3 | 面板/选项/按钮周边都没反色 | 原生 `Radiobutton`/`Checkbutton` 的指示器由系统绘制，改不动 |

问题不在修得对不对，而在**我没有一次把范围盖住**。所以这个脚本不"检查我
记得的那几个"，而是：

```
枚举所有顶级窗口 → 递归每一个控件 → 逐个回读颜色 → 和主题期望值比对
```

判据四条：控件底色必须落在主题色集合内；不许出现 `System*` 颜色名；
每个窗口的标题栏深色属性必须与主题一致；弹窗高度不得比内容高出 40 px。

**它现在也进 `check_all.py`。** 加它的同时验证了它会在真出问题时报错
（把 `theme` 参数去掉一次，看它是否报出 `SystemButtonFace`）。

---

## capture_screenshot.py

```bash
python tools/capture_screenshot.py \
  --exe <python.exe> --args "src/GUI-of-Edge-TTS.py" \
  --out shot.png --settle 9 --env ETTS_THEME=dark \
  --method printwindow --place 5,60 [--keys f1]
```

三个实测出来的细节，缺一个就抓不对：

1. **`--method printwindow` 在 Tk 上可用**，不要求窗口在最前面。
   ⚠️ 归档里同一个 API 在 wxPython 上返回过乱码——**那是另一个技术栈**，
   所以两条路都留着，可以互相对照。
2. **坐标要按窗口 DPI 换算**：抓图进程若不声明 Per-Monitor V2 感知，
   `GetWindowRect` 给的是逻辑虚拟坐标，而抓图要物理像素。
3. **必须确认窗口属于哪个可执行文件**。机器上有残留实例时，"标题是
   Edge-TTS"会把别人的窗口当成自己的——实测因此抓到一扇 891×938 的旧界面，
   还差点得出"打包打错了"的结论。现在它打印 `window exe = …` 并在不匹配时
   直接失败；起飞前也会清掉同名进程。

⚠️ **清理进程时绝不按通用解释器名**：从源码抓图时 `--exe` 就是 `python.exe`，
一句 `taskkill /F /IM python.exe` 会把**正在跑这个脚本的自己**杀掉，
症状是安静退出、一行输出都没有。现在显式跳过 `python.exe` / `pwsh.exe` 这类名字。

**它不做任何判断**，只保存 PNG。判"好不好看"是人眼的事
（`DevAesthetics` 第 22 节：把观感和可验证的属性分开）。

---

## probe_layout_negative.py

`Application.layout_findings()` 的**阳性/阴性对照**：造两种必然出问题的情形
（占位文字比控件高、提示条文字比容器宽），确认它真的会报；再造一个正常界面，
确认它不误报。

理由：**"返回通过"和"根本没有检查这一项"在输出里长得一模一样。**
这一版里那两个判据各自错过一次，都是**量错了对象**：

| 检查 | 我量的 | 应该量的 |
|---|---|---|
| 提示语会不会被截断 | Label 自己的宽度（它跟着文字长） | **容器**分给它的宽度 |
| 占位文字会不会被裁 | `dlineinfo` 数行高 | `yview()` 的上界 |

---

## probe_async_warning.py

```bash
python tools/probe_async_warning.py [用例名...]
```

`asyncio` 的 `Task was destroyed but it is pending` 只说"有个任务没关"，
不说"是谁"。这个探针按用例名逐个跑，把噪音的来源缩到一个用例上。
它就是这么定位出"取消生成时异步生成器没被 `aclose`"的。

---

## build_info.py

```bash
python tools/build_info.py version                     # 打印 version.py 里的版本
python tools/build_info.py check                        # 核对 version.txt / README 是否一致
python tools/build_info.py write-build --commit <sha>   # 生成 _build.py
```

`build.ps1` 用它把提交哈希注入包，然后**运行产物的 `--version` 核对它自报的
提交就是这一次**——「我以为我写进去了」和「它真的在里面」是两件事。

**为什么不把这段逻辑写在 `.ps1` 里**：在 PowerShell 里嵌 Python 代码要处理
两层转义（PowerShell 的 `\"` 与 Python 的引号），第一版直接在字符集上炸了。
少一层转义就少一个坑。
