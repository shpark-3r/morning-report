# 연구원 ↔ 워커 협업 (4/10 00시 시작)

연구원 클로드(이쪽 PC)가 가설/질문 추가 → 워커 클로드(다른 PC)가 답.
워커가 데이터로 검증 → 답을 추가 → 연구원이 다음 가설.

## 형식

```
## Q-N: 질문 제목 (제기일)
**가설**: 
**검증 방법**: 
**우선순위**: 🔴 high / 🟡 mid / 🟢 low

### 워커 답 (YYYY-MM-DD)
- 결과:
- 결론:
```

---

## Q-1: ⭐ 자정 대장코인 가설 (4/9 23:58 사용자 통찰)

**가설**: 매일 00:00~01:00 (KST)에 그날의 "대장코인"이 결정된다. 그 시간대 첫 큰 vol burst 코인이 그날 가장 큰 펌프가 될 가능성이 높다.

**근거**: 사용자 경험 + 데이터 일부 일치
- 4/9 ENJ 00:14~00:30 +56% (vol_x 118x)
- 4/8 SWAP 00:02 (winner)
- 4/5 PYR 00:08 (winner +9.48%)
- 4/4 OGN 00:13, COW 00:05 (winners)

**우리 FP filter는 22-02시 제외** — 사용자 통찰과 충돌. 재검증 필요.

**검증 방법**:
1. 4/10부터 매일 00:00~01:00 burst signal 모니터링 + 청산 결과 기록
2. 30일 1분봉 데이터로 사후: "그날 00:00~01:00 첫 burst 코인" vs "그날 가장 큰 펌프 코인" 일치율
3. 22-02시 vs 다른 시간대 win rate / EV 비교 (FP filter 재검증)

**우선순위**: 🔴 high

### 워커 답
- (워커가 매일 자정 ~ 1시 결과 채우기)

---

## Q-2: 호가창 슬리피지 실측

**가설**: 시뮬에서 0.3% 슬리피지 가정은 낙관적. 실제는 1~3%. 이게 EV의 결정자.

**검증 방법**:
1. live_pump_scanner가 신호 발생 시 빗썸 orderbook 호출
2. 5만/10만/50만/100만 KRW 매수 시 평균 체결가 계산
3. 5분 후 같은 깊이 매도 시 평균 체결가
4. round-trip 슬리피지 기록

**우선순위**: 🔴 high

### 워커 답
- 

---

## Q-3: Claude judgment vs adaptive trailing 비교

**가설**: Claude가 차트 보고 판단하면 단순 D adaptive trailing(EV +1.49%)보다 EV 높을 것.

**검증 방법**:
1. 77건 strict immediate burst 신호 각각의 차트 텍스트 생성
2. Claude API로 "진입 GO/SKIP + 청산 시점" 판단
3. Claude 판단대로 시뮬 결과 vs D adaptive trailing 비교

**우선순위**: 🟡 mid

### 워커 답
- 

---

## Q-4: TRAC/XTER 1~2분 폭발 타입은 진짜 못 잡는가?

**사용자 명시 제외**지만 검증 가치는 있음.

**가설**: 1~2분 폭발 코인은 진입 슬리피지 5%+, 청산 슬리피지 5%+ → trade 불가.

**검증 방법**:
- TRAC 사례 직접 분석. 호가창 깊이 측정.

**우선순위**: 🟢 low (사용자 제외)

### 워커 답
- 

---

## Q-5: 매일 신호의 일별 EV 분포

**가설**: 평균 EV +1.49%지만 변동성 매우 큼. 어떤 day는 +5%, 어떤 day는 -3%.

**검증 방법**:
- 77건 결과를 일별로 합산. boom day vs normal day 분리.

**우선순위**: 🟡 mid

### 워커 답
- 

---

## 협업 흐름

### 워커 클로드 (저쪽 PC)
1. 세션 시작 시: `git pull`
2. `RESEARCH_QUESTIONS.md` 읽고 답할 수 있는 것 처리
3. 매일 23:30쯤: `WORKER_LOG.md`에 그날 결과 append
4. `daily_results/YYYY-MM-DD.json`에 구조화된 데이터 저장
5. 새 발견이나 질문 → `WORKER_LOG.md`의 "질문" 섹션
6. `git add . && git commit && git push`

### 연구원 클로드 (이쪽 PC)
1. 세션 시작 시: `git pull`
2. `WORKER_LOG.md` 최신 entry 읽기
3. `daily_results/` 분석
4. 새 가설 / 개선점 → `RESEARCH_QUESTIONS.md`에 추가
5. 또는 직접 코드 commit으로 워커에게 새 도구 제공
6. `git push`
