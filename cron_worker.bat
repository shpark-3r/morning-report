@echo off
chcp 65001 > nul
cd /d C:\Users\Home\Documents\ClaudeCode\morning-report

set LOG=cron_worker.log
echo === %date% %time% === >> %LOG%

git pull --rebase origin master >> %LOG% 2>&1
if errorlevel 1 (
  echo PULL FAILED >> %LOG%
  exit /b 1
)

claude --print "Read .prompt_worker.txt and follow it" --append-system-prompt-file HANDOFF_QUICK.md --allowedTools "Bash(git:*) Read Edit Write Glob Grep" >> %LOG% 2>&1
if errorlevel 1 (
  echo CLAUDE FAILED >> %LOG%
  exit /b 1
)

git diff --quiet
set DIRTY1=%errorlevel%
git diff --cached --quiet
set DIRTY2=%errorlevel%
if "%DIRTY1%%DIRTY2%" neq "00" (
  git add -A
  git commit -m "auto: worker update" >> %LOG% 2>&1
  git push origin master >> %LOG% 2>&1
  if errorlevel 1 (
    echo PUSH FAILED >> %LOG%
    exit /b 1
  )
)

echo done >> %LOG%
