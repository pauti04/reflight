# AgentScope timeline UI.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_AGENTSCOPE_API=http://localhost:8724
ENV NEXT_PUBLIC_AGENTSCOPE_API=$NEXT_PUBLIC_AGENTSCOPE_API
RUN npm run build

FROM node:22-slim
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
