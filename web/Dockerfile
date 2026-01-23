FROM node:22.11.0-alpine AS build
WORKDIR /app
RUN apk update && apk upgrade --no-cache
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22.11.0-alpine AS run
WORKDIR /app
RUN apk update && apk upgrade --no-cache
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NODE_ENV=production
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
COPY --from=build /app ./
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
EXPOSE 3000
CMD ["node","node_modules/next/dist/bin/next","start","-p","3000","-H","0.0.0.0"]
