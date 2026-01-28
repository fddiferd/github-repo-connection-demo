.PHONY: dev backend frontend install install-backend install-frontend clean

# Run both backend and frontend concurrently
dev:
	@trap 'kill 0' INT; \
	make backend & \
	make frontend & \
	wait

# Run backend only (uses uv to manage venv automatically)
backend:
	cd backend && uv run uvicorn main:app --reload --port 8000

# Run frontend only  
frontend:
	cd frontend && npm run dev

# Install all dependencies
install: install-backend install-frontend

install-backend:
	cd backend && uv sync

install-frontend:
	cd frontend && npm install
