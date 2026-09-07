# Create simplified Dockerfile
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application code
COPY . .

# Create public directory if it doesn't exist
RUN mkdir -p public

EXPOSE 3000

# Start in development mode
CMD ["npm", "run", "dev"]