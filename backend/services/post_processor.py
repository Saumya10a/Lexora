"""Add a conservative executable entry point to translated Python scripts."""

from __future__ import annotations

import ast
import re


class ExecutionBlockInjector(ast.NodeTransformer):
    """Inject a guarded entry point when a translated module has none.

    `main` functions and common class entry methods (`main`, `run`, `execute`,
    `solve`) are preferred. For simple demonstration classes, a public
    zero-argument method may be used as a last resort. The source is always
    reparsed and unparsed so the compiler runs valid, normalized Python.
    """

    ENTRY_METHODS = ("main", "run", "execute", "solve")

    def __init__(self) -> None:
        self.injected = False

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self.generic_visit(node)
        if any(self._is_main_guard(statement) for statement in node.body):
            return node

        functions = [
            statement
            for statement in node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        classes = [statement for statement in node.body if isinstance(statement, ast.ClassDef)]

        invocation: list[ast.stmt] | None = None
        main_function = next((func for func in functions if func.name == "main"), None)
        if main_function is not None:
            invocation = self._invoke_function(main_function)

        if invocation is None:
            for class_node in classes:
                invocation = self._invoke_class(class_node)
                if invocation is not None:
                    break

        if invocation is None:
            function = next((func for func in functions if self._takes_no_required_arguments(func.args)), None)
            if function is not None:
                invocation = self._invoke_function(function)

        if invocation is None:
            return node

        node.body.append(
            ast.If(
                test=ast.Compare(
                    left=ast.Name(id="__name__", ctx=ast.Load()),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value="__main__")],
                ),
                body=invocation,
                orelse=[],
            )
        )
        self.injected = True
        return ast.fix_missing_locations(node)

    @classmethod
    def process(cls, source_code: str) -> str:
        """Parse, inject if needed, and return normalized source code."""
        tree = ast.parse(source_code)
        tree = cls().visit(tree)
        return ast.unparse(ast.fix_missing_locations(tree)) + "\n"

    @classmethod
    def _invoke_function(cls, function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt] | None:
        if cls._takes_no_required_arguments(function.args):
            call = ast.Call(func=ast.Name(id=function.name, ctx=ast.Load()), args=[], keywords=[])
            return cls._guarded_call(call, isinstance(function, ast.AsyncFunctionDef))
        return None

    @classmethod
    def _invoke_class(cls, class_node: ast.ClassDef) -> list[ast.stmt] | None:
        instance_name = cls._instance_name(class_node.name)
        instantiate = ast.Assign(
            targets=[ast.Name(id=instance_name, ctx=ast.Store())],
            value=ast.Call(func=ast.Name(id=class_node.name, ctx=ast.Load()), args=[], keywords=[]),
        )
        methods = [
            statement for statement in class_node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name not in {"__init__", "__new__", "__str__", "__repr__"}
        ]
        for preferred in cls.ENTRY_METHODS:
            method = next((candidate for candidate in methods if candidate.name == preferred), None)
            if method is not None and cls._takes_no_required_arguments(method.args, drop_self=True):
                call = ast.Call(
                    func=ast.Attribute(value=ast.Name(id=instance_name, ctx=ast.Load()), attr=method.name, ctx=ast.Load()),
                    args=[], keywords=[],
                )
                return [instantiate, *cls._guarded_call(call, isinstance(method, ast.AsyncFunctionDef))]

        method = next(
            (candidate for candidate in methods if cls._takes_no_required_arguments(candidate.args, drop_self=True)),
            None,
        )
        if method is not None:
            call = ast.Call(
                func=ast.Attribute(value=ast.Name(id=instance_name, ctx=ast.Load()), attr=method.name, ctx=ast.Load()),
                args=[], keywords=[],
            )
            return [instantiate, *cls._guarded_call(call, isinstance(method, ast.AsyncFunctionDef))]
        # Instantiating a data class can itself perform useful setup or output.
        # Any absent output is handled by the compiler's silent-execution guard.
        return [instantiate]

    @staticmethod
    def _guarded_call(call: ast.Call, is_async: bool) -> list[ast.stmt]:
        if is_async:
            call = ast.Call(
                func=ast.Attribute(value=ast.Name(id="asyncio", ctx=ast.Load()), attr="run", ctx=ast.Load()),
                args=[call], keywords=[],
            )
            return [ast.Import(names=[ast.alias(name="asyncio")]), ast.Expr(value=call)]
        return [ast.Expr(value=call)]

    @staticmethod
    def _takes_no_required_arguments(
        arguments: ast.arguments, *, drop_self: bool = False
    ) -> bool:
        positional = list(arguments.posonlyargs) + list(arguments.args)
        if drop_self and positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        required_positional = len(positional) - len(arguments.defaults)
        required_keyword_only = sum(
            default is None for default in arguments.kw_defaults
        )
        return required_positional <= 0 and required_keyword_only == 0

    @staticmethod
    def _is_main_guard(statement: ast.stmt) -> bool:
        if not isinstance(statement, ast.If):
            return False
        try:
            return ast.dump(statement.test, include_attributes=False) == ast.dump(
                ast.parse("__name__ == '__main__'", mode="eval").body,
                include_attributes=False,
            )
        except (SyntaxError, ValueError):
            return False

    @staticmethod
    def _instance_name(class_name: str) -> str:
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        return snake or "instance"
