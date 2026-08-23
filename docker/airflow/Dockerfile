FROM apache/airflow:3.3.0-python3.12@sha256:b572e9241d7b09b295c9ea97adeb7b3dfc932e2fbcdebec59256dad69061bb29

ARG AIRFLOW_VERSION=3.3.0
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
