#!/usr/bin/env python3
"""Check migration rule retrieval and local LoRA adapter inference."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ADAPTER_PATH = PROJECT_ROOT / "models" / "lexora-lora-adapter"


def main() -> int:
    print("LEXORA RAG & FINE-TUNED MODEL VERIFICATION")
    try:
        from backend.services.rag_service import RAGMigrationEngine
    except ModuleNotFoundError as exc:
        print(f"ChromaDB Status          : OFFLINE (missing dependency: {exc.name})")
        print("Retrieved Rules Count    : 0")
        print("Top Match Rule           : NONE")
        print("Fine-Tuned Adapter Status: NOT CHECKED")
        print("Local HF Inference Test  : SKIPPED")
        return 1

    try:
        rag = RAGMigrationEngine()
        count = rag.seed_rules_if_empty()
        matches = rag.retrieve_migration_rules(
            "C++ code declares a std::vector of integers and iterates through it",
            "cpp",
            "python",
            top_k=3,
        )
    except Exception as exc:
        print(f"ChromaDB Status          : ERROR ({type(exc).__name__}: {exc})")
        print("Retrieved Rules Count    : 0")
        print("Top Match Rule           : NONE")
        print("Fine-Tuned Adapter Status: NOT CHECKED")
        print("Local HF Inference Test  : SKIPPED")
        return 1
    print(f"ChromaDB Status          : ONLINE (Collection: {rag.collection_name})")
    print(f"Retrieved Rules Count    : {len(matches)}")
    if matches:
        top = matches[0]
        print(f"Top Match Rule           : {top['source_pattern']} -> {top['target_pattern']}")
        for index, rule in enumerate(matches, start=1):
            print(
                f"  {index}. {rule['source_pattern']} -> {rule['target_pattern']} "
                f"(distance: {rule['distance']:.4f})"
            )
    else:
        print("Top Match Rule           : NONE")

    try:
        from backend.services.finetune_service import LocalFineTunedModelInference

        inference = LocalFineTunedModelInference()
        print(f"Fine-Tuned Adapter Status: LOADED ({ADAPTER_PATH.relative_to(ADAPTER_PATH.parents[1])})")
        generated = inference.generate_translation(
            "Translate this C++ code to Python: int add(int a, int b) { return a + b; }"
        )
        ast.parse(generated)
        print("Local HF Inference Test  : SUCCESS (Generated valid target code)")
        expected_top = bool(matches) and matches[0]["rule_id"] == "cpp_vector_to_python_list"
        return 0 if count >= 3 and len(matches) == 3 and expected_top else 1
    except FileNotFoundError as exc:
        print(f"Fine-Tuned Adapter Status: NOT AVAILABLE ({exc})")
        print("Local HF Inference Test  : SKIPPED")
        return 1
    except Exception as exc:
        print(f"Fine-Tuned Adapter Status: ERROR ({type(exc).__name__}: {exc})")
        print("Local HF Inference Test  : FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
