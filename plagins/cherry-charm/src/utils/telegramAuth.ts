import WebApp from '@twa-dev/sdk';

export const getTelegramAuthHeaders = (): Record<string, string> => {
  const initData = WebApp.initData || '';
  const launchToken = new URLSearchParams(window.location.search).get('launch') || '';

  return {
    Authorization: `tma ${initData}`,
    'X-Telegram-Init-Data': initData,
    'X-WebApp-Launch-Token': launchToken,
  };
};
