"""AXON Intent / Model Router — classifies user requests for model routing."""

from enum import Enum
import re
from typing import Tuple


class Intent(Enum):
    GENERAL = "general"
    CODING = "coding"


class IntentRouter:
    """Classifies user input into GENERAL or CODING intent to select the appropriate model."""

    # File extensions commonly used in code projects
    CODE_EXTENSIONS = (
        r"\.(?:py|js|jsx|ts|tsx|html|css|scss|json|yaml|yml|md|sql|sh|bat|ps1|rs|go|c|cpp|h|hpp|java|kt|rb|php|vue|svelte)\b"
    )

    # Strong coding actions / verbs and patterns
    CODING_PATTERNS = [
        # Explicit file inspection/editing
        r"\b(?:read|inspect|view|check|open|edit|modify|update|rewrite|fix|debug)\s+[\w\-./\\]+" + CODE_EXTENSIONS,
        # Bug fixing and coding requests
        r"\b(?:fix|debug|resolve)\s+(?:the\s+)?(?:bug|error|issue|exception|crash|failure|warning)\b",
        r"\bfind\s+(?:the\s+)?bug\b",
        r"\b(?:implement|add|create|write)\s+(?:a\s+)?(?:function|method|class|component|hook|endpoint|module|feature|script|test|unit\s*test)\b",
        r"\b(?:refactor|optimize|cleanup|format)\s+(?:the\s+)?(?:code|function|class|file|repo|project)\b",
        # Test execution
        r"\b(?:run|execute)\s+(?:the\s+)?(?:tests?|pytest|npm\s+test|jest|mocha|cargo\s+test)\b",
        r"\bpytest\b",
        r"\bnpm\s+(?:test|run\s+build|run\s+dev)\b",
        # Workspace & project references
        r"\bin\s+(?:my|this|the)\s+(?:project|workspace|repo|repository|codebase)\b",
        r"\bproject\s+files?\b",
        r"\bcreate\s+(?:a\s+)?(?:react|vue|svelte|node|django|flask|fastapi)\s+(?:component|app|server|endpoint)\b",
        # Git operations
        r"\bgit\s+(?:status|diff|log|branch|commit|checkout|switch|pull|push|remote|repo|rollback)\b",
        r"\b(?:push|pull|commit)\s+.*?\b(?:git|github|remote|origin|branch|main|master)\b",
        r"\bcommit\s+(?:changes|code|files)?\b",
        r"\b(?:github\s+remote|check\s+git|git\s+changes|changed\s+files)\b",
    ]

    # Explicit general/conversational queries that should NOT be classified as coding
    GENERAL_OVERRIDE_PATTERNS = [
        r"^what\s+is\s+(?:recursion|object[\s-]oriented|polymorphism|an?\s+algorithm|python|javascript)",
        r"^explain\s+(?:recursion|how\s+.*works|what\s+.*is)",
        r"^(?:what|where|who|when|why|how)\s+(?:is|are|was|were)\s+the\s+capital\b",
        r"^what(?:'s|\s+is)\s+the\s+capital\b",
        r"\bcapital\s+of\s+[a-zA-Z]+",
    ]

    def __init__(self):
        self._compiled_coding = [re.compile(p, re.IGNORECASE) for p in self.CODING_PATTERNS]
        self._compiled_general = [re.compile(p, re.IGNORECASE) for p in self.GENERAL_OVERRIDE_PATTERNS]
        self._ext_regex = re.compile(self.CODE_EXTENSIONS, re.IGNORECASE)

    def route(self, user_input: str) -> Tuple[Intent, str]:
        """Classifies the user input into Intent.GENERAL or Intent.CODING.
        
        Returns:
            (intent, reason)
        """
        if not user_input or not user_input.strip():
            return Intent.GENERAL, "Empty input defaults to general"

        clean = user_input.strip()
        clean_lower = clean.lower()

        # 1. Check general conceptual overrides first (e.g. "Explain recursion", "What is recursion?")
        for pattern in self._compiled_general:
            if pattern.search(clean):
                return Intent.GENERAL, "Matches general knowledge / concept explanation pattern"

        # 2. Check explicit coding patterns
        for pattern in self._compiled_coding:
            if pattern.search(clean):
                return Intent.CODING, f"Matches coding intent pattern: {pattern.pattern}"

        # 3. Check code file extensions coupled with project/code intent
        if self._ext_regex.search(clean_lower):
            # If a filename with a code extension is mentioned (e.g. "main.py", "App.jsx")
            return Intent.CODING, "References specific source code file"

        # 4. Safe fallback: Ambiguous input defaults to GENERAL
        return Intent.GENERAL, "Ambiguous or standard request defaults to general"
