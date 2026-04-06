#!/usr/bin/env python3
"""
JARVIS CLI chat — stream responses from the local Ollama LLM.
Usage: uv run python ~/scripts/jarvis-chat.py

Type 'quit' or press Ctrl-D to exit.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from llm_client import LLMClient


def main() -> None:
    client = LLMClient()
    client.prewarm()
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError, KeyboardInterrupt:
            print("\n[JARVIS] Goodbye.")
            break
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "bye"}:
            print("[JARVIS] Goodbye.")
            break
        print("JARVIS: ", end="", flush=True)
        for token in client.stream(user_input):
            print(token, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
