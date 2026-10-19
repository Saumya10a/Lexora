#!/usr/bin/env python3
"""Exercise AST analysis directly and through the running Lexora API."""

import sys

import httpx
from pydantic import ValidationError

from backend.models.schemas import ASTAnalysisResponse
from backend.services.ast_analyzer import ASTAnalyzer

API_URL = "http://127.0.0.1:8000/api/analyze"
SAMPLES = {
    "cpp": r'''#include <iostream>
#include <vector>
class Engine {
public:
    class Part { };
    int run(const std::vector<int>& values) {
        int total = 0;
        for (int value : values) {
            if (value > 0) total += value;
            else if (value == 0) total++;
        }
        int index = 0;
        while (index < 2) { total += index++; }
        do { total--; } while (total > 100);
        switch (total) {
            case 1: total++; break;
            case 2: total += 2; break;
            default: total = 0;
        }
        return total;
    }
};
int main() { Engine engine; return engine.run({1, 2, 3}); }
''',
    "java": r'''import java.util.List;
class Catalog {
    private static class Entry { }
    int sum(List<Integer> values) {
        int total = 0;
        for (int value : values) {
            if (value > 0) total += value;
            else total--;
        }
        int i = 0;
        while (i < 2) { i++; }
        switch (total) {
            case 1: total++;
            case 2: total += 2; break;
            default: total = 0;
        }
        return total;
    }
}
''',
    "python": r'''class Counter:
    def total(self, values):
        result = 0
        for value in values:
            if value > 0:
                result += value
            elif value == 0:
                result += 1
        while result < 3:
            result += 1
        return result

def main():
    return Counter().total([1, 0, -1])
''',
}


def show_result(result: ASTAnalysisResponse, source: str) -> None:
    metrics = result.metrics
    print("=" * 70)
    print("LEXORA AST CODE ANALYSIS RESULTS")
    print("=" * 70)
    print(f"Language Parsed       : {result.language}")
    print(f"Total Lines of Code   : {metrics.total_lines_of_code}")
    print(f"Functions Identified  : {metrics.function_count}")
    print(f"Classes Identified    : {metrics.class_count}")
    print(f"Loops (For/While)     : {metrics.loop_count}")
    print(f"Conditionals          : {metrics.conditional_count}")
    print(
        "Cyclomatic Complexity : "
        f"{metrics.cyclomatic_complexity} (Rating: {metrics.complexity_rating})"
    )
    print("=" * 70)


def main() -> int:
    analyzer = ASTAnalyzer()
    failed = False
    try:
        with httpx.Client(timeout=10.0) as client:
            for language, source in SAMPLES.items():
                direct = analyzer.parse_code(source, language)
                expected = direct.metrics.loop_count + direct.metrics.conditional_count + 1
                if direct.metrics.cyclomatic_complexity != expected:
                    raise AssertionError(f"Incorrect complexity calculation for {language}")
                show_result(direct, source)
                try:
                    response = client.post(
                        API_URL,
                        json={"source_code": source, "language": language},
                    )
                    response.raise_for_status()
                    via_api = ASTAnalysisResponse.model_validate(response.json())
                    if via_api.metrics != direct.metrics:
                        raise AssertionError(f"Direct and API metrics differ for {language}")
                    print(f"HTTP API             : PASS ({response.status_code})\n")
                except (httpx.HTTPError, ValidationError, AssertionError) as exc:
                    print(f"HTTP API             : FAIL ({exc})\n")
                    failed = True
    except httpx.RequestError as exc:
        print(f"[FAIL] Could not connect to {API_URL}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[FAIL] AST analysis failed: {exc}", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
