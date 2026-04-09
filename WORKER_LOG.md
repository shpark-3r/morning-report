# 워커 클로드 작업 로그

매일 워커가 한 일, 발견, 질문을 append.
연구원 클로드(다른 PC)가 git pull로 읽음.

## 형식

```
## YYYY-MM-DD HH:MM (worker: claude-sonnet-4-6 / claude-opus-4-6)

### 한 일
- 

### 발견
- 

### 질문 / 의사결정 필요
- 

### 다음 작업
- 
```

---

## 2026-04-10 00:30 (worker: claude-opus-4-6)

### 한 일
- 세션 재개. `git pull` 완료 (b4e18cb..cbb3a81)
- HANDOFF_QUICK.md, RESEARCH_QUESTIONS.md, WORKER_LOG.md 전부 읽음
- 4/10 자정 실제 매매 검증 (Q-6): GRND 데이터 완전 복구
- daily_results/2026-04-10.json 작성 (첫 데이터 포인트)

### 발견 — ⭐ Q-1 자정 대장코인 가설 첫 실증
- **코인: GRND (한글명 슈퍼워크, English Superwalk)** ← 사용자의 "슈퍼위크"
- **신호 시각: 00:00:42 KST (자정 42초)**
- **신호: vol=82.1x, bar=+5.9%, tv=67M, c24=+0.3% @ 26.25**
- **immediate burst strict 기준 완전 충족 (vol≥20x의 4.1배)**
- **진입 체결 avg 26.53 (매수 슬리피지 +1.07% 실측)**
- **피크 31.00 (+16.85%) → TRAIL sell 30.62 (+15.42%)**
- **홀딩 118초, 순수익 약 101,300원** — 사용자 보고 "+10만" 정확 일치
- 00:02:44 이후 bot_live.log 23시간 내내 scan: quiet — 4/10의 **유일한 burst**

### 발견 — Q-2 슬리피지 실측 (n=1)
- 시그널가 26.25 → 체결 avg 26.53 = **매수 슬리피지 +1.07%**
- 베팅 사이즈 656,897 KRW (중형)
- 가정 0.3%보다 3.5배 큼. 1~3% 레인지의 하단.
- ⚠️ n=1이라 일반화 불가. 매일 쌓아야 함 (Q-7과 연결).

### 발견 — 어제 세션 실패
- realtime_scanner.py v2.2 (내 짜던 거) 어제 16:39 이후 잔고 -27% (968K→706K) 주범
- 4/9 15:26 XTER auto-buy → 난도가 그대로. 후행 지표 + 고점 매수 + 익절 실패 패턴.
- **midnight_bot.py는 반대로 proactive burst trigger로 +15.4% 성공** → 연구원 권고 신호 맞음

### 질문 / 의사결정 필요
- **Q-6 답변 완료** (RESEARCH_QUESTIONS.md). 연구원 확인 부탁.
- **Q-7 일부 실행 중**: live_pump_scanner.py --burst --watch (PID 338644) 어제 밤부터 돌고 있음, midnight_bot.py (PID 37016)가 실전 매매. daily_results/2026-04-10.json 적재 완료.
- **⭐⭐ 치명적 갭 발견**: live_pump_scanner와 midnight_bot의 신호가 불일치
  - live_pump_scanner → 00:01:09 **BOB** 잡음 (vol_x=293x, gain+6.62%, tv=134M) — 오늘 최강 신호
  - midnight_bot → 00:00:42 **GRND** 잡음 (vol_x=82.1x, gain+5.9%, tv=67M) — 실제 매매
  - **BOB는 signal만, midnight_bot이 BOB를 watchlist에 없어 매매 못함**
  - BOB 30분간 다단 펌프 (+15.4% peak @ 00:27), GRND 118초 단발 (+16.85% peak @ 00:02:38)
  - 우연히 두 코인 수익폭 비슷. 내일부터는 live_pump_scanner signals → midnight_bot 실매매 hook 필수.
- **슬리피지 n 늘리기**: 다음 signal마다 시그널가 vs 체결 avg 비교 → daily_results 매 항목에 slippage_buy_pct 필수 필드

### 다음 작업
1. midnight_bot.py 코드 읽고 진입 로직 디핑 (immediate burst strict vs midnight 전용?)
2. live_pump_scanner.py 의 signals 저장 경로 확인 — live_signals_2026-04-10.jsonl 존재 여부
3. 다음 23:30 일일 리포트 때 daily_results/2026-04-10.json 확장 (intraday quiet 결과, 거래 0건 포함)
4. Q-3 (Claude judgment loop) — GRND 차트 스냅 5분봉 4개로 Claude에게 "진입 GO/SKIP + 청산 시점" 물어보는 실험 시작
5. git commit + push (이 entry 포함)

