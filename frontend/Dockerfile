# ---------- Build stage ----------
FROM node:20-alpine AS build

WORKDIR /app

RUN npx create-react-app .

#COPY app/package*.json ./

RUN npm install

COPY . .
RUN npm run build

# ---------- Runtime stage ----------
FROM nginx:alpine

COPY app/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]