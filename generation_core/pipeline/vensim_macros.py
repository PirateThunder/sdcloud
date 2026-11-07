from __future__ import annotations

import re
from dataclasses import dataclass

from .exceptions import ModelValidationError

_IDENTIFIER_TEXT = r'"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*(?:[ \t]+[A-Za-z_][A-Za-z0-9_]*)*'
_IDENTIFIER = re.compile(_IDENTIFIER_TEXT)
_CALL = re.compile(rf"(?P<name>{_IDENTIFIER_TEXT})\s*\(")
_DEFINITION = re.compile(
    r"(?ims)^[ \t]*:MACRO:[ \t]*(?P<name>[A-Za-z_][A-Za-z0-9_ ]*?)\s*"
    r"\((?P<parameters>[^)\n]*)\)[ \t]*\r?\n(?P<body>.*?)"
    r"^[ \t]*:END[ \t]+OF[ \t]+MACRO:[ \t]*\r?$"
)
_EQUATION = re.compile(
    r"(?ms)^(?P<label>[^=\n]+?)\s*=\s*(?P<rhs>.*?)(?=\n[ \t]*~|\Z)"
)


@dataclass(frozen=True)
class Macro:
    name: str
    parameters: tuple[str, ...]
    equations: tuple[tuple[str, str], ...]

    @property
    def key(self) -> str:
        return _label(self.name)


def _label(value: str) -> str:
    return " ".join(value.strip().strip('"').split()).casefold()


def _arguments(source: str) -> list[str]:
    result = []
    start = 0
    depth = 0
    quoted = False
    for index, character in enumerate(source):
        if character == '"':
            quoted = not quoted
        elif not quoted:
            if character in "([":
                depth += 1
            elif character in ")]":
                depth -= 1
                if depth < 0:
                    raise ModelValidationError("unbalanced macro invocation arguments")
            elif character == "," and depth == 0:
                result.append(source[start:index].strip())
                start = index + 1
    if quoted or depth:
        raise ModelValidationError("unterminated macro invocation")
    result.append(source[start:].strip())
    return result


def _closing_parenthesis(source: str, opening: int) -> int:
    depth = 0
    quoted = False
    for index in range(opening, len(source)):
        character = source[index]
        if character == '"':
            quoted = not quoted
        elif not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    return index
    raise ModelValidationError("unterminated macro invocation")


def _expand_calls(source: str, macros: dict[str, Macro], stack: tuple[str, ...]) -> str:
    position = 0
    while match := _CALL.search(source, position):
        key = _label(match.group("name"))
        if key not in macros:
            position = match.end()
            continue
        closing = _closing_parenthesis(source, match.end() - 1)
        arguments = [
            _expand_calls(argument, macros, stack)
            for argument in _arguments(source[match.end() : closing])
        ]
        expanded = _expand_macro(macros[key], arguments, macros, stack)
        source = f"{source[:match.start()]}({expanded}){source[closing + 1:]}"
        position = match.start() + len(expanded) + 2
        if len(source) > 10_000_000:
            raise ModelValidationError("macro expansion exceeds the size limit")
    return source


def _expand_macro(
    macro: Macro,
    arguments: list[str],
    macros: dict[str, Macro],
    stack: tuple[str, ...],
) -> str:
    if macro.key in stack or len(stack) >= 32:
        raise ModelValidationError(f"recursive or excessive macro expansion: {macro.name}")
    if len(arguments) != len(macro.parameters) or any(not value for value in arguments):
        raise ModelValidationError(
            f"macro {macro.name} expects {len(macro.parameters)} arguments, got {len(arguments)}"
        )
    parameters = dict(zip(macro.parameters, arguments, strict=True))
    equations = {
        _label(label): _expand_calls(rhs, macros, (*stack, macro.key))
        for label, rhs in macro.equations
    }
    if macro.key not in equations:
        raise ModelValidationError(f"macro {macro.name} has no equation named after itself")
    cache = {}

    def inline(name: str, trail: tuple[str, ...]) -> str:
        if name in cache:
            return cache[name]
        if name in trail:
            raise ModelValidationError(f"circular local equations in macro {macro.name}")

        def replace(match: re.Match) -> str:
            key = _label(match.group())
            if key in equations:
                return f"({inline(key, (*trail, name))})"
            if key in parameters:
                return f"({parameters[key]})"
            return match.group()

        result = _IDENTIFIER.sub(replace, equations[name])
        cache[name] = result
        return result

    return inline(macro.key, ())


def expand_vensim_macros(source: str) -> str:
    definitions = list(_DEFINITION.finditer(source))
    if len(definitions) > 64:
        raise ModelValidationError("too many Vensim macro definitions")
    macros = {}
    for match in definitions:
        name = match.group("name").strip()
        parameters = tuple(
            _label(value) for value in match.group("parameters").split(",") if value.strip()
        )
        if len(parameters) != len(set(parameters)):
            raise ModelValidationError(f"duplicate macro parameter in {name}")
        equations = tuple(
            (item.group("label").strip(), item.group("rhs").strip())
            for item in _EQUATION.finditer(match.group("body"))
        )
        macro = Macro(name=name, parameters=parameters, equations=equations)
        if macro.key in macros:
            raise ModelValidationError(f"duplicate Vensim macro: {name}")
        macros[macro.key] = macro
    source = _DEFINITION.sub("", source)
    if re.search(r":MACRO:|:END[ \t]+OF[ \t]+MACRO:", source, re.IGNORECASE):
        raise ModelValidationError("malformed or nested Vensim macro definition")
    return _expand_calls(source, macros, ()) if macros else source
