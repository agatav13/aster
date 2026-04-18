Locust performance reports — Aster
===================================

This directory holds locust HTML reports generated during performance testing.

Reproducing
-----------
1. Start a production-like server in one terminal:

     DJANGO_DEBUG=False \
     DJANGO_SECRET_KEY=local-perf-key \
     DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost \
     uv run gunicorn config.wsgi --workers 1 --bind 127.0.0.1:8000

2. Seed the LoggedInBrowser test user (one-time):

     uv run manage.py shell -c "from accounts.models import User; \
       User.objects.create_user(email='perf-user@example.com', \
       password='PerfPass!23456', is_active=True, is_email_verified=True)"

3. Run locust headless in another terminal:

     uv run locust -f tests/perf/locustfile.py \
       --host http://127.0.0.1:8000 \
       --users 50 --spawn-rate 10 --run-time 5m \
       --headless --html docs/assets/perf/report.html

Pass criteria
-------------
- p95 < 500 ms for browse endpoints (/, /movies/, /movies/<id>/)
- error rate < 1%
- 50 concurrent users sustained for 5 minutes
