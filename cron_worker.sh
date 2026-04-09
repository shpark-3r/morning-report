#!/bin/bash
# 워커 클로드 cron 스크립트 (저쪽 PC)
# 매 10분: git pull → claude 분석 → daily_results / WORKER_LOG.md 업데이트 → push
#
# 등록 (Windows 작업 스케줄러):
#   매 10분 trigger
#   action: bash /c/Users/Home/Documents/ClaudeCode/morning-report/cron_worker.sh

set -e
cd /c/Users/Home/Documents/ClaudeCode/morning-report

LOG=cron_worker.log
echo "=== $(date) ===" >> $LOG

# 1. Pull (rebase)
git pull --rebase origin master >> $LOG 2>&1 || {
  echo "PULL FAILED, abort" >> $LOG
  exit 1
}

# 2. 변경 감지
LAST_PROCESSED_FILE=.cron_last_commit
CURRENT_COMMIT=$(git rev-parse HEAD)
LAST_PROCESSED=$(cat $LAST_PROCESSED_FILE 2>/dev/null || echo "none")

# 워커는 변경 없어도 매매 결과 갱신해야 하므로 항상 실행
# (Researcher와 다름)

# 3. Claude Code CLI 호출
claude --print "$(cat .prompt_worker.txt)" \
  --append-system-prompt "$(cat HANDOFF_QUICK.md)" \
  >> $LOG 2>&1 || {
  echo "CLAUDE FAILED" >> $LOG
  exit 1
}

# 4. 변경 있으면 push
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  git commit -m "auto: worker update $(date +%H:%M)" >> $LOG 2>&1
  git push origin master >> $LOG 2>&1 || {
    echo "PUSH FAILED, will retry next cycle" >> $LOG
    exit 1
  }
fi

echo "$CURRENT_COMMIT" > $LAST_PROCESSED_FILE
echo "done" >> $LOG
