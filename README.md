# :radio: GUI-of-Edge-TTS
- 开源项目 :link:https://github.com/rany2/edge-tts 的可视化用户界面。

<br>

- A graphical user interface (GUI) implementation for the open-source Edge Text-to-Speech project: :link:https://github.com/rany2/edge-tts 

<div align="center">

![GUI-of-Edge-TTS 概览](https://raw.githubusercontent.com/Neus117/GUI-of-Edge-TTS/main/images/GUI-of-Edge-TTS_preview.png)

</div>

## :earth_asia: 功能 | Features
- 文字转语音。我用来练习口语的。

<br>

- Text-to-Speech. I use it to practice my spoken English.

<br><br>

## :bulb: 使用说明 | How to Use
- 在 Releases 中下载并运行 `GUI-of-Edge-TTS.exe` 即可使用。

<br>

- Download and run `GUI-of-Edge-TTS.exe` from the Releases section to start using the program.

<br><br>

## 依赖 | Dependencies
- Python 3.12
- 请参考 `environment.yml`

<br>

- Python 3.12
- Please refer to `environment.yml`

<br><br>

## 开发者安装 | Developer Installation
1. 克隆此仓库 | Clone this repository
   ```bash
   git clone https://github.com/yourusername/GUI-of-Edge-TTS.git
2. 安装依赖 | Install the required dependencies
   ```bash
   conda env create -f environment.yml -p "Your path\edge-tts-env"
   conda activate "Your path\edge-tts-env"
3. 打包 | Package the application
   ```bash
   pyinstaller --onefile --windowed --icon="Your path\Edge-TTS_logo.ico" --add-data="Edge-TTS_logo.ico;." --version-file="Your path\version.txt" "Your path\GUI-of-Edge-TTS.py"
