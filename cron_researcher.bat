@echo off
chcp 65001 > nul
cd /d C:\Users\Park\Documents\ClaudeCode\morning-report

set LOG=cron_researcher.log
echo === %date% %time% === >> %LOG%

git pull --rebase origin master >> %LOG% 2>&1
if errorlevel 1 (
  echo PULL FAILED >> %LOG%
  exit /b 1
)

for /f "delims=" %%a in ('git rev-parse HEAD') do set CURRENT=%%a
set LAST=
if exist .cron_last_commit (
  for /f "delims=" %%a in (.cron_last_commit) do set LAST=%%a
)
if "%CURRENT%"=="%LAST%" (
  echo no new commits >> %LOG%
  exit /b 0
)

claude --print "Read .prompt_researcher.txt and follow it" --append-system-prompt-file HANDOFF_QUICK.md --allowedTools "Bash(git:*) Read Edit Write Glob Grep" >> %LOG% 2>&1
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
  git commit -m "auto: researcher analysis" >> %LOG% 2>&1
  git push origin master >> %LOG% 2>&1
  if errorlevel 1 (
    echo PUSH FAILED >> %LOG%
    exit /b 1
  )
)

echo %CURRENT% > .cron_last_commit
echo done >> %LOG%
