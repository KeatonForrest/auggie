.PHONY: test smoke-prod release-check _require-app-url

test:
	python3 -m pytest -q

smoke-prod:
	bash scripts/smoke_prod.sh $(APP_URL)

_require-app-url:
ifndef APP_URL
	$(error APP_URL is required. Usage: make release-check APP_URL=https://your-app.example.com)
endif

release-check: _require-app-url test
	bash scripts/smoke_prod.sh $(APP_URL)
