# 🧠 AXON & 🌐 OSIRIS

> **Next-Gen Autonomous AI Assistant with Interactive 3D World Intelligence** 🚀✨

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js 14+](https://img.shields.io/badge/next.js-14+-black.svg?logo=next.js&logoColor=white)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**AXON** is an autonomous personal AI agent designed for Windows with real-time reasoning, terminal command execution, and file/web tools. 
**OSIRIS** is its high-tech, futuristic 3D globe visualization frontend powered by **Next.js** and **MapLibre**.

Together, they provide a seamless, sci-fi caliber experience right on your desktop! 🌌🔮

---

## ✨ Features

- 🤖 **Autonomous Agent Brain**: Powered by advanced LLMs via OpenRouter with dynamic fallback key support.
- 💻 **Native Windows Control**: Execute terminal commands, manage running processes, and inspect files safely.
- 🌍 **Interactive 3D Globe (OSIRIS)**: Real-time geospatial data visualization and interactive map layer exploration.
- 💬 **Persistent Chat Sessions**: Auto-saves conversations locally with fast search and management.
- 🔌 **Extensible Tool Registry**: Effortlessly build and plug in your own custom Python tools.

---

## 📋 Prerequisites

Before starting, ensure you have the following installed on your system:

- 🐍 **Python 3.10+** (For the AXON AI Agent Backend)
- ⚡ **Node.js 18+** & **npm** (For the OSIRIS Frontend)
- 🔑 **OpenRouter API Key** ([Get your free or paid key here](https://openrouter.ai/keys))

---

## 🚀 Setup & Installation

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/ankit22222AXONIC/Axon.ai.git
cd Axon.ai
```

### 2️⃣ Configure Environment Variables 🔐
Create a `.env` file in the project root directory:
```bash
cp .env.example .env
```
Open `.env` in your favorite editor and paste your API key:
```env
OPENROUTER_API_KEY=sk-or-v1-YOUR-KEY-HERE
# (Optional) Add a secondary key to automatically fall back if the first runs out of credits:
# OPENROUTER_FALLBACK_API_KEY=sk-or-v1-YOUR-BACKUP-KEY-HERE
```

### 3️⃣ Install Python Dependencies 📦
Install the required packages for AXON:
```bash
pip install -r requirements.txt
```
*(If installing manually: `pip install requests pydantic psutil`)*

### 4️⃣ Install OSIRIS Frontend Dependencies 🌐
Navigate to the `osiris` directory and install the Node packages:
```bash
cd osiris
npm install
cd ..
```

---

## 🎮 Running the Application

To run the complete system, keep two terminals open:

### 🖥️ Terminal 1: Launch OSIRIS 3D Frontend
```bash
cd osiris
npm run dev
```
> 📍 *Running at: `http://localhost:3000`*

### 🧠 Terminal 2: Launch AXON AI Backend
```bash
# In the root Axon.ai directory:
python -m axon --web
```
> 📍 *Running at: `http://localhost:5000`*

---

## 🛸 Accessing the Interface

1. Open your browser and go to: **[http://localhost:5000](http://localhost:5000)** 🌐
2. Start chatting with **AXON**! 💬
3. Click **"Know the World"** to launch the futuristic **OSIRIS 3D Globe** embedded directly into the workspace! 🛰️🗺️

---

## 🛠️ Adding Custom Tools

AXON makes expanding agent capabilities as easy as writing a standard Python function:

1. Create your tool logic inside `axon/tools/`
2. Register it in `axon/core/runtime.py`:
   ```python
   reg.register(
       name="system.my_custom_tool",
       func=my_custom_tool,
       description="Briefly explain what your tool does so AXON knows when to use it."
   )
   ```
3. Restart AXON — your AI agent is now equipped with your custom superpower! ⚡🦸

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information. 📜

Made with ❤️ by [ankit22222AXONIC](https://github.com/ankit22222AXONIC) 🌟
