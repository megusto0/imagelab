PY := python3

.PHONY: install server test lint clean

install:
	$(PY) -m pip install --upgrade pip
	cd server && $(PY) -m pip install -e .[dev]

server:
	cd server && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	cd server && pytest

lint:
	cd server && $(PY) -m compileall app

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
