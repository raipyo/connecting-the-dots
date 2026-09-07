#!/bin/bash

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Node dependencies
cd apps/web
npm install
cd ../..

# Setup environment variables
cp .env.example .env

# Initialize database
python scripts/init_db.py

# Run migrations
alembic upgrade head

# Start services with Docker Compose
docker-compose up -d

# Generate initial embeddings for existing data
python scripts/generate_embeddings.py

echo "Connecting the Dots AI is now running!"
echo "Frontend: http://localhost:3000"
echo "Backend API: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"