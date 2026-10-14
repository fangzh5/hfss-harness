"""Small, validated expression language for numerical parameter constraints."""

import ast
import math
import operator
import re


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: operator.pow}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
            ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


class Constraint:
    """Compile once, match whole names, and never execute arbitrary Python."""

    def __init__(self, expression: str, names: list[str]):
        self.expression = expression
        # AEDT project variables start with '$', which Python identifiers cannot.
        self.aliases = {}
        for i, name in enumerate(names):
            if name.startswith("$"):
                alias = f"__project_{i}"
                while alias in names or alias in self.aliases.values():
                    alias += "_"
                self.aliases[name] = alias
        allowed = set(names) - self.aliases.keys() | set(self.aliases.values())
        normalized = re.sub(r"\$[A-Za-z_]\w*", lambda m: self.aliases.get(m[0], m[0]), expression)
        try:
            self.tree = ast.parse(normalized, mode="eval").body
            self._validate(self.tree, allowed)
            if not self._boolean(self.tree):
                raise ValueError("constraint must be a comparison or boolean expression")
        except (SyntaxError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid constraint {expression!r}: {exc}") from exc

    @staticmethod
    def _boolean(node):
        return isinstance(node, (ast.Compare, ast.BoolOp)) or (
            isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not))

    def _validate(self, node, names):
        if isinstance(node, ast.Constant):
            if type(node.value) not in (float, int) or not math.isfinite(float(node.value)):
                raise ValueError("only finite numerical constants are supported")
        elif isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"unknown parameter {node.id!r}")
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            self._validate(node.left, names)
            self._validate(node.right, names)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            self._validate(node.operand, names)
            if isinstance(node.op, ast.Not) and not self._boolean(node.operand):
                raise ValueError("not requires a boolean expression")
        elif isinstance(node, ast.Compare) and all(type(op) in _COMPARE for op in node.ops):
            self._validate(node.left, names)
            for child in node.comparators:
                self._validate(child, names)
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for child in node.values:
                self._validate(child, names)
                if not self._boolean(child):
                    raise ValueError("and/or require boolean expressions")
        else:
            raise ValueError(f"unsupported syntax: {type(node).__name__}")

    def evaluate(self, values: dict[str, float]) -> bool:
        try:
            context = {self.aliases.get(name, name): float(value) for name, value in values.items()}
            if not all(math.isfinite(value) for value in context.values()):
                return False
            return bool(self._evaluate(self.tree, context))
        except (ArithmeticError, ValueError, TypeError, KeyError):
            return False

    def _evaluate(self, node, context):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return context[node.id]
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate(node.operand, context)
            return not value if isinstance(node.op, ast.Not) else (
                -value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            result = _BINARY[type(node.op)](self._evaluate(node.left, context),
                                          self._evaluate(node.right, context))
            if not math.isfinite(result):
                raise ValueError("nonfinite constraint arithmetic")
            return result
        if isinstance(node, ast.BoolOp):
            values = (self._evaluate(child, context) for child in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        left = self._evaluate(node.left, context)
        for op, child in zip(node.ops, node.comparators):
            right = self._evaluate(child, context)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
