export const THEME_STORAGE_KEY = "knowledge-assistant-theme";
export const AUTH_TOKEN_KEY = "platform_access_token";
export const AUTH_USER_KEY = "platform_user";

/** 平台 API 根路径（开发环境由 Vite 代理到后端） */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
