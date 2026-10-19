"""Tree-sitter based structural source analysis for supported languages."""

from __future__ import annotations

from functools import lru_cache

from tree_sitter import Node
from tree_sitter_languages import get_parser

from backend.models.schemas import ASTAnalysisResponse, ASTMetrics

SUPPORTED_LANGUAGES = {"cpp", "java", "python"}
TREE_STRING_LIMIT = 4000


class AnalysisSyntaxError(ValueError):
    """Raised when Tree-sitter detects syntax errors in the supplied source."""


def _complexity_rating(value: int) -> str:
    if value <= 5:
        return "LOW"
    if value <= 10:
        return "MEDIUM"
    return "HIGH"


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _parser_for(language: str):
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    return get_parser(language)


class ASTAnalyzer:
    """Parse source and return node-based counts and decision complexity."""

    def parse_code(self, source_code: str, language: str) -> ASTAnalysisResponse:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError("source_code must be a non-empty string")

        source_bytes = source_code.encode("utf-8")
        tree = _parser_for(language).parse(source_bytes)
        root = tree.root_node
        if root.has_error:
            error_node = self._first_error(root)
            location = f"line {error_node.start_point.row + 1}" if error_node else "unknown location"
            raise AnalysisSyntaxError(f"Unable to parse {language} source near {location}")

        function_nodes = {
            "cpp": {"function_definition"},
            "java": {"method_declaration", "constructor_declaration"},
            "python": {"function_definition"},
        }[language]
        class_nodes = {
            "cpp": {"class_specifier", "struct_specifier"},
            "java": {"class_declaration"},
            "python": {"class_definition"},
        }[language]
        loop_nodes = {
            "cpp": {"for_statement", "while_statement", "do_statement"},
            "java": {"for_statement", "enhanced_for_statement", "while_statement", "do_statement"},
            "python": {"for_statement", "while_statement"},
        }[language]
        conditional_nodes = {
            "cpp": {"if_statement", "case_statement"},
            "java": {"if_statement", "switch_label"},
            "python": {"if_statement", "elif_clause"},
        }[language]

        function_count = 0
        class_count = 0
        loop_count = 0
        conditional_count = 0
        stack = [root]
        while stack:
            node = stack.pop()
            kind = node.type
            function_count += kind in function_nodes
            class_count += kind in class_nodes
            loop_count += kind in loop_nodes
            if kind in conditional_nodes and not self._is_default_label(node, language):
                conditional_count += 1
            stack.extend(reversed(node.children))

        complexity = loop_count + conditional_count + 1
        loc = sum(1 for line in source_code.splitlines() if line.strip())
        tree_text = root.sexp()
        if len(tree_text) > TREE_STRING_LIMIT:
            tree_text = tree_text[:TREE_STRING_LIMIT] + "... [truncated]"

        return ASTAnalysisResponse(
            language=language,
            metrics=ASTMetrics(
                total_lines_of_code=loc,
                function_count=function_count,
                class_count=class_count,
                loop_count=loop_count,
                conditional_count=conditional_count,
                cyclomatic_complexity=complexity,
                complexity_rating=_complexity_rating(complexity),
            ),
            ast_tree_string=tree_text,
        )

    @staticmethod
    def _is_default_label(node: Node, language: str) -> bool:
        if language == "cpp" and node.type == "case_statement":
            return node.text.lstrip().startswith(b"default")
        if language == "java" and node.type == "switch_label":
            return node.text.lstrip().startswith(b"default")
        return False

    @staticmethod
    def _first_error(root: Node) -> Node | None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.is_error or node.is_missing:
                return node
            stack.extend(reversed(node.children))
        return None
