# Rakshak - developer entry points. Every target has a PowerShell twin in scripts/*.ps1 (Windows).
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,$(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,python))
CC ?= cc

.PHONY: help setup up down logs certs vectors test test-py test-c test-fe lint train demo clean

help:
	@echo "setup   create .venv and install backend (+dev, ml, api extras)"
	@echo "up      docker compose up --build (mosquitto, postgres, api, web, simulator)"
	@echo "down    stop everything (add VOLUMES=1 to drop data)"
	@echo "test    run all tests (python, C vectors, frontend)"
	@echo "vectors regenerate firmware/common/spec/vectors.json + vectors.h"
	@echo "demo    run the scripted end-to-end demo"

setup:
	python -m venv .venv
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e ml -e "backend[api,dev]" -e simulator

up:
	docker compose up --build

down:
	docker compose down $(if $(VOLUMES),-v,)

logs:
	docker compose logs -f --tail=100

certs:
	sh infra/certs/gen-dev-certs.sh infra/certs/out

vectors:
	$(PY) tools/gen_vectors.py

test: test-py test-c test-fe

test-py:
	$(PY) tools/gen_vectors.py --check
	$(PY) -m pytest backend/tests ml/tests simulator/tests -q

test-c:
	CC="$(CC)" sh firmware/common/test/run_host_test.sh

test-fe:
	cd frontend && npm test --silent

lint:
	$(PY) -m ruff check backend ml simulator tools
	cd frontend && npm run lint --silent

train:
	$(PY) -m rakshak_ml.train --out ml/artifacts

demo:
	docker compose up -d --build
	$(PY) tools/demo.py

clean:
	rm -rf .cache .pytest_cache .ruff_cache frontend/dist
