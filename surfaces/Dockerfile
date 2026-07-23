# Build context is the repository root (see orchestration/Dockerfile).
FROM node:20-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY surfaces/package.json surfaces/package-lock.json ./
# devDependencies are needed: typescript and tailwind run at build time.
RUN npm ci --include=dev

COPY surfaces/ ./

# NEXT_PUBLIC_* values are inlined into the client bundle at build time, so this
# has to be a build argument rather than a runtime variable.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

EXPOSE 3000
CMD ["sh", "-c", "npm start -- --port ${PORT:-3000} --hostname 0.0.0.0"]
