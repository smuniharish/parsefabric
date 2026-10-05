# Flink runtime for examples/integrations/flink_job.py (see compose.yml).
FROM flink:2.3.0-scala_2.12-java17

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/parsefabric-python \
    && mkdir /results \
    && chown flink:flink /results
COPY pyproject.toml README.md LICENSE /opt/parsefabric/
COPY src /opt/parsefabric/src
RUN /opt/parsefabric-python/bin/pip install --no-cache-dir \
    apache-flink==2.3.0 /opt/parsefabric

ENV PATH="/opt/parsefabric-python/bin:${PATH}" \
    PYTHONPATH="/workspace" \
    PYFLINK_CLIENT_EXECUTABLE="/opt/parsefabric-python/bin/python"
USER flink
