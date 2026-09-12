"""Path security — normalizes paths, prevents directory traversal, and enforces path boundaries."""

import os
from pathlib import Path
from typing import Tuple, Optional


# Protected credential and sensitive file patterns
SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "credentials",
    "secrets.json",
    "service_account.json",
}

SENSITIVE_EXTENSIONS = {
    ".pem",
    ".key",
    ".pkcs12",
    ".pfx",
}

SENSITIVE_DIR_NAMES = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".azure",
}


def normalize_path(path_str: str, base_dir: Optional[Path] = None) -> Path:
    """Normalize a path by expanding environment variables, user home, and resolving relative segments."""
    if not path_str or str(path_str).strip() in (".", ""):
        if base_dir is not None:
            return base_dir.resolve()
        return Path.cwd().resolve()

    raw = str(path_str).strip()
    expanded = os.path.expandvars(raw)
    expanded = os.path.expanduser(expanded)

    # Common folder aliases
    lower = expanded.lower()
    home = Path.home()
    if lower == "desktop":
        return (home / "Desktop").resolve()
    elif lower == "downloads":
        return (home / "Downloads").resolve()
    elif lower == "documents":
        return (home / "Documents").resolve()

    p = Path(expanded)
    if not p.is_absolute() and base_dir is not None:
        return (base_dir / p).resolve()
    return p.resolve()


def is_system_directory(path: Path) -> bool:
    """Check if path is inside a protected Windows system or startup directory."""
    path_str = str(path).lower()
    system_prefixes = [
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        "c:\\boot",
    ]
    # Check Windows system root
    win_dir = os.environ.get("WINDIR", "C:\\Windows").lower()
    system_prefixes.append(win_dir)

    for prefix in system_prefixes:
        if path_str == prefix or path_str.startswith(prefix + "\\"):
            return True

    # Startup directory
    if "startup" in path_str and ("start menu" in path_str or "microsoft" in path_str):
        return True

    return False


def is_axon_internal_file(path: Path, workspace_root: Optional[Path] = None) -> bool:
    """Check if path is an internal AXON codebase, configuration, or audit file that cannot be modified by AI tools."""
    path_resolved = path.resolve()
    path_str = str(path_resolved).lower()

    # Protected specific filenames
    if path_resolved.name.lower() in (".env", "audit.log", "security.log", "persisted"):
        return True

    # Check if inside .axon audit or configuration directory
    axon_data_dir = (Path.home() / ".axon").resolve()
    try:
        path_resolved.relative_to(axon_data_dir)
        # It's inside ~/.axon - audit logs and internal configs are protected from deletion/modification
        if "audit" in path_str or "security" in path_str:
            return True
    except ValueError:
        pass

    # Check if inside active AXON repository source code
    # We locate the repository root containing axon package
    pkg_dir = Path(__file__).parent.parent.resolve()  # axon/
    repo_root = pkg_dir.parent.resolve()              # Axon/
    try:
        path_resolved.relative_to(pkg_dir)
        return True
    except ValueError:
        pass

    if workspace_root:
        try:
            rel = path_resolved.relative_to(workspace_root.resolve())
            parts = rel.parts
            if parts and parts[0].lower() in ("axon", ".env"):
                return True
        except ValueError:
            pass

    return False


def is_sensitive_credential_path(path: Path) -> bool:
    """Check if path targets credentials, private keys, or secret tokens."""
    path_resolved = path.resolve()
    name = path_resolved.name.lower()

    # Exact filename match
    if name in SENSITIVE_FILENAMES:
        return True

    # Extension match (.pem, .key)
    if path_resolved.suffix.lower() in SENSITIVE_EXTENSIONS:
        return True

    # Inside sensitive directory (.ssh, .aws, .gnupg)
    for part in path_resolved.parts:
        if part.lower() in SENSITIVE_DIR_NAMES:
            return True

    return False


def is_within_workspace(path: Path, workspace_root: Path) -> bool:
    """Check if the given path is strictly within the designated workspace root."""
    try:
        path_resolved = path.resolve()
        ws_resolved = workspace_root.resolve()
        path_resolved.relative_to(ws_resolved)
        return True
    except (ValueError, Exception):
        return False


def check_path_security(
    path_str: str,
    operation: str = "read",  # "read", "write", "delete", "list"
    workspace_root: Optional[Path] = None,
    enforce_workspace: bool = False,
) -> Tuple[bool, str, Path]:
    """Inspect path security for a given operation.
    
    Returns:
        (is_safe, reason, normalized_path)
    """
    if not path_str or not str(path_str).strip():
        return False, "Empty or invalid path provided", Path.cwd()

    try:
        normalized = normalize_path(path_str, base_dir=workspace_root)
    except Exception as e:
        return False, f"Failed to normalize path: {e}", Path.cwd()

    op = operation.lower()

    # Workspace confinement check if requested
    if enforce_workspace and workspace_root is not None:
        if not is_within_workspace(normalized, workspace_root):
            return False, f"Path escapes workspace boundary: {normalized}", normalized

    # 1. AXON self-protection: Modifying/deleting AXON internal code, config, or audit logs is BLOCKED
    if op in ("write", "delete", "move"):
        if is_axon_internal_file(normalized, workspace_root):
            return False, f"Modification of AXON internal file or configuration is blocked: {normalized.name}", normalized

    # 2. Sensitive credential files: Reading private keys or credentials directly is BLOCKED
    if op == "read":
        if is_sensitive_credential_path(normalized):
            return False, f"Direct access to credential or key store is blocked: {normalized.name}", normalized

    # 3. System directories: Modifying/deleting Windows system directories is BLOCKED
    if op in ("write", "delete", "move"):
        if is_system_directory(normalized):
            return False, f"Modification of protected Windows system directory is blocked: {normalized}", normalized

    return True, "Path is allowed", normalized
