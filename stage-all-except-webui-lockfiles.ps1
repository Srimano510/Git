# Stage every repository change except WebUI dependency manifests/lockfiles.
# Those files stay unstaged even if a previous command staged them.

$ErrorActionPreference = "Stop"

$excluded = @(
    "nanobot/webui/bun.lock",
    "nanobot/webui/package-lock.json",
    "nanobot/webui/package.json"
)

git restore --staged -- $excluded
git add -A -- . `
    ":(exclude)nanobot/webui/bun.lock" `
    ":(exclude)nanobot/webui/package-lock.json" `
    ":(exclude)nanobot/webui/package.json"

git status --short
