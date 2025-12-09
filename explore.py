from dotenv import load_dotenv
import os
import platform

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
POPPLER_PATH = os.getenv("POPPLER_PATH")

IS_WINDOWS = os.name == "nt" or platform.system().lower() == "windows"
print(f"Running on Windows: {IS_WINDOWS}")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set in environment variables.")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment variables.")
if not POPPLER_PATH and IS_WINDOWS:
    raise ValueError("POPPLER_PATH is not set in environment variables. This is required for Windows systems.")



