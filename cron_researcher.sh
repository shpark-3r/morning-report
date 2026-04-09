#!/bin/bash
# 연구원 클로드 cron 스크립트 (이쪽 PC)
# 매 10분: git pull → claude 분석 → RESEARCH_QUESTIONS.md 업데이트 → push
#
# 등록 (Windows 작업 스케줄러):
#   매 10분 trigger
#   action: bash /c/Users/Park/Documents/ClaudeCode/morning-report/cron_researcher.sh

set -e
cd /c/Users/Park/Documents/ClaudeCode/morning-report

LOG=cron_researcher.log
echo "=== $(date) ===" >> $LOG

# 1. Pull (rebase로 conflict 최소화)
git pull --rebase origin master >> $LOG 2>&1 || {
  echo "PULL FAILED, abort" >> $LOG
  exit 1
}

# 2. 변경 감지: 마지막 처리한 commit hash와 비교
LAST_PROCESSED_FILE=.cron_last_commit
CURRENT_COMMIT=$(git rev-parse HEAD)
LAST_PROCESSED=$(cat $LAST_PROCESSED_FILE 2>/dev/null || echo "none")

if [ "$CURRENT_COMMIT" = "$LAST_PROCESSED" ]; then
  echo "no new commits, skip" >> $LOG
  exit 0
fi

# 3. Claude Code CLI 호출
claude --print "$(cat .prompt_researcher.txt)" \
  --append-system-prompt "$(cat HANDOFF_QUICK.md)" \
  >> $LOG 2>&1 || {
  echo "CLAUDE FAILED" >> $LOG
  exit 1
}

# 4. 변경 있으면 push
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  git commit -m "auto: researcher analysis $(date +%H:%M)" >> $LOG 2>&1
  git push origin master >> $LOG 2>&1 || {
    echo "PUSH FAILED" >> $LOG
    exit 1
  }
fi

# 5. 처리한 commit 기록
echo "$CURRENT_COMMIT" > $LAST_PROCESSED_FILE
echo "done" >> $LOG
