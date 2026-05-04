import WebApp from '@twa-dev/sdk';

export const getTelegramAuthHeaders = (): Record<string, string> => {
  const initData = WebApp.initData || '';

  return {
    Authorization: `tma ${initData}`,
    'X-Telegram-Init-Data': initData,
  };
};
