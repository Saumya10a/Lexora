"""Local inference using the Lexora PEFT adapter, when it has been trained."""

from __future__ import annotations

import re
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
        fenced = re.fullmatch(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        return fenced.group(1).strip() if fenced else text

    def generate_translation(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        messages = [
            {"role": "system", "content": "Translate the given code to idiomatic Python 3. Return only valid Python code."},
            {"role": "user", "content": prompt},
        ]
        rendered = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(rendered, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0, inputs["input_ids"].shape[1] :]
        return self._clean_code(
            self.tokenizer.decode(generated, skip_special_tokens=True)
        )
