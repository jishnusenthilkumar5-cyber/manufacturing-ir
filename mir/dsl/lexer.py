from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum


class TokenKind(StrEnum):
    IDENTIFIER = "identifier"
    STRING = "string"
    NUMBER = "number"
    DURATION = "duration"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    COLON = ":"
    EQUALS = "="
    ARROW = "->"
    EOF = "end of input"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    value: str
    offset: int
    line: int
    column: int


class DSLParseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        source: str,
        line: int,
        column: int,
        offending_line: str,
    ) -> None:
        self.message = message
        self.source = source
        self.line = line
        self.column = column
        self.offending_line = offending_line
        prefix = offending_line[: max(column - 1, 0)]
        caret_padding = "".join("\t" if character == "\t" else " " for character in prefix)
        self.caret = f"{caret_padding}^"
        super().__init__(self.render())

    def render(self) -> str:
        return (
            f"{self.source}:{self.line}:{self.column}: {self.message}\n"
            f"{self.offending_line}\n{self.caret}"
        )

    def __str__(self) -> str:
        return self.render()


_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_IDENTIFIER_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789")
_IDENTIFIER_BODY = _IDENTIFIER_START | frozenset("-")
_DURATION_UNITS = ("min", "s", "h")


class Lexer:
    def __init__(self, text: str, source_name: str = "<string>") -> None:
        self.text = text
        self.source_name = source_name
        self._offset = 0
        self._line = 1
        self._column = 1
        self._lines = text.splitlines()
        if not self._lines or text.endswith(("\n", "\r")):
            self._lines.append("")

    def tokenize(self) -> tuple[Token, ...]:
        tokens: list[Token] = []
        while not self._at_end:
            character = self._peek()
            if character.isspace():
                self._advance()
                continue
            if character == "#":
                self._skip_comment()
                continue
            if character == '"':
                tokens.append(self._scan_string())
                continue
            if character == "-" and self._peek(1) == ">":
                tokens.append(self._fixed(TokenKind.ARROW, 2))
                continue
            punctuation = {
                "{": TokenKind.LBRACE,
                "}": TokenKind.RBRACE,
                "[": TokenKind.LBRACKET,
                "]": TokenKind.RBRACKET,
                "(": TokenKind.LPAREN,
                ")": TokenKind.RPAREN,
                ",": TokenKind.COMMA,
                ":": TokenKind.COLON,
                "=": TokenKind.EQUALS,
            }.get(character)
            if punctuation is not None:
                tokens.append(self._fixed(punctuation, 1))
                continue
            if character == "-" or character.isdigit():
                token = self._scan_number_or_identifier()
                if token is not None:
                    tokens.append(token)
                    continue
            if character in _IDENTIFIER_START:
                tokens.append(self._scan_identifier())
                continue
            self._raise(f"unexpected character {character!r}")
        tokens.append(
            Token(
                TokenKind.EOF,
                "",
                "",
                self._offset,
                self._line,
                self._column,
            )
        )
        return tuple(tokens)

    @property
    def _at_end(self) -> bool:
        return self._offset >= len(self.text)

    def _peek(self, distance: int = 0) -> str:
        offset = self._offset + distance
        return self.text[offset] if offset < len(self.text) else ""

    def _advance(self) -> str:
        character = self.text[self._offset]
        self._offset += 1
        if character == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return character

    def _fixed(self, kind: TokenKind, length: int) -> Token:
        offset, line, column = self._offset, self._line, self._column
        text = "".join(self._advance() for _ in range(length))
        return Token(kind, text, text, offset, line, column)

    def _skip_comment(self) -> None:
        while not self._at_end and self._peek() not in "\r\n":
            self._advance()

    def _scan_string(self) -> Token:
        offset, line, column = self._offset, self._line, self._column
        self._advance()
        escaped = False
        while not self._at_end:
            character = self._peek()
            if character in "\r\n" and not escaped:
                self._raise_at("unterminated string literal", line, column)
            self._advance()
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == '"':
                raw = self.text[offset : self._offset]
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError as exc:
                    error_column = column + max(exc.pos, 0)
                    self._raise_at(f"invalid string literal: {exc.msg}", line, error_column)
                return Token(TokenKind.STRING, raw, value, offset, line, column)
        self._raise_at("unterminated string literal", line, column)

    def _scan_number_or_identifier(self) -> Token | None:
        offset, line, column = self._offset, self._line, self._column
        match = _NUMBER.match(self.text, offset)
        if match is None:
            return None
        end = match.end()
        following = self.text[end : end + 1]
        if following and following in _IDENTIFIER_BODY:
            suffix = next(
                (
                    unit
                    for unit in _DURATION_UNITS
                    if self.text.startswith(unit, end)
                    and self._is_delimiter(end + len(unit))
                ),
                None,
            )
            if suffix is not None:
                duration_end = end + len(suffix)
                while self._offset < duration_end:
                    self._advance()
                raw_duration = self.text[offset : self._offset]
                return Token(
                    TokenKind.DURATION,
                    raw_duration,
                    raw_duration,
                    offset,
                    line,
                    column,
                )
            while self._identifier_continues():
                self._advance()
            raw_identifier = self.text[offset : self._offset]
            return Token(
                TokenKind.IDENTIFIER,
                raw_identifier,
                raw_identifier,
                offset,
                line,
                column,
            )
        while self._offset < end:
            self._advance()
        raw = self.text[offset:end]
        return Token(TokenKind.NUMBER, raw, raw, offset, line, column)

    def _scan_identifier(self) -> Token:
        offset, line, column = self._offset, self._line, self._column
        while self._identifier_continues():
            self._advance()
        raw = self.text[offset : self._offset]
        return Token(TokenKind.IDENTIFIER, raw, raw, offset, line, column)

    def _identifier_continues(self) -> bool:
        return (
            not self._at_end
            and self._peek() in _IDENTIFIER_BODY
            and not (self._peek() == "-" and self._peek(1) == ">")
        )

    def _is_delimiter(self, offset: int) -> bool:
        if offset >= len(self.text):
            return True
        character = self.text[offset]
        return (
            character.isspace()
            or character in "{}[](),:=#"
            or self.text.startswith("->", offset)
        )

    def _line_text(self, line: int) -> str:
        if 1 <= line <= len(self._lines):
            return self._lines[line - 1]
        return ""

    def _raise(self, message: str) -> None:
        self._raise_at(message, self._line, self._column)

    def _raise_at(self, message: str, line: int, column: int) -> None:
        raise DSLParseError(
            message,
            source=self.source_name,
            line=line,
            column=column,
            offending_line=self._line_text(line),
        )


def tokenize(text: str, source_name: str = "<string>") -> tuple[Token, ...]:
    return Lexer(text, source_name).tokenize()
