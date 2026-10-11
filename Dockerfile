FROM 1password/op:2.40.0@sha256:3835e4e0fa5eb0fd9c12672c6ae65530f00789663dca3ea39e5b02eb90cd1b54 AS op

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install --no-install-recommends -y tini=0.19.0-3+b8 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 broker \
    && useradd --uid 10001 --gid broker --create-home broker
COPY --from=op /usr/local/bin/op /usr/local/bin/op
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]

FROM base AS build
WORKDIR /build
RUN pip install poetry==2.5.1
COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY pkg/ pkg/
RUN poetry build && python -m venv /opt/broker \
    && POETRY_VIRTUALENVS_CREATE=false VIRTUAL_ENV=/opt/broker poetry install --only main --no-root --no-interaction \
    && /opt/broker/bin/pip install --no-deps dist/*.whl

FROM build AS development
RUN POETRY_VIRTUALENVS_CREATE=false VIRTUAL_ENV=/opt/broker poetry install --with dev --no-interaction \
    && chown -R broker:broker /build /opt/broker
ENV PATH="/opt/broker/bin:$PATH"
USER 10001:10001
CMD ["agent-broker", "demo"]

FROM base AS production
COPY --from=build /opt/broker /opt/broker
ENV PATH="/opt/broker/bin:$PATH"
WORKDIR /home/broker
USER 10001:10001
EXPOSE 8443
CMD ["agent-broker", "demo"]
