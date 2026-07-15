### Build stage ###
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* vars at build time, so the backend URL must be known here.
ARG VITE_API_URL=http://localhost:8000/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

### Serve stage ###
FROM nginx:1.27-alpine

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Render (and most PaaS) inject $PORT at runtime; default to 8080 for local `docker run`.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:${PORT}/ || exit 1

# nginx's docker-entrypoint.sh auto-runs envsubst on templates/*.template -> conf.d/
CMD ["nginx", "-g", "daemon off;"]
