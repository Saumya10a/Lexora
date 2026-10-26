"""Local inference using the Lexora PEFT adapter, when it has been trained."""

from __future__ import annotations

import re
import os
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
ADAPTER_PATH = PROJECT_ROOT / "models" / "lexora-lora-adapter"


class LocalFineTunedModelInference:
    def __init__(self, adapter_path: str | Path = ADAPTER_PATH) -> None:
        self.adapter_path = Path(adapter_path)
        if not self.adapter_path.is_dir() or not (self.adapter_path / "adapter_config.json").exists():
            raise FileNotFoundError(
                f"Fine-tuned adapter not found at {self.adapter_path}. Run train_lora.py first."
            )

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(self.adapter_path)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
            low_cpu_mem_usage=True,
        )
        self.model = PeftModel.from_pretrained(base_model, str(self.adapter_path))
        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def _clean_code(text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)\n```", text, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
        fenced = re.fullmatch(r"```[^\n]*\n(.*?)\n```", text, flags=re.DOTALL)
        return fenced.group(1).strip() if fenced else text

    def generate_translation(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        system_content = (
            "You are Lexora, an expert automated code migration model. "
            "Follow the target language, framework, and required output path specified in the user's instructions.\n"
            "CRITICAL ARCHITECTURE RULES:\n"
            "- When targeting Spring Boot (Java): Output ONLY Spring Boot server-side code (@Component, @Service, @RestController, @Repository, or POJO). NEVER import or extend android.*, androidx.*, or Activity.\n"
            "- When targeting Go Fiber (Go): Output ONLY idiomatic Go packages, structs, and Fiber route handlers.\n"
            "- Map the source file's specific data structures, functions, constants, and state faithfully.\n"
            "- Do not repeat generic boilerplate across different files. The class/package name must match the target file.\n"
            "- Return ONLY the complete target file code without markdown or explanations."
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]
        rendered = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(rendered, return_tensors="pt", max_length=2048, truncation=True).to(self.device)
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=int(os.environ.get("LEXORA_LOCAL_MAX_NEW_TOKENS", "1024")),
                do_sample=False,
                repetition_penalty=1.15,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0, inputs["input_ids"].shape[1] :]
        return self._clean_code(
            self.tokenizer.decode(generated, skip_special_tokens=True)
        )
