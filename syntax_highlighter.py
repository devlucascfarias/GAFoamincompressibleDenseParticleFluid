from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
import re

class OpenFOAMHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlightingRules = []

        # Formato para palavras-chave
        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(QColor("blue"))
        keywordFormat.setFontWeight(QFont.Bold)
        keywords = [
            r"\bFoamFile\b", r"\bversion\b", r"\bformat\b", r"\bclass\b", r"\bobject\b",
            r"\bdimensions\b", r"\binternalField\b", r"\bboundaryField\b"
        ]
        for keyword in keywords:
            self.highlightingRules.append((re.compile(keyword), keywordFormat))

        # Formato para números
        numberFormat = QTextCharFormat()
        numberFormat.setForeground(QColor("darkMagenta"))
        self.highlightingRules.append((re.compile(r"\b\d+(\.\d+)?\b"), numberFormat))

        # Formato para comentários
        commentFormat = QTextCharFormat()
        commentFormat.setForeground(QColor("green"))
        self.highlightingRules.append((re.compile(r"//[^\n]*"), commentFormat))

        # Formato para strings
        stringFormat = QTextCharFormat()
        stringFormat.setForeground(QColor("darkRed"))
        self.highlightingRules.append((re.compile(r'"[^"]*"'), stringFormat))

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                self.setFormat(start, end - start, format)
