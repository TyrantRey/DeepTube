FROM node:20-slim

WORKDIR /app

# 複製 package.json 和鎖定檔
COPY package.json package-lock.json* ./

# 在容器內安裝依賴
RUN npm install

# 複製其餘程式碼
COPY . .

EXPOSE 5173

# 啟動 Vite 服務
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]