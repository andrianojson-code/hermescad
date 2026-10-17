"""Safe expression evaluation for HermesCAD part specs.

Values in a spec may be numbers or strings such as "L/2 - 8" or "sqrt(W^2 + H^2)".
Names refer to spec parameters. Trigonometric functions use DEGREES, exactly like
FreeCAD expressions, so the same string evaluates identically here and inside
FreeCAD once it is bound to a property.
"""
import ast
import math
import re

_DEG = math.pi / 180.0

FUNCS = {
    "sin": lambda a: math.sin(a * _DEG),
    "cos": lambda a: math.cos(a * _DEG),
    "tan": lambda a: math.tan(a * _DEG),
    "asin": lambda v: math.asin(v) / _DEG,
    "acos": lambda v: math.acos(v) / _DEG,
    "atan": lambda v: math.atan(v) / _DEG,
    "atan2": lambda y, x: math.atan2(y, x) / _DEG,
    "sqrt": math.sqrt,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "hypot": math.hypot,
}
CONSTS = {"pi": math.pi, "e": math.e}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CELL_LIKE = re.compile(r"^[A-Za-z]{1,3}[0-9]+$")
# Names FreeCAD's expression engine treats specially (units, constants, functions).
_RESERVED = set(FUNCS) | set(CONSTS) | {
    "mm", "m", "cm", "km", "um", "nm", "in", "ft", "yd", "mi", "thou", "mil",
    "deg", "rad", "gon", "s", "min", "h", "g", "kg", "t", "N", "Pa", "W", "J", "V", "A",
    "K", "l", "ml", "mol", "cd", "Hz", "C", "F", "S", "T", "Wb", "H", "lb", "oz",
    "M", "G", "ms", "us", "x", "y", "z", "true", "false", "None",
}


class ExprError(ValueError):
    pass


def _to_python(src):
    # FreeCAD uses ^ for power; Python uses **.
    return src.replace("^", "**")


def _to_freecad(src):
    return src.replace("**", "^")


def names_in(src):
    """Identifiers used as variables (not function calls) in an expression string."""
    try:
        tree = ast.parse(_to_python(str(src)), mode="eval")
    except SyntaxError as exc:
        raise ExprError("bad expression %r: %s" % (src, exc.msg))
    calls = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - calls


def evaluate(src, params):
    if isinstance(src, bool):
        raise ExprError("boolean is not a number: %r" % (src,))
    if isinstance(src, (int, float)):
        return float(src)
    text = _to_python(str(src).strip())
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExprError("bad expression %r: %s" % (src, exc.msg))

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in params:
                return float(params[node.id])
            if node.id in CONSTS:
                return CONSTS[node.id]
            raise ExprError("unknown parameter %r in %r (known: %s)"
                            % (node.id, src, ", ".join(sorted(params)) or "none"))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return a + b
            if isinstance(op, ast.Sub):
                return a - b
            if isinstance(op, ast.Mult):
                return a * b
            if isinstance(op, ast.Div):
                if b == 0:
                    raise ExprError("division by zero in %r" % (src,))
                return a / b
            if isinstance(op, ast.Pow):
                return a ** b
            if isinstance(op, ast.Mod):
                return a % b
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FUNCS and not node.keywords:
            return float(FUNCS[node.func.id](*[ev(a) for a in node.args]))
        raise ExprError("unsupported syntax in %r" % (src,))

    return ev(tree)


def alias_for(name):
    """Spreadsheet alias for a parameter name (cell-like or reserved names get a p_ prefix)."""
    if not _IDENT.fullmatch(name):
        raise ExprError("parameter name %r must be an identifier (letters, digits, _)" % name)
    if _CELL_LIKE.match(name) or name in _RESERVED:
        return "p_" + name
    return name


def to_freecad_expr(src, params, sheet_name):
    """Rewrite a spec expression into a FreeCAD expression bound to the Params sheet."""
    used = names_in(src)
    unknown = used - set(params) - set(CONSTS)
    if unknown:
        raise ExprError("unknown parameter(s) %s in %r" % (", ".join(sorted(unknown)), src))
    py = _to_python(str(src))

    def repl(m):
        word = m.group(0)
        # leave function names (followed by '(') untouched
        tail = py[m.end():].lstrip()
        if word in params and not tail.startswith("("):
            return "%s.%s" % (sheet_name, alias_for(word))
        return word

    return _to_freecad(_IDENT.sub(repl, py))
