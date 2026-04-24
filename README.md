# S&P 500 Support Buy Alert Scanner

S&P 500 종목 중에서 **HH+HL 상승추세 + higher-low support 재접근** 조건을 만족하는 종목에 매수 알림을 발생시키는 스캐너. Polygon API Starter 플랜(15분 지연)과 GitHub Actions에서 돌아가도록 설계됨.

## 핵심 특징

- **차트 이미지 대신 OHLCV 구조로 계산** — 500종목 스캔을 숫자 연산으로
- **2단계 스캔 분리**: Universe Scan (전체 필터링) → Signal Scan (watchlist만 재확인)
- **Grouped Daily 엔드포인트**: 일봉 500종목을 **API 호출 1번**으로 받음
- **증분 캐시**: `data/bars.csv`에 저장해서 다음 실행은 누락된 날짜만 fetch
- **Type A (higher_low) 우선 + Type B (breakout_retest) 보조 모니터링**
- **Telegram 알림** (선택) + `out/signals_<날짜>.csv` 저장

## 빠른 시작

### 1. 로컬에서 돌려보기

```bash
git clone <your-repo>
cd sp500-support-scanner
pip install -r requirements.txt

# 로직 검증 (API 키 불필요)
python -m tests.test_pipeline         # pivot/trend/support/signal 파이프라인
python -m tests.test_scoring          # scoring 산식 회귀 테스트
python -m tests.test_universe_loader  # ticker.txt 파싱
python -m tests.test_notifier         # 텔레그램 포맷팅/청크 (네트워크 없음)
python -m tests.test_e2e              # 전체 E2E (기본 min_score로 valid signal 통과)

# 스캔 대상 티커 편집 (루트의 ticker.txt, 한 줄에 하나씩)
#   # 주석과 빈 줄 OK
#   AAPL
#   MSFT
#   BRK.B       # class-share는 점 그대로

# 실제 실행
export POLYGON_API_KEY="your_key_here"
python -m src.scan_universe     # 1) 전체 스캔 → watchlist
python -m src.scan_signals      # 2) watchlist에서 신호 탐지
```

결과는 `out/signals_<YYYY-MM-DD>.csv` 와 `out/signals_latest.csv`로 저장됨.

### 2. GitHub Actions로 자동화

**Step 1.** GitHub에 이 repo를 push.

**Step 2.** Repo → Settings → Secrets and variables → Actions에서:
- **Secrets**: `POLYGON_API_KEY` 추가
- **Secrets** (선택, 텔레그램 알림용): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Variables** (선택): `POLYGON_RATE_LIMIT_PER_MIN` (기본 5), `MAX_FETCH_PER_RUN` (기본 400), `TELEGRAM_NOTIFY_ON_EMPTY` ("1"이면 신호 0개인 날도 알림), `TELEGRAM_MAX_SIGNALS` (한 메시지에 표시할 최대 개수, 기본 30)

**Step 3.** Actions 탭에서 `Daily Scan` 워크플로를 수동으로 한 번 실행 (초기 bootstrap 용). 이후로는 매일 UTC 23:00 (월-금)에 자동 실행됨.

**Step 4.** 결과 CSV 다운로드:
- 워크플로 실행 페이지 → Artifacts → `scan-results-<run_id>.zip`
- 또는 `out/` 디렉토리에 커밋된 파일에서 직접 다운로드

## 티커 관리 (ticker.txt)

스캔 대상은 repo 루트의 `ticker.txt`에서만 읽는다. **자동 fetch 없음** — 사용자가 직접 편집.

### 포맷

```
# 주석은 # 로 시작
# 빈 줄은 무시됨

AAPL
MSFT
GOOGL
BRK.B          # class share는 점(.) 유지
BF.B

# 섹션 구분용 주석
JPM            # 인라인 주석도 OK
```

- 대소문자 구분 없음 (자동으로 대문자 변환)
- 중복 제거 (첫 등장 순서 유지)
- `,` 또는 공백으로 한 줄에 여러 개 써도 됨 (`AAPL, MSFT GOOGL`)

### GitHub 웹 UI로 편집

1. Repo에서 `ticker.txt` 클릭
2. 연필 아이콘 → 편집
3. Commit — 다음 daily 실행에 반영됨

### 로컬에서 편집

```bash
vi ticker.txt
git add ticker.txt && git commit -m "update universe" && git push
```

### 파일 위치 바꾸기

다른 경로에 두고 싶으면 env 오버라이드:

```bash
TICKERS_FILE=path/to/my_list.txt python -m src.scan_universe
```

워크플로에서도 `env: TICKERS_FILE: ...` 로 동일하게 바꿀 수 있음.

### 시작용 파일

저장소에 포함된 `ticker.txt`는 2026년 4월 기준 S&P 500 현재 503개 (듀얼 클래스 포함). S&P 500 구성은 분기마다 바뀌니 주기적으로 갱신 권장.

## 첫 실행(Bootstrap) 안내

최초 실행 시 250영업일치 데이터를 채워야 해서 Grouped Daily API를 250회 정도 호출함.

- Polygon Starter 기본 rate limit (분당 5회 가정)으로 **약 50분** 소요 → GitHub Actions 무료 runner 6시간 한도 내
- Starter 플랜이 실제로 Grouped Daily를 지원하지 않거나 rate limit이 다르면 로그에 뜸 — `POLYGON_RATE_LIMIT_PER_MIN`을 플랜에 맞게 조정
- 한 번에 다 fetch 안 되면 `MAX_FETCH_PER_RUN`에서 잘린 뒤 다음 실행이 이어 받음

## 디렉토리 구조

```
sp500-support-scanner/
├── .github/workflows/
│   └── daily-scan.yml          # 매일 실행되는 단일 워크플로
├── ticker.txt                   # 스캔 대상 티커 리스트 (사용자 관리)
├── src/
│   ├── config.py               # 모든 파라미터 (env 오버라이드 가능)
│   ├── polygon_client.py       # Polygon REST 래퍼 (throttle/재시도)
│   ├── universe_loader.py      # ticker.txt 읽기 (자동 fetch 없음)
│   ├── bar_cache.py            # OHLCV 증분 캐시
│   ├── indicators.py           # EMA, ATR
│   ├── pivots.py               # pivot 탐지 + alternating/amplitude 필터
│   ├── trend.py                # HH+HL 판정 (윈도우 기반)
│   ├── support.py              # Type A / Type B support zone
│   ├── signal.py               # 매수 신호 조건
│   ├── scoring.py              # 가중 점수 (0-100)
│   ├── notifier.py             # Telegram 알림 (선택)
│   ├── scan_universe.py        # CLI: 전체 스캔 + watchlist 생성
│   └── scan_signals.py         # CLI: watchlist에서 신호 탐지 + CSV 출력 + Telegram 발송
├── tests/
│   ├── test_pipeline.py        # 합성 데이터로 로직 검증
│   ├── test_scoring.py         # 점수 산식 회귀 방지
│   ├── test_notifier.py        # 텔레그램 포맷팅/청크 유닛 테스트
│   ├── test_universe_loader.py # ticker.txt 파싱 유닛 테스트
│   └── test_e2e.py             # 전체 파이프라인 E2E 검증 (기본 threshold)
├── data/                       # bars.csv (자동 생성)
├── state/                      # watchlist.json + scan meta (자동 생성)
├── out/                        # signals_*.csv 결과 (자동 생성)
├── requirements.txt
└── README.md
```

## 점수 체계 (v2 — 코드 리뷰 후 개정)

최종 점수 (0-100) = 5개 컴포넌트의 가중합:
- **trend** (30%): HH+HL 상승 전환 횟수, 4회 이상이면 100점
- **support_quality** (25%): zone 대비 close 위치를 3구간으로 평가
  - `close ≥ zone_high`: reclaim 강도를 ATR로 정규화 (70 → 100). **강한 rejection bar를 오히려 가산**
  - zone 내부: 50~75점
  - zone 무너짐: 40점에서 penetration ATR만큼 감점
- **reaction** (20%): recovered/bullish_body/bullish_vs_prev/lower_tail_ratio 합산
- **liquidity** (10%): 평균 거래대금 (log scale 도입은 P1 항목)
- **room_to_resistance** (15%): 다음 유의미한 저항까지의 거리
  - 후보: last_ph, 20일 고점, 52주 고점 중 `close + 0.5 × ATR` 이상인 것만
  - Piecewise: 1% → 15점, 2% → 30점, 5% → 60점, 10% → 80점, 20%+ → 95점
  - 모든 candidate가 close 아래거나 noise 범위면 whitespace = 90점

CSV 결과에는 `score_trend`, `score_support_quality`, `score_reaction`, `score_liquidity`, `score_room` 컬럼이 포함되어 어느 컴포넌트가 얼마씩 기여했는지 확인 가능.

## 전략 요약

### Type A: Higher Low Support (primary)

1. **EMA 구조**: `close > EMA200` AND `EMA50 > EMA200`
2. **Liquidity**: 최근 20일 평균 거래대금 ≥ $10M
3. **Pivot 탐지**: 좌우 k=4 봉 기준, `filter_alternating` + `filter_by_swing_amplitude` (swing ≥ ATR × 1.5)로 노이즈 제거
4. **HH+HL 검증**:
   - `max(최근 PH 절반) > max(이전 PH 절반)` AND `max_PH`가 최근 절반에 위치
   - `PL[-1] > PL[-2]`
5. **Support zone**: `zone = PL[-1] ± ATR × 0.25`
6. **Buy signal**: 현재 bar에서
   - `low ≤ zone_high` (존 진입)
   - `close ≥ zone_low` (무너지지 않음)
   - `close ≥ zone_mid` (중간 이상 회복)
   - 양봉 OR 전봉 대비 상승 OR 긴 아래꼬리

### Type B: Breakout Retest Support (monitor)

- Type A 조건 충족 안 될 때, 최근 5개 pivot high 중 현재 close가 위로 돌파한 것이 있으면
- 그 PH 가격을 support로 삼고 `monitor` 카테고리로 분류
- 베이스 매집 → 돌파 → 재지지 시나리오 포착용

### 무효화

- `close < zone_low - ATR × 0.1` → 신호 제외
- Type A 기준이었는데 재스캔 시 trend_valid == False → 제외

## 파라미터 튜닝 포인트 (`src/config.py`)

```python
pivot_window: int = 4              # 3-5 사이에서 튜닝
min_swing_atr_mult: float = 1.5    # 노이즈 필터 강도 (높일수록 swing만 인정)
support_buffer_atr_mult: float = 0.25  # zone 크기
min_avg_dollar_volume: float = 10_000_000
min_signal_score: float = 60.0     # 최소 점수 threshold
```

테스트 돌려보고 false positive가 많으면 `min_swing_atr_mult`나 `min_signal_score`를 올리고, 너무 적으면 낮추면 됨.

## Telegram 알림 설정 (선택)

봇 토큰과 chat id 두 개만 환경변수로 넣으면, 신호가 잡혔을 때 텔레그램으로 바로 푸시가 온다. 둘 다 비어 있으면 알림은 조용히 skip 되니까 설정 안 해도 스캐너는 그대로 돌아간다.

### 1) 봇 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 에게 `/newbot` 명령어
2. 이름과 유저네임 정하면 **bot token** 줌 (형식: `123456789:ABC-...`) — 이걸 `TELEGRAM_BOT_TOKEN`으로 씀
3. 방금 만든 봇 프로필을 열고 `/start`를 눌러 대화 시작 (이걸 안 하면 봇이 메시지 못 보냄)

### 2) chat id 알아내기

개인 DM으로 받고 싶은 경우:
- [@userinfobot](https://t.me/userinfobot) 에게 `/start` 치면 내 chat id를 알려줌 (숫자)

그룹으로 받고 싶은 경우:
- 그룹에 봇을 초대한 뒤 아무 메시지나 하나 쓰고, 브라우저에서 `https://api.telegram.org/bot<TOKEN>/getUpdates` 열기
- JSON에서 `"chat":{"id":-1001234567890, ...}` 의 값(보통 음수) — 이게 chat id

### 3) GitHub에 등록

Repo → Settings → Secrets and variables → Actions → New repository secret:
- `TELEGRAM_BOT_TOKEN` = 봇 토큰
- `TELEGRAM_CHAT_ID` = chat id

그게 전부. 다음 스캔부터 알림이 온다.

### 4) 로컬에서 테스트

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABC-..."
export TELEGRAM_CHAT_ID="987654321"
python -m src.scan_signals           # 신호 있을 때만 알림
python -m src.scan_signals --no-telegram  # 알림 끄고 실행
```

### 알림 동작

- 기본: **신호가 하나라도 생겼을 때만** 메시지 발송. 신호 0개인 날은 조용함.
- `TELEGRAM_NOTIFY_ON_EMPTY=1` 로 설정하면 "오늘 신호 없음"도 알림이 옴 (매일 상태 체크용)
- `TELEGRAM_MAX_SIGNALS` 로 한 메시지에 담기는 개수 상한 조정 (기본 30개, 나머지는 CSV 참고하라고 요약됨)
- 텔레그램 4096자 제한은 자동으로 줄 단위 분할
- 워크플로 자체가 실패하면 `if: failure()` 스텝이 실패 알림을 따로 쏨
- **텔레그램 에러는 스캔을 중단시키지 않음** — API가 죽어도 CSV는 정상 저장됨

### 메시지 예시

```
📊 S&P 500 Support Scan — 2024-01-15
Found 3 signals (🟢 primary: 2, 🟡 monitor: 1)

1. 🟢 AAPL  score 87.3  [primary]
   type: higher_low
   close: $182.45 (+0.25 ATR from mid)
   zone: $180.20 – $181.50
   trend: HH 4 / HL 3

2. 🟢 MSFT  score 82.1  [primary]
   ...
```

## 스케줄 조정

`.github/workflows/daily-scan.yml`의 cron:

```yaml
schedule:
  - cron: "0 23 * * 1-5"   # UTC 23:00 월-금 = 한국 시간 다음날 08:00
```

- 미국 시장 마감은 EDT/EST에 따라 UTC 20:00 또는 21:00
- 23:00 UTC면 마감 2-3시간 뒤라 Polygon에서 당일 데이터 확보 여유 있음
- 다른 시간대 원하면 cron만 수정

## 주의 사항

- 이 시스템은 **체결 엔진이 아니라 알림 엔진**. 15분 지연 데이터 기준이라 신호 발생 시점에 이미 실시간 가격은 다를 수 있음
- 백테스트할 때는 반드시 **pivot 확정 지연(k 봉)을 반영**해야 함 — lookahead bias 방지
- S&P 500 구성은 주기적으로 바뀜. 루트의 `ticker.txt`를 직접 편집해서 갱신 (자동 fetch 없음). 한 줄에 하나씩, `#`로 주석 가능

## 트러블슈팅

**Q. Grouped Daily 호출에서 403 에러가 나요.**
Starter 플랜에서 해당 엔드포인트를 지원 안 할 수 있음. Polygon 대시보드에서 플랜 상세 확인하고, 필요하면 `polygon_client.py`의 `ticker_aggs`를 사용하도록 `scan_universe.py`를 수정 (다만 500배 느려짐).

**Q. `Ticker file not found: ticker.txt` 에러가 나요.**
루트에 `ticker.txt` 파일이 없어서 그럼. repo에 포함된 샘플을 유지하거나 직접 만들면 됨 (한 줄에 한 종목). 다른 경로 쓰려면 `TICKERS_FILE` env로 오버라이드.

**Q. 워크플로 commit이 실패해요.**
Settings → Actions → General → Workflow permissions에서 "Read and write permissions" 활성화되어 있는지 확인.

**Q. 첫 실행이 6시간을 초과할 것 같아요.**
`MAX_FETCH_PER_RUN`을 낮게 설정하고 워크플로를 수동으로 여러 번 실행. 다음 실행이 이어서 채움.

**Q. signals CSV가 매일 비어 있어요.**
정상일 수 있음. HH+HL 상승추세 종목이 support 존에 접근하는 타이밍은 자주 안 오니까. watchlist는 꾸준히 차 있는지부터 확인 (`state/watchlist.json` 또는 `out/watchlist_*.csv`).

**Q. 텔레그램 알림이 안 와요.**
체크 리스트:
1. `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 둘 다 Secret으로 등록됐는지 (Variables 아니고 Secrets)
2. 봇에게 먼저 `/start` 한 번 보냈는지 (이게 없으면 봇이 DM 못 보냄)
3. Actions 로그에서 `Telegram: sent ... signal(s)` 라인이 찍히는지 확인. 찍혔는데 안 왔으면 chat id가 틀린 경우가 많음
4. 그룹 chat id는 보통 `-100` 으로 시작하는 음수. 양수 id를 넣었다면 개인 chat id와 혼동한 것

**Q. 신호가 0개인 날은 아무 메시지도 안 오는데요?**
기본값이 그래. 매일 "살아있음" 확인하고 싶으면 repo Variables에 `TELEGRAM_NOTIFY_ON_EMPTY=1` 추가.

**Q. 텔레그램 API가 죽으면 스캔도 멈추나요?**
아니. 알림 실패는 로그만 찍고 넘어가며, CSV 저장과 커밋은 정상 진행됨.
