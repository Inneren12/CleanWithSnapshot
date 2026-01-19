FROM node:20-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS run
WORKDIR /app
ARG NEXT_PUBLIC_SHOW_ADMIN_LINK
ENV NODE_ENV=production
ENV NEXT_PUBLIC_SHOW_ADMIN_LINK=$NEXT_PUBLIC_SHOW_ADMIN_LINK
COPY --from=build /app ./
RUN rm -rf /usr/lib/node_modules/npm /usr/bin/npm /usr/bin/npx
EXPOSE 3000
CMD ["node","node_modules/next/dist/bin/next","start","-p","3000","-H","0.0.0.0"]
