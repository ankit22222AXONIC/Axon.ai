"""AXON Project Intelligence — lightweight workspace analysis, project detection, and smart context.

Analyzes a workspace to extract:
- Project languages, frameworks, package managers, and test runners
- Entry points, important files, and top-level dependencies
- Bounded structure map
- Smart context selection for user requests within strict context budgets

Operates strictly read-only, within workspace boundaries, and never accesses sensitive secrets.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import List, Dict, Any, Optional, Set

from axon.security.path_security import is_within_workspace, is_sensitive_credential_path
from axon.coding.tools import IGNORED_DIRS


# Context Budget Constants
MAX_PROJECT_FILES = 200
MAX_CONTEXT_FILES = 10
MAX_FILE_SIZE = 50_000         # 50 KB max per file read for context
MAX_CONTEXT_CHARS = 4_000       # 4,000 characters total context budget
MAX_MAP_DEPTH = 3
MAX_MAP_FILES = 100


# File extension to language mapping
EXTENSION_LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
}


@dataclass
class ProjectInfo:
    """Structured metadata about a workspace project."""
    root: str
    name: str
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    package_manager: Optional[str] = None
    test_framework: Optional[str] = None
    build_system: Optional[str] = None
    entry_points: List[str] = field(default_factory=list)
    important_files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    structure_map: str = ""

    def summary(self) -> str:
        """Concise one-line summary for logging and UI status."""
        langs = ", ".join(self.languages) if self.languages else "Unknown"
        fws = f" ({', '.join(self.frameworks)})" if self.frameworks else ""
        pm = f" [{self.package_manager}]" if self.package_manager else ""
        return f"{langs}{fws}{pm}"


class ProjectIntelligence:
    """Lightweight, deterministic workspace analyzer and smart context builder."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self._root = workspace_root
        self._cache: Optional[ProjectInfo] = None
        self._cache_key: Optional[str] = None

    @property
    def root(self) -> Path:
        if self._root:
            return self._root.resolve()
        from axon.tools.filesystem import _CURRENT_WORKSPACE
        return (_CURRENT_WORKSPACE or Path.cwd()).resolve()

    def set_workspace(self, path: Path):
        """Set or update workspace root and invalidate cache."""
        self._root = path.resolve()
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear cached project metadata."""
        self._cache = None
        self._cache_key = None

    # ==========================================================================
    # 1. CORE PROJECT SCANNING & METADATA
    # ==========================================================================

    def analyze(self, refresh: bool = False) -> ProjectInfo:
        """Analyze the workspace and return structured ProjectInfo with in-memory caching."""
        ws = self.root
        if not ws.exists() or not ws.is_dir():
            return ProjectInfo(root=str(ws), name=ws.name)

        # Cache check based on workspace path
        cache_key = str(ws)
        if not refresh and self._cache is not None and self._cache_key == cache_key:
            return self._cache

        # Safe read of dependencies first (helps framework/test detection)
        dependencies = self._extract_dependencies(ws)
        dep_names_lower = {d.lower() for d in dependencies}

        languages = self._detect_languages(ws)
        frameworks = self._detect_frameworks(ws, dep_names_lower)
        package_manager = self._detect_package_manager(ws)
        test_framework = self._detect_test_framework(ws, dep_names_lower)
        build_system = self._detect_build_system(ws, dep_names_lower)
        important_files = self._detect_important_files(ws)
        entry_points = self._detect_entry_points(ws)
        structure_map = self.build_structure_map()

        info = ProjectInfo(
            root=str(ws),
            name=ws.name,
            languages=languages,
            frameworks=frameworks,
            package_manager=package_manager,
            test_framework=test_framework,
            build_system=build_system,
            entry_points=entry_points,
            important_files=important_files,
            dependencies=dependencies,
            structure_map=structure_map,
        )

        self._cache = info
        self._cache_key = cache_key
        return info

    # ==========================================================================
    # 2. DETECTION ENGINES
    # ==========================================================================

    def _detect_languages(self, ws: Path) -> List[str]:
        """Detect likely project languages based on file extensions in the workspace."""
        lang_counts: Dict[str, int] = {}
        file_count = 0

        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for f in files:
                if f.startswith("."):
                    continue
                file_path = Path(root) / f
                if not is_within_workspace(file_path, ws) or is_sensitive_credential_path(file_path):
                    continue

                ext = Path(f).suffix.lower()
                lang = EXTENSION_LANGUAGE_MAP.get(ext)
                if lang and lang not in ("JSON", "YAML", "TOML", "Markdown", "Shell", "PowerShell"):
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1

                file_count += 1
                if file_count >= MAX_PROJECT_FILES:
                    break
            if file_count >= MAX_PROJECT_FILES:
                break

        # Fallback detection from canonical files
        if not lang_counts:
            if (ws / "pyproject.toml").exists() or (ws / "requirements.txt").exists():
                lang_counts["Python"] = 1
            if (ws / "package.json").exists():
                lang_counts["JavaScript"] = 1
            if (ws / "tsconfig.json").exists():
                lang_counts["TypeScript"] = 1
            if (ws / "Cargo.toml").exists():
                lang_counts["Rust"] = 1
            if (ws / "go.mod").exists():
                lang_counts["Go"] = 1

        # If TypeScript is present, JavaScript is commonly paired
        if "TypeScript" in lang_counts and "JavaScript" not in lang_counts:
            if (ws / "package.json").exists():
                lang_counts["JavaScript"] = lang_counts.get("JavaScript", 0) + 1

        # Sort by frequency descending
        sorted_langs = sorted(lang_counts.keys(), key=lambda k: lang_counts[k], reverse=True)
        return sorted_langs

    def _detect_frameworks(self, ws: Path, deps: Set[str]) -> List[str]:
        """Detect common web and application frameworks heuristically."""
        frameworks: List[str] = []

        # React
        if "react" in deps or any(ws.glob("src/**/*.jsx")) or any(ws.glob("src/**/*.tsx")) or any(ws.glob("*.jsx")):
            if "React" not in frameworks:
                frameworks.append("React")

        # Next.js
        if "next" in deps or any(ws.glob("next.config.*")) or (ws / "pages").exists() or (ws / "app").exists():
            if "next" in deps or any(ws.glob("next.config.*")):
                if "Next.js" not in frameworks:
                    frameworks.append("Next.js")

        # Vue
        if "vue" in deps or any(ws.glob("src/**/*.vue")):
            if "Vue" not in frameworks:
                frameworks.append("Vue")

        # Svelte
        if "svelte" in deps or any(ws.glob("src/**/*.svelte")):
            if "Svelte" not in frameworks:
                frameworks.append("Svelte")

        # Python Web Frameworks: Flask, FastAPI, Django
        if "flask" in deps or self._has_import_in_entry(ws, "flask"):
            if "Flask" not in frameworks:
                frameworks.append("Flask")

        if "fastapi" in deps or self._has_import_in_entry(ws, "fastapi"):
            if "FastAPI" not in frameworks:
                frameworks.append("FastAPI")

        if "django" in deps or (ws / "manage.py").exists():
            if "Django" not in frameworks:
                frameworks.append("Django")

        return frameworks

    def _has_import_in_entry(self, ws: Path, module_name: str) -> bool:
        """Check candidate entry files for an import of module_name safely."""
        candidate_files = ["main.py", "app.py", "server.py", "src/main.py", "src/app.py"]
        for c in candidate_files:
            target = ws / c
            if target.exists() and target.is_file():
                try:
                    text = target.read_text(encoding="utf-8", errors="ignore")[:3000]
                    if re.search(rf"\b(?:import\s+{module_name}|from\s+{module_name}\b)", text, re.IGNORECASE):
                        return True
                except Exception:
                    pass
        return False

    def _detect_package_manager(self, ws: Path) -> Optional[str]:
        """Detect package manager using lockfiles and configs without executing binaries."""
        # Node lockfiles in order of specificity
        if (ws / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (ws / "yarn.lock").exists():
            return "yarn"
        if (ws / "bun.lockb").exists() or (ws / "bun.lock").exists():
            return "bun"
        if (ws / "package-lock.json").exists():
            return "npm"
        if (ws / "package.json").exists():
            return "npm"

        # Python package managers
        if (ws / "poetry.lock").exists():
            return "poetry"
        if (ws / "Pipfile.lock").exists() or (ws / "Pipfile").exists():
            return "pipenv"
        if (ws / "pyproject.toml").exists():
            try:
                content = (ws / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
                if "poetry" in content.lower():
                    return "poetry"
            except Exception:
                pass
            return "pip"
        if (ws / "requirements.txt").exists() or (ws / "setup.py").exists():
            return "pip"

        # Rust
        if (ws / "Cargo.toml").exists() or (ws / "Cargo.lock").exists():
            return "cargo"

        return None

    def _detect_test_framework(self, ws: Path, deps: Set[str]) -> Optional[str]:
        """Detect likely test runner from configuration files or dependencies."""
        # JS / TS test runners
        if any(ws.glob("vitest.config.*")) or "vitest" in deps:
            return "Vitest"
        if any(ws.glob("jest.config.*")) or "jest" in deps:
            return "Jest"

        # Python test runners
        if (
            (ws / "pytest.ini").exists()
            or (ws / "conftest.py").exists()
            or (ws / "tests" / "conftest.py").exists()
            or "pytest" in deps
            or any(ws.glob("test_*.py"))
            or any(ws.glob("tests/**/test_*.py"))
            or any(ws.glob("*_test.py"))
        ):
            return "pytest"

        # Check pyproject.toml or setup.cfg for pytest config
        for cfg in ["pyproject.toml", "setup.cfg"]:
            p = ws / cfg
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    if "pytest" in content.lower():
                        return "pytest"
                except Exception:
                    pass

        # Fallback check if Python project with tests folder
        if (ws / "tests").exists() or (ws / "test").exists():
            if any(ws.glob("*.py")) or (ws / "requirements.txt").exists():
                return "pytest"

        return None

    def _detect_build_system(self, ws: Path, deps: Set[str]) -> Optional[str]:
        """Detect frontend or project build tool."""
        if any(ws.glob("vite.config.*")) or "vite" in deps:
            return "Vite"
        if any(ws.glob("next.config.*")) or "next" in deps:
            return "Next.js"
        if any(ws.glob("webpack.config.*")) or "webpack" in deps:
            return "Webpack"
        if (ws / "Cargo.toml").exists():
            return "Cargo"
        if (ws / "setup.py").exists() or (ws / "pyproject.toml").exists():
            return "Setuptools"
        return None

    def _detect_important_files(self, ws: Path) -> List[str]:
        """Identify key configuration and architectural files that actually exist in the workspace."""
        candidate_important = [
            # Configs & Manifests
            "package.json",
            "tsconfig.json",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "Cargo.toml",
            "Dockerfile",
            "docker-compose.yml",
            "README.md",
            # Build configs
            "vite.config.ts",
            "vite.config.js",
            "next.config.js",
            "next.config.mjs",
            "webpack.config.js",
            # Test configs
            "pytest.ini",
            "jest.config.js",
            "vitest.config.ts",
            # Core source
            "src/main.tsx",
            "src/main.jsx",
            "src/index.tsx",
            "src/index.jsx",
            "src/App.tsx",
            "src/App.jsx",
            "main.py",
            "app.py",
            "manage.py",
            "index.html",
        ]

        found: List[str] = []
        for rel in candidate_important:
            target = ws / rel
            if target.exists() and target.is_file():
                if not is_sensitive_credential_path(target):
                    found.append(rel.replace("\\", "/"))
        return found

    def _detect_entry_points(self, ws: Path) -> List[str]:
        """Detect likely entry points for application execution."""
        candidate_entries = [
            "src/main.tsx",
            "src/main.jsx",
            "src/index.tsx",
            "src/index.jsx",
            "src/App.tsx",
            "src/App.jsx",
            "src/index.js",
            "src/main.py",
            "src/app.py",
            "main.py",
            "app.py",
            "server.py",
            "wsgi.py",
            "index.js",
            "server.js",
            "src/main.rs",
            "main.go",
        ]

        found: List[str] = []
        for rel in candidate_entries:
            target = ws / rel
            if target.exists() and target.is_file():
                if not is_sensitive_credential_path(target):
                    found.append(rel.replace("\\", "/"))

        # Check package.json "main" field
        pkg_file = ws / "package.json"
        if pkg_file.exists():
            try:
                data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
                main_val = data.get("main")
                if main_val and isinstance(main_val, str):
                    clean_main = main_val.replace("\\", "/").lstrip("./")
                    if (ws / clean_main).exists() and clean_main not in found:
                        found.insert(0, clean_main)
            except Exception:
                pass

        return found

    def _extract_dependencies(self, ws: Path) -> List[str]:
        """Extract top-level declared dependencies safely without executing package managers."""
        deps: Set[str] = set()

        # 1. package.json
        pkg_path = ws / "package.json"
        if pkg_path.exists() and pkg_path.is_file():
            try:
                data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                for section in ("dependencies", "devDependencies"):
                    if isinstance(data.get(section), dict):
                        deps.update(data[section].keys())
            except Exception:
                pass

        # 2. requirements.txt
        req_path = ws / "requirements.txt"
        if req_path.exists() and req_path.is_file():
            try:
                lines = req_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Strip version specifiers (e.g. "flask>=2.0" -> "flask")
                    name = re.split(r"[><=~!;]", line)[0].strip()
                    if name:
                        deps.add(name.lower())
            except Exception:
                pass

        # 3. pyproject.toml
        pyproj_path = ws / "pyproject.toml"
        if pyproj_path.exists() and pyproj_path.is_file():
            try:
                content = pyproj_path.read_text(encoding="utf-8", errors="ignore")
                # Simple regex match for dependencies = [...]
                match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
                if match:
                    items = match.group(1).split(",")
                    for it in items:
                        clean = it.strip().strip("'\"")
                        name = re.split(r"[><=~!;]", clean)[0].strip()
                        if name:
                            deps.add(name.lower())
            except Exception:
                pass

        return sorted(deps)[:50]

    # ==========================================================================
    # 3. STRUCTURE MAPPING
    # ==========================================================================

    def build_structure_map(self, max_depth: int = MAX_MAP_DEPTH, max_files: int = MAX_MAP_FILES) -> str:
        """Create a bounded visual directory tree of the workspace."""
        ws = self.root
        if not ws.exists() or not ws.is_dir():
            return f"{ws.name}/"

        lines = [f"{ws.name}/"]
        count = 0
        base_depth = len(ws.parts)

        for root, dirs, files in os.walk(ws):
            # Prune ignored and hidden directories
            dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")])
            current_depth = len(Path(root).parts) - base_depth
            if current_depth >= max_depth:
                dirs.clear()
                continue

            rel_path = Path(root).relative_to(ws)
            if str(rel_path) != ".":
                indent = "  " * current_depth
                lines.append(f"{indent}├── {Path(root).name}/")

            file_indent = "  " * (current_depth + 1)
            for f in sorted(files):
                if f.startswith("."):
                    continue
                file_path = Path(root) / f
                if is_sensitive_credential_path(file_path):
                    continue

                lines.append(f"{file_indent}└── {f}")
                count += 1
                if count >= max_files:
                    lines.append(f"{file_indent}... [truncated after {max_files} files]")
                    break
            if count >= max_files:
                break

        return "\n".join(lines)

    # ==========================================================================
    # 4. SMART CONTEXT & RELEVANCE SCORING
    # ==========================================================================

    def find_relevant_files(self, query: str, max_files: int = MAX_CONTEXT_FILES) -> List[str]:
        """Identify files in the workspace most likely relevant to the user request."""
        if not query or not query.strip():
            # Default to entry points and important files
            info = self.analyze()
            return (info.entry_points + [f for f in info.important_files if f not in info.entry_points])[:max_files]

        ws = self.root
        clean_query = query.lower()
        # Extract query tokens / keywords (3+ chars, alphanumeric)
        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", clean_query))
        # Filter out common stop words
        stop_words = {"the", "and", "for", "with", "this", "that", "from", "into", "what", "how", "file", "code", "run", "test"}
        tokens = tokens - stop_words

        # Check explicit file mention in query
        explicit_match = re.findall(r"\b[\w\-./\\]+\.[a-zA-Z0-9]+\b", query)
        explicit_files = set()
        for ef in explicit_match:
            ef_clean = ef.replace("\\", "/").lstrip("./")
            if (ws / ef_clean).exists():
                explicit_files.add(ef_clean)

        file_scores: Dict[str, int] = {}
        info = self.analyze()

        # Seed candidate pool from workspace
        candidates = set()
        file_count = 0
        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
            for f in files:
                if f.startswith("."):
                    continue
                file_path = Path(root) / f
                if is_sensitive_credential_path(file_path):
                    continue
                rel = str(file_path.relative_to(ws)).replace("\\", "/")
                candidates.add(rel)
                file_count += 1
                if file_count >= MAX_PROJECT_FILES:
                    break
            if file_count >= MAX_PROJECT_FILES:
                break

        for rel in candidates:
            score = 0
            rel_lower = rel.lower()
            stem_lower = Path(rel).stem.lower()

            # Explicit mention gets highest priority
            if rel in explicit_files:
                score += 100

            # Token matching in path, filename, or stem
            for tok in tokens:
                if tok in stem_lower or (len(stem_lower) >= 3 and stem_lower in tok):
                    score += 30
                elif tok in rel_lower or (len(tok) >= 3 and tok in rel_lower):
                    score += 15

            # Quick content scan (first 3000 chars) for token matches
            target_path = ws / rel
            if target_path.exists() and target_path.is_file():
                try:
                    sample = target_path.read_text(encoding="utf-8", errors="ignore")[:3000].lower()
                    for tok in tokens:
                        if tok in sample:
                            score += 15
                except Exception:
                    pass

            # Entry points and important files get a slight boost
            if rel in info.entry_points:
                score += 5
            if rel in info.important_files:
                score += 3

            # Test files get boosted if "test" in query
            if "test" in clean_query and ("test" in rel_lower or "spec" in rel_lower):
                score += 15

            if score > 0:
                file_scores[rel] = score

        # Sort candidate files by score descending
        sorted_files = sorted(file_scores.keys(), key=lambda f: file_scores[f], reverse=True)

        # Fallback to important files if nothing scored
        if not sorted_files:
            sorted_files = info.entry_points + [f for f in info.important_files if f not in info.entry_points]

        return sorted_files[:max_files]

    def format_model_context(self, query: str = "") -> str:
        """Generate structured project context for the Coding Model within strict context budgets."""
        info = self.analyze()
        relevant = self.find_relevant_files(query, max_files=MAX_CONTEXT_FILES)

        lines = [
            f"PROJECT: {info.name}",
            f"LANGUAGES: {', '.join(info.languages) if info.languages else 'Unknown'}",
        ]
        if info.frameworks:
            lines.append(f"FRAMEWORK: {', '.join(info.frameworks)}")
        if info.build_system:
            lines.append(f"BUILD: {info.build_system}")
        if info.package_manager:
            lines.append(f"PACKAGE MANAGER: {info.package_manager}")
        if info.test_framework:
            lines.append(f"TEST: {info.test_framework}")

        if info.important_files:
            lines.append("IMPORTANT FILES:")
            for imp in info.important_files[:6]:
                lines.append(f"- {imp}")

        if relevant:
            lines.append("RELEVANT FILES:")
            for rel in relevant:
                lines.append(f"- {rel}")

        # Add brief excerpts for top relevant files (bounded by MAX_CONTEXT_CHARS)
        header_text = "\n".join(lines)
        remaining_budget = MAX_CONTEXT_CHARS - len(header_text) - 100

        if remaining_budget > 300 and relevant:
            excerpts: List[str] = []
            for rel in relevant[:3]:  # Max 3 file snippets
                target = self.root / rel
                if not target.exists() or not target.is_file():
                    continue
                if is_sensitive_credential_path(target):
                    continue
                try:
                    size = target.stat().st_size
                    if size > MAX_FILE_SIZE:
                        # Large file: read top lines only
                        text = target.read_text(encoding="utf-8", errors="ignore")[:600]
                    else:
                        text = target.read_text(encoding="utf-8", errors="ignore")[:600]

                    clean_text = text.strip()
                    if clean_text:
                        excerpt = f"\n--- {rel} ---\n{clean_text}"
                        if len("\n".join(excerpts) + excerpt) <= remaining_budget:
                            excerpts.append(excerpt)
                        else:
                            break
                except Exception:
                    pass

            if excerpts:
                header_text += "\n\nFILE CONTEXT:" + "".join(excerpts)

        return header_text[:MAX_CONTEXT_CHARS]
