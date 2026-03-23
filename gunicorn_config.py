"""Gunicorn 설정 (Render 배포용)"""

bind = "0.0.0.0:10000"
workers = 2
timeout = 120  # 데이터 수집에 시간이 걸릴 수 있음
