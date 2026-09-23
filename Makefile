.PHONY: up test run

up:
	docker compose up -d --wait

run:
	flask --app app run --debug

test:
	pytest
