"""Git Intelligence tools — safe repository management for coding projects.

Provides safe, structured Git and GitHub operations operating strictly within
the active workspace, guarded by security policies, secret scanning, and approval gates.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from axon.tools.filesystem import get_current_workspace, resolve_path
from axon.security.secrets import redact_text


# Destructive flags and arguments forbidden across all Git tools
FORBIDDEN_FLAGS = [
    "--force",
    "-f",
    "--hard",
    "-D",
    "-d",
    "--delete",
]

SENSITIVE_FILE_PATTERNS = [
    r"^\.env(?:\..+)?$",
    r".*\.pem$",
    r".*\.key$",
    r".*\.pfx$",
    r".*\.p12$",
    r".*id_rsa(?:\..+)?$",
    r".*id_ed25519(?:\..+)?$",
    r".*id_ecdsa(?:\..+)?$",
    r"^secrets?\.(?:json|yaml|yml|xml)$",
    r"^credentials?\.(?:json|yaml|yml|xml)$",
]


def _get_target_workspace(workspace_override: Optional[str] = None) -> Path:
    """Resolve target workspace directory."""
    if workspace_override:
        return resolve_path(workspace_override)
    return get_current_workspace()


def _run_git(
    args: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 30,
) -> Tuple[int, str, str]:
    """Execute a git command with timeout and error capture.
    
    Returns:
        (returncode, stdout, stderr)
    """
    target_dir = cwd or get_current_workspace()
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Git command timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", "Git executable not found on system PATH"
    except Exception as e:
        return -1, "", f"Git execution failed: {str(e)}"


def is_git_repo(cwd: Optional[Path] = None) -> bool:
    """Check if directory is inside a valid git repository."""
    code, out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return code == 0 and out.lower() == "true"


def git_status(workspace: Optional[str] = None) -> Dict[str, Any]:
    """Inspect Git repository status: branch, tracking, staged, unstaged, and untracked files."""
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {
            "success": False,
            "error": f"Directory '{cwd}' is not a Git repository.",
            "is_git_repo": False,
        }

    # 1. Branch and tracking info
    code, out, err = _run_git(["status", "--porcelain=v1", "-b"], cwd=cwd)
    if code != 0:
        return {"success": False, "error": err or "Failed to read git status"}

    lines = out.splitlines()
    branch_line = lines[0] if lines else "## No branch"
    file_lines = lines[1:] if len(lines) > 1 else []

    # Parse branch line: ## main...origin/main [ahead 1, behind 2] or ## HEAD (no commits yet)
    branch = "unknown"
    tracking = None
    ahead = 0
    behind = 0

    if branch_line.startswith("## "):
        b_info = branch_line[3:]
        if "..." in b_info:
            parts = b_info.split("...")
            branch = parts[0].strip()
            rest = parts[1].strip()
            if " " in rest:
                tracking_part, status_part = rest.split(" ", 1)
                tracking = tracking_part.strip()
                m_ahead = re.search(r"ahead\s+(\d+)", status_part)
                m_behind = re.search(r"behind\s+(\d+)", status_part)
                if m_ahead:
                    ahead = int(m_ahead.group(1))
                if m_behind:
                    behind = int(m_behind.group(1))
            else:
                tracking = rest.strip()
        else:
            branch = b_info.split(" ")[0].strip()

    staged: List[Dict[str, str]] = []
    unstaged: List[Dict[str, str]] = []
    untracked: List[str] = []

    for line in file_lines:
        if len(line) < 3:
            continue
        index_status = line[0]
        worktree_status = line[1]
        file_path = line[3:].strip()

        if index_status == "?" and worktree_status == "?":
            untracked.append(file_path)
            continue

        if index_status not in (" ", "?"):
            staged.append({"path": file_path, "status": index_status})

        if worktree_status not in (" ", "?"):
            unstaged.append({"path": file_path, "status": worktree_status})

    is_clean = len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
    summary = f"On branch '{branch}'. "
    if is_clean:
        summary += "Working tree clean."
    else:
        summary += f"{len(staged)} staged, {len(unstaged)} unstaged, {len(untracked)} untracked."

    return {
        "success": True,
        "is_git_repo": True,
        "branch": branch,
        "tracking": tracking,
        "ahead": ahead,
        "behind": behind,
        "is_clean": is_clean,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "summary": summary,
    }


def git_diff(
    staged: bool = False,
    file_path: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspect unstaged or staged git changes with context."""
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    cmd = ["diff"]
    if staged:
        cmd.append("--cached")
    if file_path:
        cmd.extend(["--", file_path])

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {"success": False, "error": err or "Failed to execute git diff"}

    lines_added = len(re.findall(r"^\+[^+]", out, re.MULTILINE))
    lines_removed = len(re.findall(r"^-[^-]", out, re.MULTILINE))

    return {
        "success": True,
        "staged": staged,
        "file": file_path,
        "diff": out,
        "has_changes": bool(out.strip()),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "summary": f"+{lines_added} / -{lines_removed} lines changed" if out.strip() else "No changes",
    }


def git_log(
    limit: int = 10,
    file_path: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """View structured commit history."""
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    max_commits = min(max(1, limit), 50)
    cmd = ["log", f"-n{max_commits}", "--format=%H|%h|%an|%ae|%ad|%s", "--date=short"]
    if file_path:
        cmd.extend(["--", file_path])

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        if "does not have any commits yet" in err.lower() or "fatal: your current branch" in err.lower():
            return {"success": True, "commits": [], "count": 0, "summary": "No commits yet in this repository."}
        return {"success": False, "error": err or "Failed to retrieve git log"}

    commits = []
    for line in out.splitlines():
        parts = line.split("|", 5)
        if len(parts) == 6:
            commits.append({
                "commit": parts[0],
                "short_hash": parts[1],
                "author": parts[2],
                "email": parts[3],
                "date": parts[4],
                "subject": parts[5],
            })

    return {
        "success": True,
        "commits": commits,
        "count": len(commits),
        "summary": f"Retrieved {len(commits)} commits",
    }


def _is_sensitive_path(path_str: str) -> bool:
    """Check if filename or relative path is sensitive."""
    basename = os.path.basename(path_str).lower()
    for pattern in SENSITIVE_FILE_PATTERNS:
        if re.match(pattern, basename, re.IGNORECASE):
            return True
    return False


def git_commit(
    message: str,
    files: Optional[List[str]] = None,
    stage_all: bool = False,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit changes to Git with pre-commit secret scanning and changed files inspection.
    
    ALWAYS requires human approval via Security Policy.
    """
    if not message or not message.strip():
        return {"success": False, "error": "Commit message cannot be empty."}

    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    # 1. Stage requested files if any
    if files:
        for f in files:
            clean_f = f.strip()
            if _is_sensitive_path(clean_f):
                return {
                    "success": False,
                    "error": f"BLOCKED: Cannot stage sensitive credential file '{clean_f}'.",
                }
        code, _, err = _run_git(["add", *files], cwd=cwd)
        if code != 0:
            return {"success": False, "error": f"Failed to stage files: {err}"}
    elif stage_all:
        code, _, err = _run_git(["add", "-A"], cwd=cwd)
        if code != 0:
            return {"success": False, "error": f"Failed to stage all changes: {err}"}

    # 2. Inspect staged files
    code, staged_out, err = _run_git(["diff", "--cached", "--name-status"], cwd=cwd)
    if code != 0:
        return {"success": False, "error": f"Failed to inspect staged files: {err}"}

    if not staged_out.strip():
        return {
            "success": False,
            "error": "No changes staged for commit. Stage files first or use stage_all=True.",
        }

    staged_files: List[Dict[str, str]] = []
    for line in staged_out.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            status, path = parts[0], parts[1]
            # Sensitive file check
            if _is_sensitive_path(path):
                return {
                    "success": False,
                    "error": f"BLOCKED: Sensitive file '{path}' is staged for commit. Remove it before committing.",
                }
            staged_files.append({"status": status, "path": path})

    # 3. Secret scanning on staged diff
    code, diff_out, _ = _run_git(["diff", "--cached"], cwd=cwd)
    if code == 0 and diff_out:
        _, was_redacted = redact_text(diff_out)
        if was_redacted:
            return {
                "success": False,
                "error": "BLOCKED: Staged changes contain sensitive credentials (API key, token, or private key). Commit aborted.",
            }

    # 4. Perform the commit
    code, commit_out, commit_err = _run_git(["commit", "-m", message.strip()], cwd=cwd)
    if code != 0:
        return {
            "success": False,
            "error": commit_err or commit_out or "Git commit failed.",
            "staged_files": staged_files,
        }

    # 5. Extract short commit hash
    _, rev_out, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)

    return {
        "success": True,
        "commit_hash": rev_out.strip(),
        "message": message.strip(),
        "changed_files": staged_files,
        "files_count": len(staged_files),
        "output": commit_out,
        "summary": f"Created commit {rev_out.strip()} with {len(staged_files)} file(s).",
    }


def git_branch(
    name: Optional[str] = None,
    list_all: bool = False,
    delete: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """List local/remote branches or create a new branch. Destructive branch deletion is blocked."""
    if delete:
        return {
            "success": False,
            "error": "BLOCKED: Deleting branches via AXON is strictly blocked to prevent accidental code loss.",
        }

    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    # Check for destructive flags in branch name
    if name:
        clean_name = name.strip()
        for forbidden in FORBIDDEN_FLAGS:
            if forbidden in clean_name.split():
                return {"success": False, "error": f"BLOCKED: Forbidden flag '{forbidden}' in branch command."}

        # Create new branch
        code, out, err = _run_git(["branch", clean_name], cwd=cwd)
        if code != 0:
            return {"success": False, "error": err or f"Failed to create branch '{clean_name}'."}
        return {
            "success": True,
            "created": clean_name,
            "summary": f"Created new branch '{clean_name}'.",
        }

    # List branches
    cmd = ["branch", "--list"]
    if list_all:
        cmd.append("-a")

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {"success": False, "error": err or "Failed to list branches."}

    current = "unknown"
    branches = []
    for line in out.splitlines():
        clean = line.strip()
        if clean.startswith("* "):
            current = clean[2:].strip()
            branches.append(current)
        elif clean:
            branches.append(clean)

    return {
        "success": True,
        "current": current,
        "branches": branches,
        "count": len(branches),
        "summary": f"Current branch: '{current}' ({len(branches)} total).",
    }


def git_checkout(
    target: str,
    create: bool = False,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely switch or create a branch. Destructive whole-repo checkout is blocked."""
    if not target or not target.strip():
        return {"success": False, "error": "Target branch or commit must be specified."}

    clean_target = target.strip()

    # Block destructive wipe command
    if clean_target in (".", "-- .") or clean_target.startswith("-- "):
        return {
            "success": False,
            "error": "BLOCKED: Destructive checkout discarding all workspace changes is blocked.",
        }

    for forbidden in FORBIDDEN_FLAGS:
        if forbidden in clean_target.split():
            return {"success": False, "error": f"BLOCKED: Forbidden flag '{forbidden}' in checkout command."}

    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    cmd = ["checkout"]
    if create:
        cmd.append("-b")
    cmd.append(clean_target)

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {"success": False, "error": err or out or f"Failed to checkout '{clean_target}'."}

    return {
        "success": True,
        "branch": clean_target,
        "created": create,
        "output": out or err,
        "summary": f"Switched to branch '{clean_target}'." if not create else f"Created and switched to branch '{clean_target}'.",
    }


def git_switch(
    branch: str,
    create: bool = False,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely switch branches using git switch."""
    if not branch or not branch.strip():
        return {"success": False, "error": "Branch name must be specified."}

    clean_branch = branch.strip()
    for forbidden in FORBIDDEN_FLAGS:
        if forbidden in clean_branch.split():
            return {"success": False, "error": f"BLOCKED: Forbidden flag '{forbidden}' in switch command."}

    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    cmd = ["switch"]
    if create:
        cmd.append("-c")
    cmd.append(clean_branch)

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {"success": False, "error": err or out or f"Failed to switch to branch '{clean_branch}'."}

    return {
        "success": True,
        "branch": clean_branch,
        "created": create,
        "output": out or err,
        "summary": f"Switched to branch '{clean_branch}'.",
    }


def git_pull(
    remote: str = "origin",
    branch: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull changes from remote repository. Refuses to pull if uncommitted local changes exist."""
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    # Check for uncommitted changes to avoid clobbering local work
    code, status_out, _ = _run_git(["status", "--porcelain"], cwd=cwd)
    if code == 0 and status_out.strip():
        # Check if there are staged or unstaged modifications
        has_modifications = False
        for line in status_out.splitlines():
            if not line.startswith("??"):
                has_modifications = True
                break
        if has_modifications:
            return {
                "success": False,
                "error": "Cannot pull: you have uncommitted local changes that might be overwritten. Please commit or stash them first.",
            }

    cmd = ["pull", remote.strip()]
    if branch:
        cmd.append(branch.strip())

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {
            "success": False,
            "error": err or out or "Git pull failed.",
            "output": out,
        }

    return {
        "success": True,
        "remote": remote,
        "branch": branch,
        "output": out,
        "summary": "Successfully pulled remote updates." if "up to date" not in out.lower() else "Already up to date.",
    }


def git_push(
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    force: bool = False,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Push committed changes to a remote repository.
    
    ALWAYS requires explicit human approval via Security Policy.
    NEVER allows force-pushing.
    """
    if force:
        return {
            "success": False,
            "error": "BLOCKED: Force pushing is strictly forbidden in AXON.",
        }

    # Verify remote and branch strings do not contain force flags or refspec force '+'
    clean_remote = remote.strip()
    clean_branch = branch.strip() if branch else ""

    combined_check = f"{clean_remote} {clean_branch}"
    for forbidden in ("--force", "-f", "--force-with-lease", "+"):
        if forbidden in combined_check.split() or forbidden in combined_check:
            return {
                "success": False,
                "error": f"BLOCKED: Forbidden force flag or refspec '{forbidden}' in git push.",
            }

    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    cmd = ["push"]
    if set_upstream:
        cmd.append("-u")
    cmd.append(clean_remote)
    if clean_branch:
        cmd.append(clean_branch)

    code, out, err = _run_git(cmd, cwd=cwd)
    if code != 0:
        return {
            "success": False,
            "error": err or out or "Git push failed.",
            "output": out,
        }

    return {
        "success": True,
        "remote": clean_remote,
        "branch": clean_branch or "HEAD",
        "output": out or err,
        "summary": f"Successfully pushed commits to {clean_remote}.",
    }


def git_info(workspace: Optional[str] = None) -> Dict[str, Any]:
    """Detect repository details, current status, and GitHub remote information."""
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {
            "success": False,
            "is_git_repo": False,
            "error": f"Directory '{cwd}' is not a Git repository.",
        }

    # 1. Remote URLs
    code, remotes_out, _ = _run_git(["remote", "-v"], cwd=cwd)
    remotes: Dict[str, Dict[str, str]] = {}
    github_info: Optional[Dict[str, Any]] = None

    if code == 0 and remotes_out.strip():
        for line in remotes_out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                r_name, r_url, r_type = parts[0], parts[1], parts[2].strip("()")
                if r_name not in remotes:
                    remotes[r_name] = {}
                remotes[r_name][r_type] = r_url

                # Detect GitHub
                if "github.com" in r_url.lower():
                    # Parse owner and repo from URL
                    # SSH: git@github.com:owner/repo.git
                    # HTTPS: https://github.com/owner/repo.git
                    m = re.search(r"github\.com[:/]([\w\-]+)/([\w\-.]+?)(?:\.git)?$", r_url, re.IGNORECASE)
                    if m:
                        owner = m.group(1)
                        repo = m.group(2).rstrip(".git")
                        github_info = {
                            "owner": owner,
                            "repo": repo,
                            "url": f"https://github.com/{owner}/{repo}",
                            "clone_url": r_url,
                        }

    # 2. Current branch & commit
    _, current_branch, _ = _run_git(["branch", "--show-current"], cwd=cwd)
    _, head_commit, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=cwd)
    _, commit_msg, _ = _run_git(["log", "-1", "--format=%s"], cwd=cwd)

    # 3. Status summary
    st = git_status(workspace=str(cwd))

    return {
        "success": True,
        "is_git_repo": True,
        "workspace": str(cwd),
        "branch": current_branch.strip() or "HEAD (detached)",
        "head_commit": head_commit.strip(),
        "last_commit_message": commit_msg.strip(),
        "is_clean": st.get("is_clean", True) if st.get("success") else True,
        "remotes": remotes,
        "github": github_info,
        "is_github": github_info is not None,
        "summary": f"Repo on branch '{current_branch.strip()}'. GitHub: {github_info['url'] if github_info else 'No GitHub remote detected'}.",
    }


def git_safe_rollback(
    commit: Optional[str] = None,
    file_path: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely roll back changes using Git without destructive hard resets or clean -f.
    
    Options:
    - file_path: Discard uncommitted changes to a specific file safely (checkout HEAD -- <file>).
    - commit: Safely revert an existing commit using git revert --no-edit <commit>.
    """
    cwd = _get_target_workspace(workspace)
    if not is_git_repo(cwd):
        return {"success": False, "error": f"Directory '{cwd}' is not a Git repository."}

    if not commit and not file_path:
        return {
            "success": False,
            "error": "Specify either 'file_path' to revert a single file or 'commit' to revert a commit.",
        }

    # 1. Revert specific file changes
    if file_path:
        clean_file = file_path.strip()
        if _is_sensitive_path(clean_file):
            return {"success": False, "error": "BLOCKED: Cannot perform git operations on sensitive credential paths."}

        # Forbid wildcard wipe or destructive path
        if clean_file in (".", "*", "-- ."):
            return {
                "success": False,
                "error": "BLOCKED: Destructive wipe of entire workspace is blocked. Provide a specific file path.",
            }

        code, out, err = _run_git(["checkout", "HEAD", "--", clean_file], cwd=cwd)
        if code != 0:
            return {"success": False, "error": err or f"Failed to restore file '{clean_file}'."}

        return {
            "success": True,
            "file": clean_file,
            "action": "reverted_file",
            "summary": f"Safely restored '{clean_file}' to HEAD state.",
        }

    # 2. Revert commit via git revert
    if commit:
        clean_commit = commit.strip()
        for forbidden in FORBIDDEN_FLAGS:
            if forbidden in clean_commit.split():
                return {"success": False, "error": f"BLOCKED: Forbidden flag '{forbidden}'."}

        code, out, err = _run_git(["revert", "--no-edit", clean_commit], cwd=cwd)
        if code != 0:
            return {
                "success": False,
                "error": err or out or f"Failed to revert commit '{clean_commit}'.",
            }

        return {
            "success": True,
            "commit": clean_commit,
            "action": "revert_commit",
            "output": out,
            "summary": f"Safely reverted commit '{clean_commit}'.",
        }

    return {"success": False, "error": "Invalid rollback parameters."}
