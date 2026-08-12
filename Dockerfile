FROM python:3.11-slim

# tzdata is not optional here. config.py resolves ZoneInfo("Asia/Jerusalem") at
# import, and the pay engine depends on it for every candle-lighting and DST
# calculation. Debian slim images do not reliably ship the system timezone
# database, and without it zoneinfo raises ZoneInfoNotFoundError at startup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Fail the build rather than production if the timezone database is missing.
RUN python -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Jerusalem')"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Jerusalem

WORKDIR /app

# Copy only what the install needs first, so editing source does not invalidate
# the dependency layer.
COPY pyproject.toml README.md ./
COPY salary_bot ./salary_bot

RUN pip install --no-cache-dir .

# The page is a data file, not a module: verify the install actually carried it,
# from a directory where the source tree cannot mask the installed package.
RUN cd / && python -c "\
from pathlib import Path; import salary_bot; \
page = Path(salary_bot.__file__).parent / 'webapp' / 'index.html'; \
assert page.is_file(), f'the Mini App page is missing from the package: {page}'"

# Run unprivileged. /data is the mount point for the SQLite file and must be
# owned by this user, or the first write fails with a permission error.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

VOLUME ["/data"]
ENV DB_PATH=/data/salary.db

# Only listened on when WEBAPP_URL is set; harmless otherwise.
EXPOSE 8080

# The console script declared in pyproject.toml under [project.scripts].
CMD ["salary-bot"]
