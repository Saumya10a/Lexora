#!/usr/bin/env python3
"""Fine-tune a Qwen coder model with LoRA on Lexora translation examples."""

from __future__ import annotations

import os
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "backend" / "data" / "finetune_dataset.json"
OUTPUT_PATH = ROOT / "models" / "lexora-lora-adapter"
BASE_MODEL = os.environ.get("LEXORA_BASE_MODEL", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
MAX_LENGTH = 1024


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    if torch.cuda.is_available():
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    peft_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    dataset = Dataset.from_json(str(DATASET_PATH))

    def encode_example(example: dict[str, str]) -> dict[str, list[int]]:
        user_content = f"{example['instruction']}\n\n{example['input']}"
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": user_content}],
            tokenize=False,
            add_generation_prompt=True,
        )
        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        answer_ids = tokenizer(example["output"] + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
        input_ids = (prompt_ids + answer_ids)[:MAX_LENGTH]
        labels = ([-100] * len(prompt_ids) + answer_ids)[:MAX_LENGTH]
        return {
            "input_ids": input_ids,
            "attention_mask": [1] * len(input_ids),
            "labels": labels,
        }

    tokenized = dataset.map(encode_example, remove_columns=dataset.column_names)
    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=model,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )
    args = TrainingArguments(
        output_dir=str(ROOT / "outputs" / "lora-training"),
        num_train_epochs=4,
        per_device_train_batch_size=2,
        learning_rate=2e-4,
        logging_steps=1,
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        fp16=torch.cuda.is_available(),
        gradient_checkpointing=torch.cuda.is_available(),
        optim="adamw_torch",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        data_collator=collator,
        tokenizer=tokenizer,
    )
    trainer.train()
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUTPUT_PATH))
    tokenizer.save_pretrained(str(OUTPUT_PATH))
    print(f"LoRA adapter and tokenizer saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
