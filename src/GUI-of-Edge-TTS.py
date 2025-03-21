import sys
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import edge_tts
import asyncio
import threading
import srt
from typing import Dict, Any

WordBoundary = Dict[str, Any]

# 颜色配置常量
COLOR_CONFIG = {
    "PRIMARY": "#226BE0",    # 主色调
    "DISABLED_BG": "#B0BEC5", # 禁用状态背景
    "DISABLED_FG": "#616161", # 禁用状态文字
    "CURSOR": "#226BE0"      # 输入框光标颜色
}

# 字幕生成参数
MAX_WORDS_PER_CUE = 5  # 每个字幕块最大单词数

def preprocess_text(text: str) -> str:
    """
    文本预处理函数
    
    功能：
        - 转换中文标点到英文标点
        - 去除首尾空白字符
        - 确保文本符合TTS引擎输入要求
    
    参数：
        text: 原始输入文本
        
    返回：
        标准化处理后的文本
    """
    return text.translate(str.maketrans({'。':'.', '？':'?', '！':'!'})).strip()

async def get_voices() -> list:
    """
    获取可用语音列表
    
    排序规则：
        1. 美式英语(en-US)优先
        2. 简体中文(zh-CN)次之
        3. 其他语音按名称排序
    
    返回：
        排序后的语音列表，格式为(Name, ShortName)
    """
    voices = await edge_tts.list_voices()
    return sorted(
        [(v['Name'], v['ShortName']) for v in voices],
        key=lambda x: (
            0 if x[1].startswith('en-US') else 
            1 if x[1].startswith('zh-CN') else 2,
            x[1]
        )
    )

class SubMaker:
    """
    SRT字幕生成器
    
    属性：
        cues: 存储生成的字幕块列表
    """
    def __init__(self):
        self.cues = []

    def feed(self, msg: WordBoundary) -> None:
        """
        处理单词边界消息
        
        参数：
            msg: 必须包含offset/duration/text的字典
            
        异常：
            当消息类型错误时抛出ValueError
        """
        if msg["type"] != "WordBoundary":
            raise ValueError("需要WordBoundary类型消息")
            
        self.cues.append(
            srt.Subtitle(
                index=len(self.cues)+1,
                start=srt.timedelta(microseconds=msg["offset"]//10),
                end=srt.timedelta(microseconds=(msg["offset"]+msg["duration"])//10),
                content=msg["text"]
            )
        )

    def merge_cues(self) -> None:
        """
        合并相邻字幕块
        合并策略：每个字幕块最多包含MAX_WORDS_PER_CUE个单词
        """
        if not self.cues:
            return

        merged = []
        current = self.cues[0]
        
        for cue in self.cues[1:]:
            if len(current.content.split()) < MAX_WORDS_PER_CUE:
                current = srt.Subtitle(
                    index=current.index,
                    start=current.start,
                    end=cue.end,
                    content=f"{current.content} {cue.content}",
                )
            else:
                merged.append(current)
                current = cue
        merged.append(current)
        
        self.cues = merged

    def generate_srt(self) -> str:
        """生成SRT格式字符串"""
        return srt.compose(self.cues)

async def generate_audio():
    """音频生成主流程"""
    # 获取并预处理输入文本
    raw_text = text_input.get("1.0", tk.END).strip()
    processed_text = preprocess_text(raw_text)
    
    # 输入验证
    voice_index = voice_combobox.current()
    if not processed_text or voice_index < 0:
        messagebox.showerror("输入错误", "需要文本内容和有效语音选择")
        return

    # 文件保存对话框
    file_path = filedialog.asksaveasfilename(
        defaultextension=".mp3",
        filetypes=[("MP3文件", "*.mp3"), ("所有文件", "*.*")]
    )
    if not file_path:
        return

    try:
        # 初始化组件
        sub_maker = SubMaker()
        communicate = edge_tts.Communicate(processed_text, voices[voice_index][0])

        # 流式处理数据
        with open(file_path, 'wb') as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk['data'])
                elif chunk["type"] == "WordBoundary":
                    sub_maker.feed(chunk)

        # 生成字幕文件
        sub_maker.merge_cues()
        with open(file_path.replace('.mp3', '.srt'), 'w', encoding='utf-8') as f:
            f.write(sub_maker.generate_srt())

        messagebox.showinfo("成功", f"文件已生成：\n{file_path}")
    except Exception as e:
        messagebox.showerror("错误", f"生成失败：{str(e)}")

def start_generation():
    """启动生成任务前的UI准备"""
    generate_button.config(
        state=tk.DISABLED,
        bg=COLOR_CONFIG["DISABLED_BG"],
        fg=COLOR_CONFIG["DISABLED_FG"]
    )
    voice_combobox.config(state=tk.DISABLED)
    
    # 初始化进度条
    global progress_bar
    progress_bar = ttk.Progressbar(
        control_frame,
        mode='indeterminate',
        length=200
    )
    progress_bar.grid(row=0, column=3, padx=(20, 0))
    progress_bar.start(10)
    
    # 启动后台线程
    threading.Thread(target=async_wrapper).start()

def async_wrapper():
    """异步任务包装器"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_audio())
    except Exception as e:
        messagebox.showerror("线程错误", str(e))
    finally:
        root.after(0, reset_ui)

def reset_ui():
    """恢复UI状态"""
    global progress_bar
    if progress_bar:
        progress_bar.stop()
        progress_bar.destroy()
        progress_bar = None
    
    generate_button.config(
        state=tk.NORMAL,
        bg=COLOR_CONFIG["PRIMARY"],
        fg="white"
    )
    voice_combobox.config(state="readonly")

def resource_path(relative_path):
    """ 获取打包后的资源绝对路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# GUI初始化
root = tk.Tk()
root.title("Edge-TTS")
try:
    root.iconbitmap(resource_path("Edge-TTS_logo.ico"))
except Exception as e:
    print(f"图标加载失败: {str(e)}")
root.resizable(True, True)
root.minsize(320, 500)

# 文本输入框
text_input = tk.Text(
    root,
    height=25,
    width=90,
    borderwidth=2,
    relief="groove",
    insertbackground=COLOR_CONFIG["CURSOR"],
    font=("Arial", 11)
)
text_input.pack(fill=tk.BOTH, expand=True)

# 右键菜单
context_menu = tk.Menu(root, tearoff=0)
context_menu.add_command(label="Copy", command=lambda: text_input.event_generate("<<Copy>>"))
context_menu.add_command(label="Paste", command=lambda: text_input.event_generate("<<Paste>>"))
context_menu.add_command(label="Cut", command=lambda: text_input.event_generate("<<Cut>>"))
text_input.bind("<Button-3>", lambda e: context_menu.tk_popup(e.x_root, e.y_root))

# 控制面板
control_frame = tk.Frame(root, height=50)
control_frame.pack(pady=10, fill=tk.X)
control_frame.grid_columnconfigure(0, weight=1)
control_frame.grid_columnconfigure(4, weight=1)

# 语音选择
voices = asyncio.run(get_voices())
voice_combobox = ttk.Combobox(
    control_frame,
    values=[v[1] for v in voices],
    state="readonly",
    width=30
)
voice_combobox.grid(row=0, column=1, padx=(0, 20))
if voices:
    voice_combobox.current(0)

# 生成按钮
generate_button = tk.Button(
    control_frame,
    text="Gen",
    command=start_generation,
    bg=COLOR_CONFIG["PRIMARY"],
    fg="white",
    font=("Arial", 12, "bold")
)
generate_button.grid(row=0, column=2)

root.mainloop()