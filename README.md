# AXON & OSIRIS

AXON is an autonomous personal AI agent for Windows. OSIRIS is its dynamic, modern 3D globe visualization frontend built with Next.js and MapLibre.

Together, they form a powerful local AI assistant capable of reasoning, executing local terminal commands, browsing the web, and visualizing global data in a stunning interface.

## Prerequisites

- **Python 3.10+** (For the AXON AI Backend)
- **Node.js 18+** (For the OSIRIS Frontend)
- **OpenRouter API Key** (For the AI Models)

## Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/ankit22222AXONIC/Axon.ai.git
cd Axon.ai
```

### 2. Configure Environment Variables
Create a new file named `.env` in the root directory (the same folder as `axon` and `osiris`).
You can use the provided template:
```bash
cp .env.example .env
```
Open `.env` and paste your OpenRouter API Key:
```env
OPENROUTER_API_KEY=sk-or-v1-YOUR-KEY-HERE
# (Optional) You can also add OPENROUTER_FALLBACK_API_KEY for a backup key!
```

### 3. Install Python Dependencies
The backend runs using standard Python libraries, plus a few AI and system automation packages.
*(Note: If you have a `requirements.txt`, run `pip install -r requirements.txt`. Otherwise, ensure packages like `requests`, `pydantic`, `psutil` are installed.)*

### 4. Install OSIRIS Frontend Dependencies
Navigate into the OSIRIS directory and install the required Node packages:
```bash
cd osiris
npm install
```

---

## Running the Application

To run the full suite, you need to start **both** the AXON backend and the OSIRIS frontend at the same time.

### Step 1: Start the OSIRIS Frontend (Terminal 1)
Open a terminal, go to the `osiris` folder, and start the development server:
```bash
cd osiris
npm run dev
```
*(This will start OSIRIS on `http://localhost:3000`)*

### Step 2: Start the AXON Backend (Terminal 2)
Open a new terminal, go to the main `Axon.ai` folder, and start the web interface:
```bash
# From the root directory:
python -m axon --web
```
*(This will start the AXON backend on `http://localhost:5000`)*

### Step 3: Access the Interface
Open your web browser and navigate to:
**`http://localhost:5000`**

You will see the main AXON chat interface. When you trigger the globe visualization (e.g., clicking "Know the World"), the OSIRIS frontend will dynamically load inside the interface!

---

## Adding Custom Tools
AXON's Brain allows you to easily register custom tools.
1. Create your python function in `axon/tools/`
2. Register it in `axon/core/runtime.py` using `reg.register("my.tool", my_tool, "Description")`
3. The AI agent will automatically become aware of your new tool!
