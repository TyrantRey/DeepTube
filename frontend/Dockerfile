FROM node:20-slim

# 啟用 corepack 並鎖定 pnpm 版本（與 package.json 的 packageManager 一致）
RUN corepack enable

WORKDIR /app

# 複製 package.json 和 pnpm 鎖定檔
COPY package.json pnpm-lock.yaml ./

# 在容器內安裝依賴（依鎖定檔還原，確保可重現）
RUN pnpm install --frozen-lockfile

# 複製其餘程式碼
COPY . .

EXPOSE 5173

# 啟動 Vite 服務
CMD ["pnpm", "run", "dev", "--", "--host", "0.0.0.0"]
