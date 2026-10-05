# Spark runtime for examples/integrations/spark_example.py (see compose.yml).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java \
    SPARK_LOCAL_HOSTNAME=localhost \
    PYTHONUNBUFFERED=1

WORKDIR /workspace
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --root-user-action=ignore . "pyspark==4.2.0"
COPY examples/integrations ./examples/integrations

CMD ["python", "-m", "examples.integrations.spark_example"]
