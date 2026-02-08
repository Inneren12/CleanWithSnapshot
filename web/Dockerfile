FROM node:22.11.0-alpine AS build
WORKDIR /app
RUN apk update && apk upgrade --no-cache
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ARG NEXT_PUBLIC_E2E_MODE
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NEXT_PUBLIC_E2E_MODE=$NEXT_PUBLIC_E2E_MODE
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22.11.0-alpine AS run
WORKDIR /app
RUN apk update && apk upgrade --no-cache
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ARG NEXT_PUBLIC_E2E_MODE
ARG NEXT_PUBLIC_API_BASE_URL
ENV NODE_ENV=production
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NEXT_PUBLIC_E2E_MODE=$NEXT_PUBLIC_E2E_MODE
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN addgroup -S app \
    && adduser -S -G app -h /app -s /sbin/nologin app
COPY --from=build --chown=app:app /app ./
# Remove npm/npx at runtime to reduce image size and minimize attack surface.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
EXPOSE 3000
USER app
CMD ["node","node_modules/next/dist/bin/next","start","-p","3000","-H","0.0.0.0"]
