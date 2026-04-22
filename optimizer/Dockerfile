# Node.js + Python 3.12 base image for running the optimizer service.
FROM nikolaik/python-nodejs:python3.12-nodejs20

WORKDIR /app

# Install dependencies first so they cache across source changes.
COPY package*.json requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN npm ci

# Copy source and build the TypeScript server.
COPY src ./src
COPY python ./python
COPY tsconfig.json ./
RUN npm run build

# Railway sets PORT automatically; the app reads it from process.env.PORT.
CMD ["npm", "start"]
