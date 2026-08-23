FROM apache/airflow:3.3.1-python3.12@sha256:b01a795dfbd113bbbfdf3ee169b8f27e9a0090ccef105f1a452b3594a11ed316

ARG AIRFLOW_VERSION=3.3.1
ARG PYTHON_VERSION=3.12
ARG CONSTRAINTS_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

COPY --chown=airflow:root docker/airflow/requirements.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir \
    --constraint "${CONSTRAINTS_URL}" \
    --requirement /tmp/requirements-airflow.txt

COPY --chown=airflow:root pyproject.toml README.md LICENSE /opt/airflow/project/
COPY --chown=airflow:root dags /opt/airflow/dags
COPY --chown=airflow:root src /opt/airflow/project/src
COPY --chown=airflow:root config /opt/airflow/project/config
COPY --chown=airflow:root scripts /opt/airflow/project/scripts
RUN chmod -R u=rwX,go=rX /opt/airflow/dags
RUN pip install --no-cache-dir --no-deps /opt/airflow/project
