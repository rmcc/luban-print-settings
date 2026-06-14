#!/usr/bin/env python3
import sys
import re
import ast
import json
import argparse

class ConvertPythonToJS(ast.NodeVisitor):
    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_BinOp(self, node):
        ops = {
            ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
            ast.FloorDiv: '/', ast.Mod: '%'
        }
        return f"({self.visit(node.left)} {ops[type(node.op)]} {self.visit(node.right)})"

    def visit_UnaryOp(self, node):
        ops = {ast.USub: '-', ast.UAdd: '+', ast.Not: '!'}
        op_str = ops[type(node.op)]
        operand_str = self.visit(node.operand)

        # If the inner content is just a simple digit, number, or variable name,
        # do not wrap it in redundant parentheses.
        if isinstance(node.operand, (ast.Constant, ast.Name)):
            return f"{op_str}{operand_str}"

        # Keep parentheses only for complex expressions like -(layer_height * 2)
        return f"{op_str}({operand_str})"

    def visit_Compare(self, node):
        left = self.visit(node.left)

        op = node.ops[0]
        right = self.visit(node.comparators[0])

        if isinstance(op, ast.In):
            return f"{right}.includes({left})"
        if isinstance(op, ast.NotIn):
            return f"!{right}.includes({left})"

        ops = {
            ast.Eq: '===', ast.NotEq: '!==',
            ast.Lt: '<', ast.LtE: '<=', ast.Gt: '>', ast.GtE: '>='
        }
        js_op = ops.get(type(op), '===')
        return f"({left} {js_op} {right})"

    def visit_BoolOp(self, node):
        op = ' && ' if isinstance(node.op, ast.And) else ' || '
        values = [self.visit(val) for val in node.values]
        return f"({op.join(values)})"

    def visit_IfExp(self, node):
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return f"({test} ? {body} : {orelse})"

    def visit_Name(self, node):
        mapping = {'True': 'true', 'False': 'false', 'None': 'null'}
        return mapping.get(node.id, node.id)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            escaped_str = node.value.replace("'", "\\'")
            return f"'{escaped_str}'"
        if isinstance(node.value, (int, float)):
            # Force high-precision fixed point, then trim unnecessary trailing zeros
            formatted = node.value.rstrip('0')
            if formatted.endswith('.'):
                formatted = formatted[:-1]
            return formatted
        return json.dumps(node.value)

    def visit_List(self, node):
        elements = [self.visit(el) for el in node.elts]
        return f"[{', '.join(elements)}]"

    def visit_Attribute(self, node):
        value = self.visit(node.value)
        if value == 'math':
            value = 'Math'
        return f"{value}.{node.attr}"

    def visit_Call(self, node):
        func = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        return f"{func}({', '.join(args)})"

def translate_expression(val):
    if val.isdigit() or val in ["true", "false", "True", "False"]:
        return "true" if val == "True" else "false" if val == "False" else val
    try:
        tree = ast.parse(val, mode='eval')
        return ConvertPythonToJS().visit(tree)
    except Exception:
        return val

def make_modify_callback(no_rename):
    def modify_match(match):
        full_key_syntax = match.group(1)
        quote_char = match.group(2)
        inner_expr = match.group(3)

        # Luban controls "visibility", not state. This is only relevant for snapmaker_modify_0, but harmless elsewhere.
        # Still, avoid rewriting the key to "visible" if the override flag (-o) is passed
        if not no_rename and re.search(r'\benabled\b', full_key_syntax):
            full_key_syntax = full_key_syntax.replace("enabled", "visible")

        try:
            unescaped_expr = json.loads(f'"{inner_expr}"')
        except Exception:
            unescaped_expr = inner_expr

        translated = translate_expression(unescaped_expr)

        if quote_char == '"':
            escaped_translated = translated.replace('"', '\\"')
        else:
            escaped_translated = translated.replace("'", "\\'")

        return f"{full_key_syntax}{quote_char}{escaped_translated}{quote_char}"
    return modify_match

def main():
    parser = argparse.ArgumentParser(description="Convert and transform Cura fields with optional key-rename suppression (for fdmprinter).")
    parser.add_argument("infile", help="Path to the input JSON file.")
    parser.add_argument("-o", "--no-rename", action="store_true", help="Keep the 'enabled' key name intact instead of changing it to 'visible'.")
    args = parser.parse_args()

    try:
        with open(args.infile, 'r', encoding='utf-8') as f:
            content = f.read()

        field_pattern = re.compile(r'(\"\b(?:value|enabled|visible|calcu_value|resolve|min|max|minimum_value|maximum_value)\b\"\s*:\s*)(\"|\')(.*?)(?<!\\)\2')

        modify_match_fn = make_modify_callback(args.no_rename)
        translated_content = field_pattern.sub(modify_match_fn, content)

        sys.stdout.write(translated_content)
    except Exception as e:
        print(f"Error processing file: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

