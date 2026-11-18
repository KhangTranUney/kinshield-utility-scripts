#!/usr/bin/env python3
"""Fast-forward local tracking branches in the configured repositories.

Run: python3 utilities/pull_latest_branches.py
Failures are printed at the end of the run.

Steps:
1. Check each configured repository and list its local branches and worktrees.
2. Fetch each required remote once and find each branch's tracking upstream.
3. Fast-forward eligible branches without switching the current checkout.
4. Skip failures, continue with the remaining branches, and print a summary.

Only existing local branches with remote tracking upstreams are updated; remote
branches are not created locally. Fetching updates remote-tracking refs, while
fast-forwarding moves a local branch only when its commits are all in the new tip.
Branches with local-only commits, missing upstreams, failed fetches, or branches
checked out in another worktree are reported as failures. The current worktree
may be changed by Git when its checked-out branch is fast-forwarded.
"""

import subprocess
import sys
from pathlib import Path

REPOSITORIES = [
    '/Users/khang.tm/qualgo-macbook/devops-mobile-assets',
    '/Users/khang.tm/qualgo-macbook/kinsense-android',
    '/Users/khang.tm/qualgo-macbook/sdk-in-app-event-android-tracker',
    '/Users/khang.tm/qualgo-macbook/shieldnet360-android',
    '/Users/khang.tm/qualgo-macbook/strazee-android',
    '/Users/khang.tm/qualgo-macbook/safenest/core-app-debug',
    '/Users/khang.tm/qualgo-macbook/safenest/core-design-system-config',
    '/Users/khang.tm/qualgo-macbook/safenest/core-foundation-android',
    '/Users/khang.tm/qualgo-macbook/safenest/core-foundation-version-android',
    '/Users/khang.tm/qualgo-macbook/safenest/core-plugin-android',
    '/Users/khang.tm/qualgo-macbook/safenest/core-script-android',
    '/Users/khang.tm/qualgo-macbook/safenest/core-template-android',
    '/Users/khang.tm/qualgo-macbook/safenest/kinshield-android',
    '/Users/khang.tm/qualgo-macbook/safenest/kinshield-core-features-android',
    '/Users/khang.tm/qualgo-macbook/safenest/kinshield-features-version-android',
    '/Users/khang.tm/qualgo-macbook/safenest/livevpn-android',
    '/Users/khang.tm/qualgo-macbook/safenest/livevpn-infra',
    '/Users/khang.tm/qualgo-macbook/safenest/livevpn-plugin',
    '/Users/khang.tm/qualgo-macbook/safenest/local-ai-plarform-workspaces',
    '/Users/khang.tm/qualgo-macbook/safenest/pyffe-android',
]


def git(repo, *args):
    # Keep stdout and stderr available to the caller so a failed command can be
    # reported without terminating the entire batch. Pass arguments separately
    # rather than through a shell, including branch names and paths.
    return subprocess.run(['git', *args], cwd=repo, text=True, capture_output=True)


def error(result):
    # Git normally describes errors on stderr, but some commands use stdout.
    # Include the exit code if neither stream contains a useful message.
    return (result.stderr or result.stdout).strip() or f'exit code {result.returncode}'


def process(repo, failures):
    def fail(branch, message):
        # Log immediately for progress visibility and retain the same details
        # for the final summary, including the repository and branch involved.
        entry = f'{repo} [{branch}]: {message}'
        failures.append(entry)
        print(f'  {branch} -> FAIL: {message}', flush=True)

    # Require the configured path itself to be a repository root. Otherwise Git
    # could discover a parent repository and update branches in the wrong place.
    if not repo.is_dir():
        fail('repository', 'directory does not exist')
        return
    result = git(repo, 'rev-parse', '--show-toplevel')
    if result.returncode or Path(result.stdout.strip()).resolve() != repo.resolve():
        fail('repository', 'not a Git repository root')
        return

    # Enumerate local branches only. NUL separators distinguish the branch name,
    # full upstream ref and configured remote even when names contain spaces.
    # Full upstream refs allow local and remote branch names to differ.
    result = git(repo, 'for-each-ref', '--format=%(refname:short)%00%(upstream)%00%(upstream:remotename)', 'refs/heads')
    if result.returncode:
        fail('repository', error(result))
        return
    branches = [line.split('\0') for line in result.stdout.splitlines()]
    # A branch checked out in another worktree must not be moved behind that
    # worktree's back. Identify the current worktree's branch separately; a
    # detached HEAD has no current branch and can still update unoccupied refs.
    worktrees = git(repo, 'worktree', 'list', '--porcelain')
    if worktrees.returncode:
        fail('repository', error(worktrees))
        return
    checked_out = {line[7:] for line in worktrees.stdout.splitlines() if line.startswith('branch ')}
    head = git(repo, 'symbolic-ref', '-q', 'HEAD')
    current = head.stdout.strip() if head.returncode == 0 else None
    # Cache successes and failures: all branches sharing a remote use one fetch.
    fetch_results = {}
    for name, upstream, remote in branches:
        # A local upstream (remote '.') is not a remote pull target. Missing
        # tracking configuration is also a failure, rather than guessing origin.
        if not upstream or not remote or remote == '.':
            fail(name, 'no remote tracking upstream configured')
            continue
        if remote not in fetch_results:
            fetch_results[remote] = git(repo, 'fetch', '--', remote)
        fetched = fetch_results[remote]
        if fetched.returncode:
            fail(name, f'fetch {remote} failed: {error(fetched)}')
            continue
        # Skip branches checked out in a different worktree, even if their
        # upstream is already current, to avoid touching its checkout.
        local_ref = f'refs/heads/{name}'
        if local_ref in checked_out and local_ref != current:
            fail(name, 'branch is checked out in another worktree')
            continue
        # Resolve both refs after fetch. A deleted or inaccessible upstream may
        # still be configured, so report resolution errors for this branch.
        old = git(repo, 'rev-parse', '--verify', local_ref)
        target = git(repo, 'rev-parse', '--verify', upstream)
        if old.returncode or target.returncode:
            fail(name, f'cannot resolve branch or upstream: {error(old if old.returncode else target)}')
            continue
        old_sha, target_sha = old.stdout.strip(), target.stdout.strip()
        if old_sha == target_sha:
            print(f'  {name} -> Already up to date.', flush=True)
            continue
        # Fast-forward only if the existing local tip is an ancestor of the
        # upstream tip. A diverged or ahead branch needs manual resolution.
        ancestor = git(repo, 'merge-base', '--is-ancestor', old_sha, target_sha)
        if ancestor.returncode:
            fail(name, 'cannot fast-forward (branch may have local commits)' if ancestor.returncode == 1 else error(ancestor))
            continue
        if local_ref == current:
            # Git updates the working tree and rejects conflicting local changes.
            result = git(repo, 'merge', '--ff-only', target_sha)
        else:
            # Update an unoccupied branch without checking it out; old_sha guards
            # against overwriting a concurrent change to the branch.
            result = git(repo, 'update-ref', '-m', f'fast-forward {name} from {upstream}', local_ref, target_sha, old_sha)
        if result.returncode:
            fail(name, error(result))
        else:
            print(f'  {name} -> Updated.', flush=True)


def main():
    failures = []
    for repo_path in REPOSITORIES:
        repo = Path(repo_path)
        print(f'\n[{repo}]', flush=True)
        try:
            process(repo, failures)
        # Filesystem and process-launch errors should not prevent later
        # repositories from being processed or omitted from the summary.
        except (OSError, ValueError) as exc:
            failures.append(f'{repo} [repository]: {exc}')
            print(f'  repository -> FAIL: {exc}', flush=True)
    summary = 'Failed operations:\n' + ('\n'.join(failures) if failures else 'None') + '\n'
    print('\n' + summary)
    # A nonzero exit code lets callers detect a partial or complete failure.
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
