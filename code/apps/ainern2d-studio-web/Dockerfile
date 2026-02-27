FROM node:20-alpine

WORKDIR /workspace

COPY apps/ainern2d-studio-web/package*.json /workspace/
RUN npm ci

COPY apps/ainern2d-studio-web /workspace

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
