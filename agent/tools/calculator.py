"""Safe arithmetic. Parses the expression into a syntax tree and only allows numbers and + - * / ** % ( ).
Never uses eval(), which would run any Python code."""
import ast
import operator

from agent.tools.base import Tool, ToolResult

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError(f"not allowed: {type(node).__name__}")


class Calculator(Tool):
    name = "calculator"
    description = "Evaluate a pure arithmetic expression, e.g. '(12 + 3) / 5'. No variables or functions."
    schema = {"expression": {"type": "string", "required": True}}

    def run(self, expression: str) -> ToolResult:
        if len(expression) > 200:
            return ToolResult(ok=False, output="", error="expression too long")
        try:
            value = _eval(ast.parse(expression, mode="eval"))
            return ToolResult(ok=True, output=str(round(value, 6)))
        except ZeroDivisionError:
            return ToolResult(ok=False, output="", error="division by zero")
        except (ValueError, SyntaxError) as e:
            return ToolResult(ok=False, output="", error=f"rejected: {e}")
