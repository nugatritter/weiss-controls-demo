ARG BASE_IMAGE=localhost/weiss-api-upstream:latest
FROM ${BASE_IMAGE}

ARG WEISS_GIT_TIMEOUT_SECONDS=180
ENV WEISS_GIT_TIMEOUT_SECONDS=${WEISS_GIT_TIMEOUT_SECONDS}

USER root
RUN python - <<'PY'
from pathlib import Path
import re

candidates = sorted(Path('/venv/lib').glob('python*/site-packages/api/repos/staging.py'))
if not candidates:
    raise SystemExit('api/repos/staging.py not found in image')

path = candidates[0]
text = path.read_text(encoding='utf-8')
orig = text

# Keep patch idempotent across rebuilds.
if 'import os' not in text:
    text = text.replace('import logging', 'import logging\nimport os', 1)

text = re.sub(
    r"timeout:\s*int\s*=\s*30,",
    "timeout: int | None = None,",
    text,
    count=1,
)
text = text.replace('def run_git(command, cwd=None, timeout=30):', 'def run_git(command, cwd=None, timeout=None):')

marker = '    try:\n        result = subprocess.run('
injection = (
    '    if timeout is None:\n'
    '        timeout = int(os.getenv("WEISS_GIT_TIMEOUT_SECONDS", "180"))\n\n'
    '    try:\n        result = subprocess.run('
)
if 'WEISS_GIT_TIMEOUT_SECONDS' not in text:
    text = re.sub(
        r'(\s+"""Run git command[^\n]*"""\n)\s+try:\n',
        r'\1    if timeout is None:\n        timeout = int(os.getenv("WEISS_GIT_TIMEOUT_SECONDS", "180"))\n\n    try:\n',
        text,
        count=1,
    )
if marker in text and 'WEISS_GIT_TIMEOUT_SECONDS' not in text:
    text = text.replace(marker, injection, 1)

if text != orig:
    path.write_text(text, encoding='utf-8')

print(f'Patched {path}')
PY


USER 1001
