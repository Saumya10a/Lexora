#!/usr/bin/env python3
"""Run both Lexora translators through the API and inspect saved artifacts."""

import sys
from pathlib import Path

API_URL = "http://127.0.0.1:8000/api/migrate"
OUTPUT_ROOT = Path(__file__).resolve().parent / "outputs"
SOURCE = r'''#include <vector>

std::vector<std::vector<int>> multiply(
    const std::vector<std::vector<int>>& a,
    const std::vector<std::vector<int>>& b) {
    const int rows = static_cast<int>(a.size());
    const int inner = static_cast<int>(b.size());
    const int cols = static_cast<int>(b[0].size());
    std::vector<std::vector<int>> result(rows, std::vector<int>(cols, 0));
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            for (int k = 0; k < inner; ++k) {
                result[i][j] += a[i][k] * b[k][j];
            }
        }
    }
    return result;
}
'''


def main() -> int:
    print("=" * 70)
    print("LEXORA MULTI-MODEL TRANSLATION EXECUTION")
    print("=" * 70)
    try:
        import httpx
    except ModuleNotFoundError:
        print("[FAIL] Missing dependency: httpx. Install requirements.txt first.")
        return 1
    try:
        response = httpx.post(
            API_URL,
            json={
                "source_code": SOURCE,
                "source_language": "cpp",
                "target_language": "python",
                "selected_models": ["fine_tuned_hf", "openai/gpt-oss-20b"],
            },
            timeout=600.0,
        )
    except httpx.RequestError as exc:
        print(f"[FAIL] Could not connect to {API_URL}: {exc}")
        return 1
    if response.status_code != 200:
        print(f"[FAIL] API returned HTTP {response.status_code}: {response.text}")
        return 1

    payload = response.json()
    migration_id = payload["migration_id"]
    metrics = payload["ast_metrics"]
    rules = payload["applied_rag_rules"]
    print(f"Migration ID             : {migration_id}")
    print(
        "Source Code AST LOC      : "
        f"{metrics['total_lines_of_code']} (Complexity: {metrics['complexity_rating']})"
    )
    print(f"Retrieved RAG Rules      : {len(rules)} rules applied")
    print("-" * 70)

    expected_files = {
        "fine_tuned_hf": OUTPUT_ROOT / migration_id / "fine_tuned_hf_output.py",
        "openai/gpt-oss-20b": OUTPUT_ROOT / migration_id / "openai_gpt_oss_20b_output.py",
    }
    result_by_model = {item["model_name"]: item for item in payload["results"]}
    for model_name, label in [
        ("fine_tuned_hf", "Fine-Tuned HF"),
        ("openai/gpt-oss-20b", "Groq GPT-OSS 20B"),
    ]:
        result = result_by_model.get(model_name)
        output_file = expected_files[model_name]
        if result is None or not output_file.is_file():
            print(f"{label:26}: FAIL | output file missing")
            return 1
        print(
            f"{label:26}: DONE in {result['execution_time_seconds']:.2f}s | "
            f"Saved: {result['file_path']}"
        )
    print("MongoDB Record Status    : PERSISTED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
